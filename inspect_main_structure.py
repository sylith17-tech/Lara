import ast

def inspect_structure():
    print("================ فحص بنية ملف main.py ================")
    try:
        with open("main.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        tree = ast.parse(code)
        lines = code.splitlines()

        print("\n🔍 1. جميع أسطر تسجيل المعالجات (add_handler) الموجودة حالياً:")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'add_handler':
                    # استخراج رقم السطر والنص البرمجي بدقة
                    lineno = node.lineno
                    code_snippet = lines[lineno - 1].strip() if lineno <= len(lines) else "N/A"
                    print(f"   [السطر {lineno}] -> {code_snippet}")

        print("\n🔍 2. طريقة تشغيل البوت (Polling / Webhook):")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ['run_polling', 'run_webhook']:
                    lineno = node.lineno
                    code_snippet = lines[lineno - 1].strip() if lineno <= len(lines) else "N/A"
                    print(f"   [السطر {lineno}] -> {code_snippet}")

    except Exception as e:
        print(f"❌ حدث خطأ أثناء الفحص: {e}")
    print("\n=======================================================")

if __name__ == "__main__":
    inspect_structure()
