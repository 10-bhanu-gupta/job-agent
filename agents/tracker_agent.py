# agents/tracker_agent.py
#
# The TrackerAgent is the final node in the LangGraph pipeline.
# It runs AFTER the human-in-the-loop interrupt — meaning it only
# runs once you've approved outreach drafts in the dashboard.
#
# WHAT IT DOES:
# 1. Writes all discovered jobs to the DB (upsert — no duplicates)
# 2. Writes all funded companies to the DB
# 3. Writes all contacts to the DB
# 4. Writes approved outreach drafts to the DB with status "approved"
# 5. Marks rejected drafts as "rejected"
# 6. Updates pipeline_status to "complete"
#
# CONCEPT — Upsert (INSERT or UPDATE)
# We use SQLAlchemy's merge() which does an upsert:
# if a record with that ID already exists, update it.
# if it doesn't exist, insert it.
# This means running the pipeline twice won't create duplicate rows.
#
# CONCEPT — Why write to DB only at the end?
# LangGraph's checkpointer already persists state during the run.
# The DB is the permanent, queryable record for the dashboard.
# Writing only at the end (in TrackerAgent) keeps the pipeline clean —
# one agent, one responsibility.

from datetime import datetime, timezone

from db.database import get_db, init_db
from db.models import (
    UserRecord, JobRecord, CompanyRecord,
    ContactRecord, OutreachRecord
)
from graph.state import AgentState
from config.settings import is_placeholder, DATABASE_URL


# ---------------------------------------------------------------------------
# ENSURE TABLES EXIST
# ---------------------------------------------------------------------------
# init_db() is idempotent — safe to call every time
# In production this is handled by migrations, but for dev this is fine
init_db()


# ---------------------------------------------------------------------------
# UPSERT HELPERS
# ---------------------------------------------------------------------------

def upsert_job(db, job: dict, scored_jobs: list) -> None:
    """
    Inserts or updates a job record in the database.

    CONCEPT — Why look up score separately?
    Jobs are discovered by ScrapeAgent but scored by ScoringAgent.
    They live in different parts of the state. We join them here
    by matching job ID before writing to the DB.
    """
    # Find the scored version of this job if it exists
    score_data = next(
        (sj for sj in scored_jobs if sj["job"]["id"] == job["id"]),
        None
    )

    record = JobRecord(
        id=job["id"],
        user_id=job["user_id"],
        title=job["title"],
        company=job["company"],
        location=job["location"],
        description=job["description"],
        url=job["url"],
        source=job["source"],
        status=job["status"],
        score=score_data["score"] if score_data else None,
        reasoning=score_data["reasoning"] if score_data else None,
        recommended=score_data["recommended"] if score_data else False,
        date_found=datetime.now(timezone.utc),
    )
    # merge() = upsert: update if exists, insert if not
    db.merge(record)


def upsert_company(db, company: dict) -> None:
    """Inserts or updates a funded company record."""
    record = CompanyRecord(
        id=company["id"],
        user_id=company["user_id"],
        name=company["name"],
        funding_stage=company["funding_stage"],
        amount_raised=company["amount_raised"],
        funding_date=company["funding_date"],
        source_url=company["source_url"],
        website=company["website"],
        notes=company["notes"],
    )
    db.merge(record)


def upsert_contact(db, contact: dict) -> None:
    """Inserts or updates a contact record."""
    record = ContactRecord(
        id=contact["id"],
        user_id=contact["user_id"],
        company_id=contact["company_id"] or None,
        name=contact["name"],
        title=contact["title"],
        email=contact["email"],
        linkedin_url=contact["linkedin_url"],
        source=contact["source"],
    )
    db.merge(record)


def upsert_outreach(db, draft: dict, is_approved: bool) -> None:
    """
    Inserts or updates an outreach draft record.

    Sets status based on whether the user approved or rejected it.
    approved_at timestamp is set when approval happens.
    """
    status = "approved" if is_approved else "rejected"
    approved_at = datetime.now(timezone.utc) if is_approved else None

    record = OutreachRecord(
        id=draft["id"],
        user_id=draft["user_id"],
        contact_id=draft["contact_id"] or None,
        job_id=draft["job_id"] or None,
        email_subject=draft["email_subject"],
        email_body=draft["email_body"],
        linkedin_dm=draft["linkedin_dm"],
        status=status,
        approved_at=approved_at,
    )
    db.merge(record)


# ---------------------------------------------------------------------------
# ENSURE DEFAULT USER EXISTS
# ---------------------------------------------------------------------------

def ensure_default_user(db) -> str:
    """
    Creates the default user record if it doesn't exist.

    CONCEPT — Why a default user?
    Our schema requires every row to have a user_id foreign key.
    In single-user mode, we create one user automatically.
    When we add authentication later, real users will be created
    at login time instead.

    Returns the user_id string.
    """
    default_user_id = "00000000-0000-0000-0000-000000000001"

    existing = db.get(UserRecord, default_user_id)
    if not existing:
        user = UserRecord(
            id=default_user_id,
            email="bhanu_gupta@nsitonline.in",
            name="Bhanu Gupta",
        )
        db.add(user)
        db.flush()  # flush to DB without committing — makes ID available immediately
        print("  ✅ Default user created")

    return default_user_id

# ---------------------------------------------------------------------------
# ------
# ---------------------------------------------------------------------------

def pre_interrupt_tracker(state: AgentState) -> dict:
    """
    Writes jobs, companies, contacts, and pending outreach drafts to DB
    before the interrupt checkpoint.
    """
    print("\n💾 Pre-interrupt save starting...")

    jobs        = state.get("jobs_found", [])
    scored_jobs = state.get("jobs_scored", [])
    companies   = state.get("funded_companies", [])
    contacts    = state.get("contacts_found", [])
    drafts      = state.get("outreach_drafts", [])

    with get_db() as db:
        ensure_default_user(db)
        for job in jobs:
            try:
                upsert_job(db, job, scored_jobs)
            except Exception as e:
                print(f"  ⚠️  Job write failed: {e}")
        for company in companies:
            try:
                upsert_company(db, company)
            except Exception as e:
                print(f"  ⚠️  Company write failed: {e}")
        for contact in contacts:
            try:
                upsert_contact(db, contact)
            except Exception as e:
                print(f"  ⚠️  Contact write failed: {e}")
        # Write outreach drafts as pending_approval
        # TrackerAgent will update them to approved/rejected after human review
        for draft in drafts:
            try:
                record = OutreachRecord(
                    id=draft["id"],
                    user_id=draft["user_id"],
                    contact_id=draft["contact_id"] or None,
                    job_id=draft["job_id"] or None,
                    email_subject=draft["email_subject"],
                    email_body=draft["email_body"],
                    linkedin_dm=draft["linkedin_dm"],
                    status="pending_approval",
                )
                db.merge(record)
            except Exception as e:
                print(f"  ⚠️  Draft write failed: {e}")

    print(f"  ✅ Pre-interrupt save complete — {len(jobs)} jobs, {len(companies)} companies, {len(contacts)} contacts, {len(drafts)} drafts")
    return {
        "pipeline_status": "paused",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def tracker_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the TrackerAgent.

    Reads the full pipeline state and writes everything to PostgreSQL
    (or SQLite in development). This is the only agent that writes
    to the database — all other agents work purely in LangGraph state.

    CONCEPT — Single writer pattern
    Having one agent responsible for all DB writes keeps the system
    simple and predictable. No race conditions, no partial writes,
    no need to coordinate transactions across agents.
    """
    print("\n📊 TrackerAgent starting...")

    jobs           = state.get("jobs_found", [])
    scored_jobs    = state.get("jobs_scored", [])
    companies      = state.get("funded_companies", [])
    contacts       = state.get("contacts_found", [])
    drafts         = state.get("outreach_drafts", [])
    approved_ids   = set(state.get("approved_draft_ids", []))
    rejected_ids   = set(state.get("rejected_draft_ids", []))

    print(f"  Writing to database:")
    print(f"    Jobs      : {len(jobs)}")
    print(f"    Companies : {len(companies)}")
    print(f"    Contacts  : {len(contacts)}")
    print(f"    Drafts    : {len(drafts)} ({len(approved_ids)} approved, {len(rejected_ids)} rejected)")

    with get_db() as db:
        # Ensure default user exists
        ensure_default_user(db)

        # Write jobs (with scores if available)
        for job in jobs:
            try:
                upsert_job(db, job, scored_jobs)
            except Exception as e:
                print(f"  ⚠️  Failed to write job {job.get('id', '?')}: {e}")

        # Write funded companies
        for company in companies:
            try:
                upsert_company(db, company)
            except Exception as e:
                print(f"  ⚠️  Failed to write company {company.get('id', '?')}: {e}")

        # Write contacts
        for contact in contacts:
            try:
                upsert_contact(db, contact)
            except Exception as e:
                print(f"  ⚠️  Failed to write contact {contact.get('id', '?')}: {e}")

        # Write outreach drafts (approved + rejected only — skip pending)
        for draft in drafts:
            draft_id = draft["id"]
            if draft_id in approved_ids:
                upsert_outreach(db, draft, is_approved=True)
            elif draft_id in rejected_ids:
                upsert_outreach(db, draft, is_approved=False)
            # Pending drafts are not written — they stay in LangGraph state

    print(f"\n✅ TrackerAgent complete — all data written to database")

    return {
        "pipeline_status": "complete",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }