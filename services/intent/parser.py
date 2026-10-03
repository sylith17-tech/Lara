"""Conservative Arabic/English edit parser; it emits data, never commands."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EditPlan:
    operations: list[dict[str, Any]] = field(default_factory=list)
    clarification: str | None = None
    unsupported: list[str] = field(default_factory=list)
    source_text: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.operations) and self.clarification is None and not self.unsupported


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _seconds(value: str, unit: str = "") -> float:
    value = value.translate(_DIGITS).strip()
    if ":" in value:
        parts = [float(p) for p in value.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    seconds = float(value)
    if unit and unit.startswith(("د", "min")):
        seconds *= 60
    elif unit and unit.startswith(("س", "hour", "h")):
        seconds *= 3600
    return seconds


def _time_pattern():
    return r"(\d+(?::\d{1,2}){0,2})\s*(ث(?:انيه|انية|واني)?|د(?:قيقه|قيقة|قائق)?|min(?:ute)?s?|sec(?:ond)?s?)?"


def parse_edit_request(text: str, media: list[Any] | None = None) -> EditPlan:
    """Parse a safe subset of common requests and ask about missing parameters."""
    raw = (text or "").strip()
    t = raw.translate(_DIGITS).lower()
    t = re.sub(r"[أإآٱ]", "ا", t)
    t = re.sub(r"ى", "ي", t)
    t = t.replace("ة", "ه")
    plan = EditPlan(source_text=raw)
    media = media or []
    video_count = sum(getattr(m, "kind", "") in ("video", "video_document") for m in media)
    audio_count = sum(getattr(m, "kind", "") in ("audio", "audio_document", "voice") for m in media)
    image_count = sum(getattr(m, "kind", "") == "image" for m in media)
    subtitle_items = [m for m in media if getattr(m, "kind", "") == "subtitle"]

    trim_words = r"قص|اقص|قطع|احذف.*(?:جزء|من)"
    range_match = re.search(r"(?:من\s*)?(?:الدقيقه\s*)?" + _time_pattern() +
                            r"\s*(?:الى|لحد|حتى|لـ|ل{1,2}|-)\s*(?:الدقيقه\s*)?" + _time_pattern(), t)
    minute_range = re.search(r"(?:من\s*)?الدقيقه\s*(\d+)\s*(?:الى|للدقيقه|ل|حتى)\s*(?:الدقيقه\s*)?(\d+)", t)
    first_match = re.search(r"(?:اول|أول)\s*(\d+)\s*(ث|دقيق|دقايق|دقائق|minute|min|second|sec)?", t)
    first_minute = re.search(r"(?:اول|أول)\s*(?:دقيقه|دقيقه واحده|دقيقة)", t)
    remove_head = re.search(r"(?:احذف|شيل|ازل|امسح).{0,12}(?:اول|البدايه)\s*(\d+)\s*(ث|دقيق|دقايق|دقائق)?", t)
    remove_tail = re.search(r"(?:احذف|شيل|ازل|امسح).{0,12}(?:اخر|النهايه)\s*(\d+)\s*(ث|دقيق|دقايق|دقائق)?", t)
    if remove_head or remove_tail:
        if video_count:
            amount = float((remove_head or remove_tail).group(1))
            unit = (remove_head or remove_tail).group(2) or "ث"
            seconds = amount * 60 if unit.startswith("د") else amount
            plan.operations.append({"type": "trim_head" if remove_head else "trim_tail", "duration": seconds})
        else:
            plan.clarification = "هذا القص يحتاج فيديو. أرسله أولًا."
    elif re.search(trim_words, t):
        trim_type = "trim_audio" if audio_count and not video_count else "trim"
        if minute_range:
            start, end = float(minute_range.group(1)) * 60, float(minute_range.group(2)) * 60
            if end <= start:
                plan.clarification = "وقت النهاية يجب أن يكون بعد وقت البداية. أرسل البداية والنهاية من جديد."
            else:
                plan.operations.append({"type": trim_type, "start": start, "end": end})
        elif range_match:
            start = _seconds(range_match.group(1), range_match.group(2) or "")
            end = _seconds(range_match.group(3), range_match.group(4) or "")
            if end <= start:
                plan.clarification = "وقت النهاية يجب أن يكون بعد وقت البداية. أرسل البداية والنهاية من جديد."
            elif end - start > 7200:
                plan.clarification = "مقطع القص أطول من الحد المسموح به (ساعتان)."
            else:
                plan.operations.append({"type": trim_type, "start": start, "end": end})
        elif first_match or first_minute:
            if first_minute and not first_match:
                amount, unit = 1.0, "دقيقة"
            else:
                amount = float(first_match.group(1))
                unit = (first_match.group(2) or "ث").lower()
            duration = amount * 60 if unit.startswith(("د", "min")) else amount
            plan.operations.append({"type": trim_type, "start": 0.0, "end": duration})
        elif re.search(r"(?:من\s*)?الدقيقه\s*\d+\s*(?:الى|ل|حتى)\s*(?:الدقيقه\s*)?\d+", t):
            # The range expression above handles this form, retain a clear fallback if punctuation/spacing varies.
            plan.clarification = "أرسل وقت البداية والنهاية بصيغة واضحة، مثل: من 02:00 إلى 03:00."
        else:
            plan.clarification = "من أي ثانية إلى أي ثانية تريد القص؟ مثال: من 00:10 إلى 01:20."

    if re.search(r"(?:شيل|احذف|ازيل|إزالة|اكتم|كتم).{0,15}(?:الصوت|صوت الفيديو|الصوت الاصلي)|(?:remove|mute).{0,10}audio", t):
        if video_count:
            plan.operations.append({"type": "remove_audio"})
        else:
            plan.clarification = "إزالة الصوت تتطلب فيديو يحتوي على مسار صوتي. أرسل الفيديو أولًا."
    if re.search(r"(?:استخرج|طلع|طلعلي|طلع لي).{0,15}(?:الصوت|صوت الفيديو|audio)", t):
        plan.operations.append({"type": "extract_audio"})
    if re.search(r"(?:خفف|وطي|قلل).{0,15}(?:صوت الفيديو|الصوت)", t) and "remove_audio" not in [o["type"] for o in plan.operations]:
        plan.operations.append({"type": "volume", "volume": 0.5})
    if re.search(r"(?:fade|تلاشي|خفف الصوت تدريجي|دخول الصوت تدريجي|خروج الصوت تدريجي)", t) and re.search(r"(?:الصوت|صوت|audio)", t):
        direction = "out" if re.search(r"(?:fade out|خروج|نهايه|نهاية)", t) else "in"
        duration_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ث|ثانيه|ثانية)", t)
        plan.operations.append({"type": "audio_fade", "direction": direction,
                                "duration": float(duration_match.group(1)) if duration_match else 1.0})
    offset = re.search(r"(قدم|قدّم|اخر|أخر).{0,12}(?:الصوت|صوت).{0,10}(\d+(?:\.\d+)?)\s*(?:ث|ثانيه|ثانية)", t)
    if offset:
        seconds = float(offset.group(2))
        plan.operations.append({"type": "audio_offset", "seconds": -seconds if offset.group(1).startswith("ق") else seconds})
    elif re.search(r"(?:زامن|تزامن).{0,10}(?:الصوت|صوت)", t):
        plan.clarification = plan.clarification or "كم ثانية تريد تقديم الصوت أو تأخيره؟"

    video_audio_source = re.search(r"(?:صوت|الصوت).{0,24}(?:الفيديو\s*)?(?:الثاني|التاني|2|من فيديو اخر)|(?:الفيديو\s*)?(?:الثاني|التاني|2).{0,16}(?:صوت|الصوت)", t)
    audio_request = re.search(r"(?:بدل|استبدل|حط|ضيف|اضف|اضافه|ركب|ادمج|اخلط|امزج).{0,35}(?:الصوت|صوتين|صوت|اغنيه|موسيقى|audio|song|music)", t)
    if audio_request:
        mix = bool(re.search(r"(?:بالخلفيه|بالخلفية|كخلفيه|كخلفية|ادمج|اخلط|امزج|mix)", t))
        if video_audio_source and video_count >= 2:
            plan.operations.append({"type": "replace_audio", "source_video_index": 2})
        elif audio_count == 0:
            plan.clarification = plan.clarification or "أرسل ملف الصوت أولًا، ثم أعد طلب إضافته أو استبداله."
        elif mix:
            if not video_count and audio_count < 2:
                plan.clarification = plan.clarification or "أرسل ملفي صوت على الأقل لدمجهما."
            else:
                plan.operations.append({"type": "mix_audio", "media_index": 2 if not video_count else 1, "volume": 0.35})
        elif not video_count:
            plan.clarification = plan.clarification or "أرسل فيديو لتبديل مساره الصوتي، أو اطلب دمج ملفي الصوت."
        else:
            plan.operations.append({"type": "replace_audio", "media_index": 1})

    speed = re.search(r"(?:سرع|سرّع|بسرعه|بسرعة|ضاعف).{0,18}(?:للضعف|مرتين|2x|2\s*مره|2\s*مرة|السرعه)?", t)
    speed_num = re.search(r"(?:سرع|سرّع|خليه|خليها|اجعله).{0,20}(\d+(?:\.\d+)?)\s*x", t)
    slow = re.search(r"(?:ابط[أا]ه|خليه أبطأ|خليه ابطا|ابطا|أبطأ|ابطأ|بطيء|slow)", t)
    if speed or speed_num or slow:
        factor = float(speed_num.group(1)) if speed_num else (2.0 if speed else 0.5)
        if not 0.25 <= factor <= 4:
            plan.clarification = "السرعة المدعومة بين 0.25x و4x. ما السرعة التي تريدها؟"
        else:
            plan.operations.append({"type": "change_speed", "factor": factor})

    vertical_flip = re.search(r"(?:اقلب|اعكس).{0,12}(?:عمودي|راسي|فوق|تحت)", t)
    if re.search(r"(?:عمودي|طولي|للموبايل|للريلز|للريل|للستوري|9\s*[:x/]\s*16|portrait|reels?)", t) and not vertical_flip:
        plan.operations.append({"type": "resize", "width": 1080, "height": 1920, "mode": "contain"})
    elif re.search(r"(?:16\s*[:x/]\s*9|youtube|لليوتيوب)", t):
        plan.operations.append({"type": "resize", "width": 1920, "height": 1080, "mode": "contain"})
    elif re.search(r"(?:1\s*[:x/]\s*1|مربع|square)", t):
        plan.operations.append({"type": "resize", "width": 1080, "height": 1080, "mode": "contain"})
    if re.search(r"(?:صغر|خفف|قلل).{0,15}(?:الحجم|حجمه|حجم|مساحه|size|file)", t):
        plan.operations.append({"type": "compress", "crf": 28})
    rotation = re.search(r"(?:دور|دوّر|لف|لفه|rotate).{0,12}(90|180|270)", t)
    if rotation:
        plan.operations.append({"type": "rotate", "degrees": int(rotation.group(1))})
    if re.search(r"(?:اقلب|اعكس).{0,12}(?:افقي|أفقي|يمين|يسار)", t):
        plan.operations.append({"type": "flip", "direction": "horizontal"})
    if re.search(r"(?:اقلب|اعكس).{0,12}(?:عمودي|رأسي|فوق|تحت)", t):
        plan.operations.append({"type": "flip", "direction": "vertical"})

    if re.search(r"(?:ادمج|اجمع|ضم).{0,20}(?:الفيديو|فيديوه|المقطعين|المقطعين|clips?)", t):
        if video_count < 2:
            plan.clarification = plan.clarification or "أرسل فيديوهين على الأقل، ثم اطلب دمجهما."
        else:
            plan.operations.append({"type": "concat_videos"})
    if any(op["type"] == "concat_videos" for op in plan.operations):
        plan.operations.sort(key=lambda op: 0 if op["type"] == "concat_videos" else 1)

    if re.search(r"(?:حط|ضع|ضيف|اضف|اضافه|overlay).{0,25}(?:الصوره|صوره|image)", t):
        if image_count == 0:
            plan.clarification = plan.clarification or "أرسل الصورة التي تريد إضافتها إلى الفيديو."
        else:
            duration_match = re.search(r"(?:اول|أول)\s*(\d+)\s*(?:ث|ثانيه|ثانية)", t)
            plan.operations.append({"type": "overlay_image", "media_index": 1,
                                    "duration": float(duration_match.group(1)) if duration_match else None,
                                    "position": "center"})

    requests_text = re.search(r"(?:حط|ضع|ضيف|أضف|اضف).{0,20}(?:كتابه|كتابة|نص|كلام)", t)
    image_in_middle = image_count and re.search(r"(?:بالنص|في النص|بالمنتصف|بالوسط)", t)
    if requests_text and not image_in_middle:
        plan.clarification = plan.clarification or "ما النص الذي تريد كتابته على الفيديو؟ أعد إرسال الطلب مع وضع النص بين علامتي اقتباس."
        quoted = re.search(r"[\"“](.+?)[\"”]", raw)
        if quoted:
            plan.operations.append({"type": "text_overlay", "text": quoted.group(1)})
            plan.clarification = None

    for intent, pattern in (("brightness", r"(?:سطوع|إضاءة|الاضاءه|اضاءه)"),
                            ("contrast", r"(?:تباين|كونتراست)"),
                            ("saturation", r"(?:تشبع|ألوان أكثر)"),
                            ("blur", r"(?:ضباب|تمويه|غبش)"),
                            ("sharpen", r"(?:حدة|وضح|تحسين الوضوح)")):
        match = re.search(pattern + r".{0,12}([+-]?\d+(?:\.\d+)?)", t)
        if match:
            value = max(-1.0, min(1.0, float(match.group(1))))
            plan.operations.append({"type": intent, "value": value})
    if re.search(r"(?:زود|ارفع|قوي).{0,12}(?:التباين|كونتراست)", t) and not any(o["type"] == "contrast" for o in plan.operations):
        plan.operations.append({"type": "contrast", "value": 0.2})
    if re.search(r"(?:زود|ارفع|قوي).{0,12}(?:الاضاءه|اضاءه|السطوع)", t) and not any(o["type"] == "brightness" for o in plan.operations):
        plan.operations.append({"type": "brightness", "value": 0.18})
    if re.search(r"(?:زود|قوي|خلي).{0,12}(?:الالوان|الوان|التشبع)", t) and not any(o["type"] == "saturation" for o in plan.operations):
        plan.operations.append({"type": "saturation", "value": 0.35})
    if re.search(r"(?:تمويه|ضباب).{0,12}(?:خفيف|بسيط)?", t) and not any(o["type"] == "blur" for o in plan.operations):
        plan.operations.append({"type": "blur", "value": 0.35})
    if re.search(r"(?:زود|حسن).{0,12}(?:الحده|حده|الوضوح)", t):
        plan.operations.append({"type": "sharpen", "value": 0.5})
    if re.search(r"(?:ابيض واسود|ابيض و اسود|اسود وابيض|grayscale|black and white)", t):
        plan.operations.append({"type": "grayscale"})
    if not re.search(r"(?:الصوت|صوت|audio)", t) and re.search(r"(?:اعمل|حط|ضيف|اضف).{0,10}(?:fade|تلاشي).{0,12}(?:البدايه|البداية|in)", t):
        plan.operations.append({"type": "fade", "direction": "in", "duration": 1.0})
    elif not re.search(r"(?:الصوت|صوت|audio)", t) and re.search(r"(?:اعمل|حط|ضيف|اضف).{0,10}(?:fade|تلاشي).{0,12}(?:النهايه|النهاية|out)", t):
        plan.operations.append({"type": "fade", "direction": "out", "duration": 1.0})
    if re.search(r"اعكس.{0,12}(?:الفيديو|المقطع)", t) and not re.search(r"(?:افقي|عمودي|رأسي)", t):
        plan.operations.append({"type": "reverse"})
    volume_percent = re.search(r"(?:ارفع|زود|علي|عليلي).{0,15}(?:الصوت|صوت).{0,8}(\d{2,3})\s*%", t)
    volume_percent = volume_percent or re.search(r"(?:الصوت|صوت).{0,8}(\d{2,3})\s*%", t)
    if volume_percent:
        plan.operations.append({"type": "volume", "volume": min(2.0, int(volume_percent.group(1)) / 100)})
    if re.search(r"(?:وازن|طبع|normalize).{0,12}(?:الصوت|صوت)?", t):
        plan.operations.append({"type": "normalize_audio"})
    hue = re.search(r"(?:hue|درجة اللون|لون الفيديو).{0,12}([+-]?\d{1,3})", t)
    if hue:
        plan.operations.append({"type": "hue", "value": max(-180, min(180, int(hue.group(1))))})
    if re.search(r"(?:نيجاتيف|negative|اعكس الالوان)", t):
        plan.operations.append({"type": "negative"})
    if re.search(r"(?:تظليل سينمائي|vignette|تغميق الاطراف)", t):
        plan.operations.append({"type": "vignette"})
    if re.search(r"(?:حبيبات فيلم|تحبيب|film grain)", t):
        plan.operations.append({"type": "film_grain"})
    if re.search(r"(?:دف[اي]|دفي|حراره الوان|حراره الالوان|الوان ادفى|warm)", t):
        plan.operations.append({"type": "temperature", "value": 0.45})
    elif re.search(r"(?:برد الوان|برد الالوان|الوان ابرد|cool)", t):
        plan.operations.append({"type": "temperature", "value": -0.45})

    if re.search(r"(?:ترجم|طلعلي الترجمه|طلع لي الترجمه|استخرج الترجمه|transcribe)", t):
        plan.unsupported.append("إنشاء/ترجمة الترجمة يحتاج مزود Speech-to-Text/ترجمة غير مهيأ حاليًا؛ لم تُنشأ نتيجة وهمية.")
    elif re.search(r"(?:حط|ضع|احرق|ثبت|ثبّت).{0,15}الترجمه", t):
        if subtitle_items:
            plan.operations.append({"type": "burn_subtitles", "media_index": 1})
        else:
            plan.clarification = plan.clarification or "أرسل ملف ترجمة SRT أو VTT أولًا لحرقه على الفيديو."
    if re.search(r"(?:شيل|احذف|خفف).{0,20}(?:الموسيقى|الموسيقي|music).{0,20}(?:الكلام|الصوت البشري|voice)", t):
        plan.unsupported.append("فصل الموسيقى عن الكلام يحتاج مزود فصل صوت خارجي غير مهيأ.")
    if re.search(r"(?:نظف|نظّف|ازيل|أزل|شيل|إزالة).{0,20}(?:الضجيج|الضوضاء|noise)", t):
        plan.unsupported.append("إزالة الضجيج تحتاج backend صوتيًا غير مهيأ حاليًا.")

    requires_video = {"trim", "trim_head", "trim_tail", "remove_audio", "extract_audio", "replace_audio", "resize", "compress", "grayscale", "reverse",
                      "rotate", "flip", "concat_videos", "overlay_image", "text_overlay", "burn_subtitles",
                      "crop", "fade", "brightness", "contrast", "saturation", "blur", "sharpen"}
    if not video_count and any(op["type"] in requires_video for op in plan.operations):
        plan.clarification = plan.clarification or "هذا التعديل يحتاج فيديو. أرسله أولًا ثم أعد الطلب."

    if not plan.operations and not plan.clarification and not plan.unsupported:
        plan.clarification = "لم أستطع تحديد تعديل مدعوم من الطلب. صف العملية والجزء أو القيمة المطلوبة، أو اختر عملية من القائمة."
    return plan
