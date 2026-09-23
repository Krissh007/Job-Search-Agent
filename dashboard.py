"""
Job Search Agent — Streamlit Dashboard
Reads directly from data/jobs.db using the existing Database class.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# ── make src importable when run from the project root ──────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "jobs.db"

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Job Search Agent",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── colour tokens (status palette – validated, CVD-safe) ────────────────────
STATUS_COLORS = {
    "new":      "#4A90D9",   # blue
    "applied":  "#2EAA6E",   # green
    "review":   "#E8A838",   # amber
    "skipped":  "#8A8A9A",   # muted grey
    "error":    "#D94A4A",   # red
}

STATUS_ICONS = {
    "new":     "🔵",
    "applied": "✅",
    "review":  "🟡",
    "skipped": "⚫",
    "error":   "🔴",
}

# Keys match JobMatcher.category_for().
CATEGORY_COLORS = {
    "Strong": "#2EAA6E",
    "Good":   "#4A90D9",
    "Review": "#E8A838",
    "Low":    "#D94A4A",
}

# ── CSS overrides ────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Metric cards */
div[data-testid="metric-container"] {
    background: #1E1E2E;
    border: 1px solid #2A2A3E;
    border-radius: 10px;
    padding: 16px 20px;
}
div[data-testid="metric-container"] label { color: #9999BB !important; font-size: 0.78rem; }
div[data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; }

/* Section headers */
.section-header {
    font-size: 1.1rem;
    font-weight: 600;
    color: #E0E0F0;
    border-bottom: 2px solid #2A2A3E;
    padding-bottom: 6px;
    margin: 1.4rem 0 0.8rem 0;
}

/* Status badge */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #fff;
}

/* Job card */
.job-card {
    background: #1E1E2E;
    border: 1px solid #2A2A3E;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
}
.job-card h4 { margin: 0 0 4px 0; font-size: 1rem; color: #E0E0F0; }
.job-card .meta { font-size: 0.82rem; color: #9999BB; }

/* Score bar */
.score-bar-bg {
    background: #2A2A3E;
    border-radius: 6px;
    height: 8px;
    width: 100%;
    overflow: hidden;
}
.score-bar-fill {
    height: 8px;
    border-radius: 6px;
}
</style>
""", unsafe_allow_html=True)


# ── data loading ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_jobs() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM jobs ORDER BY discovered_at DESC").fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])

    # parse JSON list columns
    for col in ("match_reasons", "missing_keywords"):
        if col in df.columns:
            df[col] = df[col].apply(_parse_list)

    # datetime columns
    for col in ("discovered_at", "updated_at", "applied_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df["match_score"] = pd.to_numeric(df.get("match_score", 0), errors="coerce").fillna(0)
    df["status"] = df["status"].fillna("new")
    return df


@st.cache_data(ttl=30)
def load_applications() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    for col in ("unknown_questions", "filled_fields"):
        if col in df.columns:
            df[col] = df[col].apply(_parse_list)
    df["updated_at"] = pd.to_datetime(df.get("updated_at"), errors="coerce")
    return df


def _parse_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return json.loads(value)
        except Exception:
            pass
    return []


def _badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#555")
    icon  = STATUS_ICONS.get(status, "")
    return (
        f"<span class='badge' style='background:{color}'>"
        f"{icon} {status.upper()}"
        "</span>"
    )


def _score_bar(score: float) -> str:
    pct = min(max(score, 0), 100)
    if pct >= 75:
        bar_color = "#2EAA6E"
    elif pct >= 60:
        bar_color = "#4A90D9"
    elif pct >= 45:
        bar_color = "#E8A838"
    else:
        bar_color = "#D94A4A"
    return (
        f"<div class='score-bar-bg'>"
        f"<div class='score-bar-fill' style='width:{pct}%;background:{bar_color}'></div>"
        f"</div><small style='color:#9999BB'>{pct:.0f} / 100</small>"
    )


# ── sidebar ──────────────────────────────────────────────────────────────────
def sidebar_filters(df: pd.DataFrame):
    st.sidebar.title("🔍 Filters")
    st.sidebar.markdown("---")

    statuses  = sorted(df["status"].dropna().unique().tolist())
    sources   = sorted(df["source"].dropna().unique().tolist()) if "source" in df.columns else []
    categories = sorted(df["match_category"].dropna().unique().tolist()) if "match_category" in df.columns else []

    sel_status = st.sidebar.multiselect(
        "Status",
        statuses,
        default=[s for s in statuses if s not in ("skipped", "error", "rejected")],
    )
    sel_source = st.sidebar.multiselect("Source", sources, default=sources)
    min_score  = st.sidebar.slider("Min Match Score", 0, 100, 45)
    sel_cat    = st.sidebar.multiselect("Match Category", categories, default=categories)
    company_q  = st.sidebar.text_input("Company search", "")
    title_q    = st.sidebar.text_input("Title search", "")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"DB: `{DB_PATH}`")
    if st.sidebar.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()

    mask = pd.Series([True] * len(df), index=df.index)
    if sel_status:
        mask &= df["status"].isin(sel_status)
    if sel_source and "source" in df.columns:
        mask &= df["source"].isin(sel_source)
    if sel_cat and "match_category" in df.columns:
        mask &= df["match_category"].isin(sel_cat)
    mask &= df["match_score"] >= min_score
    if company_q and "company" in df.columns:
        mask &= df["company"].str.contains(company_q, case=False, na=False)
    if title_q and "title" in df.columns:
        mask &= df["title"].str.contains(title_q, case=False, na=False)

    return df[mask].sort_values("match_score", ascending=False)


# ── KPI row ───────────────────────────────────────────────────────────────────
def render_kpis(df: pd.DataFrame):
    total   = len(df)
    new     = (df["status"] == "new").sum()
    applied = (df["status"] == "applied").sum()
    review  = (df["status"] == "review").sum()
    skipped = (df["status"] == "skipped").sum()
    strong  = (df.get("match_category", "") == "Strong").sum()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("📥 Total Found",   total)
    c2.metric("🔵 New / Queued",  new)
    c3.metric("✅ Applied",        applied)
    c4.metric("🟡 For Review",    review)
    c5.metric("⚫ Skipped",        skipped)
    c6.metric("⭐ Strong Matches", strong)


# ── TAB 1 — Overview ──────────────────────────────────────────────────────────
def tab_overview(df: pd.DataFrame, filtered: pd.DataFrame):
    render_kpis(df)                       # always full dataset for KPIs
    st.markdown("---")

    # ── charts row ──
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("<p class='section-header'>Jobs by Status</p>", unsafe_allow_html=True)
        if not df.empty:
            counts = df["status"].value_counts()
            chart_df = pd.DataFrame({"Status": counts.index, "Count": counts.values})
            st.bar_chart(chart_df.set_index("Status"), color="#4A90D9")

    with col_b:
        st.markdown("<p class='section-header'>Match Category Distribution</p>", unsafe_allow_html=True)
        if "match_category" in df.columns and not df.empty:
            cat_counts = df["match_category"].value_counts()
            st.bar_chart(cat_counts, color="#2EAA6E")

    with col_c:
        st.markdown("<p class='section-header'>Source Breakdown</p>", unsafe_allow_html=True)
        if "source" in df.columns and not df.empty:
            src_counts = df["source"].value_counts()
            st.bar_chart(src_counts, color="#E8A838")

    # ── discovery trend ──
    st.markdown("<p class='section-header'>Discovery Trend (last 30 days)</p>", unsafe_allow_html=True)
    if "discovered_at" in df.columns:
        trend = (
            df.dropna(subset=["discovered_at"])
            .set_index("discovered_at")
            .resample("D")
            .size()
            .rename("Jobs Found")
        )
        if not trend.empty:
            st.line_chart(trend)

    # ── filtered table ──
    st.markdown(
        f"<p class='section-header'>Filtered Results &nbsp;"
        f"<small style='color:#9999BB'>({len(filtered)} jobs)</small></p>",
        unsafe_allow_html=True,
    )

    if filtered.empty:
        st.info("No jobs match the current filters.")
        return

    display_cols = ["match_score", "status", "title", "company", "location",
                    "source", "match_category", "discovered_at"]
    display_cols = [c for c in display_cols if c in filtered.columns]
    tbl = filtered[display_cols].copy()
    tbl["discovered_at"] = tbl["discovered_at"].dt.strftime("%Y-%m-%d").fillna("")
    tbl.columns = [c.replace("_", " ").title() for c in tbl.columns]

    st.dataframe(
        tbl,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Match Score": st.column_config.ProgressColumn(
                "Match Score", format="%f", min_value=0, max_value=100
            ),
        },
    )


# ── Description cleaner ───────────────────────────────────────────────────────
_NAV_JUNK = [
    "jobs companies services search jobs here",
    "loginregister for employers",
    "login register",
    "continue with google",
    "continue with linkedin",
    "sign in",
    "create account",
    "skip to main",
    "back to search",
]

def _clean_description(raw: str) -> str:
    """Strip nav/chrome junk scraped from the page and return clean paragraphs."""
    if not raw:
        return ""
    lines = raw.replace("\r", "\n").split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if any(junk in low for junk in _NAV_JUNK):
            continue
        if len(stripped) < 4:
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


def _render_job_card(row: pd.Series) -> None:
    """Render a single job as a clean, job-portal-style card."""
    title   = row.get("title", "Untitled")
    company = row.get("company", "")
    location = row.get("location", "")
    source  = row.get("source", "")
    status  = row.get("status", "new")
    score   = float(row.get("match_score", 0))
    cat     = row.get("match_category", "")
    posted  = row.get("posted_date", "") or ""
    url     = row.get("job_url", "")
    reasons = row.get("match_reasons") or []
    missing = row.get("missing_keywords") or []
    notes   = row.get("notes", "") or ""
    desc    = _clean_description(str(row.get("description", "") or ""))

    if isinstance(reasons, str):
        try:
            import json; reasons = json.loads(reasons)
        except Exception:
            reasons = [reasons]
    if isinstance(missing, str):
        try:
            import json; missing = json.loads(missing)
        except Exception:
            missing = [missing]

    discovered = row.get("discovered_at")
    applied_at = row.get("applied_at")

    # ── score colour ──
    if score >= 75:
        score_color = "#2EAA6E"
    elif score >= 60:
        score_color = "#4A90D9"
    elif score >= 45:
        score_color = "#E8A838"
    else:
        score_color = "#D94A4A"

    status_color = STATUS_COLORS.get(status, "#555")

    # ── source apply label ──
    apply_labels = {
        "naukri":   "Apply on Naukri",
        "linkedin": "Apply on LinkedIn",
        "indeed":   "Apply on Indeed",
    }
    apply_label = apply_labels.get(source.lower(), "View Job Posting")

    # ── build metadata chips before markdown ──
    meta_chips = f'<span>📍 {location or "—"}</span>'
    meta_chips += f'<span>🏢 {source.capitalize() if source else "—"}</span>'
    if posted.strip():
        meta_chips += f"<span>🕐 {posted}</span>"
    if pd.notna(applied_at):
        meta_chips += f"<span>✅ Applied: {applied_at.strftime('%d %b %Y')}</span>"
    if pd.notna(discovered):
        meta_chips += f"<span>🔍 Found: {discovered.strftime('%d %b %Y')}</span>"

    # ── header card ──
    st.markdown(
        f"""
        <div style="background:#1A1A2E;border:1px solid #2E2E4A;border-radius:12px;
                    padding:20px 24px 16px 24px;margin-bottom:4px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
            <div>
              <h2 style="margin:0 0 4px 0;font-size:1.3rem;color:#E8E8FF">{title}</h2>
              <p style="margin:0;font-size:1rem;color:#A0A0C0;font-weight:500">{company}</p>
            </div>
            <div style="text-align:right">
              <div style="font-size:1.8rem;font-weight:800;color:{score_color};line-height:1">{score:.0f}</div>
              <div style="font-size:0.72rem;color:#7070A0;margin-top:2px">Match Score</div>
              <div style="margin-top:6px">
                <span style="background:{score_color}22;color:{score_color};border:1px solid {score_color}55;
                             padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600">{cat}</span>
              </div>
            </div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:14px;font-size:0.82rem;color:#9090B8">
            {meta_chips}
          </div>
          <div style="margin-top:14px;background:#2A2A42;border-radius:8px;height:8px;overflow:hidden">
            <div style="width:{min(score,100):.0f}%;height:100%;background:{score_color};border-radius:8px"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── action row ──
    ac1, ac2, ac3 = st.columns([2, 2, 1])
    with ac3:
        if url and url.startswith("http"):
            st.link_button(apply_label, url, use_container_width=True)

    # ── match signals ──
    if reasons or missing:
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(
                "<p style='font-size:0.8rem;font-weight:600;color:#9090B8;"
                "text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px'>"
                "Matched Signals</p>",
                unsafe_allow_html=True,
            )
            if reasons:
                tags = "".join(
                    f"<span style='display:inline-block;background:#1C3A2A;color:#2EAA6E;"
                    f"border:1px solid #2EAA6E44;padding:2px 10px;border-radius:12px;"
                    f"font-size:0.75rem;margin:2px 3px 2px 0'>{r}</span>"
                    for r in reasons[:20]
                )
                st.markdown(tags, unsafe_allow_html=True)
            else:
                st.caption("None recorded")

        with m2:
            st.markdown(
                "<p style='font-size:0.8rem;font-weight:600;color:#9090B8;"
                "text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px'>"
                "Missing Keywords</p>",
                unsafe_allow_html=True,
            )
            if missing:
                tags = "".join(
                    f"<span style='display:inline-block;background:#2A1C1C;color:#D94A4A;"
                    f"border:1px solid #D94A4A44;padding:2px 10px;border-radius:12px;"
                    f"font-size:0.75rem;margin:2px 3px 2px 0'>{m}</span>"
                    for m in missing[:20]
                )
                st.markdown(tags, unsafe_allow_html=True)
            else:
                st.markdown(
                    "<span style='color:#2EAA6E;font-size:0.85rem'>No gaps — full match!</span>",
                    unsafe_allow_html=True,
                )

    if notes.strip():
        st.markdown(
            f"<div style='background:#1E2A1E;border-left:3px solid #2EAA6E;"
            f"padding:8px 14px;border-radius:0 6px 6px 0;font-size:0.83rem;color:#A0C0A0;"
            f"margin-top:8px'>📝 {notes}</div>",
            unsafe_allow_html=True,
        )

    # ── job description ──
    if desc:
        st.markdown(
            "<p style='font-size:0.8rem;font-weight:600;color:#9090B8;"
            "text-transform:uppercase;letter-spacing:0.05em;margin:14px 0 8px 0'>"
            "Job Description</p>",
            unsafe_allow_html=True,
        )
        paragraphs = [p for p in desc.split("\n") if p.strip()]
        html_desc = "".join(
            f"<p style='margin:0 0 10px 0;line-height:1.7'>{p}</p>"
            for p in paragraphs[:80]
        )
        st.markdown(
            f"<div style='background:#12121E;border:1px solid #2A2A3E;border-radius:10px;"
            f"padding:18px 22px;font-size:0.86rem;color:#C0C0D8;max-height:420px;"
            f"overflow-y:auto;line-height:1.7'>{html_desc}</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='border:none;border-top:1px solid #2A2A3E;margin:18px 0'>", unsafe_allow_html=True)


# ── TAB 2 — Job Details ───────────────────────────────────────────────────────
def tab_job_details(filtered: pd.DataFrame):
    total = len(filtered)
    show  = min(total, 50)
    st.markdown(f"Showing **{show}** of **{total}** jobs · sorted by match score")

    if filtered.empty:
        st.info("No jobs match your current filters. Try adjusting the sidebar.")
        return

    for _, row in filtered.head(50).iterrows():
        _render_job_card(row)

    if total > 50:
        st.caption(f"Showing top 50 of {total}. Narrow filters to see others.")


# ── TAB 3 — Applications ─────────────────────────────────────────────────────
def tab_applications(jobs_df: pd.DataFrame, apps_df: pd.DataFrame):
    st.markdown("<p class='section-header'>Application Pipeline</p>", unsafe_allow_html=True)

    # applied jobs from the jobs table
    applied = jobs_df[jobs_df["status"] == "applied"].copy() if not jobs_df.empty else pd.DataFrame()

    a1, a2, a3 = st.columns(3)
    a1.metric("Total Applied",    len(applied))
    a2.metric("Applications Table", len(apps_df))
    unknown_q_count = (
        apps_df["unknown_questions"].apply(lambda x: len(x) > 0).sum()
        if not apps_df.empty and "unknown_questions" in apps_df.columns
        else 0
    )
    a3.metric("Unanswered Questions", unknown_q_count)

    st.markdown("---")

    # ── Applied jobs list ──
    st.markdown("<p class='section-header'>Applied Jobs</p>", unsafe_allow_html=True)
    if applied.empty:
        st.info("No applied jobs yet.")
    else:
        disp = applied[["title", "company", "location", "source", "applied_at", "match_score"]].copy()
        disp["applied_at"] = disp["applied_at"].dt.strftime("%Y-%m-%d").fillna("")
        disp.columns = ["Title", "Company", "Location", "Source", "Applied On", "Score"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Applications tracking table (from `applications` table) ──
    st.markdown("<p class='section-header'>Application Tracking Records</p>", unsafe_allow_html=True)
    if apps_df.empty:
        st.info("No records in the applications table yet.")
    else:
        for _, row in apps_df.iterrows():
            status = row.get("status", "pending")
            title  = row.get("title", "Untitled")
            co     = row.get("company", "")
            url    = row.get("job_url", "")
            uq     = row.get("unknown_questions", [])
            ff     = row.get("filled_fields", [])
            updated = row.get("updated_at")

            with st.expander(f"{title}  ·  {co}  ·  {status.upper()}"):
                ca, cb = st.columns(2)
                with ca:
                    st.markdown(f"**Status:** {_badge(status)}", unsafe_allow_html=True)
                    if pd.notna(updated):
                        st.markdown(f"**Last updated:** {updated.strftime('%Y-%m-%d %H:%M')}")
                    if url:
                        st.link_button("🔗 Open Application", url)
                with cb:
                    if uq:
                        st.error(f"**Unanswered questions ({len(uq)}):**\n\n" +
                                 "\n".join(f"• {q}" for q in uq))
                    else:
                        st.success("No unknown questions.")
                    if ff:
                        st.info(f"**Filled fields ({len(ff)}):** " + ", ".join(ff))


# ── TAB 4 — Pipeline Board ────────────────────────────────────────────────────
def tab_pipeline(df: pd.DataFrame):
    st.markdown("<p class='section-header'>Kanban-style Pipeline View</p>", unsafe_allow_html=True)
    st.caption("Each column shows up to 10 jobs. Use sidebar filters to narrow down.")

    stages = ["new", "review", "applied", "skipped", "error"]
    cols = st.columns(len(stages))

    for col, stage in zip(cols, stages):
        stage_df = df[df["status"] == stage]
        color = STATUS_COLORS.get(stage, "#555")
        icon  = STATUS_ICONS.get(stage, "")
        col.markdown(
            f"<div style='background:{color}22;border:1px solid {color}44;"
            f"border-radius:8px;padding:8px 12px;margin-bottom:12px;'>"
            f"<strong style='color:{color}'>{icon} {stage.upper()}</strong>"
            f"<span style='float:right;color:{color};font-weight:700'>{len(stage_df)}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        for _, row in stage_df.head(10).iterrows():
            score = float(row.get("match_score", 0))
            title = row.get("title", "Untitled")
            co    = row.get("company", "")
            col.markdown(
                f"<div class='job-card'>"
                f"<h4>{title[:38]}</h4>"
                f"<p class='meta'>{co[:30]}</p>"
                f"<p class='meta'>Score: <strong>{score:.0f}</strong></p>"
                f"</div>",
                unsafe_allow_html=True,
            )
        if len(stage_df) > 10:
            col.caption(f"+{len(stage_df)-10} more")


# ── TAB 5 — Analytics ────────────────────────────────────────────────────────
def tab_analytics(df: pd.DataFrame):
    if df.empty:
        st.info("No data yet.")
        return

    st.markdown("<p class='section-header'>Score Distribution</p>", unsafe_allow_html=True)
    bins = [0, 45, 60, 75, 100]
    labels = ["Low (<45)", "Fair (45-60)", "Good (60-75)", "Strong (75+)"]
    df2 = df.copy()
    df2["score_band"] = pd.cut(df2["match_score"], bins=bins, labels=labels, right=True)
    band_counts = df2["score_band"].value_counts().reindex(labels, fill_value=0)
    st.bar_chart(band_counts, color="#4A90D9")

    st.markdown("<p class='section-header'>Top 10 Companies by Job Count</p>", unsafe_allow_html=True)
    if "company" in df.columns:
        top_co = df["company"].value_counts().head(10)
        st.bar_chart(top_co, color="#2EAA6E")

    st.markdown("<p class='section-header'>Application Funnel</p>", unsafe_allow_html=True)
    funnel_data = {
        "Scraped":    len(df),
        "Scored ≥45": int((df["match_score"] >= 45).sum()),
        "For Review": int((df["status"] == "review").sum()),
        "Applied":    int((df["status"] == "applied").sum()),
    }
    funnel_df = pd.DataFrame(
        {"Stage": list(funnel_data.keys()), "Count": list(funnel_data.values())}
    )
    st.bar_chart(funnel_df.set_index("Stage"), color="#E8A838")

    st.markdown("<p class='section-header'>Weekly Discovery Rate</p>", unsafe_allow_html=True)
    if "discovered_at" in df.columns:
        weekly = (
            df.dropna(subset=["discovered_at"])
            .set_index("discovered_at")
            .resample("W")
            .size()
            .rename("Jobs")
        )
        if not weekly.empty:
            st.line_chart(weekly)

    st.markdown("<p class='section-header'>Match Score by Source</p>", unsafe_allow_html=True)
    if "source" in df.columns:
        src_score = df.groupby("source")["match_score"].mean().sort_values(ascending=False)
        st.bar_chart(src_score, color="#9B59B6")


# ── TAB 6 — Settings & Config ─────────────────────────────────────────────────
def tab_settings():
    st.markdown("<p class='section-header'>Project Configuration</p>", unsafe_allow_html=True)

    config_files = {
        "settings.yaml":         PROJECT_ROOT / "config" / "settings.yaml",
        "candidate_profile.yaml": PROJECT_ROOT / "config" / "candidate_profile.yaml",
        "matching_rules.yaml":    PROJECT_ROOT / "config" / "matching_rules.yaml",
    }

    for name, path in config_files.items():
        with st.expander(f"📄 {name}"):
            if path.exists():
                st.code(path.read_text(encoding="utf-8"), language="yaml")
            else:
                st.warning(f"File not found: {path}")

    st.markdown("<p class='section-header'>Database Statistics</p>", unsafe_allow_html=True)
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        for tbl in ("jobs", "applications"):
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                st.markdown(f"- **{tbl}** table: {count} records")
            except Exception:
                st.markdown(f"- **{tbl}** table: not found")
        conn.close()
        size_kb = DB_PATH.stat().st_size // 1024
        st.markdown(f"- **DB size:** {size_kb} KB  (`{DB_PATH}`)")
    else:
        st.warning("Database file not found.")


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    st.title("💼 Job Search Agent — Dashboard")
    st.caption("Live view of your job pipeline, scoring, and applications.")

    if not DB_PATH.exists():
        st.error(
            f"Database not found at `{DB_PATH}`. "
            "Run the scraper first to populate it."
        )
        st.stop()

    df   = load_jobs()
    apps = load_applications()

    if df.empty:
        st.warning("The jobs table is empty. Run the scraper to populate data.")
        st.stop()

    filtered = sidebar_filters(df)

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Overview",
        "🔍 Job Details",
        "📬 Applications",
        "🗂 Pipeline Board",
        "📈 Analytics",
        "⚙️ Settings",
    ])

    with tab1:
        tab_overview(df, filtered)

    with tab2:
        tab_job_details(filtered)

    with tab3:
        tab_applications(df, apps)

    with tab4:
        tab_pipeline(filtered)

    with tab5:
        tab_analytics(df)

    with tab6:
        tab_settings()


if __name__ == "__main__":
    main()
