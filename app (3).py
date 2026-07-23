import os
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, abort, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from sqlalchemy import or_, and_
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "sabina-dev-secret-key-change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'sabina.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB uploads

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access Sabina."
login_manager.login_message_category = "info"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(200), default="")
    avatar = db.Column(db.String(255), default="")  # filename in uploads, blank = default
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship("Post", backref="author", lazy="dynamic",
                             cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar_url(self):
        if self.avatar:
            return url_for("static", filename=f"uploads/{self.avatar}")
        return url_for("static", filename="img/default-avatar.svg")


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, default="")
    image = db.Column(db.String(255), default="")  # filename in uploads
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    likes = db.relationship("Like", backref="post", lazy="dynamic",
                             cascade="all, delete-orphan")
    comments = db.relationship("Comment", backref="post", lazy="dynamic",
                                cascade="all, delete-orphan")
    shares = db.relationship("Share", backref="post", lazy="dynamic",
                              cascade="all, delete-orphan")

    def liked_by(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.likes.filter_by(user_id=user.id).first() is not None


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("post_id", "user_id", name="unique_like"),)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User")


class Share(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # like, comment, share, friend_request, friend_accept
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    actor = db.relationship("User", foreign_keys=[actor_id])
    post = db.relationship("Post", foreign_keys=[post_id])

    def message(self):
        verbs = {
            "like": "liked your post",
            "comment": "commented on your post",
            "share": "shared your post",
            "friend_request": "sent you a friend request",
            "friend_accept": "accepted your friend request",
        }
        return verbs.get(self.type, "interacted with your post")


class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(10), default="pending")  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        db.UniqueConstraint("sender_id", "receiver_id", name="unique_friend_request"),
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage):
    if not file_storage or file_storage.filename == "":
        return ""
    if not allowed_file(file_storage.filename):
        return ""
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


def create_notification(recipient_id, actor_id, ntype, post_id=None):
    if recipient_id == actor_id:
        return  # don't notify yourself
    note = Notification(recipient_id=recipient_id, actor_id=actor_id,
                         type=ntype, post_id=post_id)
    db.session.add(note)
    db.session.commit()


def friendship_status(user_a, user_b):
    """Returns 'self', 'friends', 'incoming', 'outgoing', or 'none' from user_a's POV."""
    if user_a.id == user_b.id:
        return "self"
    req = FriendRequest.query.filter(
        or_(
            and_(FriendRequest.sender_id == user_a.id, FriendRequest.receiver_id == user_b.id),
            and_(FriendRequest.sender_id == user_b.id, FriendRequest.receiver_id == user_a.id),
        )
    ).first()
    if not req or req.status == "rejected":
        return "none"
    if req.status == "accepted":
        return "friends"
    return "incoming" if req.receiver_id == user_a.id else "outgoing"


def get_friends(user):
    accepted = FriendRequest.query.filter(
        FriendRequest.status == "accepted",
        or_(FriendRequest.sender_id == user.id, FriendRequest.receiver_id == user.id)
    ).all()
    return [r.receiver if r.sender_id == user.id else r.sender for r in accepted]


@app.context_processor
def inject_globals():
    unread_notifs = 0
    unread_messages = 0
    unread_friend_requests = 0
    if current_user.is_authenticated:
        unread_notifs = Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
        unread_messages = Message.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
        unread_friend_requests = FriendRequest.query.filter_by(
            receiver_id=current_user.id, status="pending").count()
    return dict(unread_notifs=unread_notifs, unread_messages=unread_messages,
                unread_friend_requests=unread_friend_requests, app_name="Sabina")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not username or not email or not password:
            error = "All fields are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif User.query.filter_by(email=email).first():
            error = "That email is already registered."

        if error:
            flash(error, "error")
            return render_template("register.html", username=username, email=email)

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f"Welcome to Sabina, {username}!", "success")
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter(
            (db.func.lower(User.username) == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.username}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))

        flash("Invalid username/email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Main pages
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
@login_required
def home():
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        image_file = request.files.get("image")
        image_filename = save_upload(image_file)

        if not content and not image_filename:
            flash("Write something or add a picture before posting.", "error")
            return redirect(url_for("home"))

        post = Post(user_id=current_user.id, content=content, image=image_filename)
        db.session.add(post)
        db.session.commit()
        flash("Your post is live!", "success")
        return redirect(request.referrer or url_for("home"))

    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template("home.html", posts=posts)


@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        liked = False
    else:
        like = Like(post_id=post.id, user_id=current_user.id)
        db.session.add(like)
        db.session.commit()
        create_notification(post.user_id, current_user.id, "like", post.id)
        liked = True

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(liked=liked, count=post.likes.count())
    return redirect(request.referrer or url_for("home"))


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def comment_post(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get("content", "").strip()
    if content:
        comment = Comment(post_id=post.id, user_id=current_user.id, content=content)
        db.session.add(comment)
        db.session.commit()
        create_notification(post.user_id, current_user.id, "comment", post.id)
    return redirect(request.referrer or url_for("home"))


@app.route("/post/<int:post_id>/share", methods=["POST"])
@login_required
def share_post(post_id):
    post = Post.query.get_or_404(post_id)
    share = Share(post_id=post.id, user_id=current_user.id)
    db.session.add(share)
    db.session.commit()
    create_notification(post.user_id, current_user.id, "share", post.id)
    flash("Post shared to your profile!", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(request.referrer or url_for("home"))


@app.route("/profile/<username>")
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = user.posts.order_by(Post.created_at.desc()).all()

    friend_status = "self"
    incoming_request = None
    if user.id != current_user.id:
        friend_status = friendship_status(current_user, user)
        if friend_status == "incoming":
            incoming_request = FriendRequest.query.filter_by(
                sender_id=user.id, receiver_id=current_user.id, status="pending").first()

    friends_list = get_friends(user)
    friends_count = len(friends_list)
    friends_preview = friends_list[:9]

    return render_template("profile.html", profile_user=user, posts=posts,
                            friend_status=friend_status, incoming_request=incoming_request,
                            friends_count=friends_count, friends_preview=friends_preview)


@app.route("/profile/<username>/friends")
@login_required
def profile_friends(username):
    user = User.query.filter_by(username=username).first_or_404()
    friends_list = get_friends(user)
    return render_template("profile_friends.html", profile_user=user, friends=friends_list)


@app.route("/friends")
@login_required
def friends():
    friends_list = get_friends(current_user)
    incoming = FriendRequest.query.filter_by(
        receiver_id=current_user.id, status="pending").order_by(FriendRequest.created_at.desc()).all()
    outgoing = FriendRequest.query.filter_by(
        sender_id=current_user.id, status="pending").order_by(FriendRequest.created_at.desc()).all()
    return render_template("friends.html", friends=friends_list, incoming=incoming, outgoing=outgoing)


@app.route("/friends/request/<username>", methods=["POST"])
@login_required
def send_friend_request(username):
    target = User.query.filter_by(username=username).first_or_404()
    if target.id == current_user.id:
        abort(400)

    existing = FriendRequest.query.filter(
        or_(
            and_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == target.id),
            and_(FriendRequest.sender_id == target.id, FriendRequest.receiver_id == current_user.id),
        )
    ).first()

    if existing:
        if existing.status == "rejected":
            existing.status = "pending"
            existing.sender_id = current_user.id
            existing.receiver_id = target.id
            existing.created_at = datetime.utcnow()
            db.session.commit()
            create_notification(target.id, current_user.id, "friend_request")
            flash("Friend request sent.", "success")
    else:
        req = FriendRequest(sender_id=current_user.id, receiver_id=target.id)
        db.session.add(req)
        db.session.commit()
        create_notification(target.id, current_user.id, "friend_request")
        flash("Friend request sent.", "success")

    return redirect(request.referrer or url_for("profile", username=username))


@app.route("/friends/cancel/<username>", methods=["POST"])
@login_required
def cancel_friend_request(username):
    target = User.query.filter_by(username=username).first_or_404()
    req = FriendRequest.query.filter_by(
        sender_id=current_user.id, receiver_id=target.id, status="pending").first()
    if req:
        db.session.delete(req)
        db.session.commit()
        flash("Friend request cancelled.", "info")
    return redirect(request.referrer or url_for("profile", username=username))


@app.route("/friends/accept/<int:request_id>", methods=["POST"])
@login_required
def accept_friend_request(request_id):
    req = FriendRequest.query.get_or_404(request_id)
    if req.receiver_id != current_user.id:
        abort(403)
    req.status = "accepted"
    db.session.commit()
    create_notification(req.sender_id, current_user.id, "friend_accept")
    flash(f"You and {req.sender.username} are now friends.", "success")
    return redirect(request.referrer or url_for("friends"))


@app.route("/friends/reject/<int:request_id>", methods=["POST"])
@login_required
def reject_friend_request(request_id):
    req = FriendRequest.query.get_or_404(request_id)
    if req.receiver_id != current_user.id:
        abort(403)
    db.session.delete(req)
    db.session.commit()
    flash("Friend request declined.", "info")
    return redirect(request.referrer or url_for("friends"))


@app.route("/friends/remove/<username>", methods=["POST"])
@login_required
def remove_friend(username):
    target = User.query.filter_by(username=username).first_or_404()
    req = FriendRequest.query.filter(
        FriendRequest.status == "accepted",
        or_(
            and_(FriendRequest.sender_id == current_user.id, FriendRequest.receiver_id == target.id),
            and_(FriendRequest.sender_id == target.id, FriendRequest.receiver_id == current_user.id),
        )
    ).first()
    if req:
        db.session.delete(req)
        db.session.commit()
        flash(f"Removed {target.username} from your friends.", "info")
    return redirect(request.referrer or url_for("profile", username=username))


@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    users, posts = [], []
    if q:
        users = User.query.filter(
            User.username.ilike(f"%{q}%"), User.id != current_user.id
        ).order_by(User.username).limit(20).all()
        posts = Post.query.filter(Post.content.ilike(f"%{q}%")) \
            .order_by(Post.created_at.desc()).limit(20).all()
    return render_template("search.html", query=q, users=users, posts=posts)


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        bio = request.form.get("bio", "").strip()
        avatar_file = request.files.get("avatar")
        avatar_filename = save_upload(avatar_file)

        current_user.bio = bio[:200]
        if avatar_filename:
            current_user.avatar = avatar_filename
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile", username=current_user.username))

    return render_template("edit_profile.html")


@app.route("/inbox")
@login_required
def inbox():
    sent_ids = db.session.query(Message.recipient_id).filter_by(sender_id=current_user.id)
    recv_ids = db.session.query(Message.sender_id).filter_by(recipient_id=current_user.id)
    partner_ids = {row[0] for row in sent_ids.union(recv_ids).all()}

    conversations = []
    for pid in partner_ids:
        partner = User.query.get(pid)
        if not partner:
            continue
        last_msg = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.recipient_id == pid)) |
            ((Message.sender_id == pid) & (Message.recipient_id == current_user.id))
        ).order_by(Message.created_at.desc()).first()
        unread = Message.query.filter_by(sender_id=pid, recipient_id=current_user.id,
                                          is_read=False).count()
        conversations.append((partner, last_msg, unread))

    conversations.sort(key=lambda c: c[1].created_at if c[1] else datetime.min, reverse=True)

    all_users = User.query.filter(User.id != current_user.id).order_by(User.username).all()
    return render_template("inbox.html", conversations=conversations, all_users=all_users)


@app.route("/inbox/<username>", methods=["GET", "POST"])
@login_required
def conversation(username):
    partner = User.query.filter_by(username=username).first_or_404()

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            msg = Message(sender_id=current_user.id, recipient_id=partner.id, body=body)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for("conversation", username=username))

    Message.query.filter_by(sender_id=partner.id, recipient_id=current_user.id,
                             is_read=False).update({"is_read": True})
    db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.recipient_id == partner.id)) |
        ((Message.sender_id == partner.id) & (Message.recipient_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()

    return render_template("conversation.html", partner=partner, messages=messages)


@app.route("/inbox/<username>/send", methods=["POST"])
@login_required
def send_message(username):
    """AJAX endpoint used by the real-time chat window to post a message."""
    partner = User.query.filter_by(username=username).first_or_404()
    body = request.form.get("body", "").strip()
    if not body:
        return jsonify(error="Message cannot be empty."), 400

    msg = Message(sender_id=current_user.id, recipient_id=partner.id, body=body[:1000])
    db.session.add(msg)
    db.session.commit()

    return jsonify(
        id=msg.id,
        body=msg.body,
        sender_id=msg.sender_id,
        created_at=msg.created_at.strftime("%I:%M %p").lstrip("0"),
    )


@app.route("/inbox/<username>/poll")
@login_required
def poll_messages(username):
    """AJAX endpoint the chat window polls for new messages (simulated real-time)."""
    partner = User.query.filter_by(username=username).first_or_404()
    after_id = request.args.get("after", 0, type=int)

    new_msgs = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.recipient_id == partner.id),
            and_(Message.sender_id == partner.id, Message.recipient_id == current_user.id),
        ),
        Message.id > after_id,
    ).order_by(Message.id.asc()).all()

    unread_ids = [m.id for m in new_msgs if m.sender_id == partner.id and not m.is_read]
    if unread_ids:
        Message.query.filter(Message.id.in_(unread_ids)).update(
            {"is_read": True}, synchronize_session=False)
        db.session.commit()

    return jsonify(messages=[{
        "id": m.id,
        "body": m.body,
        "sender_id": m.sender_id,
        "created_at": m.created_at.strftime("%I:%M %p").lstrip("0"),
    } for m in new_msgs])


@app.route("/api/counts")
@login_required
def api_counts():
    """Polled by every page to keep nav badges (messages/notifications/friends) live."""
    unread_notifs = Notification.query.filter_by(
        recipient_id=current_user.id, is_read=False).count()
    unread_messages = Message.query.filter_by(
        recipient_id=current_user.id, is_read=False).count()
    unread_friend_requests = FriendRequest.query.filter_by(
        receiver_id=current_user.id, status="pending").count()
    return jsonify(unread_notifs=unread_notifs, unread_messages=unread_messages,
                    unread_friend_requests=unread_friend_requests)


@app.route("/notifications")
@login_required
def notifications():
    notes = Notification.query.filter_by(recipient_id=current_user.id) \
        .order_by(Notification.created_at.desc()).all()
    Notification.query.filter_by(recipient_id=current_user.id, is_read=False) \
        .update({"is_read": True})
    db.session.commit()
    return render_template("notifications.html", notes=notes)


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
