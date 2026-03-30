# dashboard/pages_outreach.py
#
# The most important dashboard page — where you review and approve
# outreach drafts before they get sent.

import streamlit as st
from datetime import datetime, timezone
from db.database import get_db
from db.models import OutreachRecord, ContactRecord
from tools.gmail_sender import send_approved_emails


@st.cache_data(ttl=30)
def load_approved_drafts():
    with get_db() as db:
        drafts = db.query(OutreachRecord).filter(
            OutreachRecord.status == "approved"
        ).all()
        contacts = {
            c.id: {
                "name": c.name,
                "email": c.email,
                "linkedin_url": c.linkedin_url,
            }
            for c in db.query(ContactRecord).all()
        }
        return [
            {
                "id": d.id,
                "contact_name": contacts.get(d.contact_id, {}).get("name", "Unknown"),
                "email": contacts.get(d.contact_id, {}).get("email", ""),
                "subject": d.email_subject,
                "body": d.email_body,
                "linkedin_dm": d.linkedin_dm,
                "linkedin_url": contacts.get(d.contact_id, {}).get("linkedin_url", ""),
            }
            for d in drafts
        ]


def mark_as_sent(draft_ids: list[str]):
    """Updates sent drafts to status='sent' in DB."""
    with get_db() as db:
        for draft_id in draft_ids:
            draft = db.get(OutreachRecord, draft_id)
            if draft:
                draft.status = "sent"
                draft.sent_at = datetime.now(timezone.utc)
    st.cache_data.clear()
    

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

    # --- Approved drafts section ---
    st.markdown("---")
    st.subheader("📤 Ready to Send")

    approved_drafts = load_approved_drafts()

    if not approved_drafts:
        st.info("No approved drafts ready to send yet.")
    else:
        # Split into with-email and without-email
        with_email    = [d for d in approved_drafts if d["email"]]
        without_email = [d for d in approved_drafts if not d["email"]]

        col1, col2 = st.columns(2)
        col1.metric("With email (sendable)", len(with_email))
        col2.metric("LinkedIn DM only",       len(without_email))

        if with_email:
            st.markdown("**Emails ready to send:**")
            for d in with_email:
                st.markdown(f"- {d['contact_name']} `{d['email']}` — {d['subject'][:50]}...")

        if without_email:
            st.markdown("**LinkedIn DM only (no email found):**")
            for d in without_email:
                lk = f"[Open ↗]({d['linkedin_url']})" if d["linkedin_url"] else ""
                st.markdown(f"- {d['contact_name']} {lk} — paste DM manually")
                if d["linkedin_dm"]:
                    st.code(d["linkedin_dm"], language=None)

        st.markdown("---")

        # Dry run toggle
        dry_run = st.checkbox(
            "Dry run (log but don't actually send)",
            value=True,
            help="Keep this ON until you're sure everything looks right"
        )

        if st.button("📧 Send All Approved Emails", type="primary"):
            with st.spinner(f"Sending {len(with_email)} emails... this will take a few minutes"):
                results = send_approved_emails(
                    drafts=with_email,
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

