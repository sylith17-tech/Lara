with open("main.py", "r", encoding="utf-8") as f:
    code = f.read()

# إصلاح استدعاء run_polling والتخلص من تضارب asyncio.run
old_main = """async def main():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).build()"""

new_main = """def main():
    asyncio.run(init_db())
    app = Application.builder().token(BOT_TOKEN).build()"""

code = code.replace(old_main, new_main)
code = code.replace("await app.run_polling()", "app.run_polling()")

with open("main.py", "w", encoding="utf-8") as f:
    f.write(code)

print("[+] main.py fixed successfully.")
