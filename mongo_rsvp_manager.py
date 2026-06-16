from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import re
import unicodedata
import hashlib
from typing import Iterable

try:
    from dotenv import load_dotenv
    # .env dosyasını özellikle app.py ile aynı klasörden yükle.
    # Böylece Windows'ta programı farklı klasörden çalıştırsan bile MONGODB_URI okunur.
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

try:
    from pymongo import MongoClient, ASCENDING
except Exception:  # pymongo kurulu değilse app açılırken anlaşılır hata döndürelim.
    MongoClient = None
    ASCENDING = 1

from invitation_engine import slugify

_client = None
_indexes_ready = False


def normalize_name(name: str) -> str:
    name = (name or "").strip().lower()
    table = str.maketrans("çğıöşüâîû", "cgiosuaiu")
    name = name.translate(table)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _pin_hash(pin: str) -> str:
    pin = (pin or "").strip()
    if not pin:
        return ""
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def _get_uri() -> str:
    return (os.getenv("MONGODB_URI") or "").strip()


def _get_db_name() -> str:
    return (os.getenv("MONGODB_DB_NAME") or "eventdavet").strip() or "eventdavet"


def get_db():
    global _client, _indexes_ready
    uri = _get_uri()
    if not uri:
        raise RuntimeError("MONGODB_URI tanımlı değil. .env dosyasına MongoDB Atlas bağlantını ekle.")
    if MongoClient is None:
        raise RuntimeError("pymongo kurulu değil. 'pip install -r requirements.txt' çalıştır.")
    if _client is None:
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = _client[_get_db_name()]
    if not _indexes_ready:
        ensure_indexes(db)
        _indexes_ready = True
    return db


def mongo_available() -> bool:
    return bool(_get_uri()) and MongoClient is not None


def ensure_indexes(db=None):
    # PyMongo Database nesnesi bool() ile kontrol edilemez.
    # Bu yüzden "db or get_db()" yerine açıkça None kontrolü yapılır.
    if db is None:
        db = get_db()
    db.invitations.create_index([("slug", ASCENDING)], unique=True)
    db.guests.create_index([("invitation_slug", ASCENDING), ("normalized_name", ASCENDING)], unique=True)
    db.guests.create_index([("invitation_slug", ASCENDING), ("status", ASCENDING)])


def parse_line(line: str) -> dict | None:
    raw = (line or "").strip()
    if not raw or raw.startswith("#"):
        return None
    parts = [p.strip() for p in raw.split("|")]
    name = parts[0].strip()
    if not name:
        return None
    status = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else "bekliyor"
    if status not in {"bekliyor", "katıldı", "katildi", "gelmeyecek"}:
        status = "bekliyor"
    if status == "katildi":
        status = "katıldı"
    timestamp = parts[2].strip() if len(parts) > 2 else ""
    return {"name": name, "key": normalize_name(name), "status": status, "timestamp": timestamp}


def parse_guest_names(text: str) -> list[dict]:
    guests: list[dict] = []
    seen = set()
    for raw in (text or "").splitlines():
        item = parse_line(raw)
        if not item:
            continue
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        item["status"] = item.get("status") or "bekliyor"
        guests.append(item)
    return guests


def _guest_doc(slug: str, item: dict, old: dict | None = None) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = old.get("status", "bekliyor") if old else item.get("status", "bekliyor")
    timestamp = old.get("timestamp", "") if old else item.get("timestamp", "")
    return {
        "invitation_slug": slug,
        "full_name": item["name"],
        "normalized_name": item["key"],
        "status": status or "bekliyor",
        "timestamp": timestamp or "",
        "updated_at": now,
        "created_at": old.get("created_at", now) if old else now,
    }


def initialize_guest_list(
    slug: str,
    names_text: str = "",
    uploaded_text: str = "",
    keep_existing_if_empty: bool = True,
    owner_pin: str = "",
    invitation_data: dict | None = None,
) -> str:
    """Panelden gelen davetli listesini MongoDB'ye kaydeder."""
    slug = slugify(slug)
    db = get_db()

    invitation_payload = {
        "slug": slug,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **(invitation_data or {}),
    }
    if owner_pin.strip():
        invitation_payload["owner_pin_hash"] = _pin_hash(owner_pin)

    db.invitations.update_one(
        {"slug": slug},
        {"$set": invitation_payload, "$setOnInsert": {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}},
        upsert=True,
    )

    existing_count = db.guests.count_documents({"invitation_slug": slug})
    incoming_text = "\n".join([uploaded_text or "", names_text or ""]).strip()
    incoming = parse_guest_names(incoming_text)

    if not incoming and keep_existing_if_empty and existing_count:
        return slug

    if not incoming:
        incoming = parse_guest_names("Ayşe Demir\nMehmet Yılmaz\nZeynep Kaya\nAli Çelik")

    existing = {
        g["normalized_name"]: g
        for g in db.guests.find({"invitation_slug": slug}, {"_id": 0})
    }
    incoming_keys = [g["key"] for g in incoming]

    # Yeni liste geldiyse artık listede olmayan kişileri kaldır.
    db.guests.delete_many({"invitation_slug": slug, "normalized_name": {"$nin": incoming_keys}})

    for item in incoming:
        old = existing.get(item["key"])
        doc = _guest_doc(slug, item, old)
        db.guests.update_one(
            {"invitation_slug": slug, "normalized_name": item["key"]},
            {"$set": doc},
            upsert=True,
        )
    return slug


def load_guests(slug: str) -> list[dict]:
    slug = slugify(slug)
    try:
        db = get_db()
    except RuntimeError:
        return []
    guests = []
    for g in db.guests.find({"invitation_slug": slug}, {"_id": 0}).sort("full_name", ASCENDING):
        guests.append({
            "name": g.get("full_name", ""),
            "key": g.get("normalized_name", ""),
            "status": g.get("status", "bekliyor"),
            "timestamp": g.get("timestamp", ""),
        })
    return guests


def save_guests(slug: str, guests: Iterable[dict]) -> str:
    slug = slugify(slug)
    db = get_db()
    docs = []
    for guest in guests:
        name = guest.get("name") or guest.get("full_name")
        if not name:
            continue
        key = guest.get("key") or guest.get("normalized_name") or normalize_name(name)
        docs.append({
            "name": name,
            "key": key,
            "status": guest.get("status", "bekliyor"),
            "timestamp": guest.get("timestamp", ""),
        })
    db.guests.delete_many({"invitation_slug": slug})
    for item in docs:
        db.guests.insert_one(_guest_doc(slug, item))
    return slug


def mark_attending(slug: str, full_name: str) -> dict:
    slug = slugify(slug)
    full_name = (full_name or "").strip()
    key = normalize_name(full_name)
    if len(key.split()) < 2:
        return {"ok": False, "code": "name_required", "message": "Lütfen ad ve soyadınızı tam yazın."}

    try:
        db = get_db()
    except RuntimeError as exc:
        return {"ok": False, "code": "mongo_missing", "message": str(exc)}

    guest = db.guests.find_one({"invitation_slug": slug, "normalized_name": key}, {"_id": 0})
    if not guest:
        return {"ok": False, "code": "not_found", "message": "Bu isim davetli listesinde bulunamadı. Lütfen ad-soyad bilgisini listedeki haliyle yazın."}

    public_guest = {
        "name": guest.get("full_name", ""),
        "key": guest.get("normalized_name", ""),
        "status": guest.get("status", "bekliyor"),
        "timestamp": guest.get("timestamp", ""),
    }
    if guest.get("status") == "katıldı":
        return {"ok": True, "already": True, "message": f"{public_guest['name']} daha önce katıldı olarak işaretlenmiş.", "guest": public_guest}

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.guests.update_one(
        {"invitation_slug": slug, "normalized_name": key},
        {"$set": {"status": "katıldı", "timestamp": ts, "updated_at": ts}},
    )
    public_guest["status"] = "katıldı"
    public_guest["timestamp"] = ts
    return {"ok": True, "already": False, "message": f"Teşekkürler {public_guest['name']}, katılımınız kaydedildi.", "guest": public_guest}


def stats(slug: str) -> dict:
    slug = slugify(slug)
    try:
        db = get_db()
    except RuntimeError:
        return {"total": 0, "attending": 0, "pending": 0}
    total = db.guests.count_documents({"invitation_slug": slug})
    attending = db.guests.count_documents({"invitation_slug": slug, "status": "katıldı"})
    return {"total": total, "attending": attending, "pending": max(0, total - attending)}


def available_lists() -> list[dict]:
    try:
        db = get_db()
    except RuntimeError:
        return []
    items = []
    for inv in db.invitations.find({}, {"_id": 0, "slug": 1}).sort("updated_at", -1):
        slug = inv.get("slug")
        if not slug:
            continue
        s = stats(slug)
        items.append({"slug": slug, **s})
    return items


def check_owner_pin(slug: str, pin: str | None) -> bool:
    slug = slugify(slug)
    try:
        db = get_db()
    except RuntimeError:
        return True
    inv = db.invitations.find_one({"slug": slug}, {"_id": 0, "owner_pin_hash": 1})
    expected = (inv or {}).get("owner_pin_hash") or ""
    if not expected:
        return True
    return _pin_hash(pin or "") == expected


def export_text(slug: str) -> str:
    lines = ["Ad Soyad | Durum | Katılım Zamanı"]
    for guest in load_guests(slug):
        lines.append(f"{guest.get('name','')} | {guest.get('status','bekliyor')} | {guest.get('timestamp','')}")
    return "\n".join(lines) + "\n"
