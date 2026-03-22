# agents/test_tracker.py
# Run with: python3 -m agents.test_tracker

import uuid
from datetime import datetime, timezone
from graph.state import AgentState, Job, ScoredJob, Company, Contact, OutreachDraft
from agents.tracker_agent import tracker_agent
from db.database import get_db
from db.models import JobRecord, CompanyRecord, ContactRecord, OutreachRecord

user_id = "00000000-0000-0000-0000-000000000001"
company_id = str(uuid.uuid4())
contact_id = str(uuid.uuid4())
job_id = str(uuid.uuid4())
draft_id = str(uuid.uuid4())

test_job = Job(
    id=job_id, user_id=user_id,
    title="AI Engineer", company="Sarvam AI",
    location="Bengaluru", description="Build LLMs",
    url="https://sarvam.ai/jobs", source="greenhouse",
    date_found=datetime.now(timezone.utc).isoformat(),
    status="new",
)
test_scored = ScoredJob(
    job=test_job, score=78,
    reasoning="Strong fit for agentic AI work",
    matched_skills=["LangGraph", "RAG"],
    missing_skills=["Production deployment"],
    recommended=True,
)
test_company = Company(
    id=company_id, user_id=user_id,
    name="Sarvam AI", funding_stage="Series A",
    amount_raised="$41M", funding_date="2024-07-01",
    source_url="https://entrackr.com",
    website="https://sarvam.ai",
    notes="Indian LLM startup",
)
test_contact = Contact(
    id=contact_id, user_id=user_id,
    company_id=company_id, name="Harshad Deo",
    title="Co-founder", email="",
    linkedin_url="https://www.linkedin.com/in/deoharshad",
    source="tavily",
)
test_draft = OutreachDraft(
    id=draft_id, user_id=user_id,
    contact_id=contact_id, job_id="",
    email_subject="AI Engineer interested in Sarvam",
    email_body="Hi Harshad, congrats on the Series A...",
    linkedin_dm="Hi Harshad — congrats on the Series A!",
    status="pending_approval",
    created_at=datetime.now(timezone.utc).isoformat(),
    sent_at="",
)

state = AgentState(
    user_id=user_id,
    run_id=str(uuid.uuid4()),
    run_triggered_by="manual",
    jobs_found=[test_job],
    funded_companies=[test_company],
    jobs_scored=[test_scored],
    contacts_found=[test_contact],
    outreach_drafts=[test_draft],
    approved_draft_ids=[draft_id],  # simulate approving the draft
    rejected_draft_ids=[],
    errors=[],
    pipeline_status="paused",
    last_updated=datetime.now(timezone.utc).isoformat(),
)

print("=" * 60)
print("Testing TrackerAgent in isolation")
print("=" * 60)

result = tracker_agent(state)

print("\n--- Verifying DB contents ---")
with get_db() as db:
    jobs     = db.query(JobRecord).all()
    companies = db.query(CompanyRecord).all()
    contacts  = db.query(ContactRecord).all()
    outreach  = db.query(OutreachRecord).all()

    print(f"  Jobs      : {len(jobs)} — {jobs[0].title} @ {jobs[0].company} (score: {jobs[0].score})")
    print(f"  Companies : {len(companies)} — {companies[0].name} ({companies[0].funding_stage})")
    print(f"  Contacts  : {len(contacts)} — {contacts[0].name}")
    print(f"  Outreach  : {len(outreach)} — status: {outreach[0].status}")