from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import math
from typing import Any

from PIL import Image, ImageStat
from werkzeug.utils import secure_filename

from invitation_engine import ROOT, slugify, load_themes, THEMES_PATH

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
CUSTOM_ASSET_DIR = ROOT / "theme_assets" / "custom_backgrounds"
CUSTOM_ASSET_DIR.mkdir(parents=True, exist_ok=True)


def image_allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = [v / 255 for v in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(rgb: tuple[int, int, int]) -> float:
    r, g, b = [v / 255 for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0
    return (mx - mn) / mx


def _mix(a: str, b: str, ratio: float) -> str:
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    ratio = max(0, min(1, ratio))
    return _hex((
        ar * (1 - ratio) + br * ratio,
        ag * (1 - ratio) + bg * ratio,
        ab * (1 - ratio) + bb * ratio,
    ))


def _pick_distinct(colors: list[tuple[str, int]], minimum_distance: int = 34, limit: int = 8) -> list[str]:
    picked: list[str] = []
    for color, _count in colors:
        rgb = _rgb(color)
        if all(math.sqrt(sum((rgb[i] - _rgb(p)[i]) ** 2 for i in range(3))) >= minimum_distance for p in picked):
            picked.append(color)
        if len(picked) >= limit:
            break
    return picked


def extract_palette(image_path: Path, color_count: int = 10) -> dict:
    img = Image.open(image_path)
    img = img.convert("RGBA")
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    background.alpha_composite(img)
    img = background.convert("RGB")
    img.thumbnail((360, 360))

    quantized = img.quantize(colors=18, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    counts = quantized.getcolors(maxcolors=360 * 360) or []

    weighted: list[tuple[str, int]] = []
    for count, idx in sorted(counts, reverse=True):
        r, g, b = palette[idx * 3: idx * 3 + 3]
        rgb = (r, g, b)
        lum = _luminance(rgb)
        sat = _saturation(rgb)
        weight = count
        if lum > .94 or lum < .06:
            weight = int(weight * .55)
        if sat < .08:
            weight = int(weight * .68)
        weighted.append((_hex(rgb), max(weight, 1)))

    weighted.sort(key=lambda x: x[1], reverse=True)
    palette_hex = _pick_distinct(weighted, limit=color_count)
    if len(palette_hex) < 4:
        palette_hex += ["#f8efe8", "#d8b45f", "#2c2430", "#ffffff"]

    stat = ImageStat.Stat(img)
    avg = tuple(int(v) for v in stat.mean[:3])
    avg_lum = _luminance(avg)

    colorful = sorted(palette_hex, key=lambda h: _saturation(_rgb(h)), reverse=True)
    accent = colorful[0]
    accent2 = colorful[1] if len(colorful) > 1 else _mix(accent, "#ffffff", .35)

    darks = sorted(palette_hex, key=lambda h: _luminance(_rgb(h)))
    lights = sorted(palette_hex, key=lambda h: _luminance(_rgb(h)), reverse=True)

    if avg_lum < .46:
        text = "#fff8ef"
        muted = _mix(text, accent2, .42)
        card = "rgba(18,14,18,.54)"
        bg = darks[0]
        bg2 = darks[1] if len(darks) > 1 else _mix(bg, "#000000", .30)
        gold = lights[0] if _saturation(_rgb(lights[0])) > .08 else _mix(accent, "#ffffff", .38)
    else:
        text = "#2b2328"
        muted = _mix(text, accent, .34)
        card = "rgba(255,255,255,.70)"
        bg = lights[0]
        bg2 = lights[1] if len(lights) > 1 else _mix(bg, accent, .14)
        gold = _mix(accent, "#b88931", .46)

    return {
        "palette": palette_hex,
        "average": _hex(avg),
        "is_dark": avg_lum < .46,
        "bg": bg,
        "bg2": bg2,
        "card": card,
        "text": text,
        "muted": muted,
        "accent": accent,
        "accent2": accent2,
        "gold": gold,
    }


def _build_theme_dict(
    *,
    image_path: Path,
    theme_name: str,
    particle: str,
    corner_flower: str,
    overlay_opacity: int,
    image_mode: str,
    background_position: str,
    frame_style: str,
    use_image_as_background: bool = True,
) -> dict[str, Any]:
    extracted = extract_palette(image_path)
    overlay_opacity = max(0, min(92, int(overlay_opacity or 45)))
    custom_bg = str(image_path) if use_image_as_background else ""
    return {
        "name": f"Özel: {theme_name.strip() or image_path.stem}",
        "season": "custom",
        "bg": extracted["bg"],
        "bg2": extracted["bg2"],
        "card": extracted["card"],
        "text": extracted["text"],
        "muted": extracted["muted"],
        "accent": extracted["accent"],
        "accent2": extracted["accent2"],
        "gold": extracted["gold"],
        "particle": particle or "🌸",
        "cornerFlower": corner_flower or "🌺",
        "ornament": "custom-image",
        "custom_background": custom_bg,
        "custom_background_fit": image_mode or "cover",
        "custom_background_position": background_position or "center center",
        "custom_overlay_opacity": overlay_opacity,
        "custom_frame_style": frame_style or "soft",
        "source_design_filename": image_path.name,
        "extracted_palette": extracted["palette"],
        "extracted_average": extracted["average"],
    }


def save_uploaded_design(uploaded_file, target_dir: Path | None = None) -> Path:
    if not uploaded_file or not uploaded_file.filename:
        raise ValueError("Görsel seçilmedi.")
    if not image_allowed(uploaded_file.filename):
        raise ValueError("Sadece PNG, JPG, JPEG veya WEBP yükleyebilirsin.")
    target_dir = target_dir or (ROOT / "uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_name = secure_filename(uploaded_file.filename)
    suffix = Path(raw_name).suffix.lower() or ".jpg"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    image_filename = f"design-{timestamp}{suffix}"
    image_path = target_dir / image_filename
    uploaded_file.save(image_path)
    return image_path


def build_runtime_theme_from_upload(
    *,
    uploaded_file,
    theme_name: str = "Özel Arkaplan",
    particle: str = "🌸",
    corner_flower: str = "🌺",
    overlay_opacity: int = 44,
    image_mode: str = "cover",
    background_position: str = "center center",
    frame_style: str = "soft",
    use_image_as_background: bool = True,
) -> dict[str, Any]:
    image_path = save_uploaded_design(uploaded_file)
    theme = _build_theme_dict(
        image_path=image_path,
        theme_name=theme_name,
        particle=particle,
        corner_flower=corner_flower,
        overlay_opacity=overlay_opacity,
        image_mode=image_mode,
        background_position=background_position,
        frame_style=frame_style,
        use_image_as_background=use_image_as_background,
    )
    return {"theme": theme, "image_path": str(image_path), "palette": theme.get("extracted_palette", [])}


def save_custom_theme(
    *,
    uploaded_file,
    theme_name: str,
    particle: str,
    corner_flower: str,
    overlay_opacity: int,
    image_mode: str,
    background_position: str,
    frame_style: str,
    use_image_as_background: bool = True,
) -> dict:
    image_path = save_uploaded_design(uploaded_file, CUSTOM_ASSET_DIR)
    raw_name = Path(image_path).name
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    clean_theme_name = theme_name.strip() or image_path.stem
    theme_key = f"ozel_{slugify(clean_theme_name)}_{timestamp}"
    final_suffix = image_path.suffix.lower() or ".jpg"
    final_name = f"{theme_key}{final_suffix}"
    final_path = CUSTOM_ASSET_DIR / final_name
    if image_path != final_path:
        image_path.replace(final_path)
    theme = _build_theme_dict(
        image_path=final_path,
        theme_name=clean_theme_name,
        particle=particle,
        corner_flower=corner_flower,
        overlay_opacity=overlay_opacity,
        image_mode=image_mode,
        background_position=background_position,
        frame_style=frame_style,
        use_image_as_background=use_image_as_background,
    )
    theme["custom_background"] = f"theme_assets/custom_backgrounds/{final_name}" if use_image_as_background else ""

    themes = load_themes()
    themes[theme_key] = theme
    THEMES_PATH.write_text(json.dumps(themes, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"key": theme_key, "theme": theme, "palette": theme.get("extracted_palette", []), "image_path": str(final_path)}
