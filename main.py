import os
from telegram.ext import Application
from flask import Flask, request
from telegram import Update
import asyncio

TOKEN = os.environ.get('BOT_TOKEN', '8927003617:AAEyXIlPMr3zjA8M9TWA6znywR9kM4ANWJQ')
PORT = int(os.environ.get('PORT', 8080))

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, application.bot)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.process_update(update))
        return 'OK', 200
    return 'Forbidden', 403

@app.route('/')
def index():
    return 'Lara Bot is Alive!', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
