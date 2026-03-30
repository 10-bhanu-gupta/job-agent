# dashboard/pages_tracker.py

import streamlit as st
import pandas as pd
from db.database import get_db
from db.models import JobRecord, OutreachRecord


@st.cache_data(ttl=60)
def load_tracker_data():
    with get_db() as db:
        jobs = [
            {"title": j.title, "company": j.company, "score": j.score,
             "status": j.status, "source": j.source, "recommended": j.recommended}
            for j in db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
        ]
        outreach = [
            {"status": o.status}
            for o in db.query(OutreachRecord).order_by(OutreachRecord.created_at.desc()).all()
        ]
        return jobs, outreach


def render_tracker_page():
    st.title("📊 Tracker")
    st.markdown("Your application funnel — from discovery to offer.")
    st.markdown("---")

    jobs, outreach = load_tracker_data()

    if not jobs:
        st.info("No data yet — run the pipeline first.")
        return
    
    # Funnel metrics
    st.subheader("Application Funnel")
    statuses = ["new", "scored", "applied", "interviewing", "offer", "rejected"]
    cols = st.columns(len(statuses))
    for col, status in zip(cols, statuses):
        count = sum(1 for j in jobs if j["status"] == status)
        col.metric(status.title(), count)

    st.markdown("---")

    # Outreach funnel
    st.subheader("Outreach Funnel")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Drafted",  len(outreach))
    col2.metric("Approved", sum(1 for o in outreach if o["status"] == "approved"))
    col3.metric("Sent",     sum(1 for o in outreach if o["status"] == "sent"))
    col4.metric("Rejected", sum(1 for o in outreach if o["status"] == "rejected"))

    st.markdown("---")

    # Jobs table
    st.subheader("All Jobs")
    jobs_data = [
        {
            "Title": j["title"],
            "Company": j["company"],
            "Score": j["score"] or 0,
            "Status": j["status"],
            "Source": j["source"],
            "Recommended": "⭐" if j["recommended"] else "",
        }
        for j in jobs
    ]
    st.dataframe(
        pd.DataFrame(jobs_data),
        use_container_width=True,
        hide_index=True,
    )
