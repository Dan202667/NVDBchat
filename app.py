import os
import uuid
from datetime import datetime
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

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
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    content = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(300), nullable=True)
    file_type = db.Column(db.String(20), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== СОЗДАНИЕ ТАБЛИЦ ====================
with app.app_context():
    db.create_all()
    print("✅ Таблицы базы данных созданы")

# ==================== ФУНКЦИИ ====================
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'm4a', 'ogg', 'wav', 'webm'}

def upload_to_cloudinary(file, folder='nvdbchat'):
    if not file:
        return None, None
    try:
        upload_result = cloudinary.uploader.upload(
            file,
            folder=folder,
            resource_type='auto'
        )
        file_url = upload_result.get('secure_url')
        file_type = upload_result.get('resource_type')
        if file_type == 'video':
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            if ext in ALLOWED_AUDIO_EXTENSIONS:
                file_type = 'audio'
        return file_url, file_type
    except Exception as e:
        print(f"Ошибка загрузки в Cloudinary: {e}")
        return None, None

def get_user_chats(user_id):
    participations = ChatParticipant.query.filter_by(user_id=user_id).all()
    chat_ids = [p.chat_id for p in participations]
    chats = Chat.query.filter(Chat.id.in_(chat_ids)).all()

    result = []
    for chat in chats:
        if chat.type == 'private':
            other = ChatParticipant.query.filter(
                ChatParticipant.chat_id == chat.id,
                ChatParticipant.user_id != user_id
            ).first()
            if other:
                other_user = User.query.get(other.user_id)
                display_name = other_user.username or other_user.name
                other_avatar = other_user.avatar_url
            else:
                display_name = 'Личный чат'
                other_avatar = None
            setattr(chat, 'other_avatar', other_avatar)
        else:
            display_name = chat.name or 'Группа без названия'
            setattr(chat, 'other_avatar', None)

        last_msg = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
        setattr(chat, 'display_name', display_name)
        setattr(chat, 'last_message', last_msg)
        setattr(chat, 'unread_count', 0)  # Пока убрали подсчёт
        result.append(chat)

    result.sort(key=lambda c: c.last_message.timestamp if c.last_message else datetime(1970, 1, 1), reverse=True)
    return result

# ==================== МАРШРУТЫ ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form['name']
    password = request.form['password']
    existing = User.query.filter_by(name=name).first()
    if existing:
        flash('Пользователь с таким именем уже существует')
        return redirect(url_for('index'))
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
        return redirect(url_for('chats'))
    flash('Неверное имя или пароль')
    return redirect(url_for('index'))

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
    target_participation = ChatParticipant.query.filter(
        ChatParticipant.chat_id.in_(current_user_chat_ids),
        ChatParticipant.user_id == user.id
    ).first()

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

    other_avatar = None
    if chat_obj.type == 'private':
        other = ChatParticipant.query.filter(
            ChatParticipant.chat_id == chat_id,
            ChatParticipant.user_id != user_id
        ).first()
        if other:
            other_user = User.query.get(other.user_id)
            chat_name = other_user.username or other_user.name
            other_avatar = other_user.avatar_url
        else:
            chat_name = 'Личный чат'
    else:
        chat_name = chat_obj.name

    all_chats = get_user_chats(user_id)

    return render_template(
        'chat.html',
        chat_id=chat_id,
        chat_name=chat_name,
        messages=messages,
        all_chats=all_chats,
        chat=chat_obj,
        other_avatar=other_avatar
    )

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
            return jsonify({
                'id': msg.id,
                'content': msg.content,
                'file_url': msg.file_url,
                'file_type': msg.file_type,
                'sender_id': msg.sender_id,
                'sender_name': sender.username or sender.name,
                'timestamp': msg.timestamp.strftime('%H:%M')
            }), 200

    if content.strip():
        msg.content = content
        msg.file_type = 'text'
        db.session.add(msg)
        db.session.commit()
        sender = User.query.get(msg.sender_id)
        return jsonify({
            'id': msg.id,
            'content': msg.content,
            'file_type': 'text',
            'sender_id': msg.sender_id,
            'sender_name': sender.username or sender.name,
            'timestamp': msg.timestamp.strftime('%H:%M')
        }), 200

    return jsonify({'error': 'Empty message'}), 400

@app.route('/get_new_messages/<int:chat_id>')
def get_new_messages(chat_id):
    if 'user_id' not in session:
        return jsonify([])
    last_id = request.args.get('last_id', 0, type=int)
    messages = Message.query.filter(
        Message.chat_id == chat_id,
        Message.id > last_id
    ).order_by(Message.timestamp).all()

    result = []
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        result.append({
            'id': msg.id,
            'content': msg.content,
            'file_url': msg.file_url,
            'file_type': msg.file_type,
            'sender_id': msg.sender_id,
            'sender_name': sender.username or sender.name,
            'timestamp': msg.timestamp.strftime('%H:%M')
        })
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)