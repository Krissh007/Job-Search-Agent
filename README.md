# Job Search Agent

A modular, configurable job discovery, matching, review, and application-tracking system.

## Principles
- SQLite is the source of truth.
- Configuration is separated from Python logic.
- Job sources are modular.
- Matching is explainable and configurable.
- Applications remain human-controlled.

## Running

```powershell
pip install -r requirements.txt
playwright install chromium
python -m src.pipelines.discovery_pipeline
```

This is the only pipeline. It runs these stages in order: discover → normalize → freshness
filter → match → save to SQLite → tailor resume + cover letter (score ≥ 60)
→ prepare applications → export Excel.
Each run logs a summary to `data/logs/job_search_agent.log`, including
how many jobs each gate rejected.

Other commands:

| Command | Purpose |
| --- | --- |
| `python -m src.reconcile_jobs` | Re-score stored jobs after editing the profile or rules |
| `python -m src.prepare_all_applications` | Pre-fill forms for every open job |
| `python -m src.generate_documents` | Tailored resume + cover letter for stored jobs scoring ≥ 60 (`--dry-run`, `--min-score`, `--limit`, `--job-url URL --force`) |
| `python -m src.project_sync` | Sync with the "Job Application" Claude project (also runs after every pipeline run) |
| `python -m src.application_review_server` | Answer screening questions at http://127.0.0.1:8765 |
| `streamlit run dashboard.py` | Browse the database |
| `python -m pytest` | Run the tests |

## Configuration

| File | Holds |
| --- | --- |
| `config/settings.yaml` | Keywords, locations, limits, sources, run flags |
| `config/candidate_profile.yaml` | Resume evidence and the experience range (years) |
| `config/matching_rules.yaml` | Weights, category bands, gates, excluded domains, aliases |
| `config/application_profile.yaml` | Contact details and screening answers (git-ignored) |

All four are validated at startup by `src/config.py` and
`src/resume_profile.py`. An unknown or misspelled key stops the run with
a message naming it, rather than being silently ignored.

Existing databases are migrated automatically. Older rows get
`posted_on` (resolved from the day they were discovered) and parsed
experience ranges.

## LinkedIn Easy Apply

Easy Apply runs in the agent's own browser profile (`data/browser_profile/`,
git-ignored). Sign in once; you type your password in the browser window,
and the agent never sees it:

```powershell
python -m src.apply.linkedin login
```

Then prepare applications for the best LinkedIn leads:

```powershell
python -m src.apply.linkedin apply              # top 5 with score >= 60
python -m src.apply.linkedin apply --limit 3 --min-score 70
python -m src.apply.linkedin apply --job-url https://www.linkedin.com/jobs/view/<id>
```

For each job, the agent clicks Easy Apply and fills empty fields from
`config/application_profile.yaml`. For a question such as
"How many years of experience do you have with SQL?", the longest matching
`screening_answers` key wins. The agent moves through the steps and stops
on the final "Submit application" step without clicking it. Tabs that
need you stay open. Review them, answer anything left blank, and submit
yourself. When LinkedIn confirms, the job is recorded as applied in
SQLite. Close the browser when you're done.

Safety limits (`easy_apply` in `settings.yaml`, all optional):
`max_jobs_per_run` (5), `seconds_between_jobs` (20, randomised),
`min_match_score` (60). Any sign-in, checkpoint or CAPTCHA page stops the
run immediately. Automating a signed-in LinkedIn account is against
LinkedIn's user agreement and can lead to restrictions, so keep batches
small.

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

## Tailored resume and cover letter

For every job with `match_score` at or above `tailoring.min_match_score`
(default 60) the pipeline writes an ATS-friendly resume and cover letter as
Word files:

```
data/applications/<date>_<Company>_<Role>/
    <Name>_Resume_<Company>.docx
    <Name>_Cover_Letter_<Company>.docx
    match_report.md      # JD keywords covered / missing, fact-check removals
```

The daily and master Excel workbooks get `tailored_resume` and
`cover_letter` columns that link straight to those files.

Setup (free):

1. Save your original resume as `config/master_resume.docx` (or .pdf/.txt;
   change `tailoring.master_resume_path`). It is the only source of facts.
2. Create a free Gemini API key at https://aistudio.google.com/apikey and put
   it in a `.env` file in the project root: `GEMINI_API_KEY=your-key`
   (or set it as an environment variable).
3. Check `python -m src.generate_documents --dry-run`, then run the pipeline
   as usual.

Truthfulness: the model is told to use only facts from the master resume,
and its answer is then checked locally. Skills, certifications, employers and
institutions not found in the master resume (or in
`candidate_profile.yaml`), and bullets containing numbers that do not appear
in the master resume, are removed and listed in `match_report.md`. JD
requirements you do not have are reported, never added. Always review the
documents before uploading.

Free-tier notes: jobs are processed best score first, at most
`max_jobs_per_run` per run with a pause between calls. Failed or deferred
jobs are retried on the next run; jobs that already have documents are
skipped. Delete a job's folder (or use `--job-url URL --force`) to
regenerate. On Gemini's free tier Google may use submitted content to
improve its products.

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

## Claude project sync

The agent and the "Job Application" Claude project share one folder,
`project_sync/`, refreshed at the end of every pipeline run (or with
`python -m src.project_sync`).

| File | Direction | Holds |
| --- | --- | --- |
| `jobs_for_review.csv` | agent → Claude | Open jobs scoring ≥ 45, best first |
| `job_descriptions.jsonl` | agent → Claude | Full JD text per job, for tailoring |
| `tracker.csv` | agent → Claude | Jobs you acted on (applied, interviewing, offer, …) |
| `open_questions.md` | agent → Claude | Real screening questions still unanswered |
| `sync_summary.md` | agent → Claude | Counts for the snapshot |
| `inbox/status_updates.csv` | Claude → agent | `job_url,status,notes`; applied on the next run, then moved to `inbox/processed/` |

Statuses: `new`, `review`, `shortlisted` (open) and `applied`,
`interviewing`, `offer`, `rejected`, `skipped` (closed: no more tailoring or
form preparation). The master resume (`config/master_resume.md`) and the
screening answers (`config/application_profile.yaml`) are shared with the
project too, so a change made in either place is the one both use.

## Auto-apply and the daily schedule

`python -m src.apply.auto_apply` applies on LinkedIn (Easy Apply) and Naukri
without you watching. It is controlled by `auto_apply` in `settings.yaml` and
only touches jobs marked **shortlisted** (Claude's daily review in the Job
Application project writes these to `project_sync/inbox/status_updates.csv`).
A form is submitted only when every required question was answered from
`config/application_profile.yaml`; otherwise it is left unsubmitted and the
questions appear in `project_sync/open_questions.md`. Daily cap, randomised
pauses, and an immediate stop on any sign-in/OTP/CAPTCHA page apply. Use
`--dry-run` to see the queue.

Sign in once per portal in the agent's browser profile:

```powershell
python -m src.apply.linkedin login
python -m src.apply.naukri login
```

`python -m src.daily` runs everything in order (import Claude's updates →
search → tailor → sync → auto-apply → sync). Register it with Windows Task
Scheduler once:

```powershell
powershell -ExecutionPolicy Bypass -File E:\job_search_agent\scripts\register_daily_tasks.ps1
```

That creates `JobAgent-Morning` (07:30, full run) and `JobAgent-Afternoon`
(13:30, `--apply`: applies to the shortlist Claude made that morning). The PC
must be on and you logged in. Automating LinkedIn or Naukri is against their
terms and can get an account restricted; keep `daily_cap` modest.

## LinkedIn resume re-upload (Mon–Fri 08:30)

`python -m src.apply.linkedin_resume` uploads `resume_upload.file`
(default `config/Krishna_Maheswaram_AI_Business_Analyst_Resume.docx`; PDF/DOCX,
max 2 MB) on LinkedIn's Jobs → Application settings page, then deletes older
copies of the same file name once the new upload is confirmed. The task
`JobAgent-ResumeUpload` (created by `scripts/register_daily_tasks.ps1`) runs it
on weekdays at 08:30; if the 07:30 run still has the browser open it retries
every 5 minutes for up to 30 minutes. Results go to
`project_sync/resume_upload_status.md`. Check with `--dry-run`.
