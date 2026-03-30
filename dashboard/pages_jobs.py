# dashboard/pages_jobs.py

import streamlit as st
import pandas as pd
from db.database import get_db
from db.models import JobRecord


@st.cache_data(ttl=60)
def load_jobs():
    with get_db() as db:
        jobs = db.query(JobRecord).order_by(JobRecord.score.desc().nullslast()).all()
        return [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "score": j.score or 0,
                "recommended": j.recommended,
                "source": j.source,
                "status": j.status,
                "url": j.url,
                "reasoning": j.reasoning or "",
            }
            for j in jobs
        ]


def render_jobs_page():
    st.title("💼 Jobs")
    st.markdown("All discovered job listings, scored by Claude against your resume.")
    st.markdown("---")

    jobs = load_jobs()
    if not jobs:
        st.info("No jobs yet — run the pipeline to discover jobs.")
        return

    df = pd.DataFrame(jobs)

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        show_recommended = st.checkbox("Recommended only", value=False)
    with col2:
        min_score = st.slider("Minimum score", 0, 100, 0)
    with col3:
        sources = ["All"] + sorted(df["source"].unique().tolist())
        selected_source = st.selectbox("Source", sources)

    # Apply filters
    filtered = df[df["score"] >= min_score]
    if show_recommended:
        filtered = filtered[filtered["recommended"] == True]
    if selected_source != "All":
        filtered = filtered[filtered["source"] == selected_source]

    st.markdown(f"**{len(filtered)} jobs** matching filters")
    st.markdown("---")

    # Job cards
    for _, job in filtered.iterrows():
        rec_badge = "⭐ Recommended" if job["recommended"] else ""
        with st.expander(f"{job['score']:3d}/100 — {job['title']} @ {job['company']}  {rec_badge}"):
            col1, col2, col3 = st.columns(3)
            col1.markdown(f"**Location:** {job['location']}")
            col2.markdown(f"**Source:** {job['source']}")
            col3.markdown(f"**Status:** {job['status']}")
            if job["reasoning"]:
                st.markdown(f"**Claude's reasoning:** {job['reasoning']}")
            if job["url"]:
                st.markdown(f"[View job posting ↗]({job['url']})")