from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(80), nullable=True)
    bio = db.Column(db.String(280), default="")
    profile_pic = db.Column(db.String(200), default="default.png")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar_url(self):
        if not self.profile_pic or self.profile_pic == "default.png":
            return "/static/img/default-avatar.png"
        return f"/static/uploads/profiles/{self.profile_pic}"


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_a = db.relationship("User", foreign_keys=[user_a_id])
    user_b = db.relationship("User", foreign_keys=[user_b_id])

    __table_args__ = (db.UniqueConstraint("user_a_id", "user_b_id", name="uq_conversation_pair"),)

    def other_user(self, current_user_id):
        return self.user_b if self.user_a_id == current_user_id else self.user_a

    def last_message(self):
        return (
            Message.query.filter_by(conversation_id=self.id)
            .order_by(Message.timestamp.desc())
            .first()
        )

    def unread_count(self, current_user_id):
        return Message.query.filter_by(
            conversation_id=self.id, is_read=False
        ).filter(Message.sender_id != current_user_id).count()


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship("User")


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    author = db.relationship("User")

    def like_count(self):
        return Like.query.filter_by(post_id=self.id).count()

    def comment_count(self):
        return Comment.query.filter_by(post_id=self.id).count()

    def liked_by(self, user_id):
        return Like.query.filter_by(post_id=self.id, user_id=user_id).first() is not None

    def comments_ordered(self):
        return Comment.query.filter_by(post_id=self.id).order_by(Comment.timestamp).all()


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("post_id", "user_id", name="uq_like_pair"),)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User")
