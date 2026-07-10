import os
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify, abort
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from sqlalchemy import or_, desc
from werkzeug.utils import secure_filename

from extensions import db, login_manager, socketio
from models import User, Conversation, Message, Post, Like, Comment

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Mount Render's persistent disk at static/uploads (see render.yaml) so photos
# survive redeploys — Flask serves them straight out of the static folder.
UPLOAD_PROFILES = os.path.join(BASE_DIR, "static", "uploads", "profiles")
UPLOAD_POSTS = os.path.join(BASE_DIR, "static", "uploads", "posts")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "ethiogram-dev-secret-change-me")
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url or f"sqlite:///{os.path.join(BASE_DIR, 'ethiogram.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB uploads

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    socketio.init_app(app, message_queue=os.environ.get("REDIS_URL"))

    os.makedirs(UPLOAD_PROFILES, exist_ok=True)
    os.makedirs(UPLOAD_POSTS, exist_ok=True)

    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file_storage, folder):
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(folder, secure_filename(fname)))
    return fname


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def find_user_by_identifier(identifier):
    return User.query.filter(
        or_(User.username == identifier, User.email == identifier, User.phone == identifier)
    ).first()


def get_or_create_conversation(user_a_id, user_b_id):
    a, b = sorted([user_a_id, user_b_id])
    convo = Conversation.query.filter_by(user_a_id=a, user_b_id=b).first()
    if not convo:
        convo = Conversation(user_a_id=a, user_b_id=b)
        db.session.add(convo)
        db.session.commit()
    return convo


def register_routes(app):

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("feed"))
        return redirect(url_for("login"))

    # ---------- AUTH ----------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("feed"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            contact = request.form.get("contact", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")

            if not username or not contact or not password:
                flash("Please fill in your username, phone/email, and password.", "error")
                return render_template("register.html")
            if password != confirm:
                flash("Passwords do not match.", "error")
                return render_template("register.html")
            if len(password) < 6:
                flash("Password should be at least 6 characters.", "error")
                return render_template("register.html")
            if User.query.filter_by(username=username).first():
                flash("That username is already taken.", "error")
                return render_template("register.html")

            is_email = "@" in contact
            if is_email and User.query.filter_by(email=contact).first():
                flash("An account with that email already exists.", "error")
                return render_template("register.html")
            if not is_email and User.query.filter_by(phone=contact).first():
                flash("An account with that phone number already exists.", "error")
                return render_template("register.html")

            user = User(
                username=username,
                email=contact if is_email else None,
                phone=None if is_email else contact,
                full_name=request.form.get("full_name", "").strip() or username,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Welcome to Ethiogram!", "success")
            return redirect(url_for("feed"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("feed"))
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            password = request.form.get("password", "")
            user = find_user_by_identifier(identifier)
            if user and user.check_password(password):
                login_user(user, remember=True)
                user.last_seen = datetime.utcnow()
                db.session.commit()
                return redirect(url_for("feed"))
            flash("No account matches those details, or the password is wrong.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------- FEED ----------
    @app.route("/feed", methods=["GET", "POST"])
    @login_required
    def feed():
        if request.method == "POST":
            content = request.form.get("content", "").strip()
            image_file = request.files.get("image")
            image_name = None
            if image_file and image_file.filename and allowed_file(image_file.filename):
                image_name = save_upload(image_file, UPLOAD_POSTS)
            if content or image_name:
                post = Post(user_id=current_user.id, content=content, image=image_name)
                db.session.add(post)
                db.session.commit()
            return redirect(url_for("feed"))

        posts = Post.query.order_by(desc(Post.timestamp)).limit(50).all()
        return render_template("feed.html", posts=posts)

    @app.route("/post/<int:post_id>/like", methods=["POST"])
    @login_required
    def like_post(post_id):
        post = Post.query.get_or_404(post_id)
        existing = Like.query.filter_by(post_id=post.id, user_id=current_user.id).first()
        if existing:
            db.session.delete(existing)
            liked = False
        else:
            db.session.add(Like(post_id=post.id, user_id=current_user.id))
            liked = True
        db.session.commit()
        return jsonify({"liked": liked, "count": post.like_count()})

    @app.route("/post/<int:post_id>/comment", methods=["POST"])
    @login_required
    def comment_post(post_id):
        post = Post.query.get_or_404(post_id)
        text = request.form.get("content", "").strip()
        if text:
            c = Comment(post_id=post.id, user_id=current_user.id, content=text)
            db.session.add(c)
            db.session.commit()
        return redirect(url_for("feed"))

    @app.route("/post/<int:post_id>/delete", methods=["POST"])
    @login_required
    def delete_post(post_id):
        post = Post.query.get_or_404(post_id)
        if post.user_id != current_user.id:
            abort(403)
        Like.query.filter_by(post_id=post.id).delete()
        Comment.query.filter_by(post_id=post.id).delete()
        db.session.delete(post)
        db.session.commit()
        return redirect(url_for("feed"))

    # ---------- PROFILE ----------
    @app.route("/profile/<int:user_id>")
    @login_required
    def profile(user_id):
        user = User.query.get_or_404(user_id)
        posts = Post.query.filter_by(user_id=user.id).order_by(desc(Post.timestamp)).all()
        return render_template("profile.html", profile_user=user, posts=posts)

    @app.route("/profile/edit", methods=["GET", "POST"])
    @login_required
    def edit_profile():
        if request.method == "POST":
            current_user.full_name = request.form.get("full_name", "").strip() or current_user.username
            current_user.bio = request.form.get("bio", "").strip()[:280]
            pic = request.files.get("profile_pic")
            if pic and pic.filename and allowed_file(pic.filename):
                current_user.profile_pic = save_upload(pic, UPLOAD_PROFILES)
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("profile", user_id=current_user.id))
        return render_template("edit_profile.html")

    # ---------- CHAT ----------
    @app.route("/chat")
    @app.route("/chat/<int:user_id>")
    @login_required
    def chat(user_id=None):
        my_convos = Conversation.query.filter(
            or_(Conversation.user_a_id == current_user.id, Conversation.user_b_id == current_user.id)
        ).all()
        my_convos.sort(key=lambda c: (c.last_message().timestamp if c.last_message() else c.created_at), reverse=True)

        active_convo = None
        active_other = None
        messages = []
        if user_id:
            other = User.query.get_or_404(user_id)
            active_convo = get_or_create_conversation(current_user.id, other.id)
            active_other = other
            messages = Message.query.filter_by(conversation_id=active_convo.id).order_by(Message.timestamp).all()
            unread = Message.query.filter_by(conversation_id=active_convo.id, is_read=False).filter(
                Message.sender_id != current_user.id
            ).all()
            for m in unread:
                m.is_read = True
            db.session.commit()

        search = request.args.get("q", "").strip()
        search_results = []
        if search:
            search_results = User.query.filter(
                User.username.ilike(f"%{search}%"), User.id != current_user.id
            ).limit(10).all()

        return render_template(
            "chat.html",
            conversations=my_convos,
            active_convo=active_convo,
            active_other=active_other,
            messages=messages,
            search=search,
            search_results=search_results,
        )

    @app.route("/api/user_search")
    @login_required
    def api_user_search():
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([])
        users = User.query.filter(User.username.ilike(f"%{q}%"), User.id != current_user.id).limit(10).all()
        return jsonify([
            {"id": u.id, "username": u.username, "avatar": u.avatar_url(), "full_name": u.full_name}
            for u in users
        ])

    @app.context_processor
    def inject_globals():
        return {"app_name": "Ethiogram"}


# ---------------- SOCKET.IO EVENTS ----------------
from flask_socketio import join_room, emit
from flask_login import current_user as _cu


@socketio.on("join")
def handle_join(data):
    room = data.get("room")
    if room:
        join_room(room)


@socketio.on("send_message")
def handle_send_message(data):
    conversation_id = data.get("conversation_id")
    sender_id = data.get("sender_id")
    content = (data.get("content") or "").strip()
    if not conversation_id or not sender_id or not content:
        return

    convo = Conversation.query.get(conversation_id)
    if not convo:
        return

    msg = Message(conversation_id=conversation_id, sender_id=sender_id, content=content)
    db.session.add(msg)
    db.session.commit()

    sender = User.query.get(sender_id)
    payload = {
        "id": msg.id,
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "sender_username": sender.username if sender else "?",
        "content": content,
        "timestamp": msg.timestamp.strftime("%H:%M"),
    }
    room = f"conv_{conversation_id}"
    emit("new_message", payload, room=room)

    other_id = convo.user_b_id if convo.user_a_id == sender_id else convo.user_a_id
    emit("chat_notify", payload, room=f"user_{other_id}")


@socketio.on("typing")
def handle_typing(data):
    room = f"conv_{data.get('conversation_id')}"
    emit("typing", data, room=room, include_self=False)


app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
