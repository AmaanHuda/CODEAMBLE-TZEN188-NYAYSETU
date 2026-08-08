# Nyay Setu

Upload a contract, lease, NDA, or other legal document and get a plain-English
breakdown: summary, key terms, deadlines, responsibilities, risks, and
questions to bring to a lawyer. Non-legal documents (recipes, resumes,
essays, etc.) are rejected with an "Out of context" message rather than
being force-analyzed.

## Stack

- **Backend:** FastAPI (Python) — file upload, text extraction (`pdfplumber`,
  `python-docx`), and the Gemini API call for classification + analysis.
- **Frontend:** Plain HTML/CSS/JS (no build step) — drag-and-drop upload,
  a staged "processing" screen, and a tabbed results dashboard.
- **AI:** Google Gemini (`google-generativeai`), prompted to run a
  relevance check before ever attempting legal analysis.

The backend serves the frontend directly, so the whole app runs as one
process during development.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your Gemini API key:

```
GEMINI_API_KEY=your_actual_key_here
```

You can get a key from https://aistudio.google.com/apikey.

## Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser. Upload a PDF, DOCX, or TXT
file (up to 15MB) and it will be analyzed.

## Project layout

```
legal-doc-decoder/
├── backend/
│   ├── main.py          # FastAPI app, /api/analyze and /api/health routes
│   ├── extraction.py    # PDF/DOCX/TXT text extraction
│   ├── ai_prompt.py      # The AI prompt, kept separate from app code
│   ├── ai_service.py     # Gemini call + JSON parsing/validation
│   ├── models.py         # Pydantic response schemas
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

## How it decides "legal" vs "not legal"

Every document goes through the same single AI request. The prompt (in
`ai_prompt.py`) requires the model to classify the document as `LEGAL`,
`NON_LEGAL`, or `UNCERTAIN` _before_ producing any analysis. `UNCERTAIN` is
treated the same as `NON_LEGAL` — the tool never guesses its way into a
legal analysis of something that isn't clearly a legal document. If the
classification is `NON_LEGAL`, the model is instructed to return nothing
but `{"status": "OUT_OF_CONTEXT"}`, and the backend maps that straight to
the "Out of context" screen without spending extra tokens on analysis.

## Known limitations (by design, for this MVP)

- **Scanned/image-only PDFs** aren't OCR'd — `extraction.py` detects this
  case and returns a clear error asking for a text-based file instead.
- **No database, auth, or storage** — files are streamed to a temp file,
  processed, and deleted immediately after the request (see the `finally`
  block in `main.py`). Nothing is persisted, per the security requirements.
- **Single AI call per document** — relevance check and full analysis are
  combined into one request for efficiency, as instructed.

## What was tested

- Upload validation: wrong file extension, empty file, oversized file.
- Extraction: real PDF (via `pdfplumber`) and DOCX (via `python-docx`)
  files, verified to extract text and reach the AI stage without errors.
- Error handling: missing `GEMINI_API_KEY` surfaces a clear message
  instead of a stack trace; unsupported file types and empty files are
  caught before any AI call.
- AI response handling: JSON parsing (including models that wrap output
  in ` ```json ` fences), and validation against the `AnalysisResult` /
  `OutOfContextResult` / `ErrorResult` schemas.
- Frontend: every DOM id referenced in `app.js` exists in `index.html`;
  JS parses without syntax errors.

**Not yet tested against a live Gemini key** — that requires your own
API key. Once you add one to `.env`, run through a real rental agreement
or NDA and a non-legal document (e.g. a recipe) to confirm the relevance
check behaves as expected on real model output.
