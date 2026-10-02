"""Optional OpenAI Responses API parser with a strict local operation validator."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import requests

from .parser import EditPlan, parse_edit_request

ALLOWED_FIELDS = {
    "trim": {"type", "start", "end"}, "trim_audio": {"type", "start", "end"},
    "remove_audio": {"type"}, "extract_audio": {"type"},
    "replace_audio": {"type", "media_index", "source_video_index"},
    "mix_audio": {"type", "media_index", "volume"},
    "audio_fade": {"type", "duration", "direction"}, "audio_offset": {"type", "seconds"},
    "change_speed": {"type", "factor"}, "resize": {"type", "width", "height", "mode"},
    "compress": {"type", "crf"}, "concat_videos": {"type"},
    "overlay_image": {"type", "media_index", "duration", "position"},
    "text_overlay": {"type", "text"}, "volume": {"type", "volume"},
    "rotate": {"type", "degrees"}, "flip": {"type", "direction"},
    "fade": {"type", "duration", "direction"},
    "crop": {"type", "width", "height"}, "burn_subtitles": {"type", "media_index"},
    "brightness": {"type", "value"}, "contrast": {"type", "value"},
    "saturation": {"type", "value"}, "blur": {"type", "value"},
    "sharpen": {"type", "value"},
}
VIDEO_KINDS = {"video", "video_document"}
AUDIO_KINDS = {"audio", "audio_document", "voice"}


class IntentProviderError(RuntimeError):
    pass


def validate_model_plan(payload: dict[str, Any], media: list[Any]) -> EditPlan:
    plan = EditPlan()
    raw_ops = payload.get("operations", [])
    if not isinstance(raw_ops, list) or len(raw_ops) > 12:
        plan.clarification = "الطلب يحتوي خطوات كثيرة أو أن صيغة الخطة غير صالحة. قسّمه إلى طلبات أصغر."
        return plan
    videos = [m for m in media if getattr(m, "kind", "") in VIDEO_KINDS]
    audios = [m for m in media if getattr(m, "kind", "") in AUDIO_KINDS]
    images = [m for m in media if getattr(m, "kind", "") == "image"]
    subtitles = [m for m in media if getattr(m, "kind", "") == "subtitle"]
    for raw in raw_ops:
        if not isinstance(raw, dict) or raw.get("type") not in ALLOWED_FIELDS:
            plan.unsupported.append("اقترح المحلل عملية غير مدعومة؛ لم تُنفذ.")
            continue
        kind = raw["type"]
        op = {key: value for key, value in raw.items() if key in ALLOWED_FIELDS[kind]}
        if kind == "trim":
            kind = "trim_audio" if audios and not videos else "trim"
            op["type"] = kind
            try:
                start, end = float(op["start"]), float(op["end"])
                if start < 0 or end <= start or end > 7200:
                    raise ValueError
                op.update(start=start, end=end)
            except (KeyError, TypeError, ValueError):
                plan.clarification = "من أي ثانية إلى أي ثانية تريد القص؟"
                return plan
        elif kind == "trim_audio":
            if videos:
                plan.clarification = "هل تريد قص الفيديو أم قص ملف الصوت المرسل؟ أرسل طلبًا واحدًا لكل ناتج."
                return plan
            try:
                start, end = float(op["start"]), float(op["end"])
                if not audios or start < 0 or end <= start or end > 7200:
                    raise ValueError
                op.update(start=start, end=end)
            except (KeyError, TypeError, ValueError):
                plan.clarification = "أرسل ملفًا صوتيًا وحدد بداية القص ونهايته."
                return plan
        elif kind in ("remove_audio", "extract_audio", "replace_audio", "resize", "compress", "rotate", "flip",
                      "concat_videos", "overlay_image", "text_overlay", "burn_subtitles", "crop", "fade",
                      "brightness", "contrast", "saturation", "blur", "sharpen") and not videos:
            plan.clarification = "هذه العملية تتطلب فيديو. أرسله أولًا ثم أعد الطلب."
            return plan
        elif kind in ("replace_audio", "mix_audio"):
            source_video = op.get("source_video_index")
            if source_video is not None:
                if not isinstance(source_video, int) or source_video < 1 or source_video > len(videos):
                    plan.clarification = "حدد فيديو مصدر الصوت بترتيبه بين الفيديوهات المرسلة."
                    return plan
            elif not audios:
                plan.clarification = "أرسل ملف الصوت الذي تريد إضافته إلى الفيديو."
                return plan
            else:
                try:
                    media_index = int(op.get("media_index", 1))
                    if media_index < 1 or media_index > len(audios):
                        raise ValueError
                    op["media_index"] = media_index
                except (TypeError, ValueError):
                    plan.clarification = "اختر رقم ملف الصوت الذي تريد استخدامه."
                    return plan
            if kind == "mix_audio" and not videos and len(audios) < 2:
                plan.clarification = "أرسل ملفي صوت على الأقل لدمجهما."
                return plan
            if kind == "mix_audio":
                try:
                    op["volume"] = max(0.0, min(2.0, float(op.get("volume", 0.35))))
                except (TypeError, ValueError):
                    plan.clarification = "ما مستوى صوت الموسيقى المطلوب بين 0 و2؟"
                    return plan
        elif kind == "concat_videos" and len(videos) < 2:
            plan.clarification = "أرسل فيديوهين على الأقل لدمجهما."
            return plan
        elif kind == "overlay_image" and not images:
            plan.clarification = "أرسل الصورة التي تريد إضافتها إلى الفيديو."
            return plan
        elif kind == "overlay_image":
            try:
                media_index = int(op.get("media_index", 1))
                if media_index < 1 or media_index > len(images):
                    raise ValueError
                op["media_index"] = media_index
                if op.get("duration") is not None:
                    duration = float(op["duration"])
                    if not 0.1 <= duration <= 7200:
                        raise ValueError
                    op["duration"] = duration
            except (TypeError, ValueError):
                plan.clarification = "حدد صورة مرسلة ومدة ظهور صالحة."
                return plan
        elif kind == "burn_subtitles" and not subtitles:
            plan.unsupported.append("حرق الترجمة يتطلب ملف SRT/VTT مرفقًا.")
            continue
        elif kind == "burn_subtitles":
            try:
                media_index = int(op.get("media_index", 1))
                if media_index < 1 or media_index > len(subtitles):
                    raise ValueError
                op["media_index"] = media_index
            except (TypeError, ValueError):
                plan.clarification = "اختر ملف ترجمة SRT/VTT صحيحًا من الملفات المرسلة."
                return plan
        elif kind == "text_overlay" and (not isinstance(op.get("text"), str) or not op["text"].strip() or len(op["text"]) > 300):
            plan.clarification = "ما النص الذي تريد كتابته على الفيديو؟"
            return plan
        elif kind == "change_speed":
            try:
                factor = float(op["factor"])
                if not 0.25 <= factor <= 4:
                    raise ValueError
                op["factor"] = factor
            except (KeyError, TypeError, ValueError):
                plan.clarification = "حدد سرعة بين 0.25x و4x."
                return plan
        elif kind == "resize":
            try:
                width, height = int(op["width"]), int(op["height"])
                if not (64 <= width <= 3840 and 64 <= height <= 2160):
                    raise ValueError
                op.update(width=width, height=height)
            except (KeyError, TypeError, ValueError):
                plan.clarification = "حدد أبعادًا صالحة ضمن 64–3840 عرضًا و64–2160 ارتفاعًا."
                return plan
        elif kind in ("volume", "brightness", "contrast", "saturation", "blur", "sharpen", "compress", "rotate", "crop", "fade"):
            # The engine performs the operation-specific final validation too.
            try:
                for key in ("volume", "value", "crf", "degrees", "width", "height", "duration"):
                    if key in op:
                        op[key] = float(op[key])
            except (TypeError, ValueError):
                plan.clarification = "أحد مقادير العملية غير صالح. أعد تحديد القيمة."
                return plan
        plan.operations.append(op)
    clarification = payload.get("clarification")
    if isinstance(clarification, str) and clarification.strip():
        plan.clarification = clarification.strip()[:400]
    unsupported = payload.get("unsupported")
    if isinstance(unsupported, list):
        plan.unsupported.extend(str(x)[:250] for x in unsupported[:4])
    if any(op["type"] == "concat_videos" for op in plan.operations):
        plan.operations.sort(key=lambda op: 0 if op["type"] == "concat_videos" else 1)
    return plan


def _call_responses_api(prompt: str, media_summary: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("LARA_INTENT_MODEL", "gpt-4.1-mini")
    if not api_key:
        raise IntentProviderError("OPENAI_API_KEY is not configured")
    body = {
        "model": model,
        "store": False,
        "instructions": (
            "You parse Arabic and colloquial Arabic video-editing requests. Return only JSON with keys: "
            "operations (array), clarification (string or null), unsupported (array). Never produce shell commands. "
            "Use only operation types: trim, trim_audio, remove_audio, extract_audio, replace_audio, mix_audio, "
            "change_speed, resize, compress, concat_videos, overlay_image, text_overlay, volume, audio_fade, audio_offset, rotate, flip, "
            "fade, crop, burn_subtitles, brightness, contrast, saturation, blur, sharpen. "
            "Times are seconds; speed is a factor; select media by its order among the matching media kind. "
            "If a required time/value/file is missing or ambiguous, ask one concise Arabic clarification question. "
            "Speech recognition, translation, noise removal, and source separation are unsupported without providers."
        ),
        "input": json.dumps({"request": prompt[:1500], "available_media": media_summary}, ensure_ascii=False),
        "text": {"format": {"type": "json_object"}},
    }
    response = requests.post("https://api.openai.com/v1/responses",
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json=body, timeout=(5, 25))
    if response.status_code >= 400:
        raise IntentProviderError(f"Intent provider returned HTTP {response.status_code}")
    data = response.json()
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parsed = json.loads(content.get("text", ""))
                    if isinstance(parsed, dict):
                        return parsed
    raise IntentProviderError("Intent provider returned no structured text")


async def parse_natural_request(prompt: str, media: list[Any]) -> EditPlan:
    """Use configured AI only when explicitly enabled; otherwise use local Arabic parsing."""
    if os.getenv("LARA_USE_AI_INTENT", "").lower() not in ("1", "true", "yes"):
        return parse_edit_request(prompt, media)
    summary: list[dict[str, Any]] = []
    for item in media:
        kind = getattr(item, "kind", "unknown")
        order = 1 + sum(x["kind"] == kind for x in summary)
        summary.append({"kind": kind, "order_of_kind": order})
    try:
        payload = await asyncio.to_thread(_call_responses_api, prompt, summary)
        plan = validate_model_plan(payload, media)
        plan.source_text = prompt
        if plan.ready or plan.clarification or plan.unsupported:
            return plan
    except Exception:
        pass
    return parse_edit_request(prompt, media)
