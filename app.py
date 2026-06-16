from pathlib import Path
from datetime import datetime
import os
from flask import Flask, render_template, request, send_from_directory, jsonify, Response
from werkzeug.utils import secure_filename
from invitation_engine import render_invitation, load_themes, ROOT, slugify
from template_extractor import (
    save_custom_theme,
    CUSTOM_ASSET_DIR,
    build_runtime_theme_from_upload,
)
from mongo_rsvp_manager import (
    initialize_guest_list, mark_attending, load_guests, stats as rsvp_stats,
    available_lists, save_guests as save_rsvp_guests, check_owner_pin, export_text, mongo_available, get_db,
)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = str(ROOT / "uploads")
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "ogg"}
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_TEXT_EXTENSIONS = {"txt"}

CHECKBOX_FIELDS = [
    "use_sample_music", "music_enabled", "music_loop",
    "use_design_image_background",
    "falling_enabled", "show_corner_flower", "ambient_wind_enabled",
    "show_countdown", "show_program", "show_map_button", "show_rsvp_button",
    "show_calendar_button", "show_dress_code", "show_gift_note", "show_family_info",
    "show_photo_gallery", "show_venue_details",
    "corner_flower_image_enabled",
    "falling_particle_image_enabled",
    "internal_rsvp_enabled",
]


def allowed_audio(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def allowed_text(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_TEXT_EXTENSIONS


def form_to_config(form_data):
    form = form_data.to_dict()
    # HTML checkbox kapalıysa tarayıcı alanı hiç göndermez.
    # Bu yüzden kapalı olanları özellikle "off" yapıyoruz.
    # Böylece çiçek / kar / konum gibi özellikler gerçekten kapanır.
    for key in CHECKBOX_FIELDS:
        if key not in form:
            form[key] = "off"
    program_lines = []
    clocks = form_data.getlist("program_clock[]")
    titles = form_data.getlist("program_title[]")
    for c, t in zip(clocks, titles):
        if c.strip() or t.strip():
            program_lines.append(f"{c.strip()} | {t.strip()}")
    if program_lines:
        form["program"] = "\n".join(program_lines)
    return form


def save_music_from_request():
    music_path = None
    file = request.files.get("music_upload")
    if file and file.filename and allowed_audio(file.filename):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}-{secure_filename(file.filename)}"
        music_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        file.save(music_path)
    elif request.form.get("use_sample_music") == "on":
        music_path = ROOT / "static/music/sample-romantik-chime.wav"
    return music_path



def save_corner_image_from_request(form):
    file = request.files.get("corner_flower_image")
    if file and file.filename and allowed_image(file.filename):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"corner-{timestamp}-{secure_filename(file.filename)}"
        image_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        file.save(image_path)
        form["corner_flower_image_enabled"] = "on"
        form["corner_flower_image_file"] = str(image_path)
    return form




def save_falling_particle_from_request(form):
    file = request.files.get("falling_particle_image")
    if file and file.filename and allowed_image(file.filename):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"particle-{timestamp}-{secure_filename(file.filename)}"
        image_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        file.save(image_path)
        form["falling_particle_image_enabled"] = "on"
        form["falling_particle_image_file"] = str(image_path)
    return form


def save_gallery_images_from_request(form):
    for idx in range(1, 4):
        file = request.files.get(f"gallery_image_{idx}")
        if file and file.filename and allowed_image(file.filename):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"gallery-{idx}-{timestamp}-{secure_filename(file.filename)}"
            image_path = Path(app.config["UPLOAD_FOLDER"]) / filename
            file.save(image_path)
            form[f"gallery_image_{idx}_file"] = str(image_path)
    return form


def setup_rsvp_for_invitation(form, preview=False):
    """MongoDB davetli listesini hazırlar ve davetiye HTML içine API/panel linklerini ekler."""
    owner_pin = (form.get("owner_pin") or "").strip()
    if form.get("internal_rsvp_enabled") != "on":
        form.pop("owner_pin", None)
        return form, owner_pin

    raw_slug = form.get("slug") or f"{form.get('bride_name', '')}-{form.get('groom_name', '')}"
    slug = slugify(raw_slug)
    uploaded_text = ""
    file = request.files.get("guest_list_file")
    if file and file.filename and allowed_text(file.filename):
        uploaded_text = file.read().decode("utf-8-sig", errors="ignore")

    invitation_data = {
        "bride_name": form.get("bride_name", ""),
        "groom_name": form.get("groom_name", ""),
        "event_type": form.get("event_type", ""),
        "event_date": form.get("date", ""),
        "event_time": form.get("time", ""),
        "venue": form.get("venue", ""),
    }
    initialize_guest_list(
        slug,
        names_text=form.get("guest_names_text", ""),
        uploaded_text=uploaded_text,
        keep_existing_if_empty=True,
        owner_pin=owner_pin,
        invitation_data=invitation_data,
    )

    # eventdavet.com/ayse-mert/ formatı için göreli URL'ler.
    form["rsvp_api_url"] = f"/{slug}/api/katilim"
    form["rsvp_owner_url"] = f"/{slug}/katilimcilar"

    # PIN davetiye HTML içine gömülmesin. Düğün sahibine panel linki sonuç ekranında ayrıca gösterilir.
    form.pop("owner_pin", None)
    return form, owner_pin


def build_theme_override_from_request(form):
    use_uploaded_design = form.get("use_design_image_background") == "on"
    design_file = request.files.get("design_image")
    if not use_uploaded_design or not design_file or not design_file.filename:
        return None
    particle = form.get("design_particle") or "🌸"
    corner_flower = form.get("design_corner_flower") or "🌺"
    result = build_runtime_theme_from_upload(
        uploaded_file=design_file,
        theme_name=form.get("design_theme_name", "Özel Arkaplan"),
        particle=particle,
        corner_flower=corner_flower,
        overlay_opacity=int(form.get("design_overlay_opacity", 44) or 44),
        image_mode=form.get("design_image_mode", "cover"),
        background_position=form.get("design_background_position", "center center"),
        frame_style=form.get("design_frame_style", "soft"),
        use_image_as_background=True,
    )
    return result["theme"]


@app.route("/mongo/status", methods=["GET"])
def mongo_status():
    return jsonify({"ok": mongo_available()})


@app.route("/", methods=["GET"])
def index():
    return render_template("admin.html", themes=load_themes(), result=None)


@app.route("/debug/env", methods=["GET"])
def debug_env():
    env_path = ROOT / ".env"
    uri = (os.getenv("MONGODB_URI") or "").strip()
    masked = ""
    if uri:
        try:
            left, right = uri.split("@", 1)
            masked = left.split("://", 1)[0] + "://***:***@" + right
        except Exception:
            masked = "loaded-but-could-not-mask"
    return jsonify({
        "env_file_path": str(env_path),
        "env_file_exists": env_path.exists(),
        "mongodb_uri_loaded": bool(uri),
        "mongodb_uri_masked": masked,
        "mongodb_db_name": os.getenv("MONGODB_DB_NAME", "eventdavet"),
        "expected_database_design": "Tek database: eventdavet | Collections: invitations, guests",
        "hint": "mongodb_uri_loaded false ise .env dosyası app.py ile aynı klasörde değildir, adı .env.txt kalmıştır veya MONGODB_URI satırı hatalıdır."
    })


@app.route("/debug/mongo", methods=["GET"])
def debug_mongo():
    try:
        db = get_db()
        db.command("ping")
        return jsonify({
            "ok": True,
            "database": db.name,
            "collections": sorted(db.list_collection_names()),
            "message": "MongoDB bağlantısı başarılı. Data Explorer'da eventdavet database'i altında invitations ve guests collections görünmeli."
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "message": "Bağlantı başarısız. .env içindeki MONGODB_URI, MONGODB_DB_NAME ve Atlas Network Access/IP ayarını kontrol et."
        }), 500


@app.route("/template-lab", methods=["GET"])
def template_lab():
    return render_template("template_lab.html", themes=load_themes(), result=None, error=None)


@app.route("/template-lab/extract", methods=["POST"])
def extract_template():
    try:
        result = save_custom_theme(
            uploaded_file=request.files.get("design_image"),
            theme_name=request.form.get("theme_name", "Özel Şablon"),
            particle=request.form.get("particle", "🌸"),
            corner_flower=request.form.get("corner_flower", "🌺"),
            overlay_opacity=int(request.form.get("overlay_opacity", 44) or 44),
            image_mode=request.form.get("image_mode", "cover"),
            background_position=request.form.get("background_position", "center center"),
            frame_style=request.form.get("frame_style", "soft"),
            use_image_as_background=request.form.get("use_image_as_background") == "on",
        )
        return render_template("template_lab.html", themes=load_themes(), result=result, error=None)
    except Exception as exc:
        return render_template("template_lab.html", themes=load_themes(), result=None, error=str(exc)), 400


@app.route("/theme-image/<path:filename>")
def theme_image(filename):
    return send_from_directory(CUSTOM_ASSET_DIR, filename)


@app.route("/generate", methods=["POST"])
def generate():
    form = form_to_config(request.form)
    form = save_corner_image_from_request(form)
    form = save_falling_particle_from_request(form)
    form = save_gallery_images_from_request(form)
    form, owner_pin = setup_rsvp_for_invitation(form)
    music_path = save_music_from_request()
    if music_path:
        form["music_enabled"] = "on"
    theme_override = build_theme_override_from_request(request.form)
    path = render_invitation(
        form,
        template_key=form.get("theme"),
        out_dir=ROOT / "dist",
        music_path=music_path,
        theme_override=theme_override,
    )
    rel = path.relative_to(ROOT)
    public_url = f"/{path.parent.name}/"
    owner_url = f"/{path.parent.name}/katilimcilar" + (f"?pin={owner_pin}" if owner_pin else "")
    return render_template("admin.html", themes=load_themes(), result={"path": str(rel), "url": public_url, "slug": path.parent.name, "owner_url": owner_url})


@app.route("/live-preview", methods=["POST"])
def live_preview():
    try:
        form = form_to_config(request.form)
        form = save_corner_image_from_request(form)
        form = save_falling_particle_from_request(form)
        form = save_gallery_images_from_request(form)
        original_slug = form.get("slug") or "onizleme"
        form["slug"] = f"_onizleme-{secure_filename(original_slug).lower() or 'davet'}"
        form, _owner_pin = setup_rsvp_for_invitation(form, preview=True)
        music_path = save_music_from_request()
        if music_path:
            form["music_enabled"] = "on"
        theme_override = build_theme_override_from_request(request.form)
        path = render_invitation(
            form,
            template_key=form.get("theme"),
            out_dir=ROOT / "dist" / "_previews",
            music_path=music_path,
            theme_override=theme_override,
        )
        slug = path.parent.name
        return jsonify({
            "ok": True,
            "url": f"/live/{slug}/?v={datetime.now().timestamp()}",
            "slug": slug,
        })
    except Exception as exc:
        # Ön izleme hatasında HTML debug sayfası yerine JSON döndür.
        # Böylece arayüzde "Unexpected token '<'" yerine asıl hata görünür.
        return jsonify({"ok": False, "message": str(exc)}), 500


@app.route("/api/rsvp/<slug>", methods=["POST"])
def api_rsvp(slug):
    payload = request.get_json(silent=True) or request.form
    full_name = payload.get("full_name", "") if hasattr(payload, "get") else ""
    result = mark_attending(slug, full_name)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code



def render_owner_panel_for_slug(slug):
    pin = request.args.get("pin", "")
    if not check_owner_pin(slug, pin):
        return render_template("rsvp_panel.html", lists=None, slug=slug, guests=[], stats=None, locked=True, pin="")
    guests = load_guests(slug)
    return render_template("rsvp_panel.html", lists=None, slug=slug, guests=guests, stats=rsvp_stats(slug), locked=False, pin=pin)

@app.route("/owner/rsvp", methods=["GET"])
def owner_rsvp_index():
    return render_template("rsvp_panel.html", lists=available_lists(), slug=None, guests=[], stats=None, mongo_available=mongo_available())


@app.route("/owner/rsvp/<slug>", methods=["GET"])
def owner_rsvp_panel(slug):
    return render_owner_panel_for_slug(slug)


@app.route("/owner/rsvp/<slug>/download", methods=["GET"])
def owner_rsvp_download(slug):
    pin = request.args.get("pin", "")
    if not check_owner_pin(slug, pin):
        return Response("Yetkisiz erişim.", status=403, mimetype="text/plain; charset=utf-8")
    return Response(export_text(slug), mimetype="text/plain; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={slug}-katilim-listesi.txt"})

@app.route("/owner/rsvp/<slug>/reset", methods=["POST"])
def owner_rsvp_reset(slug):
    payload = request.get_json(silent=True) or {}
    pin = request.args.get("pin", "") or payload.get("pin", "")
    if not check_owner_pin(slug, pin):
        return jsonify({"ok": False, "message": "Yetkisiz erişim."}), 403
    guests = load_guests(slug)
    for guest in guests:
        guest["status"] = "bekliyor"
        guest["timestamp"] = ""
    save_rsvp_guests(slug, guests)
    return jsonify({"ok": True, "message": "Liste sıfırlandı."})



# ------------------------------------------------------------
# EventDavet public URL routes
# ------------------------------------------------------------
# Bu bölüm Shopify/Cloudflare reverse proxy ile eventdavet.com/slug/
# şeklinde çalışacak şekilde hazırlandı.
@app.route("/<slug>/", methods=["GET"])
def public_invitation(slug):
    return send_from_directory(ROOT / "dist" / slug, "index.html")


@app.route("/<slug>/katilimcilar", methods=["GET"])
@app.route("/<slug>/katilimcilar/", methods=["GET"])
def public_owner_rsvp_panel(slug):
    return render_owner_panel_for_slug(slug)


@app.route("/<slug>/katilimcilar/download", methods=["GET"])
def public_owner_rsvp_download(slug):
    pin = request.args.get("pin", "")
    if not check_owner_pin(slug, pin):
        return Response("Yetkisiz erişim.", status=403, mimetype="text/plain; charset=utf-8")
    return Response(export_text(slug), mimetype="text/plain; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={slug}-katilim-listesi.txt"})

@app.route("/<slug>/katilimcilar/reset", methods=["POST"])
def public_owner_rsvp_reset(slug):
    payload = request.get_json(silent=True) or {}
    pin = request.args.get("pin", "") or payload.get("pin", "")
    if not check_owner_pin(slug, pin):
        return jsonify({"ok": False, "message": "Yetkisiz erişim."}), 403
    guests = load_guests(slug)
    for guest in guests:
        guest["status"] = "bekliyor"
        guest["timestamp"] = ""
    save_rsvp_guests(slug, guests)
    return jsonify({"ok": True, "message": "Liste sıfırlandı."})


@app.route("/<slug>/api/katilim", methods=["POST"])
def public_api_rsvp(slug):
    payload = request.get_json(silent=True) or request.form
    full_name = payload.get("full_name", "") if hasattr(payload, "get") else ""
    result = mark_attending(slug, full_name)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.route("/<slug>/<path:filename>", methods=["GET"])
def public_invitation_assets(slug, filename):
    # Davetiye içindeki assets/music, assets/gallery gibi dosyalar için.
    return send_from_directory(ROOT / "dist" / slug, filename)


@app.route("/preview/<slug>/")
def preview(slug):
    return send_from_directory(ROOT / "dist" / slug, "index.html")


@app.route("/preview/<slug>/<path:filename>")
def preview_assets(slug, filename):
    return send_from_directory(ROOT / "dist" / slug, filename)


@app.route("/live/<slug>/")
def live(slug):
    return send_from_directory(ROOT / "dist" / "_previews" / slug, "index.html")


@app.route("/live/<slug>/<path:filename>")
def live_assets(slug, filename):
    return send_from_directory(ROOT / "dist" / "_previews" / slug, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=True)
