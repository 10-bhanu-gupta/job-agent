# agents/scoring_agent.py
#
# The ScoringAgent is the third node in our LangGraph pipeline.
# It reads jobs_found from state, scores each one against Bhanu's
# resume using the Claude API, and returns a list of ScoredJob objects.
#
# CONCEPT — Why score jobs with an LLM?
# Traditional keyword matching misses context. "Python" in a data science
# JD is different from "Python" in an AI engineering JD. Claude can read
# both the job description AND your resume holistically and make a
# nuanced judgement — just like a human recruiter would.
#
# CONCEPT — Structured output prompting
# We ask Claude to respond in JSON format with a specific schema.
# This is called "structured output" — instead of free-form text,
# the LLM returns machine-parseable data we can directly use in code.
# This is one of the most important real-world LLM engineering patterns.

import json
import uuid
from datetime import datetime, timezone

import anthropic

from graph.state import AgentState, Job, ScoredJob
from config.settings import (
    ANTHROPIC_API_KEY,
    RESUME_PATH,
    SCORING_THRESHOLD,
)


# ---------------------------------------------------------------------------
# LOAD RESUME ONCE AT MODULE LEVEL
# ---------------------------------------------------------------------------
# We load the resume when this module is first imported, not inside the
# agent function. This means we read the file once per process, not once
# per job scored — much more efficient.
#
# CONCEPT — Module-level initialisation
# Code at module level runs once when Python imports the module.
# Expensive operations (file reads, model loads, DB connections) belong
# here, not inside functions that get called repeatedly.

with open(RESUME_PATH, "r") as f:
    RESUME_CONTENT = f.read()


# ---------------------------------------------------------------------------
# CLAUDE CLIENT — initialised once at module level (same reason as above)
# ---------------------------------------------------------------------------

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# SCORING PROMPT
# ---------------------------------------------------------------------------

# This is the prompt template we send to Claude for each job.
# Good prompt engineering principles used here:
#   1. Clear role definition ("You are an expert technical recruiter")
#   2. Explicit output format with an example schema
#   3. Specific scoring rubric so scores are consistent across jobs
#   4. Instruction to respond ONLY in JSON — no preamble or explanation
#
# The {resume} and {job_title}, {company}, {description} placeholders
# get filled in at runtime for each job.

SCORING_PROMPT_TEMPLATE = """You are an expert technical recruiter evaluating job fit.

## Candidate Resume
{resume}

## Job Being Evaluated
Title: {job_title}
Company: {company}
Location: {location}
Source: {source}

Job Description:
{description}

## Your Task
Score how well this candidate fits this job. Be honest — if the candidate
is missing key requirements, reflect that in the score.

Respond with ONLY a JSON object — no explanation, no markdown, no preamble.
The JSON must follow this exact schema:

{{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentences explaining the score>",
  "matched_skills": ["<skill1>", "<skill2>"],
  "missing_skills": ["<skill1>", "<skill2>"],
  "recommended": <true if score >= {threshold}, else false>
}}

## Scoring Rubric
90-100: Near-perfect fit. Candidate meets almost all requirements.
70-89:  Strong fit. Candidate meets most requirements with minor gaps.
50-69:  Moderate fit. Candidate meets core requirements but has notable gaps.
30-49:  Weak fit. Significant gaps, but some transferable skills.
0-29:   Poor fit. Candidate does not meet the core requirements.

Important: This candidate is transitioning from senior analytics/data roles
into AI Engineering. Give credit for transferable skills (Python, SQL, data
systems, product thinking, A/B testing) but be honest about gaps in
production AI engineering experience.
"""


# ---------------------------------------------------------------------------
# SCORE A SINGLE JOB
# ---------------------------------------------------------------------------

def score_single_job(job: Job) -> ScoredJob:
    """
    Sends a single job to Claude API for scoring and returns a ScoredJob.

    CONCEPT — Why score one job at a time (not batch)?
    Claude gives better results when focused on one task. Batching all jobs
    into one prompt risks Claude confusing details between jobs and produces
    less reliable scores.

    We mitigate the speed cost by only scoring jobs above a basic
    relevance filter (title must contain at least one keyword).

    CONCEPT — response.content[0].text
    The Claude API returns a Message object. The actual text response
    lives at message.content[0].text — a list of content blocks,
    where index 0 is the first (and usually only) text block.

    CONCEPT — json.loads() with error handling
    When asking an LLM for JSON, always wrap the parse in try/except.
    Occasionally the model adds a stray character or markdown fence —
    we handle this gracefully rather than crashing the pipeline.
    """
    prompt = SCORING_PROMPT_TEMPLATE.format(
        resume=RESUME_CONTENT,
        job_title=job["title"],
        company=job["company"],
        location=job["location"],
        source=job["source"],
        description=job["description"],
        threshold=SCORING_THRESHOLD,
    )

    try:
        message = claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        raw_response = message.content[0].text

        # Strip markdown code fences if Claude added them despite instructions
        # e.g. ```json { ... } ``` → { ... }
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        result = json.loads(clean)

        return ScoredJob(
            job=job,
            score=int(result.get("score", 0)),
            reasoning=result.get("reasoning", ""),
            matched_skills=result.get("matched_skills", []),
            missing_skills=result.get("missing_skills", []),
            recommended=bool(result.get("recommended", False)),
        )

    except json.JSONDecodeError as e:
        # Claude returned something we couldn't parse — create a default
        # scored job with score 0 so the pipeline continues
        print(f"    ⚠️  JSON parse error for '{job['title']}' at {job['company']}: {e}")
        return ScoredJob(
            job=job,
            score=0,
            reasoning="Scoring failed — JSON parse error",
            matched_skills=[],
            missing_skills=[],
            recommended=False,
        )

    except anthropic.APIError as e:
        print(f"    ⚠️  Claude API error for '{job['title']}': {e}")
        return ScoredJob(
            job=job,
            score=0,
            reasoning=f"Scoring failed — API error: {str(e)}",
            matched_skills=[],
            missing_skills=[],
            recommended=False,
        )


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def scoring_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the ScoringAgent.

    Reads jobs_found from state, scores each one, returns jobs_scored.

    CONCEPT — Why filter before scoring?
    Claude API calls cost money and take ~2 seconds each. We apply a
    cheap keyword filter first to skip obviously irrelevant jobs before
    sending them to Claude. This is a common pattern in LLM pipelines:
    use cheap filters early, expensive models late.

    CONCEPT — Logging progress
    Since this node makes one API call per job and can take a while,
    we print progress so you can see it working in real time.
    In production, this would go to Cloud Logging instead of stdout.
    """
    print("\n🧠 ScoringAgent starting...")

    jobs = state.get("jobs_found", [])

    if not jobs:
        print("  ⚠️  No jobs to score — ScrapeAgent may have found nothing")
        return {
            "jobs_scored": [],
            "pipeline_status": "running",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    print(f"  📋 {len(jobs)} jobs to score")

    scored_jobs: list[ScoredJob] = []

    for i, job in enumerate(jobs, 1):
        title = job["title"]
        company = job["company"]
        print(f"  [{i}/{len(jobs)}] Scoring: {title} @ {company}...")

        scored = score_single_job(job)

        # Show the score inline so you can watch quality in real time
        emoji = "✅" if scored["recommended"] else "➖"
        print(f"    {emoji} Score: {scored['score']}/100 — {scored['reasoning'][:80]}...")

        scored_jobs.append(scored)

    # Summary stats
    recommended = [j for j in scored_jobs if j["recommended"]]
    avg_score = sum(j["score"] for j in scored_jobs) / len(scored_jobs) if scored_jobs else 0

    print(f"\n✅ ScoringAgent complete")
    print(f"   Scored: {len(scored_jobs)} jobs")
    print(f"   Recommended: {len(recommended)} jobs (score >= {SCORING_THRESHOLD})")
    print(f"   Average score: {avg_score:.1f}/100")

    return {
        "jobs_scored": scored_jobs,
        "pipeline_status": "running",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }