"""
Wraps the Gemini API call: sends the prompt + document text, parses the
JSON response, and maps it onto our Pydantic models. Isolated from
main.py so the AI provider or model version can change independently.
"""
import json
import os
import re
from typing import Union

import google.generativeai as genai

from ai_prompt import SYSTEM_PROMPT, build_user_message
from models import AnalysisResult, OutOfContextResult, ErrorResult

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

_configured = False


class AIServiceError(Exception):
    pass


def _ensure_configured():
    global _configured
    if _configured:
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise AIServiceError(
            "GEMINI_API_KEY is not set. Add it to your .env file before analyzing documents."
        )
    genai.configure(api_key=api_key)
    _configured = True


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    # Handle ```json ... ``` or ``` ... ``` wrappers some models add anyway.
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def analyze_document(document_text: str) -> Union[AnalysisResult, OutOfContextResult, ErrorResult]:
    """
    Sends the document text to Gemini for relevance-check + analysis.
    Returns a parsed AnalysisResult, OutOfContextResult, or ErrorResult.
    """
    try:
        _ensure_configured()
    except AIServiceError as exc:
        return ErrorResult(message=str(exc))

    try:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT,
            generation_config={"response_mime_type": "application/json"},
        )
        response = model.generate_content(build_user_message(document_text))
        raw = response.text
    except Exception as exc:
        return ErrorResult(message=f"The AI service could not process this document right now. ({exc})")

    try:
        cleaned = _strip_code_fences(raw)
        data = json.loads(cleaned)
    except Exception:
        return ErrorResult(
            message="The AI returned a response we couldn't parse. Please try again."
        )

    status = data.get("status")
    if status == "OUT_OF_CONTEXT":
        classification = data.get("classification", "NON_LEGAL")
        return OutOfContextResult.for_classification(classification)

    
    if status == "ANALYZED":
        try:
            return AnalysisResult(**data)
        except Exception as exc:
            return ErrorResult(message=f"The AI response didn't match the expected format. ({exc})")

    return ErrorResult(message="The AI returned an unrecognized response format.")
