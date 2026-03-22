# agents/test_scoring.py
#
# Tests ScrapeAgent + ScoringAgent together in sequence.
# Run with: python3 -m agents.test_scoring
#
# CONCEPT — Integration testing
# Unit tests test one function in isolation.
# Integration tests test two or more components working together.
# This test verifies that the output of ScrapeAgent feeds correctly
# into ScoringAgent — the most common source of pipeline bugs.

import uuid
from datetime import datetime, timezone

from graph.state import AgentState
from agents.scrape_agent import scrape_agent
from agents.scoring_agent import scoring_agent

# Build initial state
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
print("Integration test: ScrapeAgent → ScoringAgent")
print("=" * 60)

# Step 1 — Run ScrapeAgent
scrape_result = scrape_agent(state)

# Merge result into state (simulating what LangGraph does automatically)
state["jobs_found"] = scrape_result["jobs_found"]
print(f"\n✅ ScrapeAgent done — {len(state['jobs_found'])} jobs found")

# Step 2 — Run ScoringAgent
score_result = scoring_agent(state)

# Step 3 — Show results
print("\n--- Scoring Results ---")
for scored_job in sorted(score_result["jobs_scored"],
                          key=lambda x: x["score"], reverse=True):
    job = scored_job["job"]
    rec = "⭐ RECOMMENDED" if scored_job["recommended"] else ""
    print(f"\n  {scored_job['score']:3d}/100  {job['title']} @ {job['company']} {rec}")
    print(f"           {scored_job['reasoning'][:100]}...")
    if scored_job["matched_skills"]:
        print(f"           Matched: {', '.join(scored_job['matched_skills'][:4])}")
    if scored_job["missing_skills"]:
        print(f"           Missing: {', '.join(scored_job['missing_skills'][:3])}")