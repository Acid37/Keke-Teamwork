"""Built-in assets (preset wallpapers, etc.)."""



from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Preset definitions: (id, label, category, svg_factory_name)
# Categories: 'dark' | 'light' | 'colorful'
PRESETS: list[dict] = [
    {"id": "midnight", "label": "午夜深空", "category": "dark", "style": "midnight"},
    {"id": "aurora", "label": "极光", "category": "colorful", "style": "aurora"},
    {"id": "geometry", "label": "几何极简", "category": "light", "style": "geometry"},
    {"id": "ocean", "label": "深海", "category": "dark", "style": "ocean"},
    {"id": "sunset", "label": "日落", "category": "colorful", "style": "sunset"},
    {"id": "paper", "label": "纸面", "category": "light", "style": "paper"},
]


def _svg_midnight() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<defs><radialGradient id="g" cx="30%" cy="20%" r="80%">'
        '<stop offset="0%" stop-color="#2a3a5c"/>'
        '<stop offset="60%" stop-color="#0f1729"/>'
        '<stop offset="100%" stop-color="#050811"/>'
        '</radialGradient></defs>'
        '<rect width="1920" height="1080" fill="url(#g)"/>'
        # stars
        '<g fill="#ffffff" opacity="0.6">'
        '<circle cx="180" cy="120" r="1.2"/><circle cx="420" cy="220" r="0.8"/>'
        '<circle cx="780" cy="80" r="1.5"/><circle cx="1200" cy="180" r="1.0"/>'
        '<circle cx="1560" cy="90" r="1.3"/><circle cx="1750" cy="280" r="0.9"/>'
        '<circle cx="340" cy="380" r="0.7"/><circle cx="980" cy="420" r="1.1"/>'
        '<circle cx="1440" cy="500" r="0.8"/><circle cx="220" cy="640" r="1.0"/>'
        '<circle cx="600" cy="720" r="0.6"/><circle cx="1100" cy="800" r="1.2"/>'
        '<circle cx="1620" cy="900" r="0.9"/><circle cx="1380" cy="640" r="0.7"/>'
        '</g>'
        '</svg>'
    )


def _svg_aurora() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#0a1a2f"/>'
        '<stop offset="100%" stop-color="#02060f"/>'
        '</linearGradient>'
        '<linearGradient id="aur" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#22d3ee" stop-opacity="0.0"/>'
        '<stop offset="30%" stop-color="#22d3ee" stop-opacity="0.7"/>'
        '<stop offset="60%" stop-color="#a78bfa" stop-opacity="0.6"/>'
        '<stop offset="100%" stop-color="#ec4899" stop-opacity="0.0"/>'
        '</linearGradient>'
        '<filter id="blur"><feGaussianBlur stdDeviation="30"/></filter>'
        '</defs>'
        '<rect width="1920" height="1080" fill="url(#bg)"/>'
        '<g filter="url(#blur)" opacity="0.85">'
        '<path d="M -100,400 C 400,200 800,700 1300,350 C 1700,150 1900,500 2100,400 L 2100,1080 L -100,1080 Z" fill="url(#aur)"/>'
        '<path d="M -100,600 C 300,450 700,800 1100,550 C 1500,400 1800,650 2100,550 L 2100,1080 L -100,1080 Z" fill="url(#aur)" opacity="0.6"/>'
        '</g>'
        '</svg>'
    )


def _svg_geometry() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<rect width="1920" height="1080" fill="#fafaf7"/>'
        '<g stroke="#1a1a1a" stroke-width="1.5" fill="none" opacity="0.85">'
        '<circle cx="960" cy="540" r="220"/>'
        '<circle cx="960" cy="540" r="380"/>'
        '<line x1="0" y1="540" x2="1920" y2="540"/>'
        '<line x1="960" y1="0" x2="960" y2="1080"/>'
        '<rect x="660" y="240" width="600" height="600" transform="rotate(45 960 540)"/>'
        '</g>'
        '<circle cx="960" cy="540" r="6" fill="#ef4444"/>'
        '</svg>'
    )


def _svg_ocean() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<defs><linearGradient id="o" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#0c4a6e"/>'
        '<stop offset="50%" stop-color="#082f49"/>'
        '<stop offset="100%" stop-color="#020617"/>'
        '</linearGradient></defs>'
        '<rect width="1920" height="1080" fill="url(#o)"/>'
        '<g stroke="#7dd3fc" stroke-width="1" fill="none" opacity="0.25">'
        '<path d="M 0,720 Q 480,680 960,720 T 1920,720"/>'
        '<path d="M 0,780 Q 480,740 960,780 T 1920,780"/>'
        '<path d="M 0,840 Q 480,800 960,840 T 1920,840"/>'
        '<path d="M 0,900 Q 480,860 960,900 T 1920,900"/>'
        '</g>'
        '<circle cx="1500" cy="280" r="80" fill="#fef3c7" opacity="0.85"/>'
        '</svg>'
    )


def _svg_sunset() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#fde68a"/>'
        '<stop offset="35%" stop-color="#fb923c"/>'
        '<stop offset="70%" stop-color="#db2777"/>'
        '<stop offset="100%" stop-color="#1e1b4b"/>'
        '</linearGradient></defs>'
        '<rect width="1920" height="1080" fill="url(#s)"/>'
        '<circle cx="960" cy="640" r="140" fill="#fef3c7" opacity="0.95"/>'
        '<circle cx="960" cy="640" r="200" fill="#fef3c7" opacity="0.15"/>'
        '</svg>'
    )


def _svg_paper() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
        '<rect width="1920" height="1080" fill="#f5f1e8"/>'
        '<g fill="#c2410c" opacity="0.08">'
        '<circle cx="380" cy="320" r="180"/>'
        '<circle cx="1480" cy="780" r="240"/>'
        '<circle cx="900" cy="180" r="120"/>'
        '</g>'
        '<g stroke="#1a1a1a" stroke-width="1" fill="none" opacity="0.3">'
        '<line x1="0" y1="540" x2="1920" y2="540" stroke-dasharray="4 8"/>'
        '</g>'
        '</svg>'
    )


_FACTORIES = {
    "midnight": _svg_midnight,
    "aurora": _svg_aurora,
    "geometry": _svg_geometry,
    "ocean": _svg_ocean,
    "sunset": _svg_sunset,
    "paper": _svg_paper,
}


def get_preset_dir(assets_root: Path) -> Path:
    """Directory where preset PNGs are cached."""
    return assets_root / "wallpapers"


def ensure_presets(assets_root: Path) -> list[dict]:
    """Make sure preset PNG files exist on disk; return their info.

    Strategy: write a tiny SVG (acts as the canonical preset) and let the
    frontend use `/api/wallpaper/preset/{id}` to fetch a PNG-converted file.
    For simplicity we just keep SVGs and serve them as-is (browsers render
    SVG via <img> just fine).
    """
    preset_dir = get_preset_dir(assets_root)
    preset_dir.mkdir(parents=True, exist_ok=True)

    result = []
    for preset in PRESETS:
        svg_path = preset_dir / f"preset-{preset['id']}.svg"
        if not svg_path.exists():
            svg_path.write_text(_FACTORIES[preset["style"]](), encoding="utf-8")
        result.append({
            "id": preset["id"],
            "label": preset["label"],
            "category": preset["category"],
            "filename": svg_path.name,
        })
    return result


def resolve_preset_path(assets_root: Path, preset_id: str) -> Path | None:
    """Return the filesystem path for a preset id, or None if unknown."""
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return get_preset_dir(assets_root) / f"preset-{preset_id}.svg"
    return None
