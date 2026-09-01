import os
from telegram.ext import Application
from flask import Flask, request
import asyncio

TOKEN = os.environ.get('BOT_TOKEN', '8927003617:AAEyXIlPMr3zjA8M9TWA6znywR9kM4ANWJQ')
PORT = int(os.environ.get('PORT', 8080))

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_data = request.get_json(force=True)
    from telegram import Update
    update = Update.de_json(json_data, application.bot)
    asyncio.run(application.process_update(update))
    return 'OK', 200

@app.route('/')
def index():
    return 'Lara Bot is Alive!', 200

if __name__ == '__main__':
    application.initialize()
    application.bot.set_webhook(url=f'https://lara-iecv.onrender.com/{TOKEN}')
    app.run(host='0.0.0.0', port=PORT)
