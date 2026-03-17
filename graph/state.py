# graph/state.py
#
# This file defines the SHARED STATE that flows through the entire LangGraph pipeline.
#
# CONCEPT — What is LangGraph State?
# ------------------------------------
# LangGraph models your application as a graph of nodes (agents) connected by edges.
# Every node receives the current state, does its work, and returns an UPDATED state.
# The graph carries this updated state forward to the next node automatically.
#
# Think of it like a baton in a relay race — each runner (agent) receives it,
# adds something to it, and hands it off. By the end, the baton contains the
# full record of everything that happened.
#
# WHY TypedDict?
# --------------
# TypedDict lets us define exactly what keys the state has and what type each
# value is. This means:
#   - Your editor will autocomplete state keys
#   - You'll get errors early if an agent writes the wrong type
#   - The code is self-documenting — the schema IS the documentation
#
# MULTI-TENANCY NOTE
# ------------------
# Every entity in this state is tied to a user_id (UUID). Right now only one
# user exists (you), but the design supports multiple users from day one.
# When we add authentication later, we'll simply start creating more users.

from typing import TypedDict, Annotated
from uuid import UUID
from datetime import datetime
import operator


# ---------------------------------------------------------------------------
# SUB-TYPES — these are the data shapes that populate the state lists
# ---------------------------------------------------------------------------

class Job(TypedDict):
    """
    Represents a single job listing discovered by the ScrapeAgent.

    Fields:
        id              — unique identifier (we generate this, not the portal)
        user_id         — which user this job belongs to
        title           — job title e.g. "AI Engineer"
        company         — company name e.g. "Sarvam AI"
        location        — e.g. "Bengaluru" or "Remote"
        description     — full job description text (used for scoring)
        url             — direct link to the job posting
        source          — which portal it came from: "linkedin", "wellfound", "yc", etc.
        date_found      — when our agent discovered this listing
        status          — lifecycle stage: "new" | "scored" | "applied" | "rejected" | "interviewing"
    """
    id: str
    user_id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    date_found: str        # ISO format string e.g. "2025-03-17T09:00:00"
    status: str


class ScoredJob(TypedDict):
    """
    A Job that has been evaluated by the ScoringAgent.

    WHY a separate type?
    The ScoringAgent enriches a Job with relevance data. Keeping this
    separate from Job makes it clear which fields are scraped vs computed.

    Fields:
        job             — the original Job dict (nested)
        score           — relevance score 0-100 (100 = perfect match)
        reasoning       — Claude's explanation of the score
        matched_skills  — list of skills in the JD that match your resume
        missing_skills  — skills in the JD you don't have (honest gap analysis)
        recommended     — True if score >= threshold (configurable in config/)
    """
    job: Job
    score: int
    reasoning: str
    matched_skills: list[str]
    missing_skills: list[str]
    recommended: bool


class Company(TypedDict):
    """
    A company identified by the FundingIntelAgent as a cold outreach target.
    These are recently funded companies that may be actively hiring AI engineers.

    Fields:
        id              — unique identifier
        user_id         — which user this belongs to
        name            — company name
        funding_stage   — e.g. "Seed", "Series A", "Series B"
        amount_raised   — e.g. "$5M" (string because formats vary)
        funding_date    — when they raised
        source_url      — the Entrackr/TechCrunch article we found this from
        website         — company website if found
        notes           — any additional context Tavily found
    """
    id: str
    user_id: str
    name: str
    funding_stage: str
    amount_raised: str
    funding_date: str
    source_url: str
    website: str
    notes: str


class Contact(TypedDict):
    """
    A person at a target company, found by the ContactFinderAgent.
    This could be a hiring manager, CTO, or founder.

    Fields:
        id              — unique identifier
        user_id         — which user this belongs to
        company_id      — links back to a Company
        name            — full name
        title           — job title e.g. "Head of Engineering"
        email           — verified email address (via Hunter.io)
        linkedin_url    — their LinkedIn profile URL
        source          — how we found them: "tavily" | "proxycurl" | "hunter"
    """
    id: str
    user_id: str
    company_id: str
    name: str
    title: str
    email: str
    linkedin_url: str
    source: str


class OutreachDraft(TypedDict):
    """
    A cold email or LinkedIn DM drafted by the OutreachAgent.
    Sits in a queue waiting for human approval before sending.

    Fields:
        id              — unique identifier
        user_id         — which user this belongs to
        contact_id      — links to the Contact we're reaching out to
        job_id          — links to the Job we're applying for (optional for cold outreach)
        email_subject   — subject line for cold email
        email_body      — full email body
        linkedin_dm     — shorter version for LinkedIn DM (under 300 chars)
        status          — "pending_approval" | "approved" | "sent" | "rejected"
        created_at      — when the draft was generated
        sent_at         — when it was actually sent (None until sent)
    """
    id: str
    user_id: str
    contact_id: str
    job_id: str            # empty string if pure cold outreach (not tied to a specific job)
    email_subject: str
    email_body: str
    linkedin_dm: str
    status: str
    created_at: str
    sent_at: str           # empty string until sent


# ---------------------------------------------------------------------------
# MAIN STATE — this is what flows through the entire LangGraph graph
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """
    The master state object that every LangGraph node reads from and writes to.

    HOW UPDATES WORK — the Annotated[list, operator.add] pattern
    -------------------------------------------------------------
    For list fields, we use Annotated[list[X], operator.add].
    This tells LangGraph to APPEND new items to the list rather than
    replace it entirely when an agent returns updates.

    Example: if ScrapeAgent finds 10 jobs and returns them, LangGraph
    appends them to jobs_found rather than replacing whatever was there.
    This is crucial for a pipeline where multiple agents contribute data.

    For non-list fields (strings, bools), the last write wins — whichever
    agent writes to it last is what gets stored.

    PIPELINE FLOW
    -------------
    ScrapeAgent         → populates jobs_found
    FundingIntelAgent   → populates funded_companies
    ScoringAgent        → reads jobs_found, populates jobs_scored
    ContactFinderAgent  → reads funded_companies + jobs_scored, populates contacts_found
    OutreachAgent       → reads contacts_found + jobs_scored, populates outreach_drafts
    [INTERRUPT]         → human reviews outreach_drafts in dashboard, populates approved_ids
    TrackerAgent        → reads everything, writes final state to PostgreSQL
    """

    # --- Identity ---
    user_id: str                    # UUID of the user running this pipeline run
    run_id: str                     # UUID of this specific pipeline run (for logging)
    run_triggered_by: str           # "scheduler" | "manual"

    # --- Job Discovery (populated by ScrapeAgent) ---
    jobs_found: Annotated[list[Job], operator.add]

    # --- Funding Intelligence (populated by FundingIntelAgent) ---
    funded_companies: Annotated[list[Company], operator.add]

    # --- Scoring (populated by ScoringAgent) ---
    jobs_scored: Annotated[list[ScoredJob], operator.add]

    # --- Contact Discovery (populated by ContactFinderAgent) ---
    contacts_found: Annotated[list[Contact], operator.add]

    # --- Outreach (populated by OutreachAgent) ---
    outreach_drafts: Annotated[list[OutreachDraft], operator.add]

    # --- Human Approval (populated by you via the dashboard) ---
    # List of OutreachDraft IDs you have approved for sending
    approved_draft_ids: Annotated[list[str], operator.add]

    # List of OutreachDraft IDs you have rejected
    rejected_draft_ids: Annotated[list[str], operator.add]

    # --- Pipeline Metadata ---
    errors: Annotated[list[str], operator.add]   # any errors encountered, non-fatal
    pipeline_status: str                          # "running" | "paused" | "complete" | "failed"
    last_updated: str                             # ISO timestamp of last state change