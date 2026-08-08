"""
speech_service.py — Speech-to-Text (STT) for NyaySetu.

This is the SERVER-SIDE FALLBACK only. The mic button in the chat UI uses
the browser's own Web Speech API (SpeechRecognition) by default — free,
instant, no round trip. It calls into this service only when the browser
has no SpeechRecognition support at all (Safari/iOS, most in-app webviews),
or if the native recognizer refuses to start.

STT is done with Gemini's multimodal audio understanding, reusing the same
google-generativeai client/API key NyaySetu's gemini_service.py already
uses — no separate Google Cloud Speech project or billing needed.

--------------------------------------------------------------------------
Setup
--------------------------------------------------------------------------
1. Install dependencies:
       pip install google-generativeai flask

2. Make sure GEMINI_API_KEY (or GOOGLE_API_KEY) is set in the environment —
   the same variable your existing gemini_service.py already reads.

3. Register the blueprint in app.py:

       from speech_service import speech_bp
       app.register_blueprint(speech_bp)

   That's it — this adds one route to your existing Flask app:
       POST /api/speech-to-text
"""

from __future__ import annotations

import base64
import logging
import os

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

speech_bp = Blueprint("speech", __name__)

# ---------------------------------------------------------------------------
# Language config — must stay in sync with the <select id="speechLangSelect">
# options in case_chat.html.
# ---------------------------------------------------------------------------

# Hints passed to Gemini so it knows what it's listening for (it will still
# transcribe whatever language is actually spoken).
STT_LANGUAGE_HINTS = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
}

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25MB — generous for a voice message


def _gemini_model():
    """Lazily configure and return a Gemini model for transcription.

    Imported lazily so this module can be imported (and its blueprint
    registered) even in environments where google-generativeai isn't
    installed yet, and so we don't reconfigure the SDK's global API key
    for every import if gemini_service.py already did it.
    """
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


@speech_bp.route("/api/speech-to-text", methods=["POST"])
def speech_to_text():
    """Transcribe a short voice recording.

    Request JSON:
        {
          "audio_base64": "<base64-encoded audio bytes>",
          "mime_type": "audio/webm",   # whatever MediaRecorder produced
          "language": "hi"             # one of STT_LANGUAGE_HINTS, hint only
        }

    Response JSON:
        { "text": "...", "language": "hi" }
        or { "error": "..." } with a 4xx/5xx status
    """
    data = request.get_json(force=True, silent=True) or {}
    audio_b64 = data.get("audio_base64")
    mime_type = data.get("mime_type") or "audio/webm"
    language = data.get("language") or "en"

    if not audio_b64:
        return jsonify({"error": "No audio provided."}), 400

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({"error": "Audio could not be decoded."}), 400

    if not audio_bytes:
        return jsonify({"error": "Audio was empty."}), 400

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return jsonify({"error": "Audio clip is too long (25MB max)."}), 400

    lang_hint = STT_LANGUAGE_HINTS.get(language, "English")
    prompt = (
        "Transcribe the following spoken audio exactly as spoken. "
        f"The speaker is likely speaking {lang_hint}, but transcribe "
        "whatever language is actually used, in that language's native "
        "script. Return ONLY the transcribed text — no commentary, no "
        "quotation marks, no preamble, no translation."
    )

    try:
        model = _gemini_model()
        response = model.generate_content(
            [prompt, {"mime_type": mime_type, "data": audio_bytes}]
        )
        transcript = (getattr(response, "text", None) or "").strip()
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the UI
        logger.exception("Speech-to-text transcription failed")
        return jsonify({"error": f"Transcription failed: {exc}"}), 502

    if not transcript:
        return jsonify({"error": "Could not make out any speech in that clip."}), 200

    return jsonify({"text": transcript, "language": language})