# Job Search Agent

A modular, configurable job discovery, matching, review, and application-tracking system.

## Principles
- SQLite is the source of truth.
- Configuration is separated from Python logic.
- Job sources are modular.
- Matching is explainable and configurable.
- Applications remain human-controlled.

## Freshness and daily exports

The search pipeline keeps records within the configured 30-day posting
horizon and creates daily Excel workbooks for newly discovered leads:

- `data/exports/new_leads_7d_YYYY-MM-DD.xlsx`
- `data/exports/new_leads_30d_YYYY-MM-DD.xlsx`

The 7-day workbook contains leads with a verifiable posting age of seven
days or less. The 30-day workbook uses the same rule for thirty days. A job
already present in SQLite is updated but is not exported again as a new lead.
Posting ages that a source does not expose are retained in the database but
are excluded from freshness workbooks.

## Match-quality basis

Matching uses explicit evidence from the candidate profile: target role,
proven skills, responsibilities, tools, industry/domain, demonstrated
experience areas, and India/remote location preference. Domain and experience
matches are included in the explainable score and match reasons.

The profile structure follows the kinds of occupational evidence used by the
Government of India's National Career Service and the U.S. Department of
Labor-sponsored O*NET occupational model: skills, knowledge areas, work
activities, and tasks. These are decision-support signals, not a guarantee of
selection or application success.

## Easy Apply assistant

The project includes a guarded form assistant in
`src/application_assistant.py`. Configure personal values and approved
screening answers in `config/application_profile.yaml`, then use it with an
already authenticated Playwright page:

```python
from src.application_assistant import EasyApplyAssistant

assistant = EasyApplyAssistant(
	page,
	"config/application_profile.yaml",
)
review = assistant.prepare()

if review.ready_for_review:
	assistant.submit(review, confirm=True)
```

The assistant fills only known fields and configured screening-answer
matches. It refuses to submit without `confirm=True` and refuses to submit
while unknown questions remain. It does not bypass CAPTCHA or login
verification and never invents answers for sensitive questions.

When `application.prepare_after_search` is enabled in
`config/settings.yaml`, each daily search prepares up to the configured
number of new leads. It opens each job URL in a visible browser, fills known
values, and creates `data/exports/application_review_YYYY-MM-DD.html`.
The daily Excel files contain an `application_progress` link for each lead.
Open that link to review the job URL, preparation status, and the unique list
of unanswered screening questions. Add approved answers to
`config/application_profile.yaml`, rerun preparation, and confirm the final
submission yourself.

The pipeline never submits an application automatically.

## Source quality policy

The default source list currently uses Naukri only. A local data-quality audit
found that the stored Naukri records included descriptions and posting-age
data, while the Indeed records had no usable descriptions or posting dates
and none passed the current India/resume-fit gates. Indeed remains available
in code for future repair, but it is intentionally disabled in
`config/settings.yaml` until its India detail-page extraction reaches the same
quality level.

To enable the answer form, start the local review server in a separate
terminal:

```powershell
python -m src.application_review_server
```

Then open `http://127.0.0.1:8765`. Submit the unique answers once there; the
server writes them into `config/application_profile.yaml` and future
preparation runs reuse them. The server also shows tracked application
statuses, filled fields, and unanswered questions from SQLite.
