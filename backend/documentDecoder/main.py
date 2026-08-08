import os
import traceback
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

load_dotenv()

from ai_service import analyze_document
from extraction import ExtractionError, ScannedPdfError, extract_text
from models import ErrorResult

MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "15"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "templates"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_BYTES  # Flask-level hard cap on request size

CORS(app)  # tighten this to your actual frontend origin in production


def json_error(message: str, status_code: int):
    return jsonify(ErrorResult(message=message).model_dump()), status_code


@app.get("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "documentDecoder.html")

@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/analyze")
def analyze():
    if "file" not in request.files:
        return json_error("No file was uploaded.", 400)

    file = request.files["file"]
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        return json_error(
            f"Unsupported file type '{suffix or 'unknown'}'. Please upload a PDF, DOCX, or TXT file.",
            400,
        )

    tmp_path = None
    try:
        # Save to a temp file rather than holding everything in memory; Flask has
        # already enforced MAX_CONTENT_LENGTH above the request, so this is a
        # bounded write.
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            file.save(tmp_path)

        size = tmp_path.stat().st_size
        if size == 0:
            return json_error("The uploaded file is empty.", 400)

        try:
            text = extract_text(tmp_path, filename)
        except ScannedPdfError as exc:
            return json_error(str(exc), 422)
        except ExtractionError as exc:
            return json_error(str(exc), 422)

        result = analyze_document(text)
        status_code = 200 if result.status != "ERROR" else 502
        return jsonify(result.model_dump()), status_code

    except Exception:
        # Never leak raw backend errors/tracebacks to the client.
        traceback.print_exc()
        return json_error(
            "Something went wrong while processing your document. Please try again.", 500
        )
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@app.errorhandler(413)
def too_large(_exc):
    return json_error(f"File exceeds the {MAX_FILE_SIZE_MB}MB size limit.", 413)


# server so the whole app can be run with a single process during development.


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(str(FRONTEND_DIR), path)

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8001,
        debug=True
    )