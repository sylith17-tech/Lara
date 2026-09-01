import os
from telegram.ext import Application
from flask import Flask, request
from telegram import Update
import asyncio

TOKEN = os.environ.get('BOT_TOKEN', '8927003617:AAEyXIlPMr3zjA8M9TWA6znywR9kM4ANWJQ')
PORT = int(os.environ.get('PORT', 10000))

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.method == 'POST':
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, application.bot)
        
        async def run_async():
            await application.initialize()
            await application.process_update(update)
            
        asyncio.run(run_async())
        return 'OK', 200
    return 'OK', 200

@app.route('/')
def index():
    return 'Lara Bot is Alive!', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
