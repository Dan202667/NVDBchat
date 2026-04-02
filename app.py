import os
import uuid
from datetime import datetime
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'

# Настройка базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dhkol0drf'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '816413685482328'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'xf42h1mQQKprlwl0dujXHUpX7Ow')
)

# Настройка OneSignal
ONESIGNAL_APP_ID = "effc2b7e-2a19-4666-a270-4f413081d020"
ONESIGNAL_REST_API_KEY = os.environ.get('ONESIGNAL_REST_API_KEY', '')

def send_onesignal_notification(user_id, title, body):
    if not ONESIGNAL_REST_API_KEY:
        return
    try:
        requests.post(
            "https://onesignal.com/api/v1/notifications",
            headers={"Authorization": f"Basic {ONESIGNAL_REST_API_KEY}", "Content-Type": "application/json"},
            json={"app_id": ONESIGNAL_APP_ID, "include_external_user_ids": [str(user_id)], "headings": {"en": title}, "contents": {"en": body}}
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")

db = SQLAlchemy(app)

# ==================== МОДЕЛИ ====================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=True)
    avatar_url = db.Column(db.String(300), nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Chat(db.Model):
    __tablename__ = 'chats'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10))
    name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatParticipant(db.Model):
    __tablename__ = 'chat_participants'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id', ondelete='CASCADE'))
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    content = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(300), nullable=True)
    file_type = db.Column(db.String(20), nullable=True)
    is_edited = db.Column(db.Boolean, default=False)
    reactions = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class MessageReaction(db.Model):
    __tablename__ = 'message_reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='CASCADE'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    print("✅ Таблицы базы данных созданы")

# ==================== ФУНКЦИИ ====================
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'm4a', 'ogg', 'wav', 'webm'}

def upload_to_cloudinary(file, folder='nvdbchat'):
    if not file:
        return None, None
    try:
        upload_result = cloudinary.uploader.upload(file, folder=folder, resource_type='auto')
        file_url = upload_result.get('secure_url')
        file_type = upload_result.get('resource_type')
        if file_type == 'video':
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            if ext in ALLOWED_AUDIO_EXTENSIONS:
                file_type = 'audio'
        return file_url, file_type
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None, None

def update_user_online_status(user_id, is_online):
    user = User.query.get(user_id)
    if user:
        user.is_online = is_online
        user.last_seen = datetime.utcnow()
        db.session.commit()

def get_user_chats(user_id):
    participations = ChatParticipant.query.filter_by(user_id=user_id).all()
    chat_ids = [p.chat_id for p in participations]
    chats = Chat.query.filter(Chat.id.in_(chat_ids)).all()
    result = []
    for chat in chats:
        if chat.type == 'private':
            other = ChatParticipant.query.filter(ChatParticipant.chat_id == chat.id, ChatParticipant.user_id != user_id).first()
            if other:
                other_user = User.query.get(other.user_id)
                display_name = other_user.username or other_user.name
                other_avatar = other_user.avatar_url
                other_online = other_user.is_online
            else:
                display_name = 'Личный чат'
                other_avatar = None
                other_online = False
            setattr(chat, 'other_avatar', other_avatar)
            setattr(chat, 'other_online', other_online)
        else:
            display_name = chat.name or 'Группа без названия'
            setattr(chat, 'other_avatar', None)
            setattr(chat, 'other_online', False)
        last_msg = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
        setattr(chat, 'display_name', display_name)
        setattr(chat, 'last_message', last_msg)
        result.append(chat)
    result.sort(key=lambda c: c.last_message.timestamp if c.last_message else datetime(1970, 1, 1), reverse=True)
    return result

# ==================== МАРШРУТЫ ====================
@app.route('/')
def index():
    if 'user_id' in session:
        update_user_online_status(session['user_id'], True)
        return redirect(url_for('chats'))
    return render_template('index.html')

@app.route('/login_page')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('chats'))
    return render_template('login.html')

@app.route('/register_page')
def register_page():
    if 'user_id' in session:
        return redirect(url_for('chats'))
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form['name']
    password = request.form['password']
    existing = User.query.filter_by(name=name).first()
    if existing:
        flash('Пользователь с таким именем уже существует')
        return redirect(url_for('register_page'))
    user = User(name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    session['temp_user_id'] = user.id
    return redirect(url_for('create_profile'))

@app.route('/login', methods=['POST'])
def login():
    name = request.form['name']
    password = request.form['password']
    user = User.query.filter_by(name=name).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['username'] = user.username
        update_user_online_status(user.id, True)
        return redirect(url_for('chats'))
    flash('Неверное имя или пароль')
    return redirect(url_for('login_page'))

@app.route('/create_profile', methods=['GET', 'POST'])
def create_profile():
    if 'temp_user_id' not in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username'].lstrip('@')
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Этот @username уже занят')
            return render_template('create_profile.html')
        user = User.query.get(session['temp_user_id'])
        user.username = username
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file.filename:
                avatar_url, _ = upload_to_cloudinary(file, folder='nvdbchat/avatars')
                if avatar_url:
                    user.avatar_url = avatar_url
        db.session.commit()
        session['user_id'] = user.id
        session['username'] = user.username
        session.pop('temp_user_id', None)
        update_user_online_status(user.id, True)
        return redirect(url_for('chats'))
    return render_template('create_profile.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file.filename:
            avatar_url, _ = upload_to_cloudinary(file, folder='nvdbchat/avatars')
            if avatar_url:
                user.avatar_url = avatar_url
                db.session.commit()
                flash('Аватар обновлён')
    return redirect(url_for('profile'))

@app.route('/logout')
def logout():
    if 'user_id' in session:
        update_user_online_status(session['user_id'], False)
    session.clear()
    return redirect(url_for('index'))

@app.route('/chats')
def chats():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user_id = session['user_id']
    chats_list = get_user_chats(user_id)
    return render_template('chats.html', chats=chats_list)

@app.route('/search_user', methods=['POST'])
def search_user():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    username = request.form['username'].lstrip('@')
    user = User.query.filter_by(username=username).first()
    if not user:
        flash('Пользователь не найден')
        return redirect(url_for('chats'))
    current_user_id = session['user_id']
    if user.id == current_user_id:
        flash('Нельзя начать чат с самим собой')
        return redirect(url_for('chats'))
    participations = ChatParticipant.query.filter_by(user_id=current_user_id).all()
    current_user_chat_ids = [p.chat_id for p in participations]
    target_participation = ChatParticipant.query.filter(ChatParticipant.chat_id.in_(current_user_chat_ids), ChatParticipant.user_id == user.id).first()
    if target_participation:
        chat_id = target_participation.chat_id
    else:
        new_chat = Chat(type='private')
        db.session.add(new_chat)
        db.session.flush()
        db.session.add(ChatParticipant(chat_id=new_chat.id, user_id=current_user_id))
        db.session.add(ChatParticipant(chat_id=new_chat.id, user_id=user.id))
        db.session.commit()
        chat_id = new_chat.id
    return redirect(url_for('chat', chat_id=chat_id))

@app.route('/chat/<int:chat_id>')
def chat(chat_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user_id = session['user_id']
    participant = ChatParticipant.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if not participant:
        flash('Вы не участник этого чата')
        return redirect(url_for('chats'))
    chat_obj = Chat.query.get(chat_id)
    messages = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        msg.sender_name = sender.username or sender.name
        msg.sender_avatar = sender.avatar_url
        reactions = MessageReaction.query.filter_by(message_id=msg.id).all()
        msg.reactions_list = [{'emoji': r.emoji, 'user_id': r.user_id} for r in reactions]
    other_avatar = None
    other_online = False
    if chat_obj.type == 'private':
        other = ChatParticipant.query.filter(ChatParticipant.chat_id == chat_id, ChatParticipant.user_id != user_id).first()
        if other:
            other_user = User.query.get(other.user_id)
            chat_name = other_user.username or other_user.name
            other_avatar = other_user.avatar_url
            other_online = other_user.is_online
        else:
            chat_name = 'Личный чат'
    else:
        chat_name = chat_obj.name
    all_chats = get_user_chats(user_id)
    return render_template('chat.html', chat_id=chat_id, chat_name=chat_name, messages=messages, all_chats=all_chats, chat=chat_obj, other_avatar=other_avatar, other_online=other_online)

@app.route('/send_message/<int:chat_id>', methods=['POST'])
def send_message(chat_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 403
    content = request.form.get('content', '')
    file = request.files.get('file')
    msg = Message(chat_id=chat_id, sender_id=session['user_id'])
    if file and file.filename:
        file_url, file_type = upload_to_cloudinary(file, folder='nvdbchat/uploads')
        if file_url:
            msg.file_url = file_url
            msg.file_type = file_type
            msg.content = content if content else None
            db.session.add(msg)
            db.session.commit()
            sender = User.query.get(msg.sender_id)
            if msg.sender_id != session['user_id']:
                participants = ChatParticipant.query.filter(ChatParticipant.chat_id == chat_id, ChatParticipant.user_id != msg.sender_id).first()
                if participants:
                    send_onesignal_notification(participants.user_id, "Новое сообщение", content[:50] if content else "Файл")
            return jsonify({'id': msg.id, 'content': msg.content, 'file_url': msg.file_url, 'file_type': msg.file_type, 'sender_id': msg.sender_id, 'sender_name': sender.username or sender.name, 'timestamp': msg.timestamp.strftime('%H:%M')}), 200
    if content.strip():
        msg.content = content
        msg.file_type = 'text'
        db.session.add(msg)
        db.session.commit()
        sender = User.query.get(msg.sender_id)
        if msg.sender_id != session['user_id']:
            participants = ChatParticipant.query.filter(ChatParticipant.chat_id == chat_id, ChatParticipant.user_id != msg.sender_id).first()
            if participants:
                send_onesignal_notification(participants.user_id, "Новое сообщение", content[:50] + ("..." if len(content) > 50 else ""))
        return jsonify({'id': msg.id, 'content': msg.content, 'file_type': 'text', 'sender_id': msg.sender_id, 'sender_name': sender.username or sender.name, 'timestamp': msg.timestamp.strftime('%H:%M')}), 200
    return jsonify({'error': 'Empty message'}), 400

@app.route('/edit_message/<int:message_id>', methods=['POST'])
def edit_message(message_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    msg = Message.query.get(message_id)
    if not msg or msg.sender_id != session['user_id']:
        return jsonify({'error': 'Not allowed'}), 403
    data = request.get_json()
    new_content = data.get('content', '')
    if new_content.strip():
        msg.content = new_content
        msg.is_edited = True
        db.session.commit()
        return jsonify({'status': 'ok', 'content': new_content})
    return jsonify({'error': 'Empty content'}), 400

@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    msg = Message.query.get(message_id)
    if not msg or msg.sender_id != session['user_id']:
        return jsonify({'error': 'Not allowed'}), 403
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/add_reaction/<int:message_id>', methods=['POST'])
def add_reaction(message_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    emoji = data.get('emoji')
    if not emoji:
        return jsonify({'error': 'No emoji'}), 400
    existing = MessageReaction.query.filter_by(message_id=message_id, user_id=session['user_id'], emoji=emoji).first()
    if existing:
        db.session.delete(existing)
    else:
        reaction = MessageReaction(message_id=message_id, user_id=session['user_id'], emoji=emoji)
        db.session.add(reaction)
    db.session.commit()
    reactions = MessageReaction.query.filter_by(message_id=message_id).all()
    result = [{'emoji': r.emoji, 'user_id': r.user_id} for r in reactions]
    return jsonify({'reactions': result})

@app.route('/delete_chat/<int:chat_id>', methods=['POST'])
def delete_chat(chat_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    Message.query.filter_by(chat_id=chat_id).delete()
    ChatParticipant.query.filter_by(chat_id=chat_id, user_id=session['user_id']).delete()
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/get_new_messages/<int:chat_id>')
def get_new_messages(chat_id):
    if 'user_id' not in session:
        return jsonify([])
    last_id = request.args.get('last_id', 0, type=int)
    messages = Message.query.filter(Message.chat_id == chat_id, Message.id > last_id).order_by(Message.timestamp).all()
    result = []
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        reactions = MessageReaction.query.filter_by(message_id=msg.id).all()
        reactions_list = [{'emoji': r.emoji, 'user_id': r.user_id} for r in reactions]
        result.append({'id': msg.id, 'content': msg.content, 'file_url': msg.file_url, 'file_type': msg.file_type, 'sender_id': msg.sender_id, 'sender_name': sender.username or sender.name, 'timestamp': msg.timestamp.strftime('%H:%M'), 'is_edited': msg.is_edited, 'reactions': reactions_list})
    return jsonify(result)

@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        group_name = request.form['group_name']
        members_str = request.form['members']
        usernames = [u.strip().lstrip('@') for u in members_str.split(',') if u.strip()]
        current_user = User.query.get(session['user_id'])
        if current_user.username not in usernames:
            usernames.append(current_user.username)
        users = User.query.filter(User.username.in_(usernames)).all()
        if len(users) != len(usernames):
            flash('Некоторые пользователи не найдены')
            return render_template('create_group.html')
        chat = Chat(type='group', name=group_name)
        db.session.add(chat)
        db.session.flush()
        for user in users:
            db.session.add(ChatParticipant(chat_id=chat.id, user_id=user.id))
        db.session.commit()
        return redirect(url_for('chat', chat_id=chat.id))
    return render_template('create_group.html')

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    if not user or user.username != 'admin':
        flash('Доступ запрещён')
        return redirect(url_for('chats'))
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/register_token', methods=['POST'])
def register_token():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    token = data.get('token')
    if token:
        user = User.query.get(session['user_id'])
        user.fcm_token = token
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'No token'}), 400

# ==================== ВРЕМЕННЫЙ МАРШРУТ ДЛЯ ОБНОВЛЕНИЯ БД ====================
@app.route('/fix_db')
def fix_db():
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            # Добавляем колонки в таблицу users
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP DEFAULT NULL"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT FALSE"))
            # Добавляем колонки в таблицу messages
            conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_edited BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reactions TEXT DEFAULT NULL"))
            conn.commit()
        return "✅ База данных обновлена! Все новые колонки добавлены."
    except Exception as e:
        return f"❌ Ошибка: {e}"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)