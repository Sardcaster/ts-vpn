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

# ... инициализация бота ...
bot = telebot.TeleBot(BOT_TOKEN)
# Словарь для запоминания последнего сообщения бота
# Структура: {user_id: message_id}
last_bot_messages = {}
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

def delete_last_message(chat_id):
    """Удаляет последнее сообщение бота в этом чате, если оно записано"""
    if chat_id in last_bot_messages:
        msg_id = last_bot_messages[chat_id]
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass # Если сообщение уже удалено или не найдено - не страшно
        # Убираем из памяти
        del last_bot_messages[chat_id]

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

@bot.message_handler(func=lambda m: m.text == "🛒 Купить подписку (100р)") # Или какой у тебя текст
def buy(message):
    # 1. Сначала удаляем старое сообщение (то самое, что дублируется на скрине)
    delete_last_message(message.chat.id)

    price = 100
    pay_url, label = create_payment(message.chat.id, price) # (Твоя функция создания ссылки)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Оплатить картой (или СБП)", url=pay_url))
    markup.add(types.InlineKeyboardButton("🔄 Я оплатил", callback_data=f"check_{label}"))
    
    # 2. Отправляем новое сообщение и СОХРАНЯЕМ его в переменную msg
    msg = bot.send_message(message.chat.id, 
                     f"Счет создан!\nЦена: {price} руб.\n\nНажми кнопку, оплати картой (или СБП), затем нажми 'Я оплатил'.", 
                     reply_markup=markup)
    
    # 3. Запоминаем ID этого сообщения в словарь
    last_bot_messages[message.chat.id] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def check_handler(call):
    label = call.data.split("_")[1]
    
    # ⚠️ МЫ УБРАЛИ ОТСЮДА СТРОЧКУ "Проверяю оплату..."
    # Теперь бот сначала проверит, а потом ответит результатом.
    
    if check_payment(label):
        # === ЕСЛИ ОПЛАТА ЕСТЬ ===
        bot.answer_callback_query(call.id, "✅ Оплата принята!", show_alert=False)
        
        # 1. Удаляем сообщение с кнопкой оплаты
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        
        # 2. Чистим память дублей
        if call.message.chat.id in last_bot_messages:
             del last_bot_messages[call.message.chat.id]

        bot.send_message(call.message.chat.id, "✅ Оплата получена! Выдаю доступ...")
        
        # === ВЫДАЧА КЛЮЧА ===
        new_uuid = str(uuid.uuid4())
        email = f"tg_{call.from_user.id}"
        
        # Логика выдачи (как была раньше)
        if add_client(new_uuid, email, days=30):
            # Сохраняем в БД (Используем REPLACE на случай пересоздания)
            conn = sqlite3.connect('shop.db')
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO users (user_id, username, vpn_uuid, email) 
                VALUES (?, ?, ?, ?)
            """, (call.from_user.id, call.from_user.username, new_uuid, email))
            conn.commit()
            conn.close()
            
            link = generate_link(new_uuid, email)
            bot.send_message(call.message.chat.id, 
                             f"🎉 **Подписка активирована!**\n\nТвоя ссылка:\n`{link}`", 
                             parse_mode='Markdown')
            try:
                bot.send_message(ADMIN_ID, f"💰 Продажа @{call.from_user.username}", parse_mode='HTML')
            except: pass
        else:
            bot.send_message(call.message.chat.id, "Ошибка выдачи. Админ уведомлен.")
            bot.send_message(ADMIN_ID, f"❌ Ошибка выдачи ключа для {call.from_user.username}. Деньги получены!")
            
    else:
        # === ЕСЛИ ОПЛАТЫ НЕТ ===
        # Теперь эта строчка сработает, потому что мы не отвечали раньше!
        # show_alert=True покажет всплывающее окно по центру экрана
        bot.answer_callback_query(call.id, "❌ Оплата еще не пришла. Попробуйте через минуту.", show_alert=True)

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