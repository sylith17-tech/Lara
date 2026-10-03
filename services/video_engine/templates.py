"""Local, deterministic Video Studio recipes composed only of engine operations."""
from __future__ import annotations

from copy import deepcopy


TEMPLATES: dict[str, dict] = {
    "cinematic_trailer": {"name": "Cinematic Trailer", "group": "🎬 سينمائي", "operations": [{"type": "contrast", "value": 0.2}, {"type": "saturation", "value": -0.12}, {"type": "fade", "direction": "in", "duration": 0.8}]},
    "dark_cinema": {"name": "Dark Cinema", "group": "🎬 سينمائي", "operations": [{"type": "brightness", "value": -0.1}, {"type": "contrast", "value": 0.24}, {"type": "saturation", "value": -0.1}]},
    "epic_trailer": {"name": "Epic Trailer", "group": "🎬 سينمائي", "operations": [{"type": "contrast", "value": 0.3}, {"type": "saturation", "value": 0.18}, {"type": "fade", "direction": "out", "duration": 1.0}]},
    "film_story": {"name": "Film Story", "group": "🎬 سينمائي", "operations": [{"type": "saturation", "value": -0.18}, {"type": "contrast", "value": 0.12}, {"type": "fade", "direction": "in", "duration": 0.7}]},
    "velocity_pro": {"name": "Velocity Pro", "group": "⚡ إيقاع سريع", "operations": [{"type": "change_speed", "factor": 1.25}, {"type": "contrast", "value": 0.16}]},
    "beat_rush": {"name": "Pulse Sprint", "group": "⚡ إيقاع سريع", "operations": [{"type": "change_speed", "factor": 1.5}, {"type": "saturation", "value": 0.22}]},
    "flash_motion": {"name": "Flash Motion", "group": "⚡ إيقاع سريع", "operations": [{"type": "change_speed", "factor": 1.25}, {"type": "brightness", "value": 0.12}, {"type": "contrast", "value": 0.18}]},
    "glitch_energy": {"name": "High Energy", "group": "⚡ إيقاع سريع", "operations": [{"type": "contrast", "value": 0.28}, {"type": "saturation", "value": 0.35}, {"type": "change_speed", "factor": 1.25}]},
    "impact": {"name": "Impact", "group": "⚡ إيقاع سريع", "operations": [{"type": "contrast", "value": 0.35}, {"type": "fade", "direction": "in", "duration": 0.35}]},
    "viral_short": {"name": "Viral Short", "group": "📱 صانع محتوى", "operations": [{"type": "resize", "width": 1080, "height": 1920}, {"type": "brightness", "value": 0.08}, {"type": "saturation", "value": 0.24}]},
    "fast_hook": {"name": "Fast Hook", "group": "📱 صانع محتوى", "operations": [{"type": "resize", "width": 1080, "height": 1920}, {"type": "change_speed", "factor": 1.25}, {"type": "contrast", "value": 0.18}]},
    "talking_head": {"name": "Talking Head Pro", "group": "📱 صانع محتوى", "operations": [{"type": "brightness", "value": 0.08}, {"type": "contrast", "value": 0.1}, {"type": "sharpen", "value": 0.25}]},
    "mini_vlog": {"name": "Mini Vlog", "group": "📱 صانع محتوى", "operations": [{"type": "saturation", "value": 0.18}, {"type": "brightness", "value": 0.06}, {"type": "fade", "direction": "in", "duration": 0.5}]},
    "day_in_life": {"name": "Day in My Life", "group": "📱 صانع محتوى", "operations": [{"type": "saturation", "value": 0.12}, {"type": "contrast", "value": 0.08}, {"type": "fade", "direction": "out", "duration": 0.8}]},
    "storytelling": {"name": "Storytelling Pro", "group": "📱 صانع محتوى", "operations": [{"type": "contrast", "value": 0.14}, {"type": "saturation", "value": -0.05}, {"type": "fade", "direction": "in", "duration": 0.7}]},
    "music_montage": {"name": "Visual Montage", "group": "🎵 مونتاج", "operations": [{"type": "contrast", "value": 0.18}, {"type": "saturation", "value": 0.22}, {"type": "fade", "direction": "out", "duration": 0.7}]},
    "bass_impact": {"name": "Bold Impact", "group": "🎵 مونتاج", "operations": [{"type": "contrast", "value": 0.3}, {"type": "brightness", "value": -0.04}, {"type": "fade", "direction": "in", "duration": 0.25}]},
    "clean_creator": {"name": "Clean Creator", "group": "✨ عصري", "operations": [{"type": "brightness", "value": 0.05}, {"type": "contrast", "value": 0.08}, {"type": "sharpen", "value": 0.2}]},
    "luxury": {"name": "Luxury", "group": "✨ عصري", "operations": [{"type": "saturation", "value": -0.08}, {"type": "contrast", "value": 0.2}, {"type": "brightness", "value": -0.02}]},
    "neon_future": {"name": "Neon Future", "group": "✨ عصري", "operations": [{"type": "saturation", "value": 0.4}, {"type": "contrast", "value": 0.2}, {"type": "hue", "value": 12}]},
    "cyber": {"name": "Cyber", "group": "✨ عصري", "operations": [{"type": "saturation", "value": 0.3}, {"type": "contrast", "value": 0.25}, {"type": "hue", "value": -10}]},
    "y2k_remix": {"name": "Y2K Remix", "group": "✨ عصري", "operations": [{"type": "saturation", "value": 0.32}, {"type": "brightness", "value": 0.08}, {"type": "contrast", "value": 0.16}]},
    "minimal_pro": {"name": "Minimal Pro", "group": "✨ عصري", "operations": [{"type": "saturation", "value": -0.08}, {"type": "brightness", "value": 0.03}, {"type": "contrast", "value": 0.08}]},
    "product_showcase": {"name": "Product Showcase", "group": "📸 أعمال", "operations": [{"type": "contrast", "value": 0.18}, {"type": "saturation", "value": 0.14}, {"type": "sharpen", "value": 0.2}]},
    "before_after": {"name": "Before / After", "group": "📸 أعمال", "operations": [{"type": "contrast", "value": 0.12}, {"type": "saturation", "value": 0.12}, {"type": "fade", "direction": "in", "duration": 0.4}]},
    "tutorial_pro": {"name": "Tutorial Pro", "group": "📸 أعمال", "operations": [{"type": "brightness", "value": 0.06}, {"type": "contrast", "value": 0.12}, {"type": "sharpen", "value": 0.18}]},
    "promo_ad": {"name": "Promo / Ad", "group": "📸 أعمال", "operations": [{"type": "contrast", "value": 0.2}, {"type": "saturation", "value": 0.18}, {"type": "fade", "direction": "out", "duration": 0.8}]},
    "portfolio_reel": {"name": "Portfolio Reel", "group": "📸 أعمال", "operations": [{"type": "resize", "width": 1080, "height": 1920}, {"type": "contrast", "value": 0.14}, {"type": "saturation", "value": 0.12}]},
    "bright_pop": {"name": "Bright Pop", "group": "✨ عصري", "operations": [{"type": "brightness", "value": 0.16}, {"type": "saturation", "value": 0.2}]},
    "monochrome_story": {"name": "Monochrome Story", "group": "🎬 سينمائي", "operations": [{"type": "grayscale"}, {"type": "contrast", "value": 0.18}, {"type": "fade", "direction": "in", "duration": 0.6}]},
}

TEMPLATE_IDS = tuple(TEMPLATES)
ALLOWED_TEMPLATE_OPS = {"brightness", "contrast", "saturation", "hue", "grayscale", "change_speed", "resize", "sharpen", "fade"}


def get_template(template_id: str) -> dict:
    try:
        template = TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError("Unknown Video Studio template") from exc
    operations = template.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("Template pipeline is empty")
    for operation in operations:
        if operation.get("type") not in ALLOWED_TEMPLATE_OPS:
            raise ValueError("Template uses an unsupported operation")
    return {**template, "operations": deepcopy(operations)}
