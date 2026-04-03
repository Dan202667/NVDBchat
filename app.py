import os
import uuid
import secrets
from datetime import datetime, timedelta
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
    is_banned = db.Column(db.Boolean, default=False)
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

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

with app.app_context():
    db.create_all()
    # Создаём настройку "registration_enabled" если нет
    if not SystemSetting.query.filter_by(key='registration_enabled').first():
        db.session.add(SystemSetting(key='registration_enabled', value='true'))
        db.session.commit()
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

def admin_required(f):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        user = User.query.get(session['user_id'])
        if not user or user.username != 'Dan':
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('profile'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==================== ОСНОВНЫЕ МАРШРУТЫ ====================
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
    # Проверяем, включена ли регистрация
    setting = SystemSetting.query.filter_by(key='registration_enabled').first()
    if setting and setting.value == 'false':
        flash('Регистрация временно закрыта администратором', 'warning')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register():
    # Проверка регистрации
    setting = SystemSetting.query.filter_by(key='registration_enabled').first()
    if setting and setting.value == 'false':
        flash('Регистрация временно закрыта', 'warning')
        return redirect(url_for('index'))
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
        if user.is_banned:
            flash('Ваш аккаунт заблокирован', 'danger')
            return redirect(url_for('index'))
        session['user_id'] = user.id
        session['username'] = user.username
        update_user_online_status(user.id, True)
        return redirect(url_for('chats'))
    flash('Неверное имя или пароль')
    return redirect(url_for('login_page'))

# ... (остальные маршруты chats, chat, send_message и т.д. остаются без изменений, как в стабильной версии)
# Для краткости я пропущу дублирование, но предполагается, что они есть.

# ==================== АДМИН-ПАНЕЛЬ ====================
@app.route('/admin')
@admin_required
def admin_index():
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    active_today = User.query.filter(User.last_seen >= datetime.utcnow().replace(hour=0, minute=0, second=0)).count()
    total_messages = Message.query.count()
    total_chats = Chat.query.count()
    total_media = Message.query.filter(Message.file_url.isnot(None)).count()
    banned_users = User.query.filter_by(is_banned=True).count()
    return render_template('admin_dashboard.html',
        total_users=total_users,
        active_today=active_today,
        total_messages=total_messages,
        total_chats=total_chats,
        total_media=total_media,
        banned_users=banned_users
    )

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.id).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/ban/<int:user_id>', methods=['POST'])
@admin_required
def admin_user_ban(user_id):
    user = User.query.get(user_id)
    if user and user.username != 'Dan':  # Нельзя забанить главного админа
        user.is_banned = not user.is_banned
        db.session.commit()
        flash(f'Пользователь {user.name} {"заблокирован" if user.is_banned else "разблокирован"}')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def admin_user_reset_password(user_id):
    user = User.query.get(user_id)
    if user:
        new_password = secrets.token_urlsafe(8)
        user.set_password(new_password)
        db.session.commit()
        flash(f'Новый пароль для {user.name}: {new_password}', 'info')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    user = User.query.get(user_id)
    if user and user.username != 'Dan':
        # Удаляем все сообщения пользователя, реакции, участников чатов
        MessageReaction.query.filter_by(user_id=user_id).delete()
        Message.query.filter_by(sender_id=user_id).delete()
        ChatParticipant.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
        flash(f'Пользователь {user.name} удалён')
    return redirect(url_for('admin_users'))

@app.route('/admin/messages')
@admin_required
def admin_messages():
    messages = Message.query.order_by(Message.timestamp.desc()).limit(200).all()
    return render_template('admin_messages.html', messages=messages)

@app.route('/admin/message/delete/<int:message_id>', methods=['POST'])
@admin_required
def admin_message_delete(message_id):
    msg = Message.query.get(message_id)
    if msg:
        db.session.delete(msg)
        db.session.commit()
        flash('Сообщение удалено')
    return redirect(url_for('admin_messages'))

@app.route('/admin/chats')
@admin_required
def admin_chats():
    chats = Chat.query.order_by(Chat.created_at.desc()).all()
    return render_template('admin_chats.html', chats=chats)

@app.route('/admin/chat/delete/<int:chat_id>', methods=['POST'])
@admin_required
def admin_chat_delete(chat_id):
    chat = Chat.query.get(chat_id)
    if chat:
        db.session.delete(chat)
        db.session.commit()
        flash('Чат удалён')
    return redirect(url_for('admin_chats'))

@app.route('/admin/media')
@admin_required
def admin_media():
    media_messages = Message.query.filter(Message.file_url.isnot(None)).order_by(Message.timestamp.desc()).limit(200).all()
    return render_template('admin_media.html', media=media_messages)

@app.route('/admin/settings')
@admin_required
def admin_settings():
    registration_enabled = SystemSetting.query.filter_by(key='registration_enabled').first()
    return render_template('admin_settings.html', registration_enabled=registration_enabled.value == 'true')

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def admin_settings_update():
    reg = request.form.get('registration_enabled') == 'on'
    setting = SystemSetting.query.filter_by(key='registration_enabled').first()
    if setting:
        setting.value = 'true' if reg else 'false'
        db.session.commit()
    flash('Настройки сохранены')
    return redirect(url_for('admin_settings'))

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)