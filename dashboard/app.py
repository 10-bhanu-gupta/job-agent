# dashboard/app.py
#
# Main Streamlit application entry point.
# Run with: streamlit run dashboard/app.py
#
# CONCEPT — Streamlit basics
# Streamlit turns Python scripts into web apps.
# Every time you interact with the UI (click a button, change a filter),
# Streamlit reruns the entire script from top to bottom.
# This sounds inefficient but is elegant in practice — your UI is always
# a pure function of your data.
#
# CONCEPT — st.cache_data
# Since the script reruns on every interaction, expensive operations
# (DB queries, API calls) need caching. @st.cache_data caches the
# return value of a function. It only reruns when the inputs change.
#
# CONCEPT — st.session_state
# Since the script reruns on every interaction, regular Python variables
# get reset. st.session_state persists values across reruns — like a
# server-side session. We use it to track pipeline run status.

import streamlit as st
import sys
import os

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_db, init_db
from db.models import JobRecord, CompanyRecord, ContactRecord, OutreachRecord

# Initialise DB on startup
init_db()

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Job Agent Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# SIDEBAR NAVIGATION
# ---------------------------------------------------------------------------

st.sidebar.title("🤖 Job Agent")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Overview", "💼 Jobs", "🏢 Companies", "✉️ Outreach", "📊 Tracker"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

# Pipeline trigger button
st.sidebar.subheader("Pipeline")
if st.sidebar.button("▶️ Run Pipeline Now", use_container_width=True):
    st.session_state["trigger_pipeline"] = True

# Show last run time
if "last_run" in st.session_state:
    st.sidebar.caption(f"Last run: {st.session_state['last_run']}")

st.sidebar.markdown("---")
st.sidebar.caption("Built with LangGraph + Claude API")

# ---------------------------------------------------------------------------
# CACHED DB QUERIES
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)  # cache for 60 seconds
def get_stats():
    """Fetches summary stats for the overview page."""
    with get_db() as db:
        total_jobs      = db.query(JobRecord).count()
        recommended     = db.query(JobRecord).filter(JobRecord.recommended == True).count()
        total_companies = db.query(CompanyRecord).count()
        total_contacts  = db.query(ContactRecord).count()
        pending         = db.query(OutreachRecord).filter(
                            OutreachRecord.status == "pending_approval").count()
        approved        = db.query(OutreachRecord).filter(
                            OutreachRecord.status == "approved").count()
        sent            = db.query(OutreachRecord).filter(
                            OutreachRecord.status == "sent").count()
    return {
        "total_jobs": total_jobs,
        "recommended": recommended,
        "total_companies": total_companies,
        "total_contacts": total_contacts,
        "pending_outreach": pending,
        "approved_outreach": approved,
        "sent_outreach": sent,
    }


# ---------------------------------------------------------------------------
# PAGES
# ---------------------------------------------------------------------------

if page == "🏠 Overview":
    st.title("🤖 Job Agent Dashboard")
    st.markdown("Your AI-powered job search pipeline — built with LangGraph + Claude API.")
    st.markdown("---")

    stats = get_stats()

    # Metric cards row 1
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Jobs Found",     stats["total_jobs"])
    col2.metric("Recommended Jobs",     stats["recommended"])
    col3.metric("Target Companies",     stats["total_companies"])
    col4.metric("Contacts Found",       stats["total_contacts"])

    # Metric cards row 2
    col5, col6, col7, _ = st.columns(4)
    col5.metric("Pending Approval",     stats["pending_outreach"])
    col6.metric("Approved Outreach",    stats["approved_outreach"])
    col7.metric("Sent",                 stats["sent_outreach"])

    st.markdown("---")
    st.subheader("Pipeline Status")

    # Pipeline trigger handler
    if st.session_state.get("trigger_pipeline"):
        st.session_state["trigger_pipeline"] = False
        with st.spinner("Running pipeline... this may take 2-3 minutes"):
            try:
                import uuid
                from datetime import datetime, timezone
                from graph.graph import build_graph
                from graph.state import AgentState

                graph = build_graph()
                initial_state = AgentState(
                    user_id="00000000-0000-0000-0000-000000000001",
                    run_id=str(uuid.uuid4()),
                    run_triggered_by="manual",
                    jobs_found=[],
                    funded_companies=[],
                    jobs_scored=[],
                    contacts_found=[],
                    outreach_drafts=[],
                    approved_draft_ids=[],
                    rejected_draft_ids=[],
                    errors=[],
                    pipeline_status="running",
                    last_updated=datetime.now(timezone.utc).isoformat(),
                )
                config = {"configurable": {"thread_id": str(uuid.uuid4())}}
                # Run until interrupt
                for event in graph.stream(initial_state, config):
                    for key, val in event.items():
                        if key != "__end__":
                            st.write(f"✅ {key} complete")

                st.session_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.session_state["pipeline_config"] = config
                st.success("Pipeline paused — review outreach drafts in ✉️ Outreach tab")
                st.cache_data.clear()
                st.rerun()

            except Exception as e:
                st.error(f"Pipeline error: {e}")

    else:
        st.info("Click **▶️ Run Pipeline Now** in the sidebar to start the pipeline.")

elif page == "💼 Jobs":
    from dashboard.pages_jobs import render_jobs_page
    render_jobs_page()

elif page == "🏢 Companies":
    from dashboard.pages_companies import render_companies_page
    render_companies_page()

elif page == "✉️ Outreach":
    from dashboard.pages_outreach import render_outreach_page
    render_outreach_page()

elif page == "📊 Tracker":
    from dashboard.pages_tracker import render_tracker_page
    render_tracker_page()