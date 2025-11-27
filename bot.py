import secrets
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
# Нужен для режима "Одного окна"
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

def add_client(uuid_str, sub_id_str, email, days=30):
    login_to_xui()
    # Вычисляем дату окончания (в миллисекундах)
    expire_time = int(time.time() * 1000) + (days * 24 * 60 * 60 * 1000)
    
    settings = {
        "clients": [
            {
                "id": uuid_str,
                "subId": sub_id_str,
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

def generate_sub_link(sub_id_str):
    # Нам нужен порт панели. Обычно он есть в XUI_HOST (например http://127.0.0.1:2053)
    # Но для клиента нам нужен ВНЕШНИЙ IP.
    
    # 1. Вытаскиваем порт панели из настройки (например, 2053)
    # Если ты помнишь порт наизусть, можешь просто написать panel_port = "2053"
    panel_port = "2096" 
    
    # 2. Формируем ссылку-подписку
    # Формат: http://IP:PORT/sub/UUID
    sub_link = f"http://{SERVER_IP}:{panel_port}/sub/{sub_id_str}"
    
    return sub_link


# === ЮМАНИ ПЛАТЕЖИ ===
# === ЮМАНИ ===
def create_payment(user_id, price):
    label = f"vpn_{user_id}_{int(time.time())}"
    quickpay = Quickpay(
            receiver=YM_WALLET,
            quickpay_form="shop",
            targets="VPN 1 месяц",
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
    except: pass
    return False

# === UI HELPERS ===
def clean_chat(chat_id, current_msg_id=None):
    if chat_id in users_last_messages:
        last_id = users_last_messages[chat_id]
        if current_msg_id and last_id == current_msg_id: return
        try: bot.delete_message(chat_id, last_id)
        except: pass

def send_or_edit(chat_id, text, markup, message_id=None):
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
            users_last_messages[chat_id] = message_id
            return
        except: pass
    clean_chat(chat_id)
    msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
    users_last_messages[chat_id] = msg.message_id

# === ЭКРАНЫ МЕНЮ ===

def show_main_menu(chat_id, message_id=None):
    text = (
        "🚀 **TS VPN**\n\n"
        "Быстрый. Стабильный. Твой.\n"
        "Выберите действие:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🛒 Купить подписку (100р)", callback_data="goto_buy"),
        types.InlineKeyboardButton("👤 Мой ключ", callback_data="goto_profile"),
        types.InlineKeyboardButton("📚 Как подключить (Happ)", callback_data="goto_instructions"),
        types.InlineKeyboardButton("🆘 Поддержка", url=f"tg://user?id={ADMIN_ID}")
    )
    send_or_edit(chat_id, text, markup, message_id)

def show_payment_method(chat_id, message_id):
    price = 100
    pay_url, label = create_payment(chat_id, price)
    
    text = (
        f"💳 **Оплата подписки**\n\n"
        f"Цена: **{price} руб.**\n"
        f"Срок: **30 дней**\n\n"
        f"1. Нажмите кнопку «Оплатить» (Карта РФ / СБП).\n"
        f"2. После оплаты нажмите «Я оплатил»."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🔗 Оплатить через ЮMoney", url=pay_url))
    markup.add(types.InlineKeyboardButton("🔄 Я оплатил", callback_data=f"check_{label}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="goto_main"))
    
    send_or_edit(chat_id, text, markup, message_id)

def show_profile(chat_id, message_id):
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("SELECT sub_id, email FROM users WHERE user_id = ?", (chat_id,))
    res = c.fetchone()
    conn.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="goto_main"))

    if res and res[0]:
        # Получаем теперь не vless://, а http://...
        link = generate_sub_link(res[0], res[1]) 
        
        text = (
            f"👤 **Твой профиль**\n\n"
            f"✅ Подписка активна!\n\n"
            f"🔗 **Ссылка-подписка:**\n"
            f"`{link}`\n\n"
            f"Открой ссылку в стороннем браузере (НЕ во встроенном в Telegram), внизу выбери свое операционную систему -> **Happ**\n"
            f"Или нажми на ссылку, чтобы скопировать.\n"
            f"И вставляй её в приложение в раздел **Subscription** (Подписки)."
        )
    else:
        text = "👤 **Твой профиль**\n\n❌ Активной подписки нет.\nПерейдите в меню и нажмите «Купить»."
    
    send_or_edit(chat_id, text, markup, message_id)

def show_instructions_menu(chat_id, message_id):
    text = (
        "📲 **Настройка подключения (Happ)**\n\n"
        "Выберите ваше устройство:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🍏 iOS (iPhone)", callback_data="guide_ios"),
        types.InlineKeyboardButton("🤖 Android", callback_data="guide_android"),
        types.InlineKeyboardButton("💻 Windows", callback_data="guide_windows"),
        types.InlineKeyboardButton("🍎 macOS", callback_data="guide_macos"),
        types.InlineKeyboardButton("🔙 Назад", callback_data="goto_main")
    )
    send_or_edit(chat_id, text, markup, message_id)

def show_platform_guide(chat_id, platform, message_id):
    guides = {
        'ios': {
            'link': 'https://apps.apple.com/us/app/happ-proxy-utility/id6443956488',
            'text': (
                "🍏 **Подписка Happ (iOS)**\n\n"
                "1. Скачайте Happ.\n"
                "2. Скопируйте ссылку-подписку из раздела «👤 Мой ключ».\n"
                "3. Откройте Happ.\n"
                "4. Нажмите **+ (плюс)** -> **Add Subscription**.\n"
                "5. В поле **URL** вставьте вашу ссылку.\n"
                "6. Нажмите **Save** (или OK).\n"
                "7. Нажмите **Update** (обновить) и подключайтесь."
            )
        },
        'android': {
            'link': 'https://play.google.com/store/apps/details?id=com.v2ray.ang',
            'text': (
                "🤖 **Подписка Happ/v2rayNG (Android)**\n\n"
                "1. Скачайте приложение.\n"
                "2. Скопируйте ссылку-подписку в боте.\n"
                "3. Откройте приложение.\n"
                "4. Откройте боковое меню (три полоски) -> **Настройки подписки**.\n"
                "5. Нажмите **+** -> Вставьте ссылку -> Сохраните.\n"
                "6. Вернитесь на главный экран, нажмите **три точки** -> **Обновить подписку**."
            )
        },
        # Для Windows и Mac логика похожая: "Subscription" -> "Add" -> "Update".
        # ... (остальные можно оставить похожими или обновить под "Подписку")
        'windows': {
            'link': 'https://github.com/hiddify/hiddify-next/releases/latest',
            'text': (
                "💻 **Подписка на Windows**\n\n"
                "1. Скачайте приложение.\n"
                "2. Скопируйте ссылку-подписку.\n"
                "3. В программе найдите раздел **Группа подписок** (или Subscription Group).\n"
                "4. Добавьте новую подписку, вставив ссылку из бота.\n"
                "5. Нажмите кнопку **Обновить**."
            )
        },
        'macos': {
            'link': 'https://apps.apple.com/us/app/happ-proxy-utility/id6443956488',
            'text': (
                "🍎 **Подписка Happ (macOS)**\n\n"
                "1. Скачайте Happ.\n"
                "2. Скопируйте ссылку-подписку.\n"
                "3. Нажмите **Add Subscription**.\n"
                "4. Вставьте ссылку и нажмите OK.\n"
                "5. Подключитесь."
            )
        }
    }
    # ... код отправки остается тем же ...
    data = guides.get(platform)
    if data:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📥 Скачать приложение", url=data['link']))
        markup.add(types.InlineKeyboardButton("🔙 К выбору устройства", callback_data="goto_instructions"))
        send_or_edit(chat_id, data['text'], markup, message_id)

# === ОБРАБОТЧИКИ (HANDLERS) ===
# === HANDLERS ===
@bot.message_handler(commands=['start'])
def start(message):
    init_db()
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    # Здесь sub_id пока null, так как юзер еще не купил
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (message.chat.id, message.from_user.username))
    conn.commit()
    conn.close()
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    show_main_menu(message.chat.id)

@bot.message_handler(commands=['give'])
def admin_give(message):
    if message.chat.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        # Генерируем и UUID, и SUB_ID
        new_uuid = str(uuid.uuid4())
        new_sub_id = secrets.token_hex(8) # Генерируем случайную строку для подписки
        email = f"tg_{user_id}"
        
        if add_client(new_uuid, new_sub_id, email):
            conn = sqlite3.connect('shop.db')
            c = conn.cursor()
            c.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
            u = c.fetchone()
            uname = u[0] if u else "Unknown"
            
            # Сохраняем sub_id тоже!
            c.execute("INSERT OR REPLACE INTO users (user_id, username, vpn_uuid, sub_id, email) VALUES (?, ?, ?, ?, ?)", 
                      (user_id, uname, new_uuid, new_sub_id, email))
            conn.commit()
            conn.close()
            
            link = generate_sub_link(new_sub_id)
            bot.send_message(user_id, f"🎉 **Подписка выдана!**\n🔗: `{link}`", parse_mode='Markdown')
            bot.send_message(ADMIN_ID, f"✅ Выдано для {user_id}")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    if data == "goto_main": show_main_menu(chat_id, msg_id)
    elif data == "goto_buy": show_payment_method(chat_id, msg_id)
    elif data == "goto_profile": show_profile(chat_id, msg_id)
    elif data == "goto_instructions": show_instructions_menu(chat_id, msg_id)
    elif data.startswith("guide_"): show_platform_guide(chat_id, data.split("_")[1], msg_id)
    
    elif data.startswith("check_"):
        label = data.split("_")[1]
        if check_payment(label):
            # Генерируем данные
            new_uuid = str(uuid.uuid4())
            new_sub_id = secrets.token_hex(8) # Пример: 'a1b2c3d4e5f6'
            email = f"tg_{call.from_user.id}"
            
            if add_client(new_uuid, new_sub_id, email):
                conn = sqlite3.connect('shop.db')
                c = conn.cursor()
                c.execute("""
                    INSERT OR REPLACE INTO users (user_id, username, vpn_uuid, sub_id, email) 
                    VALUES (?, ?, ?, ?, ?)
                """, (call.from_user.id, call.from_user.username, new_uuid, new_sub_id, email))
                conn.commit()
                conn.close()
                
                link = generate_sub_link(new_sub_id)
                text = f"🎉 **Оплата прошла!**\n\n🔗 **Ссылка-подписка:**\n`{link}`"
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("👤 Профиль", callback_data="goto_profile"))
                markup.add(types.InlineKeyboardButton("📚 Как подключить", callback_data="goto_instructions"))
                send_or_edit(chat_id, text, markup, msg_id)
                try: bot.send_message(ADMIN_ID, f"💰 Продажа {call.from_user.username}")
                except: pass
            else:
                bot.answer_callback_query(call.id, "Ошибка создания ключа.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Оплата не найдена.", show_alert=True)

if __name__ == "__main__":
    init_db()
    print("Бот запущен...")
    bot.infinity_polling()