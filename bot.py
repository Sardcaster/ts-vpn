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
                "flow": "xtls-rprx-vision", # Если не Vision, оставь пустым ""
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
    # ⚠️ ВСТАВЬ СЮДА СВОЙ ШАБЛОН ССЫЛКИ ИЗ ПАНЕЛИ
    # Не забудь заменить PBK, SID и SNI на свои реальные значения!
    return f"vless://{uuid_str}@{SERVER_IP}:{VLESS_PORT}?type=tcp&security=reality&pbk=cGL0Zsjx2OkWTK5GLbcbyCFZ3rs5DgN0phuWhHlUawQ&fp=chrome&sni=google.com&sid=0c&spx=%2F#%F0%9F%87%AB%F0%9F%87%AE%20Finland-1%20%D0%BC%D0%B5%D1%81%D1%8F%D1%86&flow=xtls-rprx-vision#{email}"

# === ЮМАНИ ПЛАТЕЖИ ===
def create_payment(user_id, price):
    # Метка платежа: ID юзера + время, чтобы было уникально
    label = f"vpn_{user_id}_{int(time.time())}"
    
    quickpay = Quickpay(
            receiver=YM_WALLET,
            quickpay_form="shop",
            targets="VPN на 1 месяц",
            paymentType="SB", # SB = Банковская карта
            sum=price,
            label=label
            )
    return quickpay.base_url, label

def check_payment(label):
    try:
        client = Client(YM_TOKEN)
        # Ищем в истории входящих платежей нашу метку (label)
        history = client.operation_history(label=label)
        for op in history.operations:
            if op.status == 'success':
                return True
    except Exception as e:
        print(f"Ошибка проверки Юмани: {e}")
    return False

# === ЛОГИКА БОТА ===
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
    markup.add("🛒 Купить подписку (100р)", "👤 Мой ключ")
    
    bot.send_message(message.chat.id, "Привет! Это TS VPN 🚀\nЖми кнопку ниже.", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛒 Купить подписку (100р)")
def buy(message):
    price = 100 # Цена в рублях
    # 1. Создаем ссылку
    pay_url, label = create_payment(message.chat.id, price)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Оплатить картой (или СБП)", url=pay_url))
    # В кнопку проверки зашиваем метку (label)
    markup.add(types.InlineKeyboardButton("🔄 Я оплатил", callback_data=f"check_{label}"))
    
    bot.send_message(message.chat.id, 
                     f"Счет создан!\nЦена: {price} руб.\n\nНажми кнопку, оплати картой (или СБП), затем нажми 'Я оплатил'.", 
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def check_handler(call):
    label = call.data.split("_")[1]
    
    bot.answer_callback_query(call.id, "Проверяю оплату...")
    
    if check_payment(label):
        # === ОПЛАТА УСПЕШНА ===
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Оплата получена! Настраиваю сервер...")
        
        # 1. Данные для ключа
        new_uuid = str(uuid.uuid4())
        email = f"tg_{call.from_user.id}"
        
        # 2. Создаем в панели
        if add_client(new_uuid, email, days=30):
            # 3. Сохраняем в БД
            conn = sqlite3.connect('shop.db')
            c = conn.cursor()
            c.execute("UPDATE users SET vpn_uuid = ?, email = ? WHERE user_id = ?", 
                      (new_uuid, email, call.from_user.id))
            conn.commit()
            conn.close()
            
            # 4. Отдаем клиенту
            link = generate_link(new_uuid, email)
            bot.send_message(call.message.chat.id, 
                             f"🎉 **Подписка активирована!**\n\nТвоя ссылка:\n`{link}`\n\n(Нажми чтобы скопировать)", 
                             parse_mode='Markdown')
            
            # Уведомляем админа
            try:
                bot.send_message(ADMIN_ID, f"💰 **Продажа!**\nЮзер: @{call.from_user.username}\nСумма: 150р", parse_mode='HTML')
            except: pass
            
        else:
            bot.send_message(call.message.chat.id, "❌ Деньги пришли, но возникла ошибка при создании ключа. Перешлите это сообщение админу.")
            bot.send_message(ADMIN_ID, f"❌ Ошибка выдачи ключа для {call.from_user.username}. Деньги получены!")
            
    else:
        # === ОПЛАТА НЕ НАЙДЕНА ===
        bot.send_message(call.message.chat.id, "❌ Платеж пока не видим. Если оплатили только что - подождите минуту и нажмите кнопку снова.")

@bot.message_handler(func=lambda m: m.text == "👤 Мой ключ")
def my_key(message):
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("SELECT vpn_uuid, email FROM users WHERE user_id = ?", (message.chat.id,))
    res = c.fetchone()
    conn.close()
    
    if res and res[0]:
        link = generate_link(res[0], res[1])
        bot.send_message(message.chat.id, f"Твой ключ:\n`{link}`", parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "Активной подписки не найдено.")

if __name__ == "__main__":
    init_db()
    print("Бот запущен...")
    bot.infinity_polling()