# agents/test_scrape.py
#
# Quick standalone test for the ScrapeAgent.
# Run with: python3 -m agents.test_scrape
#
# This tests the agent IN ISOLATION — without the full LangGraph pipeline.
# This is good practice: test each agent independently before wiring them
# together. Bugs are much easier to find and fix in isolation.

from graph.state import AgentState
from agents.scrape_agent import scrape_agent
from datetime import datetime, timezone
import uuid

# Build a minimal AgentState with just enough fields to run the ScrapeAgent
# We only need user_id — the rest can be empty for this test
test_state = AgentState(
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
print("Testing ScrapeAgent in isolation")
print("=" * 60)

result = scrape_agent(test_state)

print("\n--- State update returned by ScrapeAgent ---")
print(f"pipeline_status : {result['pipeline_status']}")
print(f"jobs_found count: {len(result['jobs_found'])}")
print(f"last_updated    : {result['last_updated']}")

if result["jobs_found"]:
    print("\n--- First job found ---")
    job = result["jobs_found"][0]
    print(f"  title   : {job['title']}")
    print(f"  company : {job['company']}")
    print(f"  location: {job['location']}")
    print(f"  source  : {job['source']}")
    print(f"  url     : {job['url']}")
else:
    print("\n⚠️  No jobs found — check your network or API keys")