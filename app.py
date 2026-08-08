import os
import base64
from functools import wraps

import cloudinary
import cloudinary.uploader
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


@app.context_processor
def inject_user():
    """Makes `user` available in every template automatically, so the nav
    partial's {% if user %} works no matter which route rendered the page.
    Without this, only routes that explicitly passed user=... into
    render_template() showed the logged-in state in the nav — e.g. home()
    never set it, so the nav showed Login/Signup on '/' even while logged
    in. Explicitly passing user=... into a specific render_template() call
    still overrides this if you ever need to.
    """
    user = None
    if session.get("user_id"):
        user = db.get_user_by_id(session["user_id"])
    return {"user": user}


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


# NOTE: this used to be named `home()` too, which silently overwrote the
# "/" route in Flask's url map (duplicate endpoint name -> AssertionError
# on startup, or the wrong view winning depending on import order). Renamed.
@app.route("/dashboard")
@login_required
def dashboard():
    # `user` no longer needs to be passed explicitly here — inject_user()
    # above supplies it to every template, including this one. Left the
    # lookup out entirely rather than keep a now-redundant duplicate call.
    return render_template("dashboard.html")


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
    return redirect(next_url or url_for("dashboard"))


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
    return redirect(url_for("dashboard"))


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
    return render_template("new_issue.html", pending_upload=_pop_pending_upload())


@app.route("/case/<int:case_id>")
@login_required
def resume_case(case_id):
    """Clicking a row in the dashboard's case list (= chat history) lands
    here. We verify ownership, make this the active case for the session,
    and hand the chat template the full message history so it can render
    the thread instead of starting blank."""
    user_id = session["user_id"]
    case = db.get_case(case_id, user_id=user_id)
    if not case:
        flash("That case couldn't be found.")
        return redirect(url_for("dashboard"))

    session["active_case_id"] = case["id"]
    history = db.get_case_messages(case["id"])
    return render_template(
        "new_issue.html",
        case=case,
        chat_history=history,
        pending_upload=_pop_pending_upload(),
    )


def _pop_pending_upload():
    """A doc uploaded from the dashboard sidebar is stashed in the session
    for exactly one request, then handed to new_issue.html so its JS can
    render the attachment bubble and pre-fill the file_url/file_name/etc.
    fields that /api/legal-chat expects on the next message. Template side
    (new_issue.html) needs something like:

        {% if pending_upload %}
        <script>
          window.__PENDING_UPLOAD__ = {{ pending_upload | tojson }};
        </script>
        {% endif %}

    and JS that reads window.__PENDING_UPLOAD__ on load to show the
    attached-file chip above the composer.
    """
    return session.pop("pending_upload", None)


# ---------------------------------------------------------------------------
# Dashboard data API — replaces the SAMPLE_* constants in dashboard.html
# ---------------------------------------------------------------------------

def _status_for_case(case):
    """Cases don't carry an explicit UI status column in the current model,
    so we derive the 3-way dashboard status from what already exists:
    a case is 'resolved' once marked so, otherwise 'needs' action if there's
    no AI-suggested next step yet (fresh/awaiting-strength), else 'review'.
    If you add a real `status` column to Case, swap this for `case["status"]`.
    """
    if case.get("resolved"):
        return "resolved"
    if case.get("strength") is None and not case.get("summary"):
        return "needs"
    return "review"


@app.route("/api/dashboard/data")
@login_required
def dashboard_data():
    user_id = session["user_id"]

    cases = db.get_user_cases(user_id)
    cases_out = [
        {
            "id": c["id"],
            "title": c.get("category") or c.get("summary") or "Untitled issue",
            "category": c.get("category") or "Uncategorized",
            "status": _status_for_case(c),
            "updated": c.get("updated_at_display", ""),
            "desc": c.get("summary") or "No summary yet — continue the conversation to get guidance.",
            "step": c.get("step", 0),
        }
        for c in cases
    ]

    total = len(cases_out)
    resolved = sum(1 for c in cases_out if c["status"] == "resolved")
    needs = sum(1 for c in cases_out if c["status"] == "needs")
    active = total - resolved

    documents = db.get_user_documents(user_id)
    docs_out = [
        {
            "name": d["file_name"] or "document",
            "size": d.get("size_display", ""),
            "date": d.get("uploaded_at_display", ""),
            "url": d["file_url"],
            "case_id": d["case_id"],
        }
        for d in documents
    ]

    activity = db.get_recent_activity(user_id, limit=8)

    return jsonify(
        {
            "stats": [
                {"label": "Active cases", "value": str(active), "delta": "", "tone": "st-1"},
                {"label": "Resolved", "value": str(resolved), "delta": "", "tone": "st-2"},
                {"label": "Pending actions", "value": str(needs), "delta": "", "tone": "st-3"},
                {"label": "Documents on file", "value": str(len(docs_out)), "delta": "", "tone": "st-4"},
            ],
            "cases": cases_out,
            "documents": docs_out,
            "activity": activity,
        }
    )


@app.route("/api/dashboard/cases/<int:case_id>/resolve", methods=["POST"])
@login_required
@csrf.exempt
def resolve_case(case_id):
    user_id = session["user_id"]
    case = db.get_case(case_id, user_id=user_id)
    if not case:
        return jsonify({"error": "Case not found."}), 404
    db.mark_case_resolved(case_id)
    return jsonify({"ok": True})


@app.route("/api/dashboard/upload-document", methods=["POST"])
@login_required
@csrf.exempt
def dashboard_upload_document():
    """The sidebar 'Upload a document' button in dashboard.html posts here.
    We store the file on Cloudinary, attach it to a case (an existing one if
    case_id was passed, otherwise a fresh one), stash it as a pending upload
    for that case's chat page, and hand the frontend a redirect URL. The
    frontend then does `window.location = redirect_url` so the user lands
    directly in the chat with their file already attached.
    """
    user_id = session["user_id"]

    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "No file provided."}), 400

    file_bytes = uploaded.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "File exceeds the 100MB limit."}), 400

    try:
        upload_result = cloudinary.uploader.upload(
            file_bytes,
            resource_type="auto",
            folder="nyaysetu/case-documents",
            filename=uploaded.filename,
            use_filename=True,
            unique_filename=True,
        )
    except Exception:
        app.logger.exception("Cloudinary upload failed (dashboard sidebar)")
        return jsonify({"error": "Failed to store the uploaded file."}), 502

    file_url = upload_result.get("secure_url")
    file_public_id = upload_result.get("public_id")
    mime_type = uploaded.mimetype or "application/octet-stream"

    case_id = request.form.get("case_id", type=int)
    case = db.get_case(case_id, user_id=user_id) if case_id else None
    if not case:
        case = db.create_case(user_id=user_id)

    # Stash for the chat page to pick up on next render (see _pop_pending_upload)
    session["pending_upload"] = {
        "file_url": file_url,
        "file_name": uploaded.filename,
        "file_type": mime_type,
        "file_public_id": file_public_id,
    }

    return jsonify(
        {
            "ok": True,
            "case_id": case["id"],
            "redirect_url": url_for("resume_case", case_id=case["id"]),
        }
    )


@app.route("/api/legal-chat", methods=["POST"])
@login_required
@csrf.exempt
def legal_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    # Optional — set when this turn is attached to a file uploaded via
    # /api/analyze-document (or the dashboard sidebar) just before this call.
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
        {"role": "model" if m["role"] == "assistant" else "user", "content": m["content"]}
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
        return jsonify({"error": "Failed to store the uploaded file. Check server logs / Cloudinary credentials."}), 502

    file_url = upload_result.get("secure_url")
    file_public_id = upload_result.get("public_id")
    app.logger.info("Uploaded %s to Cloudinary: %s", file_name or "(unnamed)", file_url)

    # 2. Ask Gemini to read and explain the document. If this fails, the file
    # is already safely on Cloudinary — just degrade to a fallback
    # explanation instead of discarding the upload and erroring out.
    try:
        result = analyze_legal_document(file_bytes, mime_type=mime_type, file_name=file_name)
    except Exception:
        app.logger.exception("Document analysis failed (file is still stored on Cloudinary: %s)", file_url)
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