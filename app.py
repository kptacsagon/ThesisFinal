import os
from datetime import datetime, timezone, timedelta
from functools import wraps

import jwt
from flask import Flask, jsonify, request, render_template, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///thesis.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")  # student/advisor/admin
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    theses = db.relationship("Thesis", backref="student", lazy=True, foreign_keys="Thesis.student_id")
    reviews = db.relationship("Review", backref="reviewer", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Thesis(db.Model):
    __tablename__ = "theses"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    abstract = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending/approved/needs_revision/rejected
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    reviews = db.relationship("Review", backref="thesis", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "abstract": self.abstract,
            "content": self.content,
            "student_id": self.student_id,
            "student_username": self.student.username if self.student else None,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    thesis_id = db.Column(db.Integer, db.ForeignKey("theses.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    decision = db.Column(db.String(20), nullable=False)  # approved/needs_revision/rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "thesis_id": self.thesis_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_username": self.reviewer.username if self.reviewer else None,
            "comment": self.comment,
            "decision": self.decision,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def create_token(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
        if not token:
            return jsonify({"error": "Token is missing"}), 401
        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            g.current_user = db.session.get(User, data["user_id"])
            if g.current_user is None:
                return jsonify({"error": "User not found"}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if g.current_user.role not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ---------------------------------------------------------------------------
# Routes – frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes – auth
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "student").strip()

    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400
    if role not in ("student", "advisor", "admin"):
        return jsonify({"error": "role must be student, advisor or admin"}), 400
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"error": "Username or email already exists"}), 409

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
    )
    db.session.add(user)
    db.session.commit()
    token = create_token(user.id)
    return jsonify({"message": "User registered successfully", "token": token, "user": user.to_dict()}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_token(user.id)
    return jsonify({"token": token, "user": user.to_dict()})


# ---------------------------------------------------------------------------
# Routes – theses
# ---------------------------------------------------------------------------

@app.route("/api/theses", methods=["GET"])
@token_required
def list_theses():
    if g.current_user.role == "student":
        theses = Thesis.query.filter_by(student_id=g.current_user.id).all()
    else:
        theses = Thesis.query.all()
    return jsonify([t.to_dict() for t in theses])


@app.route("/api/theses", methods=["POST"])
@token_required
@role_required("student")
def submit_thesis():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    abstract = (data.get("abstract") or "").strip()
    content = (data.get("content") or "").strip()

    if not title or not abstract or not content:
        return jsonify({"error": "title, abstract and content are required"}), 400

    thesis = Thesis(
        title=title,
        abstract=abstract,
        content=content,
        student_id=g.current_user.id,
    )
    db.session.add(thesis)
    db.session.commit()
    return jsonify(thesis.to_dict()), 201


@app.route("/api/theses/<int:thesis_id>", methods=["GET"])
@token_required
def get_thesis(thesis_id):
    thesis = db.session.get(Thesis, thesis_id)
    if thesis is None:
        return jsonify({"error": "Thesis not found"}), 404
    if g.current_user.role == "student" and thesis.student_id != g.current_user.id:
        return jsonify({"error": "Access denied"}), 403
    return jsonify(thesis.to_dict())


@app.route("/api/theses/<int:thesis_id>", methods=["PUT"])
@token_required
@role_required("student")
def update_thesis(thesis_id):
    thesis = db.session.get(Thesis, thesis_id)
    if thesis is None:
        return jsonify({"error": "Thesis not found"}), 404
    if thesis.student_id != g.current_user.id:
        return jsonify({"error": "Access denied"}), 403
    if thesis.status not in ("pending", "needs_revision"):
        return jsonify({"error": "Thesis cannot be edited in its current status"}), 400

    data = request.get_json(silent=True) or {}
    if "title" in data and data["title"].strip():
        thesis.title = data["title"].strip()
    if "abstract" in data and data["abstract"].strip():
        thesis.abstract = data["abstract"].strip()
    if "content" in data and data["content"].strip():
        thesis.content = data["content"].strip()
    thesis.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(thesis.to_dict())


@app.route("/api/theses/<int:thesis_id>/review", methods=["POST"])
@token_required
@role_required("advisor", "admin")
def submit_review(thesis_id):
    thesis = db.session.get(Thesis, thesis_id)
    if thesis is None:
        return jsonify({"error": "Thesis not found"}), 404

    data = request.get_json(silent=True) or {}
    comment = (data.get("comment") or "").strip()
    decision = (data.get("decision") or "").strip()

    if not comment or not decision:
        return jsonify({"error": "comment and decision are required"}), 400
    if decision not in ("approved", "needs_revision", "rejected"):
        return jsonify({"error": "decision must be approved, needs_revision or rejected"}), 400

    review = Review(
        thesis_id=thesis_id,
        reviewer_id=g.current_user.id,
        comment=comment,
        decision=decision,
    )
    db.session.add(review)
    thesis.status = decision
    thesis.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(review.to_dict()), 201


# ---------------------------------------------------------------------------
# Routes – users (admin only)
# ---------------------------------------------------------------------------

@app.route("/api/users", methods=["GET"])
@token_required
@role_required("admin")
def list_users():
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
