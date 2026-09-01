import asyncio
from app.ai.intents.engine import IntentEngine

def test_intent_engine():
    engine = IntentEngine()
    
    test_cases = [
        "احظر @bad_user",
        "كتم المستخدم123",
        "معلومات المجموعات",
        "مرحبا يا لارا",
        "اقترح علي كتاب ممتاز في البرمجة"
    ]
    
    print("=== [ PHASE 8: Intent Engine Test ] ===\n")
    for text in test_cases:
        result = engine.parse(text)
        print(f"النص: '{text}'")
        print(f"  └─ النية المكتشفة: {result['intent']}")
        print(f"  └─ الهدف/الهدف المرفق: {result['target']}")
        print("-" * 40)

if __name__ == "__main__":
    test_intent_engine()
