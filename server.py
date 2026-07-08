from flask import Flask, request, jsonify, render_template
import threading
import time
import sqlite3
import datetime
import uuid
import requests
import json
import config
from database import init_db, get_user, get_user_by_ref, update_user_limit, increment_used_photos, get_all_users

app = Flask(__name__)

# ===== API для приёма фото =====
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
    # Отправляем админу
    files = {'photo': (photo.filename, photo.stream, photo.mimetype)}
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
    data = {'chat_id': config.ADMIN_CHAT_ID, 'caption': f"📸 Новое фото от {ref}"}
    resp = requests.post(url, data=data, files=files)
    if resp.status_code != 200:
        return jsonify({'error': 'Telegram send failed'}), 500
    increment_used_photos(ref)
    return jsonify({'status': 'ok'})

# ===== Веб-интерфейс админа =====
@app.route('/admin')
def admin_panel():
    users = get_all_users()
    total_users = len(users)
    total_photos = sum(u[2] for u in users)  # photos_limit
    return render_template('admin.html', users=users, total_users=total_users, total_photos=total_photos)

# ===== API для админа (добавление фото) =====
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
    # Уведомим пользователя в Telegram
    send_message(chat_id, f"✅ Админ добавил {count} фото. Новый лимит: {new_limit}")
    return 'OK', 200

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(url, json=data)

# ===== Запуск бота в отдельном потоке =====
def run_bot():
    # Импортируем бота из bot_light.py, но чтобы не дублировать код, просто запустим его main()
    import bot_light
    bot_light.main()

# ===== Запуск Flask =====
if __name__ == '__main__':
    # Инициализируем БД
    init_db()
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    # Запускаем веб-сервер
    app.run(host='0.0.0.0', port=5000, debug=False)
