# -*- coding: utf-8 -*-
"""
Droid Market Suggestion Bot
Многошаговая предложка + модерация админом
"""
import json
import os
import time
import secrets
import telebot
from telebot import types
from telebot import apihelper

# === ПРОКСИ ===
# apihelper.proxy = {'https': 'http://127.0.0.1:7890'}

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("DROIDMARKET_BOT_TOKEN", "")
SUGGESTIONS_FILE = os.environ.get("SUGGESTIONS_FILE", "suggestions.json")

# ID АДМИНА — сюда вставь свой Telegram ID (можно узнать через @userinfobot)
ADMIN_ID = int(os.environ.get("DROIDMARKET_ADMIN_ID", "0"))

apihelper.CONNECT_TIMEOUT = 60
apihelper.READ_TIMEOUT = 60

bot = telebot.TeleBot(BOT_TOKEN)

# === СОСТОЯНИЯ ===
user_states = {}
user_data = {}

# === ХРАНИЛИЩЕ ===
def load_suggestions():
    if os.path.exists(SUGGESTIONS_FILE):
        try:
            with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except:
            return []
    return []

def save_suggestions(data):
    if not isinstance(data, list):
        return
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def safe_send(chat_id, text, parse_mode='HTML', reply_markup=None):
    for attempt in range(3):
        try:
            return bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e:
            print(f"[!] Попытка {attempt+1} не удалась: {e}")
            if attempt < 2:
                time.sleep(2)
    return None

def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def reset_user(user_id):
    user_states.pop(user_id, None)
    user_data.pop(user_id, None)

def is_admin(user_id):
    return user_id == ADMIN_ID

def notify_admin(suggestion):
    """Отправка уведомления админу о новом предложении"""
    sid = suggestion["id"]
    text = (
        f"📬 <b>Новое предложение!</b>\n\n"
        f"👤 От: @{escape_html(suggestion['username'])} (ID: {suggestion['user_id']})\n"
        f"📱 Название: <b>{escape_html(suggestion['name'])}</b>\n"
        f"📝 Описание: {escape_html(suggestion['description'])}\n"
        f"🔗 Ссылка: {escape_html(suggestion['link'])}\n\n"
        f"⏰ Время: {time.strftime('%Y-%m-%d %H:%M', time.localtime(suggestion['timestamp']))}"
    )
    
    # Кнопки Одобрить / Отклонить
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{sid}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{sid}")
    )
    
    try:
        bot.send_message(ADMIN_ID, text, parse_mode='HTML', reply_markup=markup)
    except Exception as e:
        print(f"[!] Не удалось уведомить админа: {e}")

def notify_user(user_id, suggestion, approved):
    """Уведомление пользователя о решении"""
    if approved:
        text = (
            f"✅ <b>Ваше предложение одобрено!</b>\n\n"
            f"📱 {escape_html(suggestion['name'])}\n"
            f"Скоро появится в маркете."
        )
    else:
        text = (
            f"❌ <b>Ваше предложение отклонено.</b>\n\n"
            f"📱 {escape_html(suggestion['name'])}\n"
            f"Если считаете что это ошибка — напишите админу."
        )
    try:
        safe_send(user_id, text)
    except:
        pass

# === КОМАНДЫ ===

@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    text = (
        "<b>🤖 Droid Market Suggestion Bot</b>\n\n"
        "Предложи приложение для маркета!\n\n"
        "<b>Команды:</b>\n"
        "/suggest — предложить приложение\n"
        "/cancel — отменить ввод\n"
        "/mystatus — статус твоих предложений\n\n"
        "Бот проведёт тебя по шагам:\n"
        "1. Название → 2. Описание → 3. Ссылка\n"
        "После этого админ рассмотрит предложение."
    )
    safe_send(message.chat.id, text)

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    uid = message.from_user.id
    if uid in user_states:
        reset_user(uid)
        safe_send(message.chat.id, "❌ Ввод отменён.")
    else:
        safe_send(message.chat.id, "ℹ️ Нечего отменять.")

@bot.message_handler(commands=['suggest'])
def cmd_suggest(message):
    uid = message.from_user.id
    if uid in user_states:
        safe_send(message.chat.id, "⚠️ Ты уже в процессе. /cancel чтобы начать заново.")
        return
    
    user_states[uid] = "waiting_name"
    user_data[uid] = {}
    safe_send(message.chat.id,
        "<b>📱 Шаг 1/3: Название</b>\n\n"
        "Введи название приложения (например: <code>YouTube</code>):\n\n"
        "/cancel — отмена"
    )

@bot.message_handler(commands=['mystatus'])
def cmd_mystatus(message):
    uid = message.from_user.id
    suggestions = load_suggestions()
    my_suggestions = [s for s in suggestions if s.get('user_id') == uid]
    
    if not my_suggestions:
        safe_send(message.chat.id, "📭 У тебя пока нет предложений.")
        return
    
    text = "<b>📋 Твои предложения:</b>\n\n"
    for s in my_suggestions[-10:]:
        status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(s.get("status", "pending"), "❓")
        status_text = {"pending": "На рассмотрении", "approved": "Одобрено", "rejected": "Отклонено"}.get(s.get("status", "pending"), "Неизвестно")
        text += f"{status_emoji} <b>{escape_html(s['name'])}</b> — {status_text}\n"
    
    safe_send(message.chat.id, text)

# === АДМИНСКИЕ КОМАНДЫ ===

@bot.message_handler(commands=['pending'])
def cmd_pending(message):
    if not is_admin(message.from_user.id):
        safe_send(message.chat.id, "⛔ Только для админов.")
        return
    
    suggestions = load_suggestions()
    pending = [s for s in suggestions if s.get("status", "pending") == "pending"]
    
    if not pending:
        safe_send(message.chat.id, "✅ Нет предложений на рассмотрении.")
        return
    
    text = f"<b>⏳ Ожидают решения ({len(pending)}):</b>\n\n"
    for s in pending[-15:]:
        sid = s["id"]
        text += (
            f"📱 <b>{escape_html(s['name'])}</b>\n"
            f"👤 @{escape_html(s.get('username', 'unknown'))}\n"
            f"🔗 {escape_html(s.get('link', 'нет'))}\n\n"
        )
    
    safe_send(message.chat.id, text)

@bot.message_handler(commands=['suggestions'])
def cmd_suggestions(message):
    if not is_admin(message.from_user.id):
        safe_send(message.chat.id, "⛔ Только для админов.")
        return
    
    suggestions = load_suggestions()
    pending = len([s for s in suggestions if s.get("status", "pending") == "pending"])
    approved = len([s for s in suggestions if s.get("status") == "approved"])
    rejected = len([s for s in suggestions if s.get("status") == "rejected"])
    
    text = (
        f"<b>📊 Статистика предложений</b>\n\n"
        f"⏳ На рассмотрении: <b>{pending}</b>\n"
        f"✅ Одобрено: <b>{approved}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>\n"
        f"📦 Всего: <b>{len(suggestions)}</b>"
    )
    safe_send(message.chat.id, text)

# === FSM: ВВОД ДАННЫХ ===

@bot.message_handler(func=lambda m: m.from_user.id in user_states, content_types=['text'])
def handle_fsm(message):
    uid = message.from_user.id
    text = message.text.strip()
    state = user_states.get(uid)
    
    if not state:
        return
    
    # ШАГ 1: Название
    if state == "waiting_name":
        if len(text) < 2:
            safe_send(message.chat.id, "❌ Слишком коротко. Минимум 2 символа.")
            return
        if len(text) > 100:
            safe_send(message.chat.id, "❌ Слишком длинно. Максимум 100 символов.")
            return
        
        user_data[uid]["name"] = text
        user_states[uid] = "waiting_desc"
        safe_send(message.chat.id,
            f"✅ Название: <b>{escape_html(text)}</b>\n\n"
            "<b>📝 Шаг 2/3: Описание</b>\n\n"
            "Опиши приложение (например: <code>Старая версия для Android 2.3</code>):\n\n"
            "/cancel — отмена"
        )
        return
    
    # ШАГ 2: Описание
    if state == "waiting_desc":
        if len(text) < 3:
            safe_send(message.chat.id, "❌ Слишком коротко. Минимум 3 символа.")
            return
        if len(text) > 500:
            safe_send(message.chat.id, "❌ Слишком длинно. Максимум 500 символов.")
            return
        
        user_data[uid]["description"] = text
        user_states[uid] = "waiting_link"
        safe_send(message.chat.id,
            "✅ Описание принято.\n\n"
            "<b>🔗 Шаг 3/3: Ссылка</b>\n\n"
            "Отправь ссылку на APK (например: <code>https://t.me/apksherr/123</code>):\n\n"
            "/cancel — отмена"
        )
        return
    
    # ШАГ 3: Ссылка
    if state == "waiting_link":
        if not (text.startswith("http://") or text.startswith("https://") or text.startswith("t.me/") or text.startswith("www.")):
            safe_send(message.chat.id,
                "❌ Не похоже на ссылку. Должна начинаться с <code>http://</code>, <code>https://</code> или <code>t.me/</code>."
            )
            return
        if len(text) > 500:
            safe_send(message.chat.id, "❌ Слишком длинно. Максимум 500 символов.")
            return
        
        user_data[uid]["link"] = text
        data = user_data[uid]
        
        # Сохраняем предложение
        sid = secrets.token_hex(6)
        suggestion = {
            "id": sid,
            "user_id": uid,
            "username": message.from_user.username or message.from_user.first_name or "unknown",
            "name": data["name"],
            "description": data["description"],
            "link": data["link"],
            "timestamp": time.time(),
            "status": "pending"
        }
        
        suggestions = load_suggestions()
        suggestions.append(suggestion)
        save_suggestions(suggestions)
        
        # Подтверждение юзеру
        safe_send(message.chat.id,
            "<b>✅ Предложение отправлено!</b>\n\n"
            f"📱 {escape_html(data['name'])}\n"
            f"📝 {escape_html(data['description'])}\n"
            f"🔗 {escape_html(data['link'])}\n\n"
            "⏳ Админ рассмотрит его. Статус можно посмотреть через /mystatus"
        )
        
        # Уведомление админу
        notify_admin(suggestion)
        
        reset_user(uid)
        return

# === CALLBACK: ОДОБРИТЬ / ОТКЛОНИТЬ ===

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    # Только админ может нажимать кнопки
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Только админ может это делать", show_alert=True)
        return
    
    data = call.data
    if not (data.startswith("approve_") or data.startswith("reject_")):
        return
    
    action, sid = data.split("_", 1)
    
    suggestions = load_suggestions()
    target = None
    for s in suggestions:
        if s.get("id") == sid:
            target = s
            break
    
    if not target:
        bot.answer_callback_query(call.id, "❌ Предложение не найдено", show_alert=True)
        return
    
    if target.get("status") != "pending":
        bot.answer_callback_query(call.id, "⚠️ Уже обработано", show_alert=True)
        return
    
    if action == "approve":
        target["status"] = "approved"
        target["reviewed_at"] = time.time()
        save_suggestions(suggestions)
        
        # Обновляем сообщение админа
        try:
            bot.edit_message_text(
                call.message.chat.id,
                call.message.message_id,
                call.message.text + "\n\n✅ <b>ОДОБРЕНО</b>",
                parse_mode='HTML'
            )
        except: pass
        
        bot.answer_callback_query(call.id, "✅ Одобрено!")
        notify_user(target["user_id"], target, approved=True)
    
    elif action == "reject":
        target["status"] = "rejected"
        target["reviewed_at"] = time.time()
        save_suggestions(suggestions)
        
        try:
            bot.edit_message_text(
                call.message.chat.id,
                call.message.message_id,
                call.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>",
                parse_mode='HTML'
            )
        except: pass
        
        bot.answer_callback_query(call.id, "❌ Отклонено")
        notify_user(target["user_id"], target, approved=False)

# === ЗАГЛУШКА ===
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_other(message):
    if message.text and not message.text.startswith('/'):
        safe_send(message.chat.id,
            "ℹ️ Используй /suggest чтобы предложить приложение."
        )

# === ЗАПУСК ===
if __name__ == "__main__":
    print("🤖 Droid Market Suggestion Bot запущен...")
    print(f"📁 Файл предложений: {SUGGESTIONS_FILE}")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print("Нажми Ctrl+C для остановки")
    
    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True
    )