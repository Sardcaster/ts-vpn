import telebot
from telebot import types
import requests
import json
import uuid
import sqlite3
import os
from dotenv import load_dotenv

# Загружаем настройки из файла .env
load_dotenv()

# Получаем переменные
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
XUI_HOST = os.getenv('XUI_HOST')
XUI_USERNAME = os.getenv('XUI_USERNAME')
XUI_PASSWORD = os.getenv('XUI_PASSWORD')
INBOUND_ID = int(os.getenv('INBOUND_ID'))
SERVER_IP = os.getenv('SERVER_IP')
VLESS_PORT = os.getenv('VLESS_PORT')

bot = telebot.TeleBot(BOT_TOKEN)
session = requests.Session()

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        vpn_uuid TEXT,
        email TEXT
    )''')
    conn.commit()
    conn.close()

# === API 3X-UI ===
def login_to_xui():
    try:
        session.post(f"{XUI_HOST}/login", data={"username": XUI_USERNAME, "password": XUI_PASSWORD})
    except Exception as e:
        print(f"Ошибка входа в панель: {e}")

def add_client(uuid_str, email):
    login_to_xui()
    # Настройки клиента. ВАЖНО: flow нужен только для Reality/Vision.
    # Если у тебя простой VLESS, flow оставь пустым: "flow": ""
    settings = {
        "clients": [
            {
                "id": uuid_str,
                "email": email,
                "enable": True,
                "flow": "xtls-rprx-vision" 
            }
        ]
    }
    
    payload = {
        "id": INBOUND_ID,
        "settings": json.dumps(settings)
    }
    
    headers = {'Content-Type': 'application/json'}
    try:
        response = session.post(f"{XUI_HOST}/panel/api/inbounds/addClient", json=payload, headers=headers)
        return response.json().get('success', False)
    except Exception as e:
        print(f"Ошибка API: {e}")
        return False

def generate_link(uuid_str, email):
    # ⚠️ СЮДА НУЖНО ВСТАВИТЬ ТВОЙ ШАБЛОН ССЫЛКИ
    # Скопируй реальную ссылку из панели и замени UUID и IP на переменные
    return f"vless://{uuid_str}@{SERVER_IP}:{VLESS_PORT}?type=tcp&security=reality&fp=chrome&pbk=CHANGE_ME&sni=google.com&sid=CHANGE_ME&spx=%2F#{email}"

# === БОТ ===
@bot.message_handler(commands=['start'])
def start(message):
    init_db()
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
              (message.chat.id, message.from_user.username))
    conn.commit()
    conn.close()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🛒 Купить VPN", "👤 Мой ключ")
    
    bot.send_message(message.chat.id, "Привет! Это TS VPN бот.", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛒 Купить VPN")
def buy(message):
    markup = types.InlineKeyboardMarkup()
    # Кнопка сразу ведет к оплате или проверке
    btn = types.InlineKeyboardButton("Оплатить 150р", callback_data="pay_manual")
    markup.add(btn)
    bot.send_message(message.chat.id, "Тариф: Месяц подписки\nЦена: 100 руб.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "pay_manual")
def manual_pay(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, 
                     "💳 Переведи 100р на карту: `0000 0000 0000 0000`\n\nКак переведешь - жми кнопку.", 
                     parse_mode='Markdown',
                     reply_markup=types.InlineKeyboardMarkup().add(
                         types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"confirm_{call.from_user.id}")
                     ))

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
def user_confirmed(call):
    bot.edit_message_text("⏳ Заявка отправлена админу...", call.message.chat.id, call.message.message_id)
    
    # Кнопка для админа
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Выдать доступ", callback_data=f"admin_yes_{call.from_user.id}"))
    
    bot.send_message(ADMIN_ID, 
                     f"💰 **Новая оплата!**\nОт: @{call.from_user.username}", 
                     reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_yes_"))
def admin_approve(call):
    client_id = call.data.split("_")[2]
    
    # Генерация
    new_uuid = str(uuid.uuid4())
    email = f"tg_{client_id}"
    
    if add_client(new_uuid, email):
        # Сохраняем в БД
        conn = sqlite3.connect('shop.db')
        c = conn.cursor()
        c.execute("UPDATE users SET vpn_uuid = ?, email = ? WHERE user_id = ?", (new_uuid, email, client_id))
        conn.commit()
        
        # Отправляем
        link = generate_link(new_uuid, email)
        bot.send_message(client_id, f"✅ Оплата принята!\nТвой ключ:\n`{link}`", parse_mode='Markdown')
        bot.send_message(ADMIN_ID, "✅ Клиент создан.")
    else:
        bot.send_message(ADMIN_ID, "❌ Ошибка создания клиента в панели.")

@bot.message_handler(func=lambda m: m.text == "👤 Мой ключ")
def my_key(message):
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("SELECT vpn_uuid, email FROM users WHERE user_id = ?", (message.chat.id,))
    res = c.fetchone()
    
    if res and res[0]:
        link = generate_link(res[0], res[1])
        bot.send_message(message.chat.id, f"Твой ключ:\n`{link}`", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "У тебя нет активной подписки.")

if __name__ == "__main__":
    init_db()
    print("Бот запущен...")
    bot.infinity_polling()