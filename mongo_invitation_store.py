from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import shutil
import tempfile
import zipfile

from gridfs import GridFSBucket

from invitation_engine import ROOT, slugify
from mongo_rsvp_manager import get_db

BUCKET_NAME = "invitation_bundles"
BUNDLE_FORMAT_VERSION = 1
MARKER_FILENAME = ".eventdavet_bundle.json"


def _files_collection(db):
    return db[f"{BUCKET_NAME}.files"]


def _get_latest_record(slug: str):
    slug = slugify(slug)
    db = get_db()
    return _files_collection(db).find_one(
        {"metadata.slug": slug},
        sort=[("uploadDate", -1)],
    )


def _read_marker(invite_dir: Path) -> dict:
    marker = invite_dir / MARKER_FILENAME
    if not marker.exists():
        return {}
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_marker(invite_dir: Path, file_id, updated_at: str = "") -> None:
    payload = {
        "bundle_file_id": str(file_id),
        "updated_at": updated_at,
        "format_version": BUNDLE_FORMAT_VERSION,
    }
    (invite_dir / MARKER_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _zip_directory(source_dir: Path) -> bytes:
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Davetiye klasörü bulunamadı: {source_dir}")
    if not (source_dir / "index.html").exists():
        raise FileNotFoundError(f"Davetiye index.html dosyası bulunamadı: {source_dir / 'index.html'}")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name == MARKER_FILENAME:
                continue
            rel = path.relative_to(source_dir)
            zf.write(path, arcname=rel.as_posix())
    return buffer.getvalue()


def _safe_extract_zip(zip_bytes: bytes, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()

    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
        for info in zf.infolist():
            candidate = (target_dir / info.filename).resolve()
            try:
                candidate.relative_to(target_root)
            except ValueError as exc:
                raise RuntimeError("Güvensiz ZIP yolu tespit edildi.") from exc
        zf.extractall(target_dir)


def store_invitation_bundle(slug: str, source_dir: str | Path) -> dict:
    """Generated invitation directory'yi MongoDB GridFS içine tek paket olarak kaydeder."""
    slug = slugify(slug)
    source_dir = Path(source_dir)
    zip_bytes = _zip_directory(source_dir)

    db = get_db()
    bucket = GridFSBucket(db, bucket_name=BUCKET_NAME)

    # Önce yeni paketi yükle. Yükleme başarılı olduktan sonra eski sürümleri sileriz;
    # böylece ağ hatasında mevcut çalışan davetiye kaybolmaz.
    old_ids = [row["_id"] for row in _files_collection(db).find({"metadata.slug": slug}, {"_id": 1})]

    updated_at = datetime.now(timezone.utc).isoformat()
    file_id = bucket.upload_from_stream(
        f"{slug}.zip",
        BytesIO(zip_bytes),
        metadata={
            "slug": slug,
            "updated_at": updated_at,
            "format_version": BUNDLE_FORMAT_VERSION,
        },
    )

    for old_id in old_ids:
        if old_id == file_id:
            continue
        try:
            bucket.delete(old_id)
        except Exception:
            pass

    db.invitations.update_one(
        {"slug": slug},
        {
            "$set": {
                "bundle_file_id": file_id,
                "bundle_updated_at": updated_at,
                "bundle_size_bytes": len(zip_bytes),
                "bundle_format_version": BUNDLE_FORMAT_VERSION,
            }
        },
        upsert=True,
    )

    _write_marker(source_dir, file_id, updated_at)
    return {
        "slug": slug,
        "file_id": str(file_id),
        "size_bytes": len(zip_bytes),
        "updated_at": updated_at,
    }


def ensure_invitation_materialized(slug: str, dist_root: str | Path | None = None) -> Path:
    """Davetiye lokalde yoksa veya GridFS'teki sürüm daha yeniyse otomatik geri yükler."""
    slug = slugify(slug)
    dist_root = Path(dist_root or (ROOT / "dist"))
    invite_dir = dist_root / slug
    index_path = invite_dir / "index.html"

    marker = _read_marker(invite_dir)
    # Marker varsa bu klasör zaten GridFS'ten indirilmiş veya başarıyla kaydedilmiştir.
    # Her resim/müzik isteğinde Atlas'a tekrar sorgu atmayız.
    if index_path.exists() and marker.get("bundle_file_id"):
        return invite_dir

    record = _get_latest_record(slug)
    if record is None:
        if index_path.exists():
            return invite_dir
        raise FileNotFoundError(
            f"{slug} için MongoDB davetiye paketi bulunamadı. Davetiyeyi yönetim panelinden bir kez yeniden oluştur."
        )

    remote_file_id = str(record["_id"])

    db = get_db()
    bucket = GridFSBucket(db, bucket_name=BUCKET_NAME)
    output = BytesIO()
    bucket.download_to_stream(record["_id"], output)

    dist_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"._restore-{slug}-", dir=str(dist_root)))
    try:
        _safe_extract_zip(output.getvalue(), temp_dir)
        if not (temp_dir / "index.html").exists():
            raise RuntimeError("MongoDB paketi içinde index.html bulunamadı.")

        if invite_dir.exists():
            shutil.rmtree(invite_dir)
        temp_dir.replace(invite_dir)
        _write_marker(
            invite_dir,
            record["_id"],
            (record.get("metadata") or {}).get("updated_at", ""),
        )
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return invite_dir


def invitation_bundle_status(slug: str, dist_root: str | Path | None = None) -> dict:
    slug = slugify(slug)
    dist_root = Path(dist_root or (ROOT / "dist"))
    invite_dir = dist_root / slug
    record = _get_latest_record(slug)
    marker = _read_marker(invite_dir)

    if record is None:
        return {
            "slug": slug,
            "stored_in_mongodb": False,
            "local_exists": (invite_dir / "index.html").exists(),
            "message": "MongoDB paketi yok. Davetiyeyi bir kez yeniden oluştur.",
        }

    metadata = record.get("metadata") or {}
    return {
        "slug": slug,
        "stored_in_mongodb": True,
        "local_exists": (invite_dir / "index.html").exists(),
        "bundle_file_id": str(record["_id"]),
        "bundle_size_bytes": record.get("length", 0),
        "bundle_updated_at": metadata.get("updated_at", ""),
        "local_bundle_file_id": marker.get("bundle_file_id", ""),
        "local_is_current": marker.get("bundle_file_id") == str(record["_id"]),
        "message": "Davetiye MongoDB GridFS içinde kalıcı olarak saklanıyor.",
    }
