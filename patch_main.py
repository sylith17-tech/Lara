import os
import ast

def patch_main_file():
    main_path = "main.py"
    backup_path = "main.py.bak"
    
    if not os.path.exists(main_path):
        print("❌ خطأ: ملف main.py غير موجود!")
        return False

    # 1. إنشاء نسخة احتياطية آمنة قبل أي تعديل
    with open(main_path, "r", encoding="utf-8") as f:
        original_content = f.read()
        
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(original_content)
    print("✅ [1/5] تم إنشاء نسخة احتياطية آمنة للملف باسم: main.py.bak")

    import_snippet = "from main_vip import handle_vip_menu, handle_start_video_edit, handle_vip_stats\nfrom handlers.video import handle_incoming_video\n"
    
    handlers_snippet = """    # --- [VIP_ARM] معالجات لوحة الـ VIP ومحرر الفيديو الذكي ---
    app.add_handler(CallbackQueryHandler(handle_vip_menu, pattern="^vip_menu$"))
    app.add_handler(CallbackQueryHandler(handle_start_video_edit, pattern="^start_video_edit$"))
    app.add_handler(CallbackQueryHandler(handle_vip_stats, pattern="^vip_stats$"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_incoming_video))
"""

    content = original_content

    # 2. إدراج الاستيرادات إذا لم تكن موجودة
    if "from main_vip import" not in content:
        lines = content.splitlines()
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("import ") or line.startswith("from "):
                insert_idx = i
                break
        lines.insert(insert_idx, import_snippet.strip())
        content = "\n".join(lines)
        print("📦 [2/5] تم حقن الاستيرادات الجديدة في أعلى الملف بنجاح.")
    else:
        print("ℹ️ [2/5] الاستيرادات موجودة مسبقاً.")

    # 3. إدراج المعالجات قبل button_router
    if "handle_vip_menu" not in content:
        target_pattern = "app.add_handler(CallbackQueryHandler(button_router))"
        if target_pattern in content:
            content = content.replace(target_pattern, handlers_snippet + "    " + target_pattern)
            print("🔗 [3/5] تم حقن الـ Handlers بدقة قبل المعالج العام (button_router).")
        else:
            print("⚠️ تحذير: لم يتم العثور على button_router، يرجى مراجعة الملف يدوياً.")
            return False
    else:
        print("ℹ️ [3/5] المعالجات موجودة مسبقاً.")

    # 4. فحص النحو للتأكد من سلامة الكود البرمجي بعد التعديل
    try:
        ast.parse(content)
        print("✅ [4/5] فحص النحو (Syntax): الكود الجديد سليم 100% ولا توجد أخطاء.")
    except SyntaxError as e:
        print(f"❌ خطأ نحوي تم اكتشافه: {e.text}. جارٍ التراجع واستعادة النسخة الاحتياطية...")
        with open(backup_path, "r", encoding="utf-8") as f:
            with open(main_path, "w", encoding="utf-8") as wf:
                wf.write(f.read())
        return False

    # 5. الحفظ النهائي للملف المعدل
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("🚀 [5/5] تم تحديث وحفظ ملف main.py بنجاح تامة دون أي تدخل يدوي!")
    return True

if __name__ == "__main__":
    patch_main_file()
