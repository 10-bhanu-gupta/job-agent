# dashboard/pages_outreach.py
#
# Redesigned Outreach Dashboard with split-pane layout.
# - Left pane: List of jobs/companies with filters
# - Right pane: Detailed view + outreach drafts + multi-contact selection
# - Toggle between warm outreach (jobs) and cold outreach (companies)

import streamlit as st
import json
from datetime import datetime, timezone
from db.database import get_db
from db.models import OutreachRecord, ContactRecord, JobRecord, CompanyRecord
from tools.gmail_sender import send_approved_emails


# ---------------------------------------------------------------------------
# STATE MANAGEMENT
# ---------------------------------------------------------------------------

def init_session_state():
    """Initialize Streamlit session state for this page."""
    if "outreach_tab" not in st.session_state:
        st.session_state.outreach_tab = "jobs"  # "jobs" or "companies"
    
    if "selected_job_id" not in st.session_state:
        st.session_state.selected_job_id = None
    
    if "selected_company_id" not in st.session_state:
        st.session_state.selected_company_id = None
    
    if "selected_contacts" not in st.session_state:
        st.session_state.selected_contacts = {}  # {contact_id: True/False}


# ---------------------------------------------------------------------------
# DATABASE QUERIES
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_recommended_jobs():
    """Load jobs with score >= 60 (recommended)."""
    with get_db() as db:
        jobs = db.query(JobRecord).filter(
            JobRecord.recommended == True
        ).order_by(JobRecord.created_at.desc()).all()
        
        return [
            {
                "id": j.id,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "score": j.score,
                # "days_posted": j.days_posted,
                # "experience_level": j.experience_level or "Not specified",
                "description": j.description,
                "url": j.url,
                "source": j.source,
                "created_at": j.created_at,
            }
            for j in jobs
        ]


@st.cache_data(ttl=30)
def load_funded_companies():
    """Load funded companies for cold outreach."""
    with get_db() as db:
        companies = db.query(CompanyRecord).order_by(
            CompanyRecord.funding_date.desc()
        ).all()
        
        return [
            {
                "id": c.id,
                "name": c.name,
                "funding_stage": c.funding_stage,
                "amount_raised": c.amount_raised,
                "funding_date": c.funding_date,
                "source_url": c.source_url,
                "created_at": c.created_at,
            }
            for c in companies
        ]


@st.cache_data(ttl=30)
def load_contacts_for_job(job_id: str):
    """Load all contacts and draft associated with a job posting."""
    with get_db() as db:
        # Find outreach draft for this job
        draft = db.query(OutreachRecord).filter(
            OutreachRecord.job_id == job_id,
            OutreachRecord.status.in_(["pending_approval", "approved", "rejected"])
        ).first()
        
        # Extract contact IDs from contact_ids JSON array
        contact_ids = set()
        if draft and draft.contact_ids:
            try:
                contact_ids = set(json.loads(draft.contact_ids))
            except json.JSONDecodeError:
                pass
        
        # Fetch contact details
        contacts = {}
        if contact_ids:
            contact_records = db.query(ContactRecord).filter(
                ContactRecord.id.in_(list(contact_ids))
            ).all()
            contacts = {
                c.id: {
                    "name": c.name,
                    "title": c.title,
                    "email": c.email,
                    "linkedin_url": c.linkedin_url,
                }
                for c in contact_records
            }
        
        # Return draft and contacts
        if draft:
            return {
                "contacts": contacts,
                "draft": {
                    "id": draft.id,
                    "email_subject": draft.email_subject,
                    "email_body": draft.email_body,
                    "linkedin_dm": draft.linkedin_dm,
                    "status": draft.status,
                },
            }
        else:
            return {"contacts": {}, "draft": None}


@st.cache_data(ttl=30)
def load_contacts_for_company(company_id: str):
    """Load all contacts and draft associated with a company."""
    with get_db() as db:
        # Find outreach draft for this company
        draft = db.query(OutreachRecord).filter(
            OutreachRecord.company_id == company_id,
            OutreachRecord.status.in_(["pending_approval", "approved", "rejected"])
        ).first()
        
        # Extract contact IDs from contact_ids JSON array
        contact_ids = set()
        if draft and draft.contact_ids:
            try:
                contact_ids = set(json.loads(draft.contact_ids))
            except json.JSONDecodeError:
                pass
        
        # Fetch contact details
        contacts = {}
        if contact_ids:
            contact_records = db.query(ContactRecord).filter(
                ContactRecord.id.in_(list(contact_ids))
            ).all()
            contacts = {
                c.id: {
                    "name": c.name,
                    "title": c.title,
                    "email": c.email,
                    "linkedin_url": c.linkedin_url,
                }
                for c in contact_records
            }
        
        # Return draft and contacts
        if draft:
            return {
                "contacts": contacts,
                "draft": {
                    "id": draft.id,
                    "email_subject": draft.email_subject,
                    "email_body": draft.email_body,
                    "linkedin_dm": draft.linkedin_dm,
                    "status": draft.status,
                },
            }
        else:
            return {"contacts": {}, "draft": None}


# ---------------------------------------------------------------------------
# APPROVAL LOGIC
# ---------------------------------------------------------------------------

def approve_draft(draft_id: str):
    """Mark draft as approved."""
    with get_db() as db:
        draft = db.get(OutreachRecord, draft_id)
        if draft:
            draft.status = "approved"
            draft.approved_at = datetime.now(timezone.utc)
    st.cache_data.clear()


def reject_draft(draft_id: str):
    """Mark draft as rejected."""
    with get_db() as db:
        draft = db.get(OutreachRecord, draft_id)
        if draft:
            draft.status = "rejected"
    st.cache_data.clear()


def mark_as_sent(draft_ids: list[str]):
    """Mark approved drafts as sent."""
    with get_db() as db:
        for draft_id in draft_ids:
            draft = db.get(OutreachRecord, draft_id)
            if draft:
                draft.status = "sent"
                draft.sent_at = datetime.now(timezone.utc)
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# UI RENDERING
# ---------------------------------------------------------------------------

def render_outreach_page():
    """Main outreach dashboard page."""
    st.title("✉️ Outreach")
    st.markdown("Warm outreach to job postings or cold outreach to funded companies.")
    st.markdown("---")
    
    # Initialize session state
    init_session_state()
    
    # Tab selection: Jobs vs Companies
    tab_jobs, tab_companies = st.tabs(["🔥 Job Postings (Warm)", "❄️ Companies (Cold)"])
    
    with tab_jobs:
        st.subheader("Warm Outreach — Job Postings")
        render_jobs_tab()
    
    with tab_companies:
        st.subheader("Cold Outreach — Funded Companies")
        render_companies_tab()
    
    # Separator
    st.markdown("---")
    
    # Approved drafts section
    render_approved_drafts_section()


def render_jobs_tab():
    """Render the warm outreach (jobs) tab."""
    jobs = load_recommended_jobs()
    
    if not jobs:
        st.info("No recommended jobs yet. Run the pipeline to discover and score jobs.")
        return
    
    # Split layout
    col_left, col_right = st.columns([1, 2], gap="large")
    
    with col_left:
        st.markdown("### Jobs List")
        
        # Filters
        with st.expander("Filters", expanded=False):
            min_score = st.slider("Minimum score", 0, 100, 60, key="job_score_filter")
            days_filter = st.selectbox(
                "Posted within",
                ["Any time", "7 days", "30 days", "90 days"],
                key="job_days_filter"
            )
        
        # Filter jobs
        filtered_jobs = [j for j in jobs if j["score"] >= min_score]
        
        # Display job list
        for job in filtered_jobs:
            # Format score with color
            score_color = "🟢" if job["score"] >= 70 else "🟡" if job["score"] >= 60 else "🔴"
            
            # Display clickable job item
            if st.button(
                f"{score_color} {job['title'][:30]} @ {job['company'][:20]}",
                key=f"job_{job['id']}",
                use_container_width=True,
            ):
                st.session_state.selected_job_id = job["id"]
                st.rerun()
    
    with col_right:
        if st.session_state.selected_job_id:
            # Find selected job
            selected_job = next(
                (j for j in jobs if j["id"] == st.session_state.selected_job_id),
                None
            )
            
            if selected_job:
                render_job_detail_panel(selected_job)
        else:
            st.info("👈 Select a job from the list to view details and outreach options")


def render_companies_tab():
    """Render the cold outreach (companies) tab."""
    companies = load_funded_companies()
    
    if not companies:
        st.info("No funded companies found yet. Run the pipeline to discover companies.")
        return
    
    # Split layout
    col_left, col_right = st.columns([1, 2], gap="large")
    
    with col_left:
        st.markdown("### Companies List")
        
        # Filters
        with st.expander("Filters", expanded=False):
            funding_stage = st.multiselect(
                "Funding stage",
                ["Seed", "Series A", "Series B", "Series C+"],
                key="company_stage_filter"
            )
        
        # Filter companies
        filtered_companies = companies
        if funding_stage:
            filtered_companies = [c for c in companies if c["funding_stage"] in funding_stage]
        
        # Display company list
        for company in filtered_companies:
            funding_emoji = "💰" if company.get("amount_raised") else "💵"
            
            if st.button(
                f"{funding_emoji} {company['name'][:30]}",
                key=f"company_{company['id']}",
                use_container_width=True,
            ):
                st.session_state.selected_company_id = company["id"]
                st.rerun()
    
    with col_right:
        if st.session_state.selected_company_id:
            # Find selected company
            selected_company = next(
                (c for c in companies if c["id"] == st.session_state.selected_company_id),
                None
            )
            
            if selected_company:
                render_company_detail_panel(selected_company)
        else:
            st.info("👈 Select a company from the list to view details and outreach options")


def render_job_detail_panel(job: dict):
    """Render the detail panel for a selected job."""
    st.markdown("### Job Details")
    
    # Job metadata
    col1, col2 = st.columns(2)
    col1.metric("Score", f"{job['score']}/100")
    col2.metric("Source", job.get("source", "N/A"))
    # col2.metric("Posted", job.get("days_posted", "N/A"))
    # col3.metric("Experience", job.get("experience_level", "N/A"))
    
    st.markdown(f"**Title:** {job['title']}")
    st.markdown(f"**Company:** {job['company']}")
    st.markdown(f"**Location:** {job['location']}")
    st.markdown(f"**Source:** {job['source']}")
    st.markdown(f"[View on source ↗]({job['url']})")
    
    # Job description
    from html.parser import HTMLParser
    
    class MLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.strict = False
            self.convert_charrefs = True
            self.text = []
        def handle_data(self, d):
            self.text.append(d)
        def get_data(self):
            return ''.join(self.text)
    
    def strip_html_tags(html):
        s = MLStripper()
        s.feed(html)
        return s.get_data()
    
    with st.expander("Full Description"):
        raw_desc = job.get("description", "No description available")
        clean_desc = strip_html_tags(raw_desc)
        st.write(clean_desc)
    
    st.markdown("---")
    
    # Load contacts and draft for this job
    job_data = load_contacts_for_job(job["id"])
    
    if job_data["draft"]:
        draft = job_data["draft"]
        contacts = job_data["contacts"]
        
        st.markdown("### Outreach")
        
        # Email/DM tabs
        tab_email, tab_linkedin = st.tabs(["📧 Email", "💬 LinkedIn"])
        
        with tab_email:
            st.markdown(f"**Subject:** {draft['email_subject']}")
            st.text_area(
                "Email body",
                value=draft["email_body"],
                height=200,
                disabled=True,
                key=f"email_preview_{job['id']}",
            )
        
        with tab_linkedin:
            st.markdown(f"**Characters:** {len(draft['linkedin_dm'])}/280")
            st.text_area(
                "LinkedIn DM",
                value=draft["linkedin_dm"],
                height=100,
                disabled=True,
                key=f"dm_preview_{job['id']}",
            )
        
        st.markdown("---")
        
        # Multi-contact selection
        st.markdown("### Select Recipients")
        
        if contacts:
            for contact_id, contact in contacts.items():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{contact['name']}** — {contact['title']}")
                    if contact['email']:
                        st.caption(f"📧 {contact['email']}")
                    if contact['linkedin_url']:
                        st.caption(f"[🔗 LinkedIn]({contact['linkedin_url']})")
                
                with col2:
                    is_selected = st.checkbox(
                        "Select",
                        key=f"contact_{contact_id}_{job['id']}",
                        label_visibility="collapsed"
                    )
                    st.session_state.selected_contacts[contact_id] = is_selected
        else:
            st.warning("No contacts found for this job")
        
        st.markdown("---")
        
        # Approval buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve", key=f"approve_job_{job['id']}", type="primary"):
                approve_draft(draft["id"])
                st.success("Draft approved!")
                st.rerun()
        with col2:
            if st.button("❌ Reject", key=f"reject_job_{job['id']}"):
                reject_draft(draft["id"])
                st.warning("Draft rejected")
                st.rerun()
    else:
        st.warning("No outreach draft found for this job")


def render_company_detail_panel(company: dict):
    """Render the detail panel for a selected company."""
    st.markdown("### Company Details")
    
    # Company metadata
    col1, col2, col3 = st.columns(3)
    col1.metric("Funding Stage", company.get("funding_stage", "N/A"))
    col2.metric("Funding Raised", company.get("amount_raised", "N/A"))
    col3.metric("Funded", company.get("funding_date", "N/A"))
    
    st.markdown(f"**Company:** {company['name']}")
    
    if company.get("source_url"):
        st.markdown(f"[View on source ↗]({company['source_url']})")
    
    st.markdown("---")
    
    # Load contacts and draft for this company
    company_data = load_contacts_for_company(company["id"])
    
    if company_data["draft"]:
        draft = company_data["draft"]
        contacts = company_data["contacts"]
        
        st.markdown("### Outreach")
        
        # Email/DM tabs
        tab_email, tab_linkedin = st.tabs(["📧 Email", "💬 LinkedIn"])
        
        with tab_email:
            st.markdown(f"**Subject:** {draft['email_subject']}")
            st.text_area(
                "Email body",
                value=draft["email_body"],
                height=200,
                disabled=True,
                key=f"email_preview_{company['id']}",
            )
        
        with tab_linkedin:
            st.markdown(f"**Characters:** {len(draft['linkedin_dm'])}/280")
            st.text_area(
                "LinkedIn DM",
                value=draft["linkedin_dm"],
                height=100,
                disabled=True,
                key=f"dm_preview_{company['id']}",
            )
        
        st.markdown("---")
        
        # Multi-contact selection
        st.markdown("### Select Recipients")
        
        if contacts:
            for contact_id, contact in contacts.items():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{contact['name']}** — {contact['title']}")
                    if contact['email']:
                        st.caption(f"📧 {contact['email']}")
                    if contact['linkedin_url']:
                        st.caption(f"[🔗 LinkedIn]({contact['linkedin_url']})")
                
                with col2:
                    is_selected = st.checkbox(
                        "Select",
                        key=f"contact_{contact_id}_{company['id']}",
                        label_visibility="collapsed"
                    )
                    st.session_state.selected_contacts[contact_id] = is_selected
        else:
            st.warning("No contacts found for this company")
        
        st.markdown("---")
        
        # Approval buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve", key=f"approve_company_{company['id']}", type="primary"):
                approve_draft(draft["id"])
                st.success("Draft approved!")
                st.rerun()
        with col2:
            if st.button("❌ Reject", key=f"reject_company_{company['id']}"):
                reject_draft(draft["id"])
                st.warning("Draft rejected")
                st.rerun()
    else:
        st.warning("No outreach draft found for this company")


def render_approved_drafts_section():
    """Render the approved/ready-to-send section."""
    st.subheader("📤 Ready to Send")
    
    with get_db() as db:
        approved = db.query(OutreachRecord).filter(
            OutreachRecord.status == "approved"
        ).count()
        sent = db.query(OutreachRecord).filter(
            OutreachRecord.status == "sent"
        ).count()
    
    col1, col2 = st.columns(2)
    col1.metric("Approved (ready to send)", approved)
    col2.metric("Sent", sent)
    
    if approved == 0:
        st.info("No approved drafts ready to send yet.")
        return
    
    st.markdown("---")
    
    # Dry run toggle
    dry_run = st.checkbox(
        "Dry run (log but don't actually send)",
        value=True,
        help="Keep this ON until you're sure everything looks right"
    )
    
    if st.button("📧 Send All Approved Emails", type="primary"):
        # Load approved drafts
        with get_db() as db:
            drafts = db.query(OutreachRecord).filter(
                OutreachRecord.status == "approved"
            ).all()
            
            # Prepare for sending
            sendable = []
            for draft in drafts:
                # For now, send to the first contact (we'll improve multi-contact later)
                contact_ids = []
                if draft.contact_ids:
                    try:
                        contact_ids = json.loads(draft.contact_ids)
                    except json.JSONDecodeError:
                        pass
                
                if contact_ids:
                    contact = db.query(ContactRecord).filter(
                        ContactRecord.id == contact_ids[0]
                    ).first()
                    
                    if contact and contact.email:
                        sendable.append({
                            "id": draft.id,
                            "email": contact.email,
                            "subject": draft.email_subject,
                            "body": draft.email_body,
                            "contact_name": contact.name,
                        })
        
        if sendable:
            with st.spinner(f"Sending {len(sendable)} emails... this will take a few minutes"):
                results = send_approved_emails(
                    drafts=sendable,
                    dry_run=dry_run,
                )
                if results["sent"] > 0:
                    mark_as_sent(results["sent_ids"])
                    st.success(f"✅ Sent {results['sent']} emails!")
                if results["skipped"] > 0:
                    st.info(f"ℹ️ {results['skipped']} skipped (no email address)")
                if results["failed"] > 0:
                    st.error(f"⚠️ {results['failed']} failed — check terminal for details")
                st.rerun()
        else:
            st.warning("No approved drafts with email addresses to send")