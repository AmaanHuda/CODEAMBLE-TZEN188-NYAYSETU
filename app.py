import os
import base64
from functools import wraps

import cloudinary
import cloudinary.uploader
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

import db

# --- Load env vars BEFORE anything else touches os.environ ---
load_dotenv()

# Import the Gemini service AFTER load_dotenv() so its module-level
# client init sees the key.
from gemini_service import get_legal_ai_reply, analyze_legal_document

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-only-fallback-key"
)  # set SECRET_KEY in .env for real use
csrf = CSRFProtect(app)

with app.app_context():
    db.init_db()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB, matches the frontend's stated limit

# --- Google OAuth setup ---
# Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env
# and http(s)://<your-host>/login/google/callback registered as an
# authorized redirect URI in the Google Cloud Console.
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


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
    if (
        not user
        or not user.get("password_hash")
        or not check_password_hash(user["password_hash"], password)
    ):
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


@app.route("/login/google")
def login_google():
    # Preserve ?next= across the OAuth round trip via the session, since
    # Google's redirect back to us won't carry our query params.
    next_url = request.args.get("next")
    if next_url:
        session["post_login_next"] = next_url
    redirect_uri = url_for("login_google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def login_google_callback():
    try:
        token = google.authorize_access_token()
    except Exception:
        app.logger.exception("Google OAuth token exchange failed")
        flash("Google sign-in failed. Please try again.")
        return redirect(url_for("login"))

    userinfo = token.get("userinfo")
    if not userinfo:
        # Some providers/configs don't inline userinfo in the token; fetch explicitly.
        userinfo = google.get("https://openid.net/specs/connect/1_0/userinfo").json()

    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name") or (email.split("@")[0] if email else "User")
    email_verified = userinfo.get("email_verified", False)

    if not google_id or not email:
        flash("Couldn't read your Google account details. Please try again.")
        return redirect(url_for("login"))

    if not email_verified:
        flash("Please verify your email with Google before signing in.")
        return redirect(url_for("login"))

    # Link to an existing account by google_id first, then by email
    # (covers a user who originally signed up with a password).
    user = db.get_user_by_google_id(google_id)
    if not user:
        user = db.get_user_by_email(email)
        if user:
            db.link_google_account(user["id"], google_id)
        else:
            user = db.create_google_user(name, email, google_id)

    session["user_id"] = user["id"]
    next_url = session.pop("post_login_next", None)
    return redirect(next_url or url_for("chat"))


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
    # Optional — set when this turn is attached to a file uploaded via
    # /api/analyze-document just before this call.
    file_url = data.get("file_url")
    file_name = data.get("file_name")
    file_type = data.get("file_type")
    file_public_id = data.get("file_public_id")

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
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "content": m["content"],
        }
        for m in prior_messages
    ]

    # Persist the user's message, with the Cloudinary link if one was attached
    db.save_chat_message(
        case_id=case["id"],
        role="user",
        content=message,
        file_url=file_url,
        file_name=file_name,
        file_type=file_type,
        file_public_id=file_public_id,
    )

    try:
        result = get_legal_ai_reply(history, message)
    except Exception:
        app.logger.exception("Gemini call failed")
        return (
            jsonify({"error": "Failed to generate a response. Please try again."}),
            502,
        )

    # Persist the assistant's reply
    db.save_chat_message(
        case_id=case["id"], role="assistant", content=result.get("reply", "")
    )

    # Keep the case row's category/summary/strength in sync as the model
    # learns more, so a case list / dashboard elsewhere stays accurate.
    if (
        result.get("category")
        or result.get("summary")
        or result.get("strength") is not None
    ):
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

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "File exceeds the 100MB limit."}), 400

    # 1. Upload the original file to Cloudinary FIRST — resource_type="auto"
    # handles both PDFs and images. Neon only ever stores the URL this
    # returns. This must not be gated on the Gemini call below: if the AI
    # analysis fails for any reason, the user's file should still be safely
    # stored and linked, not silently dropped.
    try:
        upload_result = cloudinary.uploader.upload(
            file_bytes,
            resource_type="auto",
            folder="nyaysetu/case-documents",
            filename=file_name or None,
            use_filename=bool(file_name),
            unique_filename=True,
        )
    except Exception:
        app.logger.exception("Cloudinary upload failed")
        return (
            jsonify(
                {
                    "error": "Failed to store the uploaded file. Check server logs / Cloudinary credentials."
                }
            ),
            502,
        )

    file_url = upload_result.get("secure_url")
    file_public_id = upload_result.get("public_id")
    app.logger.info("Uploaded %s to Cloudinary: %s", file_name or "(unnamed)", file_url)

    # 2. Ask Gemini to read and explain the document. If this fails, the file
    # is already safely on Cloudinary — just degrade to a fallback
    # explanation instead of discarding the upload and erroring out.
    try:
        result = analyze_legal_document(
            file_bytes, mime_type=mime_type, file_name=file_name
        )
    except Exception:
        app.logger.exception(
            "Document analysis failed (file is still stored on Cloudinary: %s)",
            file_url,
        )
        result = {
            "status": "ERROR",
            "error": "We stored your document, but couldn't automatically analyze it right now. "
            "You can still reference it below, and describe its contents in the chat.",
        }

    result["file_url"] = file_url
    result["file_name"] = file_name
    result["file_type"] = mime_type
    result["file_public_id"] = file_public_id

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=9000)