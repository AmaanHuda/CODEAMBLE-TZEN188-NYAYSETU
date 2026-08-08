import os
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import db

# --- Load env vars BEFORE anything else touches os.environ ---
load_dotenv()

# Import the Gemini service AFTER load_dotenv() so its module-level
# client init (if any) sees the key. If gemini_service reads the key
# lazily inside a function instead, import order won't matter, but
# this is the safe default either way.
 # adjust name if different

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-only-fallback-key"
)  # set SECRET_KEY in .env for real use
csrf = CSRFProtect(app)

with app.app_context():
    db.init_db()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.")
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


@app.route("/")
def home():
    return render_template("main.html")


@app.route("/login", methods=["GET"])
def login():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_submit():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = db.get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Incorrect email or password.")
        return redirect(url_for("login"))

    session["user_id"] = user["id"]
    next_url = request.args.get("next")
    return redirect(next_url or url_for("chat"))


@app.route("/signup", methods=["POST"])
def signup():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        flash("All fields are required.")
        return redirect(url_for("login"))

    if db.get_user_by_email(email):
        flash("An account with that email already exists.")
        return redirect(url_for("login"))

    user = db.create_user(name, email, generate_password_hash(password))
    session["user_id"] = user["id"]
    return redirect(url_for("chat"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("home"))


@app.route("/new-issue")
@login_required
def chat():
    return render_template("new-issue.html")


@app.route("/api/legal-chat", methods=["POST"])
@login_required
def legal_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    case_id = data.get("case_id")
    language = data.get("language", "en")

    if not message:
        return jsonify({"error": "Message is required."}), 400

    user_id = session["user_id"]

    # Get or create the case this conversation belongs to.
    # Adjust to your actual db.py function names if different.
    if case_id:
        case = db.get_case(case_id, user_id=user_id)
        if not case:
            return jsonify({"error": "Case not found."}), 404
    else:
        case = db.create_case(user_id=user_id)

    # Persist the user's message
    db.save_chat_message(case_id=case["id"], role="user", content=message)

    try:
        gemini_result = generate_legal_response(
            message=message,
            case_id=case["id"],
            language=language,
        )
    except Exception as e:
        app.logger.exception("Gemini call failed")
        return jsonify({"error": "Failed to generate a response. Please try again."}), 502

    # Persist the assistant's reply
    db.save_chat_message(case_id=case["id"], role="assistant", content=gemini_result)

    return jsonify({
        "case_id": case["id"],
        "response": gemini_result,
    })


if __name__ == "__main__":
    app.run(debug=True, port=9000)