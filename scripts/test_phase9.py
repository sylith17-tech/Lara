import asyncio
from app.handlers.main_handler import MessageDispatcher

async def test_live_execution():
    dispatcher = MessageDispatcher()
    
    print("=== [ PHASE 9: Live Execution Framework Test ] ===\n")
    
    # محاكاة أحداث قادمة من التليجرام
    events = [
        {"user_id": 123456789, "username": "vip_arm", "first_name": "VIP ARM", "group_id": -100123456789, "group_title": "Lara Main Group", "text": "مرحبا يا لارا"},
        {"user_id": 123456789, "username": "vip_arm", "first_name": "VIP ARM", "group_id": -100123456789, "group_title": "Lara Main Group", "text": "احظر @spammer_user"},
        {"user_id": 987654321, "username": "alex_dev", "first_name": "Alex", "group_id": -100123456789, "group_title": "Lara Main Group", "text": "معلومات المجموعات"},
    ]

    for ev in events:
        response = await dispatcher.process_message(
            user_id=ev["user_id"],
            username=ev["username"],
            first_name=ev["first_name"],
            group_id=ev["group_id"],
            group_title=ev["group_title"],
            message_text=ev["text"]
        )
        print(f"👤 الرسالة من [{ev['first_name']}]: '{ev['text']}'")
        print(f"🤖 رد البوت: {response}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(test_live_execution())
