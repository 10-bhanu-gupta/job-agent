# agents/test_funding.py
# Run with: python3 -m agents.test_funding

import uuid
from datetime import datetime, timezone
from graph.state import AgentState
from agents.funding_intel_agent import funding_intel_agent

state = AgentState(
    user_id=str(uuid.uuid4()),
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

print("=" * 60)
print("Testing FundingIntelAgent in isolation")
print("=" * 60)

result = funding_intel_agent(state)

print(f"\n--- {len(result['funded_companies'])} Companies Found ---")
for company in result["funded_companies"]:
    print(f"\n  {company['name']}")
    print(f"  Stage  : {company['funding_stage']}")
    print(f"  Raised : {company['amount_raised']}")
    print(f"  Source : {company['source_url'][:70]}...")
    print(f"  Notes  : {company['notes'][:100]}...")