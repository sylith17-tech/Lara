import os
import ast

def audit_file(filepath):
    print(f"\n================ FQ_AUDIT: {filepath} ================")
    if not os.path.exists(filepath):
        print(f"❌ الملف غير موجود: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. فحص الأخطاء النحوية (Syntax Errors)
    try:
        tree = ast.parse(content)
        print("✅ فحص النحو (Syntax): سليم 100% (لا توجد أخطاء برمجية)")
    except SyntaxError as e:
        print(f"❌ خطأ نحوي خطير في السطر {e.lineno}: {e.text}")
        return False

    # 2. استخراج المعالجات والاستيرادات الحالية
    imports = []
    handlers_found = []
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == 'add_handler':
                # محاولة استخراج نوع المعالج المسجل
                try:
                    handler_code = ast.unparse(node)
                    handlers_found.append(handler_code)
                except:
                    handlers_found.append("add_handler object")

    print(f"📦 إجمالي الاستيرادات الحالية: {len(imports)}")
    print(f"🔗 الـ Handlers المسجلة حالياً ({len(handlers_found)}):")
    for h in handlers_found:
        print(f"   -> {h}")
        
    return True

if __name__ == "__main__":
    audit_file("main.py")
    audit_file("main_vip.py")
    print("\n================ انتهاء الفحص الهندسي ================\n")
