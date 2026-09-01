import os
import re

env_file = ".env"

if not os.path.exists(env_file):
    if os.path.exists(".env.example"):
        with open(".env.example", "r") as f:
            content = f.read()
        with open(env_file, "w") as f:
            f.write(content)
    else:
        with open(env_file, "w") as f:
            f.write("TELEGRAM_BOT_TOKEN=\nADMIN_CHAT_ID=\n")

token = input("\n[+] أدخل توكن البوت (Telegram Bot Token): ").strip()
chat_id = input("[+] أدخل الـ Chat ID الخاص بك (Telegram Chat ID): ").strip()

with open(env_file, "r") as f:
    content = f.read()

if "TELEGRAM_BOT_TOKEN=" in content:
    content = re.sub(r"TELEGRAM_BOT_TOKEN=.*", f"TELEGRAM_BOT_TOKEN={token}", content)
else:
    content += f"\nTELEGRAM_BOT_TOKEN={token}\n"

if "ADMIN_CHAT_ID=" in content:
    content = re.sub(r"ADMIN_CHAT_ID=.*", f"ADMIN_CHAT_ID={chat_id}", content)
else:
    content += f"\nADMIN_CHAT_ID={chat_id}\n"

with open(env_file, "w") as f:
    f.write(content)

print("\n[✓] تم حفظ التوكن والـ Chat ID بنجاح داخل ملف .env !\n")
