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
    # ⚠️ ВНИМАНИЕ: Здесь должна быть ТВОЯ ссылка.
    # Я вставил шаблон на основе того, что ты присылал ранее (Reality + Vision).
    # Убедись, что pbk, sid и sni соответствуют твоему серверу.
    return f"vless://{uuid_str}@{SERVER_IP}:{VLESS_PORT}?type=tcp&security=reality&pbk=cGL0Zsjx2OkWTK5GLbcbyCFZ3rs5DgN0phuWhHlUawQ&fp=chrome&sni=google.com&sid=0c&spx=%2F&flow=xtls-rprx-vision#{email}"

# === ЮМАНИ ПЛАТЕЖИ ===
def create_payment(user_id, price):
    # Уникальная метка: vpn_ID_TIMESTAMP
    label = f"vpn_{user_id}_{int(time.time())}"
    
    quickpay = Quickpay(
            receiver=YM_WALLET,
            quickpay_form="shop",
            targets="VPN Подписка (1 месяц)",
            paymentType="SB", # SB = Банковская карта / СБП
            sum=price,
            label=label
            )
    return quickpay.base_url, label

def check_payment(label):
    try:
        client = Client(YM_TOKEN)
        # Проверяем историю
        history = client.operation_history(label=label)
        for op in history.operations:
            if op.status == 'success':
                return True
    except Exception as e:
        print(f"Ошибка проверки Юмани: {e}")
    return False

# === СИСТЕМА ОДНОГО ОКНА (UI HELPERS) ===

def clean_chat(chat_id, current_msg_id=None):
    """Удаляет старое сообщение бота, если оно есть."""
    if chat_id in users_last_messages:
        last_id = users_last_messages[chat_id]
        if current_msg_id and last_id == current_msg_id:
            return
        try:
            bot.delete_message(chat_id, last_id)
        except: pass

def send_or_edit(chat_id, text, markup, message_id=None):
    """Редактирует текущее сообщение или отправляет новое, сохраняя чистоту чата."""
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
            users_last_messages[chat_id] = message_id
            return
        except Exception:
            pass # Если не вышло отредактировать, шлем новое
    
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
    c.execute("SELECT vpn_uuid, email FROM users WHERE user_id = ?", (chat_id,))
    res = c.fetchone()
    conn.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="goto_main"))

    if res and res[0]:
        link = generate_link(res[0], res[1])
        text = f"👤 **Твой профиль**\n\n✅ Подписка активна!\n\n🔑 **Твой ключ:**\n`{link}`\n\n(Нажми на ключ, чтобы скопировать)"
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
    # Данные инструкций. Везде используем бренд "Happ".
    guides = {
        'ios': {
            'link': 'https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973',
            'text': (
                "🍏 **Happ для iOS**\n\n"
                "1. Скачайте Happ по кнопке ниже.\n"
                "2. Скопируйте ключ из раздела «👤 Мой ключ».\n"
                "3. Откройте Happ.\n"
                "4. Приложение само предложит добавить ключ (или нажмите + -> **Импорт из буфера**).\n"
                "5. Нажмите кнопку подключения."
            )
        },
        'macos': {
            'link': 'hhttps://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973',
            'text': (
                "🍎 **Happ для macOS**\n\n"
                "1. Скачайте Happ из AppStore.\n"
                "2. Скопируйте ваш ключ.\n"
                "3. В приложении нажмите ***+ (Новый профиль)** -> **Импорт из буфера**.\n"
                "4. Подключитесь."
            )
        },
        'android': {
            'link': 'https://play.google.com/store/apps/details?id=com.happproxy', # Ссылка на v2rayNG (стандарт для Android)
            'text': (
                "🤖 **Happ для Android**\n\n"
                "1. Скачайте приложение по кнопке ниже.\n"
                "2. Скопируйте ключ в боте.\n"
                "3. Откройте приложение.\n"
                "4. Нажмите **+** (сверху) -> **Импорт из буфера**.\n"
                "5. Нажмите большую кнопку подключения."
            )
        },
        'windows': {
            'link': 'https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe', # Ссылка на Hiddify
            'text': (
                "💻 **Happ для Windows**\n\n"
                "1. Скачайте и установите приложение.\n"
                "2. Скопируйте ваш ключ.\n"
                "3. Откройте программу и нажмите **+ (Новый профиль)** -> **Импорт из буфера**.\n"
                "4. Нажмите большую кнопку подключения."
            )
        }
    }

    data = guides.get(platform)
    if data:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📥 Скачать приложение", url=data['link']))
        markup.add(types.InlineKeyboardButton("🔙 К выбору устройства", callback_data="goto_instructions"))
        send_or_edit(chat_id, data['text'], markup, message_id)

# === ОБРАБОТЧИКИ (HANDLERS) ===

@bot.message_handler(commands=['start'])
def start(message):
    init_db()
    conn = sqlite3.connect('shop.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
              (message.chat.id, message.from_user.username))
    conn.commit()
    conn.close()

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except: pass

    show_main_menu(message.chat.id)

# ЕДИНЫЙ ЦЕНТР УПРАВЛЕНИЯ КНОПКАМИ
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data

    # --- НАВИГАЦИЯ ---
    if data == "goto_main":
        show_main_menu(chat_id, msg_id)
    
    elif data == "goto_buy":
        show_payment_method(chat_id, msg_id)
    
    elif data == "goto_profile":
        show_profile(chat_id, msg_id)
        
    elif data == "goto_instructions":
        show_instructions_menu(chat_id, msg_id)
        
    elif data.startswith("guide_"):
        platform = data.split("_")[1]
        show_platform_guide(chat_id, platform, msg_id)

    # --- ПРОВЕРКА ОПЛАТЫ ---
    elif data.startswith("check_"):
        label = data.split("_")[1]
        
        if check_payment(label):
            # УСПЕХ
            new_uuid = str(uuid.uuid4())
            email = f"tg_{call.from_user.id}"
            
            if add_client(new_uuid, email, days=30):
                # REPLACE гарантирует запись даже если юзер удалялся
                conn = sqlite3.connect('shop.db')
                c = conn.cursor()
                c.execute("""
                    INSERT OR REPLACE INTO users (user_id, username, vpn_uuid, email) 
                    VALUES (?, ?, ?, ?)
                """, (call.from_user.id, call.from_user.username, new_uuid, email))
                conn.commit()
                conn.close()
                
                link = generate_link(new_uuid, email)
                
                text = f"🎉 **Оплата прошла успешно!**\n\nТвой ключ готов:\n`{link}`"
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("👤 В профиль", callback_data="goto_profile"))
                markup.add(types.InlineKeyboardButton("📚 Как подключить", callback_data="goto_instructions"))
                
                send_or_edit(chat_id, text, markup, msg_id)
                
                try:
                    bot.send_message(ADMIN_ID, f"💰 Продажа @{call.from_user.username}", parse_mode='HTML')
                except: pass
            else:
                bot.answer_callback_query(call.id, "Ошибка создания ключа! Свяжитесь с поддержкой.", show_alert=True)
        else:
            # НЕУДАЧА (показываем алерт, окно не меняем)
            bot.answer_callback_query(call.id, "❌ Оплата еще не пришла. Попробуйте через минуту.", show_alert=True)

if __name__ == "__main__":
    init_db()
    print("Бот запущен...")
    bot.infinity_polling()