NyaySetu

> Understand your rights. In your language.

An AI-powered legal guidance, case intake, and document analysis platform built to make the Indian legal system accessible, understandable, and actionable for every citizen.

---

# Overview

NyaySetu (*Bridge to Justice*) is a full-stack legal technology application designed to help citizens, tenants, employees, and small business owners navigate personal legal conflicts in India. It allows users to:

* Describe legal conflicts conversationally in plain language
* Receive structured action plans with interactive checklists
* Measure case strength via a dynamic Situation Risk Assessment Meter
* Interact via text or voice input in **English, Hindi (हिंदी), and Marathi (मराठी)**
* Upload and analyze legal documents (PDFs & images) through a draggable split-pane sidebar
* Preserve case history permanently with paginated database storage
* Track ongoing cases, documents, and progress through a personal dashboard

The platform is built with production scalability, data privacy, and security in mind using Flask, serverless PostgreSQL (Neon), Cloudinary media storage, and Google Gemini 2.5 Flash AI.

---

# Features

## Adaptable Conversational Fact-Gathering
* Evaluates 5 core legal dimensions: Timelines, Financial Figures, Evidence, Jurisdiction (State/UT), and Completed Actions.
* Asks targeted, single follow-up questions until sufficient details exist.
* Transitions dynamically into a final structured action plan when complete.

## Structured Action Plan & Risk Assessment
* Formats advice into 4 sections: *Summary of Situation*, *Actionable Next Steps* (with interactive checkboxes), *What You Must Have & Ensure* (evidence items), and *Important Precautions & Timelines*.
* Displays a dynamic 0–100% **Situation Risk Meter** with color-coded risk indicators (*Low Risk*, *Moderate Risk*, *High Risk*).

## Native Multilingual Support
* Live topbar toggle pills for **EN | हिंदी | मराठी**.
* Instant UI translation engine synced with `localStorage`.
* Direct AI system mandates enforcing responses in Devanagari script for Hindi and Marathi.

## Voice Input (Speech-to-Text)
* Integrated using the native **Web Speech API**.
* Automatically switches speech locales based on active language (`en-IN`, `hi-IN`, `mr-IN`).
* Pulsing red microphone animation provides live audio recording feedback.

## Resizable Split-Pane Document Analysis
* Upload legal documents (PDFs and Images) to Cloudinary.
* Draggable split-pane divider allows resizing the breakdown panel.
* Extracts Plain English Summaries, Risk Severity Chips (*LOW*, *MEDIUM*, *HIGH*), Timelines & Deadlines Table, Party Responsibilities, and Questions for a Lawyer.

## 10-Message Paginated History & Session Persistence
* All conversations and uploaded files are saved in PostgreSQL.
* Reloading or resuming a case fetches the 10 most recent messages.
* Includes an **"⬆ Load Previous Messages"** button to load older history batches seamlessly.

## User Dashboard
* Real-time metrics showing Active Cases, Resolved Cases, Pending Actions, and Files on record.
* Interactive case progress timeline (Submitted, Under Review, Guidance Ready, Resolved).
* Case search filtering, recent documents vault, and recent activity feed.

---

# Tech Stack

## Frontend
* HTML5
* CSS3 (Design Tokens & Dark Mode Theme)
* Vanilla JavaScript (ES6+)
* Web Speech API (Voice Input)

## Backend
* Python 3.10+
* Flask
* Werkzeug (Password Hashing)
* Flask-WTF (CSRF Protection)

## Database
* PostgreSQL / Neon Serverless (`psycopg2` Connection Pool)

## AI & Cloud Services
* Google Gemini API (`google-genai` SDK using `gemini-2.5-flash`)
* Cloudinary (Document & Image Storage)

## Deployment
* Custom Domain / Render / Railway Compatible

---

# Project Structure

```bash
NyaySetu/
│
├── static/
│   └── (Design Tokens & Fonts)
│
├── templates/
│   ├── partials/
│   │   └── nav.html
│   ├── dashboard.html
│   ├── login.html
│   ├── main.html
│   └── new_issue.html
│
├── app.py
├── db.py
├── gemini_service.py
├── requirements.txt
├── .env
└── README.md

