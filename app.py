import os
import base64
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import db

# --- Load env vars BEFORE anything else touches os.environ ---
load_dotenv()

# Import the Gemini service AFTER load_dotenv() so its module-level
# client init sees the key.
from gemini_service import get_legal_ai_reply, analyze_legal_document

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
    # Starting a fresh issue should start a fresh case, not keep appending
    # to whatever case was active before.
    session.pop("active_case_id", None)
    return render_template("new_issue.html")


@app.route("/api/legal-chat", methods=["POST"])
@login_required
@csrf.exempt
def legal_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is required."}), 400

    user_id = session["user_id"]

    # One active case per browser session; a fresh case starts when the
    # user lands on /new-issue (see chat() above) or has no active case yet.
    case_id = session.get("active_case_id")
    case = db.get_case(case_id, user_id=user_id) if case_id else None
    if not case:
        case = db.create_case(user_id=user_id)
        session["active_case_id"] = case["id"]

    # Build the conversation history Gemini needs from what's already
    # persisted for this case (source of truth is Postgres, not the client).
    prior_messages = db.get_case_messages(case["id"])
    history = [
        {"role": "model" if m["role"] == "assistant" else "user", "content": m["content"]}
        for m in prior_messages
    ]

    # Persist the user's message
    db.save_chat_message(case_id=case["id"], role="user", content=message)

    try:
        result = get_legal_ai_reply(history, message)
    except Exception:
        app.logger.exception("Gemini call failed")
        return jsonify({"error": "Failed to generate a response. Please try again."}), 502

    # Persist the assistant's reply
    db.save_chat_message(case_id=case["id"], role="assistant", content=result.get("reply", ""))

    # Keep the case row's category/summary/strength in sync as the model
    # learns more, so a case list / dashboard elsewhere stays accurate.
    if result.get("category") or result.get("summary") or result.get("strength") is not None:
        db.update_case_meta(
            case["id"],
            category=result.get("category"),
            summary=result.get("summary"),
            strength=result.get("strength"),
        )

    # Response is flat (not nested) — chat.html reads result.type / result.reply /
    # result.category / result.summary / result.strength directly off the JSON body.
    result["case_id"] = case["id"]
    return jsonify(result)


@app.route("/api/analyze-document", methods=["POST"])
@login_required
@csrf.exempt
def analyze_document():
    data = request.get_json(silent=True) or {}
    file_b64 = data.get("file_base64")
    mime_type = data.get("mime_type") or "application/pdf"
    file_name = data.get("file_name", "")

    if not file_b64:
        return jsonify({"error": "file_base64 is required."}), 400

    try:
        file_bytes = base64.b64decode(file_b64)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid base64 file data."}), 400

    try:
        result = analyze_legal_document(file_bytes, mime_type=mime_type, file_name=file_name)
    except Exception:
        app.logger.exception("Document analysis failed")
        return jsonify({"error": "Failed to analyze document."}), 502

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=9000)