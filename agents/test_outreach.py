# agents/test_outreach.py
# Run with: python3 -m agents.test_outreach

import uuid
from datetime import datetime, timezone
from graph.state import AgentState, Contact, Company
from agents.outreach_agent import outreach_agent

user_id = str(uuid.uuid4())
company_id = str(uuid.uuid4())

test_companies = [
    Company(
        id=company_id,
        user_id=user_id,
        name="Sarvam AI",
        funding_stage="Series A",
        amount_raised="$41M",
        funding_date="2024-07-01",
        source_url="https://entrackr.com",
        website="https://sarvam.ai",
        notes="Indian AI startup building LLMs for Indian languages. "
              "Recently raised Series A to expand their model capabilities "
              "and grow their engineering team.",
    ),
]

test_contacts = [
    Contact(
        id=str(uuid.uuid4()),
        user_id=user_id,
        company_id=company_id,
        name="Harshad Deo",
        title="Co-founder",
        email="",
        linkedin_url="https://www.linkedin.com/in/deoharshad",
        source="tavily",
    ),
]

state = AgentState(
    user_id=user_id,
    run_id=str(uuid.uuid4()),
    run_triggered_by="manual",
    jobs_found=[],
    funded_companies=test_companies,
    jobs_scored=[],
    contacts_found=test_contacts,
    outreach_drafts=[],
    approved_draft_ids=[],
    rejected_draft_ids=[],
    errors=[],
    pipeline_status="running",
    last_updated=datetime.now(timezone.utc).isoformat(),
)

print("=" * 60)
print("Testing OutreachAgent in isolation")
print("=" * 60)

result = outreach_agent(state)

for draft in result["outreach_drafts"]:
    print(f"\n{'='*60}")
    print(f"SUBJECT : {draft['email_subject']}")
    print(f"{'='*60}")
    print(draft["email_body"])
    print(f"\n--- LinkedIn DM ({len(draft['linkedin_dm'])} chars) ---")
    print(draft["linkedin_dm"])