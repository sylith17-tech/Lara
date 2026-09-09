import re

def audit_callbacks():
    print("================ فحص تطابق الأزرار (Callback Data Audit) ================")
    
    # قراءة main_vip.py لمعرفة نصوص الـ callback_data الفعلية للأزرار
    try:
        with open("main_vip.py", "r", encoding="utf-8") as f:
            vip_code = f.read()
        vip_callbacks = re.findall(r'callback_data\s*=\s*["\']([^"\']+)["\']', vip_code)
        print(f"🔘 الأزرار المعرفة في main_vip.py ({len(vip_callbacks)}):")
        for cb in vip_callbacks:
            print(f"   -> callback_data = '{cb}'")
    except Exception as e:
        print(f"❌ خطأ في قراءة main_vip.py: {e}")

    # قراءة main.py لمعرفة الأنماط المرصودة (patterns)
    try:
        with open("main.py", "r", encoding="utf-8") as f:
            main_code = f.read()
        main_patterns = re.findall(r'pattern\s*=\s*["\']([^"\']+)["\']', main_code)
        print(f"\n🔗 الأنماط (Patterns) المرصودة في main.py ({len(main_patterns)}):")
        for pat in main_patterns:
            if any(k in pat for k in ['vip', 'video', 'stat']):
                print(f"   -> pattern = '{pat}'")
    except Exception as e:
        print(f"❌ خطأ في قراءة main.py: {e}")

    print("==========================================================================")

if __name__ == "__main__":
    audit_callbacks()
