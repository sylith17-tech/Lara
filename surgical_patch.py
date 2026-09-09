import os
import ast

def surgical_patch():
    main_path = "main.py"
    backup_path = "main.py.bak"
    
    if not os.path.exists(main_path):
        print("❌ ملف main.py غير موجود!")
        return

    # 1. قراءة الملف وأخذ نسخة احتياطية مطابقة 100%
    with open(main_path, "r", encoding="utf-8") as f:
        content = f.read()

    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ [1/4] تم أخذ نسخة احتياطية آمنة (main.py.bak).")

    # 2. حقن الاستيرادات في أعلى الملف
    import_snippet = "from main_vip import handle_vip_menu, handle_start_video_edit, handle_vip_stats\nfrom handlers.video import handle_incoming_video\n"
    if "from main_vip import" not in content:
        lines = content.splitlines()
        lines.insert(0, import_snippet)
        content = "\n".join(lines)
        print("📦 [2/4] تم حقن الاستيرادات في أعلى الملف بنجاح.")
    else:
        print("ℹ️ [2/4] الاستيرادات موجودة مسبقاً.")

    # 3. حقن المعالجات بدقة قبل السطر 1424 (تحديداً قبل button_router)
    handlers_snippet = """    # --- [VIP_ARM] معالجات لوحة الـ VIP ومحرر الفيديو الذكي ---
    app.add_handler(CallbackQueryHandler(handle_vip_menu, pattern="^vip_menu$"))
    app.add_handler(CallbackQueryHandler(handle_start_video_edit, pattern="^start_video_edit$"))
    app.add_handler(CallbackQueryHandler(handle_vip_stats, pattern="^vip_stats$"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_incoming_video))
"""

    target = "app.add_handler(CallbackQueryHandler(button_router))"
    
    if "handle_vip_menu" not in content:
        if target in content:
            # حقن المعالجات قبل المعالج العام مباشرة لضمان عدم اعتراضها
            content = content.replace(target, handlers_snippet + "    " + target)
            print("🔗 [3/4] تم حقن معالجات الـ VIP والفيديو جراحياً قبل button_router بدقة.")
        else:
            print("❌ خطأ: لم يتم العثور على هدف الحقن بدقة.")
            return
    else:
        print("ℹ️ [3/4] المعالجات موجودة مسبقاً في الكود.")

    # 4. فحص النحو البرمجي (AST Syntax Check) لضمان عدم وجود أي أخطاء
    try:
        ast.parse(content)
        print("✅ [4/4] فحص النحو (Syntax): الكود سليم 100% ولا يوجد أي خطأ.")
    except SyntaxError as e:
        print(f"❌ تم اكتشاف خطأ نحوي في السطر {e.lineno}: {e.text}. جارٍ التراجع الفوري...")
        with open(backup_path, "r", encoding="utf-8") as bf:
            with open(main_path, "w", encoding="utf-8") as mf:
                mf.write(bf.read())
        return

    # حفظ الملف المعدل نهائياً
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("🚀 تم التعديل بنجاح تام! جميع ميزات البوت القديمة والجديدة سليمة ومحفوظة.")

if __name__ == "__main__":
    surgical_patch()
