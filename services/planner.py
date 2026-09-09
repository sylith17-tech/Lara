import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# 🛡️ قائمة العمليات المسموح بها حصراً (Whitelist Security Policy)
ALLOWED_OPERATIONS = {
    "trim", "resize", "aspect_ratio", "mute", "volume", 
    "speed", "rotate", "crop", "subtitles", "object_removal", 
    "cinematic_style", "background_change"
}

# ⚙️ جدول التوجيه الذكي (يقرر أين تُنفذ العملية بدقة)
OPERATION_ROUTER = {
    "trim": "ffmpeg",
    "resize": "ffmpeg",
    "aspect_ratio": "ffmpeg",
    "mute": "ffmpeg",
    "volume": "ffmpeg",
    "speed": "ffmpeg",
    "rotate": "ffmpeg",
    "crop": "ffmpeg",
    "subtitles": "stt_ffmpeg",
    "object_removal": "model_a",
    "background_change": "model_a",
    "cinematic_style": "model_b"
}

def validate_and_filter_plan(ai_response_json: str) -> List[Dict[str, Any]]:
    """فحص صارم للـ JSON الناتج من الـ AI والتأكد من مطابقته للـ Whitelist"""
    try:
        data = json.loads(ai_response_json)
        raw_operations = data.get("operations", [])
        
        validated_operations = []
        for op in raw_operations:
            op_type = op.get("type")
            
            # منع أي عملية غير موجودة في الـ Whitelist تماماً
            if op_type in ALLOWED_OPERATIONS:
                target_engine = OPERATION_ROUTER.get(op_type, "ffmpeg")
                op["engine"] = target_engine
                validated_operations.append(op)
            else:
                logger.warning(f"[Security Alert] Blocked unauthorized operation attempt: {op_type}")
                
        return validated_operations
    except json.JSONDecodeError:
        logger.error("[AI Planner] Failed to parse AI response as JSON.")
        return []
    except Exception as e:
        logger.error(f"[AI Planner Error] {e}")
        return []
