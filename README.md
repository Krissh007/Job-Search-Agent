# Job Search Agent

The search-and-match engine behind JobPilot. It finds
jobs on Naukri and LinkedIn, normalizes them, drops stale ones, and scores
each against the candidate profile with explainable reasons and hard gates.

JobPilot (`E:\JobPilot`) runs this engine on a schedule through its legacy
shim, then saves, scores with Gemini, writes tailored documents and handles
applying, all against its own `jobpilot.db`. This repo saves nothing itself.

## Principles
- Configuration is separated from Python logic.
- Job sources are modular.
- Matching is explainable and configurable.
- Applications remain human-controlled.

## What JobPilot uses from here

| Part | Used for |
| --- | --- |
| `src/pipelines/discovery_pipeline.py` | `discover_jobs()` and `score_jobs()`: the scheduled search |
| `src/sources/` | Naukri, LinkedIn (public job pages) and Indeed adapters |
| `src/normalizer.py`, `src/freshness.py`, `src/matching/` | Normalizing, posting age, rule-based scoring and gates |
| `src/config.py`, `config/*.yaml` | Validated settings, matching rules, candidate profile |
| `src/tailoring/` | Tailored resume and cover letter (JobPilot's docs step) |
| `src/apply/easy_apply.py`, `src/apply/naukri.py` | Form filling that JobPilot's apply agent builds on |

Changing these interfaces changes what JobPilot runs on its next search.

## Running

```powershell
pip install -r requirements.txt
playwright install chromium
python -m src.pipelines.discovery_pipeline                       # dry run: print matches, save nothing
python -m src.pipelines.discovery_pipeline --sources linkedin --keywords "Business Analyst"
python -m pytest
```

The dry run uses the keywords and sources in `config/settings.yaml`. JobPilot
passes its own from its Settings screen.

## Signing in

Applying and the resume upload use the agent's own browser profile
(`data/browser_profile/`, git-ignored), which JobPilot shares. Sign in once;
you type the password in the browser window and the agent never sees it:

```powershell
python -m src.apply.linkedin login
python -m src.apply.naukri login
```

Any sign-in, checkpoint or CAPTCHA page stops automation immediately.

## LinkedIn resume re-upload

`python -m src.apply.linkedin_resume` uploads `resume_upload.file` to LinkedIn
(Jobs → Application settings) so Easy Apply attaches the latest copy, then
removes older copies of the same file. It isn't scheduled: run it after
replacing the file. `--dry-run` only checks the file and sign-in. The result
is written to `project_sync/resume_upload_status.md`, which JARVIS reads.

## Configuration

| File | Holds |
| --- | --- |
| `config/settings.yaml` | Locations, limits, freshness, detail enrichment, browser, tailoring, resume upload |
| `config/candidate_profile.yaml` | Resume evidence and the experience range (years) |
| `config/matching_rules.yaml` | Weights, category bands, gates, excluded domains, aliases |
| `config/application_profile.yaml` | Contact details and screening answers (git-ignored) |

All are validated at startup by `src/config.py` and `src/resume_profile.py`.
An unknown or misspelled key stops the run with a message naming it.

## Match-quality basis

Matching uses explicit evidence from the candidate profile: target role,
proven skills, responsibilities, tools, industry/domain, demonstrated
experience areas, and India/remote location preference. Terms match as
whole words, and evidence must come from the job description, not only its
title. Jobs whose required experience doesn't overlap the profile's range,
whose posting is older than `max_posted_days`, or that fail the India or
domain gates are dropped.

The profile structure follows the kinds of occupational evidence used by the
Government of India's National Career Service and the U.S. Department of
Labor-sponsored O*NET occupational model: skills, knowledge areas, work
activities, and tasks. These are decision-support signals, not a guarantee of
selection or application success.

## Tailored documents

`src/tailoring` turns the master resume (`tailoring.master_resume_path`) and a
job description into an ATS-friendly resume, cover letter and keyword report.
The model may use only facts from the master resume, and its answer is checked
locally: skills, employers, institutions and numbers not in the master resume
are removed and listed in the report. JD requirements the candidate lacks are
reported, never added. JobPilot's docs step runs this with its own Gemini key.

## Source quality policy

Indeed remains in code but is off by default: an audit found its India
records had no usable descriptions or posting dates. Naukri and LinkedIn are
the active sources.
