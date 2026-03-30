# dashboard/pages_outreach.py
#
# The most important dashboard page — where you review and approve
# outreach drafts before they get sent.

import streamlit as st
from datetime import datetime, timezone
from db.database import get_db
from db.models import OutreachRecord, ContactRecord


@st.cache_data(ttl=30)
def load_pending_drafts():
    with get_db() as db:
        drafts = db.query(OutreachRecord).filter(
            OutreachRecord.status == "pending_approval"
        ).all()
        contacts = {c.id: c for c in db.query(ContactRecord).all()}
        return [
            {
                "id": d.id,
                "contact_name": contacts.get(d.contact_id).name if d.contact_id and contacts.get(d.contact_id) else "Unknown",
                "contact_linkedin": contacts.get(d.contact_id).linkedin_url if d.contact_id and contacts.get(d.contact_id) else "",
                "email_subject": d.email_subject,
                "email_body": d.email_body,
                "linkedin_dm": d.linkedin_dm,
                "status": d.status,
            }
            for d in drafts
        ]


def approve_draft(draft_id: str):
    with get_db() as db:
        draft = db.get(OutreachRecord, draft_id)
        if draft:
            draft.status = "approved"
            draft.approved_at = datetime.now(timezone.utc)
    st.cache_data.clear()


def reject_draft(draft_id: str):
    with get_db() as db:
        draft = db.get(OutreachRecord, draft_id)
        if draft:
            draft.status = "rejected"
    st.cache_data.clear()


def render_outreach_page():
    st.title("✉️ Outreach")
    st.markdown("Review and approve cold emails and LinkedIn DMs before sending.")
    st.markdown("---")

    drafts = load_pending_drafts()

    if not drafts:
        st.success("No pending drafts — all caught up!")

        # Show approved drafts count
        with get_db() as db:
            approved = db.query(OutreachRecord).filter(
                OutreachRecord.status == "approved"
            ).count()
            sent = db.query(OutreachRecord).filter(
                OutreachRecord.status == "sent"
            ).count()
        st.metric("Approved (ready to send)", approved)
        st.metric("Sent", sent)
        return

    st.markdown(f"**{len(drafts)} drafts** pending your review")
    st.markdown("---")

    for draft in drafts:
        with st.container():
            st.subheader(f"To: {draft['contact_name']}")

            tab1, tab2 = st.tabs(["📧 Email", "💬 LinkedIn DM"])

            with tab1:
                st.markdown(f"**Subject:** {draft['email_subject']}")
                st.markdown("**Body:**")
                # Editable text area — you can edit before approving
                edited_body = st.text_area(
                    "Email body",
                    value=draft["email_body"],
                    height=250,
                    key=f"email_{draft['id']}",
                    label_visibility="collapsed",
                )

            with tab2:
                st.markdown(f"**{len(draft['linkedin_dm'])} / 280 characters**")
                edited_dm = st.text_area(
                    "LinkedIn DM",
                    value=draft["linkedin_dm"],
                    height=100,
                    key=f"dm_{draft['id']}",
                    label_visibility="collapsed",
                )
                if draft["contact_linkedin"]:
                    st.markdown(f"[Open LinkedIn profile ↗]({draft['contact_linkedin']})")

            col1, col2, _ = st.columns([1, 1, 4])
            with col1:
                if st.button("✅ Approve", key=f"approve_{draft['id']}", type="primary"):
                    approve_draft(draft["id"])
                    st.success("Approved!")
                    st.rerun()
            with col2:
                if st.button("❌ Reject", key=f"reject_{draft['id']}"):
                    reject_draft(draft["id"])
                    st.warning("Rejected")
                    st.rerun()

            st.markdown("---")