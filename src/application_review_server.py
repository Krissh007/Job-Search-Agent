from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import yaml

from src.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "config" / "application_profile.yaml"
DATABASE_PATH = PROJECT_ROOT / "data" / "jobs.db"


def _load_profile() -> dict:
    with PROFILE_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _save_answer(question: str, answer: str) -> None:
    profile = _load_profile()
    answers = profile.setdefault("screening_answers", {})
    answers[question] = answer
    PROFILE_PATH.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _page(message: str = "") -> bytes:
    with Database(DATABASE_PATH) as database:
        records = database.connection.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC"
        ).fetchall()

    questions: set[str] = set()
    cards: list[str] = []
    for record in records:
        unknown = json.loads(record["unknown_questions"] or "[]")
        questions.update(unknown)
        cards.append(
            "<article>"
            f"<h2>{html.escape(record['title'] or 'Untitled')}</h2>"
            f"<p>{html.escape(record['company'] or '')}</p>"
            f"<p>Status: <strong>{html.escape(record['status'])}</strong></p>"
            f"<a href='{html.escape(record['job_url'])}' target='_blank'>"
            "Open application page</a>"
            "</article>"
        )

    question_fields = "".join(
        f"<label>{html.escape(question)}"
        f"<input name='question' value='{html.escape(question)}' readonly>"
        f"<input name='answer' placeholder='Answer for this question'></label>"
        for question in sorted(questions)
    )
    body = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Application Review</title><style>
body {{ max-width: 960px; margin: 2rem auto; font-family: sans-serif; }}
article {{ border: 1px solid #ccc; padding: 1rem; margin: 1rem 0; }}
label {{ display: block; margin: 1rem 0; }} input {{ display:block; width: 100%; padding:.5rem; }}
</style></head><body><h1>Application Review</h1>
<p>{html.escape(message)}</p><h2>Answer unique questions once</h2>
<form method='post' action='/answers'>{question_fields}
<button type='submit'>Save answers</button></form>
<h2>Application tracking</h2>{''.join(cards) or '<p>No applications queued.</p>'}
</body></html>"""
    return body.encode("utf-8")


class ReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"))
        questions = values.get("question", [])
        answers = values.get("answer", [])
        for question, answer in zip(questions, answers):
            if answer.strip():
                _save_answer(question, answer.strip())

        self.send_response(303)
        self.send_header("Location", "/?" + urlencode({"saved": "1"}))
        self.end_headers()


def main() -> None:
    server = HTTPServer(("127.0.0.1", 8765), ReviewHandler)
    print("Application review server: http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
