#!/bin/bash

echo "=========================================="
echo "    إعداد توكن البوت والـ Chat ID لـ Lara  "
echo "=========================================="

# طلب التوكن من المستخدم
read -p "أدخل توكن البوت (Telegram Bot Token): " BOT_TOKEN

# طلب Chat ID من المستخدم
read -p "أدخل Chat ID الخاص بالمجموعة أو المشرف: " CHAT_ID

# التأكد من وجود ملف .env أو إنشاؤه
if [ ! -f .env ]; then
    touch .env
fi

# تحديث أو إضافة TELEGRAM_BOT_TOKEN
if grep -q "^TELEGRAM_BOT_TOKEN=" .env; then
    sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${BOT_TOKEN}|" .env
else
    echo "TELEGRAM_BOT_TOKEN=${BOT_TOKEN}" >> .env
fi

# تحديث أو إضافة TELEGRAM_CHAT_ID
if grep -q "^TELEGRAM_CHAT_ID=" .env; then
    sed -i "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${CHAT_ID}|" .env
else
    echo "TELEGRAM_CHAT_ID=${CHAT_ID}" >> .env
fi

echo ""
echo "[✓] تم حفظ التوكن والـ Chat ID بنجاح في ملف .env!"
echo "=========================================="
