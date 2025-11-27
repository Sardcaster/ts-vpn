import telebot
from telebot import types
import requests
import json
import uuid
import sqlite3
import time
import os
from dotenv import load_dotenv
from yoomoney import Quickpay, Client

# === ЗАГРУЗКА НАСТРОЕК ===
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
XUI_HOST = os.getenv('XUI_HOST')
XUI_USERNAME = os.getenv('XUI_USERNAME')
XUI_PASSWORD = os.getenv('XUI_PASSWORD')
INBOUND_ID = int(os.getenv('INBOUND_ID'))
SERVER_IP = os.getenv('SERVER_IP')
VLESS_PORT = os.getenv('VLESS_PORT')

YM_TOKEN = os.getenv('YOOMONEY_TOKEN')
YM_WALLET = os.getenv('YOOMONEY_WALLET')

bot = telebot.TeleBot(BOT_TOKEN)
session = requests.Session()

# Словарь для хранения ID последнего сообщения бота {chat_id: message_id}
# Это нужно для режима "Одного окна"
users_last_messages = {}

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        vpn_uuid TEXT,
        email TEXT,
        expiry_date INTEGER
    )''')
    conn.commit()
    conn.close()

# === ИНТЕГРАЦИЯ С 3X-UI ===
def login_to_xui():
    try:
        session.post(f"{XUI_HOST}/login", data={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    except:
        pass

def add_client(uuid_str, email, days=30):
    login_to_xui()
    # Вычисляем дату окончания (в миллисекундах)
    expire_time = int(time.time() * 1000) + (days * 24 * 60 * 60 * 1000)
    
    settings = {
        "clients": [
            {
                "id": uuid_str,
                "email": email,
                "enable": True,
                "flow": "xtls-rprx-vision",
                "expiryTime": expire_time
            }
        ]
    }
    
    payload = {"id": INBOUND_ID, "settings": json.dumps(settings)}
    headers = {'Content-Type': 'application/json'}
    
    try:
        resp = session.post(f"{XUI_HOST}/panel/api/inbounds/addClient", json=payload, headers=headers)
        return resp.json().get('success', False)
    except Exception as e:
        print(f"Ошибка X-UI: {e}")
        return False

def generate_link(uuid_str, email):
    # Твой шаблон с Reality настройками
    return f"vless://{uuid_str}@{SERVER_IP}:{VLESS_PORT}?type=tcp&security=reality&pbk=cGL0Zsjx2OkWTK5GLbcbyCFZ3rs5DgN0phuWhHlUawQ&fp=chrome&sni=google.com&sid=0c&spx=%2F#%F0%9F%87%AB%F0%9F%87%AE%20Finland-1%20%D0%BC%D0%B5%D1%81%D1%8F%D1%86&flow=xtls-rprx-vision#{email}"

# === ЮМАНИ ПЛАТЕЖИ ===
def create_payment(user_id, price):
    label = f"vpn_{user_id}_{int(time.time())}"
    
    quickpay = Quickpay(
            receiver=YM_WALLET,
            quickpay_form="shop",
            targets="VPN на 1 месяц",
            paymentType="SB", 
            sum=price,
            label=label
            )
    return quickpay.base_url, label

def check_payment(label):
    try:
        client = Client(YM_TOKEN)
        history = client.operation_history(label=label)
        for op in history.operations:
            if op.status == 'success':
                return True
    except Exception as e:
        print(f"Ошибка проверки Юмани: {e}")
    return False

# === СИСТЕМА ОДНОГО ОКНА (UI) ===

def clean_chat(chat_id, current_msg_id=None):
    """Удаляет старое сообщение, чтобы не мусорить."""
    if chat_id in users_last_messages:
        last_id = users_last_messages[chat_id]
        if current_msg_id and last_id == current_msg_id:
            return
        try:
            bot.delete_message(chat_id, last_id)
        except: pass

def send_or_edit(chat_id, text, markup, message_id=None):
    #Редактирует старое сообщение или отправляет новое.
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
            users_last_messages[chat_id] = message_id
            return
        except Exception:
            pass
    
    clean_chat(chat_id)
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    users_last_messages[chat_id] = msg.message_id

# --- ЭКРАНЫ МЕНЮ ---

def show_main_menu(chat_id, message_id=None):
    text = (
        "🚀 **TS VPN**\n\n"
        "Быстрый. Безопасный. Твой.\n"
        "Выберите действие:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🛒 Купить подписку (100р)", callback_data="goto_buy"),
        types.InlineKeyboardButton("👤 Мой ключ", callback_data="goto_profile"),
        types.InlineKeyboardButton("🆘 Поддержка", url="https://t.me/t_smirnoff")