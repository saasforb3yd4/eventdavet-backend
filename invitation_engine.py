from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json, re, shutil
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent
THEMES_PATH = ROOT / "themes.json"
TEMPLATE_DIR = ROOT / "templates"
DEFAULT_OUT = ROOT / "dist"

DEFAULT_CONFIG = {
    "bride_name": "Ayşe",
    "groom_name": "Mert",
    "event_title": "Düğün Davetiyesi",
    "event_type": "Düğün",
    "date": "2026-09-12",
    "time": "19:30",
    "timezone": "Europe/Istanbul",
    "venue": "Beyaz Köşk Davet Salonu",
    "address": "Adana / Seyhan",
    "maps_url": "https://maps.google.com/",
    "rsvp_url": "https://wa.me/905555555555",
    "internal_rsvp_enabled": True,
    "rsvp_api_url": "",
    "rsvp_owner_url": "",
    "rsvp_list_file": "",
    "intro": "Bir ömür mutluluğa evet dediğimiz bu özel günde sizleri de aramızda görmekten mutluluk duyarız.",
    "quote": "Sevgiyle başlayan her hikaye, birlikte yazıldıkça güzelleşir.",
    "hosts": "Ailelerimiz adına davetlisiniz.",
    "bride_family_title": "Gelin Tarafı",
    "bride_family": "Ayşe Ailesi",
    "groom_family_title": "Damat Tarafı",
    "groom_family": "Mert Ailesi",
    "show_family_info": True,
    "show_photo_gallery": True,
    "show_venue_details": True,
    "luxury_subtitle": "Wedding Celebration",
    "monogram_text": "AB",
    "monogram_subtitle": "Luxury Black Collection",
    "venue_title": "Düğün Salonu Bilgileri",
    "venue_detail": "Raffles İstanbul, Bosphorus Ballroom",
    "venue_note": "1894, Karteito, Malronk, 28093",
    "gallery_image_1_file": "static/gallery/luxury_sample_1.jpg",
    "gallery_image_2_file": "static/gallery/luxury_sample_2.jpg",
    "gallery_image_3_file": "static/gallery/luxury_sample_3.jpg",
    "dress_code": "Şık / Zarif",
    "gift_note": "En güzel hediyeniz yanımızda olmanızdır.",
    "slug": "ayse-mert",
    "program": [
        {"clock":"19:30", "title":"Karşılama"},
        {"clock":"20:15", "title":"Nikah Merasimi"},
        {"clock":"21:00", "title":"İlk Dans"},
        {"clock":"21:30", "title":"Eğlence"}
    ],
    "theme": "royal_rose",
    "music_enabled": True,
    "music_file": "static/music/sample-romantik-chime.wav",
    "music_button_text": "Müziği Aç",
    "music_loop": True,
    "autoplay_hint": "Tarayıcı izin verirse müzik otomatik başlar; izin vermezse butona dokunun.",
    "show_countdown": True,
    "show_program": True,
    "show_rsvp_button": True,
    "show_map_button": True,
    "show_calendar_button": True,
    "show_dress_code": True,
    "show_gift_note": True,
    "show_corner_flower": True,
    "corner_flower_position": "right-bottom",
    "corner_flower_size": "large",
    "corner_flower_text": "Dokun",
    "corner_flower_emoji": "🌺",
    "corner_flower_image_enabled": False,
    "corner_flower_image_file": "",
    "tap_effect": "petal_burst",
    "falling_enabled": True,
    "ambient_wind_enabled": True,
    "falling_type": "theme",
    "falling_particle_image_enabled": False,
    "falling_particle_image_file": "",
    "falling_particle_size": 34,
    "falling_density": 24,
    "falling_speed": 13,
    "wind_strength": 42,
    "burst_count": 30,
    "glass_intensity": 68,
    "roundness": 34,
    "button_style": "pill",
    "hero_layout": "center",
    "extra_note": ""
}

TRUE_VALUES = {"1", "true", "on", "yes", "evet", "var"}
FALSE_VALUES = {"0", "false", "off", "no", "hayır", "yok", ""}


def slugify(value: str) -> str:
    value = (value or "davetiyem").strip().lower()
    replacements = str.maketrans("çğıöşüı", "cgiosui")
    value = value.translate(replacements)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "davetiyem"


def boolish(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default


def load_themes() -> dict:
    return json.loads(THEMES_PATH.read_text(encoding="utf-8"))


def normalize_config(raw: dict | None) -> dict:
    data = {**DEFAULT_CONFIG, **(raw or {})}
    bride = data.get("bride_name", "").strip() or DEFAULT_CONFIG["bride_name"]
    groom = data.get("groom_name", "").strip() or DEFAULT_CONFIG["groom_name"]
    data["bride_name"] = bride
    data["groom_name"] = groom
    data["couple"] = f"{bride} & {groom}"
    data["slug"] = slugify(data.get("slug") or f"{bride}-{groom}")

    program = data.get("program", [])
    if isinstance(program, str):
        parsed = []
        for line in program.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                clock, title = line.split("|", 1)
            elif "-" in line:
                clock, title = line.split("-", 1)
            else:
                clock, title = "", line
            parsed.append({"clock": clock.strip(), "title": title.strip()})
        data["program"] = parsed

    for key in [
        "music_enabled", "music_loop", "show_countdown", "show_program", "show_rsvp_button", "show_map_button",
        "show_calendar_button", "show_dress_code", "show_gift_note", "show_family_info", "show_photo_gallery", "show_venue_details", "show_corner_flower", "corner_flower_image_enabled", "falling_enabled", "falling_particle_image_enabled", "internal_rsvp_enabled", "ambient_wind_enabled"
    ]:
        data[key] = boolish(data.get(key), DEFAULT_CONFIG.get(key, False))

    for key, fallback in [("falling_density",24), ("falling_speed",13), ("wind_strength",42), ("burst_count",30), ("glass_intensity",68), ("roundness",34), ("falling_particle_size",34)]:
        try:
            data[key] = int(data.get(key, fallback))
        except Exception:
            data[key] = fallback

    data["human_date"] = data.get("date", "")
    try:
        dt = datetime.fromisoformat(f"{data.get('date')}T{data.get('time','00:00')}")
        months = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran","Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
        weekdays = ["Pazartesi","Salı","Çarşamba","Perşembe","Cuma","Cumartesi","Pazar"]
        data["human_date"] = f"{dt.day} {months[dt.month-1]} {dt.year}, {weekdays[dt.weekday()]}"
        data["iso_datetime"] = dt.strftime("%Y-%m-%dT%H:%M:%S")
        data["calendar_start"] = dt.strftime("%Y%m%dT%H%M00")
        data["calendar_end"] = dt.replace(hour=min(dt.hour+4,23)).strftime("%Y%m%dT%H%M00")
    except Exception:
        data["iso_datetime"] = ""
        data["calendar_start"] = ""
        data["calendar_end"] = ""
    return data


def copy_music_if_needed(data: dict, invite_dir: Path, explicit_music_path: str | Path | None = None) -> dict:
    music_value = explicit_music_path or data.get("music_file")
    data["music_src"] = ""
    if not data.get("music_enabled") or not music_value:
        return data
    source = Path(music_value)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists() or not source.is_file():
        return data
    target_dir = invite_dir / "assets" / "music"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = slugify(source.stem) + source.suffix.lower()
    target = target_dir / safe_name
    shutil.copy2(source, target)
    data["music_src"] = f"assets/music/{safe_name}"
    data["music_filename"] = source.name
    return data



def copy_corner_image_if_needed(data: dict, invite_dir: Path) -> dict:
    data["corner_flower_image_src"] = ""
    image_value = data.get("corner_flower_image_file")
    if not data.get("corner_flower_image_enabled") or not image_value:
        return data
    source = Path(str(image_value))
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists() or not source.is_file():
        return data
    target_dir = invite_dir / "assets" / "decorations"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = slugify(source.stem) + source.suffix.lower()
    target = target_dir / safe_name
    shutil.copy2(source, target)
    data["corner_flower_image_src"] = f"assets/decorations/{safe_name}"
    data["corner_flower_image_name"] = source.name
    return data




def copy_falling_particle_if_needed(data: dict, invite_dir: Path) -> dict:
    data["falling_particle_image_src"] = ""
    image_value = data.get("falling_particle_image_file")
    if not data.get("falling_particle_image_enabled") or not image_value:
        return data
    source = Path(str(image_value))
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists() or not source.is_file():
        return data
    target_dir = invite_dir / "assets" / "particles"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = slugify(source.stem) + source.suffix.lower()
    target = target_dir / safe_name
    shutil.copy2(source, target)
    data["falling_particle_image_src"] = f"assets/particles/{safe_name}"
    data["falling_particle_image_name"] = source.name
    return data


def copy_gallery_images_if_needed(data: dict, invite_dir: Path) -> dict:
    """Telefon lüks şablondaki 3 fotoğraf alanını davetiye klasörüne kopyalar."""
    data["gallery_images"] = []
    for idx in range(1, 4):
        value = data.get(f"gallery_image_{idx}_file")
        if not value:
            continue
        source = Path(str(value))
        if not source.is_absolute():
            source = ROOT / source
        if not source.exists() or not source.is_file():
            continue
        target_dir = invite_dir / "assets" / "gallery"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"galeri-{idx}-" + slugify(source.stem) + source.suffix.lower()
        target = target_dir / safe_name
        shutil.copy2(source, target)
        data["gallery_images"].append(f"assets/gallery/{safe_name}")
    return data

def copy_theme_assets_if_needed(theme: dict, invite_dir: Path) -> dict:
    theme = dict(theme)
    bg_value = theme.get("custom_background")
    theme["custom_background_src"] = ""
    if not bg_value:
        return theme
    source = Path(str(bg_value))
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists() or not source.is_file():
        return theme
    target_dir = invite_dir / "assets" / "designs"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = slugify(source.stem) + source.suffix.lower()
    target = target_dir / safe_name
    shutil.copy2(source, target)
    theme["custom_background_src"] = f"assets/designs/{safe_name}"
    return theme


def render_invitation(
    config: dict | None = None,
    template_key: str | None = None,
    out_dir: str | Path = DEFAULT_OUT,
    music_path: str | Path | None = None,
    theme_override: dict | None = None,
) -> Path:
    themes = load_themes()
    data = normalize_config(config)
    key = template_key or data.get("theme") or "royal_rose"
    if key not in themes:
        key = "royal_rose"
    data["theme"] = key
    theme = dict(theme_override) if theme_override else dict(themes[key])

    invite_dir = Path(out_dir) / data["slug"]
    invite_dir.mkdir(parents=True, exist_ok=True)
    theme = copy_theme_assets_if_needed(theme, invite_dir)
    data = copy_music_if_needed(data, invite_dir, music_path)
    data = copy_corner_image_if_needed(data, invite_dir)
    data = copy_falling_particle_if_needed(data, invite_dir)
    data = copy_gallery_images_if_needed(data, invite_dir)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html", "xml"]))
    template = env.get_template("invitation.html")
    html_out = template.render(
        data=data,
        theme=theme,
        data_json=json.dumps(data, ensure_ascii=False),
        theme_json=json.dumps(theme, ensure_ascii=False)
    )
    index_path = invite_dir / "index.html"
    index_path.write_text(html_out, encoding="utf-8")
    (invite_dir / "config.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def render_from_json(config_path: str | Path, template_key: str | None = None, out_dir: str | Path = DEFAULT_OUT, music_path: str | Path | None = None) -> Path:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return render_invitation(config, template_key=template_key, out_dir=out_dir, music_path=music_path)
