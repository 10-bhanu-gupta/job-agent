# agents/test_contacts.py
# Run with: python3 -m agents.test_contacts
#
# Tests ContactFinderAgent with a small hardcoded list of companies
# so we don't burn API credits running the full pipeline every time.

import uuid
from datetime import datetime, timezone
from graph.state import AgentState, Company
from agents.contact_finder_agent import contact_finder_agent

# Use a small handpicked list of known Indian AI companies
# rather than running FundingIntelAgent first
test_companies = [
    Company(
        id=str(uuid.uuid4()),
        user_id="test-user",
        name="Sarvam AI",
        funding_stage="Series A",
        amount_raised="$41M",
        funding_date="2024-07-01",
        source_url="https://entrackr.com",
        website="https://sarvam.ai",
        notes="Indian AI startup building LLMs for Indian languages",
    ),
    Company(
        id=str(uuid.uuid4()),
        user_id="test-user",
        name="Krutrim",
        funding_stage="Series A",
        amount_raised="$50M",
        funding_date="2024-02-01",
        source_url="https://entrackr.com",
        website="https://krutrim.ai",
        notes="Ola's AI subsidiary building Indian AI infrastructure",
    ),
]

state = AgentState(
    user_id=str(uuid.uuid4()),
    run_id=str(uuid.uuid4()),
    run_triggered_by="manual",
    jobs_found=[],
    funded_companies=test_companies,
    jobs_scored=[],
    contacts_found=[],
    outreach_drafts=[],
    approved_draft_ids=[],
    rejected_draft_ids=[],
    errors=[],
    pipeline_status="running",
    last_updated=datetime.now(timezone.utc).isoformat(),
)

print("=" * 60)
print("Testing ContactFinderAgent in isolation")
print("=" * 60)

result = contact_finder_agent(state)

print(f"\n--- {len(result['contacts_found'])} Contacts Found ---")
for contact in result["contacts_found"]:
    print(f"\n  Name    : {contact['name']}")
    print(f"  Title   : {contact['title']}")
    print(f"  Email   : {contact['email'] or '(not found)'}")
    print(f"  LinkedIn: {contact['linkedin_url'][:70] if contact['linkedin_url'] else '(not found)'}")
    print(f"  Source  : {contact['source']}")