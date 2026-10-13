"""
Check that tailoring is ready: master resume readable + Gemini key working.

    python -m src.check_setup
"""

from __future__ import annotations

from src.pipelines.discovery_pipeline import load_context
from src.tailoring.llm import LLMError, create_client
from src.tailoring.master_resume import MasterResumeError, load_master_resume


def main() -> None:
    context = load_context()
    tailoring = context.settings.tailoring
    ok = True

    resume_path = context.path(tailoring.master_resume_path)
    try:
        text = load_master_resume(resume_path)
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        print(f"[OK]   Master resume: {resume_path.name} ({len(text)} characters, starts with '{first_line[:40]}')")
    except MasterResumeError as error:
        ok = False
        print(f"[FAIL] Master resume: {error}")

    try:
        client = create_client(tailoring, context.project_root)
        answer = client.generate_json(
            "Reply with JSON only.",
            'Return exactly this JSON: {"status": "ok"}',
        )
        if answer.get("status") != "ok":
            raise LLMError(f"unexpected reply {answer}")
        print(f"[OK]   Gemini key works (model: {client.model_name})")
    except LLMError as error:
        ok = False
        print(f"[FAIL] Gemini: {error}")

    print("\nAll set - tailoring is ready." if ok else "\nFix the [FAIL] items above and run this again.")


if __name__ == "__main__":
    main()
