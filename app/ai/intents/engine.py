import re
from typing import Dict, Any, Optional

class IntentEngine:
    def __init__(self):
        # تعريف الأنماط والقواعد للتعرف على النوايا
        self.intent_patterns = {
            "BAN_USER": [
                r"احظر\s+(.*)",
                r"بان\s+(.*)",
                r"حظر\s+(.*)",
                r"/ban\s+(.*)"
            ],
            "MUTE_USER": [
                r"كتم\s+(.*)",
                r"اسكت\s+(.*)",
                r"/mute\s+(.*)"
            ],
            "UNBAN_USER": [
                r"فك\s+حظر\s+(.*)",
                r"/unban\s+(.*)"
            ],
            "GET_INFO": [
                r"معلومات\s+(.*)",
                r"منو\s+(.*)",
                r"ايدي\s+(.*)",
                r"/info",
                r"/id"
            ],
            "GREETING": [
                r"^هلا",
                r"^مرحبا",
                r"^السلام عليكم",
                r"^أهلا"
            ]
        }

    def parse(self, text: str) -> Dict[str, Any]:
        """تحليل النص واستخراج النية مع المتغيرات المرفقة"""
        if not text:
            return {"intent": "UNKNOWN", "target": None, "raw_text": ""}

        text_clean = text.strip()

        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, text_clean, re.IGNORECASE)
                if match:
                    target = match.group(1).strip() if match.groups() else None
                    return {
                        "intent": intent,
                        "target": target,
                        "raw_text": text_clean
                    }

        return {"intent": "GENERAL_CHAT", "target": None, "raw_text": text_clean}
