# agents/outreach_agent.py
#
# The OutreachAgent drafts personalised cold emails and LinkedIn DMs
# for each contact found by the ContactFinderAgent.
#
# It runs JUST BEFORE the human-in-the-loop interrupt checkpoint.
# After this agent completes, the graph pauses and waits for you to
# review and approve each draft in the Streamlit dashboard.
#
# CONCEPT — Why personalisation matters
# A generic cold email ("I'm interested in AI roles at your company")
# gets ignored. A specific one ("I saw Sarvam just raised Series A —
# your work on Indian language LLMs aligns with my LangGraph experience")
# gets responses. Claude can generate this personalisation at scale.
#
# CONCEPT — Two output formats
# We generate both a cold EMAIL and a LinkedIn DM for each contact.
# Email: longer, more context, sent via Gmail API after approval
# LinkedIn DM: under 300 chars, you paste it manually (account safety)

import json
from datetime import datetime, timezone
import uuid

import anthropic

from graph.state import AgentState, Contact, ScoredJob, OutreachDraft
from config.settings import ANTHROPIC_API_KEY, RESUME_PATH

# ---------------------------------------------------------------------------
# LOAD RESUME + INIT CLIENT
# ---------------------------------------------------------------------------

with open(RESUME_PATH, "r") as f:
    RESUME_CONTENT = f.read()

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# PROMPTS
# ---------------------------------------------------------------------------

COLD_OUTREACH_PROMPT = """You are Nisha, Bhanu's AI agent. You're helping draft a personalised cold outreach email
and LinkedIn DM to a contact at a company (that has been recently funded or has been in the news) on behalf of Bhanu Gupta.

## Bhanu's Resume
{resume}

## Target Contact
Name: {contact_name}
Title: {contact_title}
Company: {company_name}
LinkedIn: {linkedin_url}

## Company Context
{company_context}

## Instructions
Write a cold outreach email and a LinkedIn DM.

The email should:
- START with a genuine congratulations about their recent growth / funding round news (include specific amount and date if available)
- Then introduce yourself as Nisha, Bhanu Gupta's AI agent, and briefly explain: "I came across your company's recent (funding or growth) news and noticed [specific detail]"
- Then tell them that the purpose of this email is that you feel that Bhanu would be great fit at their company.
- Briefly tell them about Bhanu's 10 years of experince with consumer internet companies and how excited and passionate he is about AI-tech.
- Highlight how Bhanu's AI engineering skills (LangGraph, RAG, agentic systems) could be valuable to their team, and them that he has created you - Nisha - as a part of his jobs-agent project that helps him find relevant jobs and reach out.
- Also mention why his experience with data and decision sciences puts him in a unique & strong position when it comes to making and evaluating probabilistic systems.
- Include Bhanu's contact information: phone +91-9663938263, email in signature
- Mention that you've attached Bhanu's resume (PDF) for reference
- Make a clear, specific ask - 15-minute call or refer to open role
- Close with: "Feel free to reach out to Bhanu directly at +91-9663938263 or respond to this email."
- Sign as: "Best, Nisha (on behalf of Bhanu Gupta) | AI Agent"
- Keep it warm but professional, under 250 words

The LinkedIn DM should:
- Be under 280 characters
- Start with congratulations on their growth / funding news
- Mention Bhanu's AI background
- Include the phone number +91-9663938263
- End with a clear ask

Respond with ONLY a JSON object, no markdown, no preamble:
{{
  "email_subject": "<subject line>",
  "email_body": "<full email body>",
  "linkedin_dm": "<linkedin dm under 280 chars>"
}}"""


JOB_APPLICATION_PROMPT = """You are Nisha, Bhanu's AI agent. You're helping draft a personalised outreach email
and LinkedIn DM to a hiring manager for a specific role Bhanu is interested in applying to.

## Bhanu's Resume
{resume}

## Scoring Reasoning
{scoring_reasoning}

## Job Details
Title: {job_title}
Company: {company_name}
Job URL: {job_url}
Job Description (excerpt):
{job_description}

## Contact
Name: {contact_name}
Title: {contact_title}
LinkedIn: {linkedin_url}

## Instructions
Write an outreach email and LinkedIn DM. You are writing on behalf of Bhanu, signed as "Nisha - Bhanu's AI agent".

The email should:

- Introduce yourself as Nisha, Bhanu's AI agent: "I came across this job posting on {job_source} and I believe Bhanu would be a great fit for this role."
- Reference the specific role by name
- Then tell them that the purpose of this email is that you feel that Bhanu would be great fit at their company. Use Claude's scoring reasoning to explain why Bhanu is a great match (highlight 2-3 key reasons from the reasoning).
- Briefly tell them about Bhanu's 10 years of experince with consumer internet companies and how excited and passionate he is about AI-tech.
- Highlight how Bhanu's has created you - Nisha - as a part of his jobs-agent project that helps him find relevant jobs and reach out.
- Also mention why his experience with data and decision sciences puts him in a unique & strong position when it comes to making and evaluating probabilistic systems.
- Mention Bhanu's relevant skills/experiences for THIS role
- Include Bhanu's contact information: phone +91-9663938263
- Mention that you've attached Bhanu's resume (PDF) for reference
- Make a clear ask (would love to chat about the role, happy to discuss further)
- Close with: "Feel free to reach out to Bhanu directly at +91-9663938263 or respond to this email."
- Sign as: "Best, Nisha (on behalf of Bhanu Gupta) | AI Agent"
- Keep it warm but professional, under 250 words

The LinkedIn DM should:
- Be under 280 characters
- Reference the specific role
- Mention 1-2 relevant skills
- Include phone number +91-9663938263
- End with a clear ask

Respond with ONLY a JSON object, no markdown, no preamble:
{{
  "email_subject": "<subject line>",
  "email_body": "<full email body>",
  "linkedin_dm": "<linkedin dm under 280 chars>"
}}"""


# ---------------------------------------------------------------------------
# DRAFT FOR ONE CONTACT
# ---------------------------------------------------------------------------

def draft_outreach(
    contact: Contact,
    company_context: str = "",
    scored_job: ScoredJob | None = None,
) -> OutreachDraft | None:
    """
    Drafts a cold email and LinkedIn DM for a single contact.

    Uses different prompts depending on context:
    - If scored_job provided: job application outreach (warm)
    - If no scored_job: cold company outreach (cold)

    CONCEPT — Prompt selection based on context
    The same contact might need different messaging depending on whether
    we're applying for a specific role or doing general cold outreach.
    We select the right prompt template at runtime based on what data
    we have available. This is a common pattern in LLM pipelines.
    """
    contact_name = contact["name"] if contact["name"] != "See LinkedIn" else "there"
    contact_title = contact["title"] if contact["title"] != "See LinkedIn" else ""

    try:
        if scored_job:
            # Warm outreach — applying for a specific job
            prompt = JOB_APPLICATION_PROMPT.format(
                resume=RESUME_CONTENT,
                job_title=job["title"],
                company_name=job["company"],
                job_url=job["url"],
                job_description=job["description"][:1000],
                scoring_reasoning=scored_job.get("reasoning", "N/A")[:500],  # Add this line
                job_source=scored_job.get("job", {}).get("source", "HN"),  # Add this line
                contact_name=contact_name,
                contact_title=contact_title,
                linkedin_url=contact["linkedin_url"],
            )
        else:
            # Cold outreach — funded company, no specific role
            prompt = COLD_OUTREACH_PROMPT.format(
                resume=RESUME_CONTENT,
                contact_name=contact_name,
                contact_title=contact_title,
                company_name=company_context.split("\n")[0] if company_context else "your company",
                linkedin_url=contact["linkedin_url"],
                company_context=company_context[:500],
            )

        message = claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)

        return OutreachDraft(
            id=str(uuid.uuid4()),
            user_id=contact["user_id"],
            contact_id=contact["id"],
            job_id=scored_job["job"]["id"] if scored_job else "",
            company_id=contact.get("company_id", ""),
            email_subject=result.get("email_subject", ""),
            email_body=result.get("email_body", ""),
            linkedin_dm=result.get("linkedin_dm", ""),
            status="pending_approval",
            created_at=datetime.now(timezone.utc).isoformat(),
            sent_at="",
        )

    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON parse error for {contact_name}: {e}")
        return None
    except anthropic.APIError as e:
        print(f"    ⚠️  Claude API error for {contact_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def outreach_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the OutreachAgent.

    Processes contacts from two sources:
    1. Contacts linked to funded companies → cold outreach drafts
    2. Contacts linked to recommended jobs → job application drafts

    After this node completes, the graph hits the interrupt_before
    checkpoint and pauses. The Streamlit dashboard reads the
    outreach_drafts from state and presents them for your approval.
    """
    print("\n✍️  OutreachAgent starting...")

    contacts = state.get("contacts_found", [])
    scored_jobs = state.get("jobs_scored", [])
    funded_companies = state.get("funded_companies", [])

    if not contacts:
        print("  ⚠️  No contacts found — skipping outreach drafting")
        return {
            "outreach_drafts": [],
            "pipeline_status": "paused",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    # Build lookup maps for efficient access
    company_map = {c["id"]: c for c in funded_companies}
    job_map = {j["job"]["id"]: j for j in scored_jobs}

    drafts: list[OutreachDraft] = []
    print(f"  📋 Drafting outreach for {len(contacts)} contacts...")

    for i, contact in enumerate(contacts, 1):
        print(f"  [{i}/{len(contacts)}] Drafting for {contact['name']} at contact_id={contact['id'][:8]}...")

        # Determine context — is this contact from a job or a company?
        company_context = ""
        scored_job = None

        if contact["company_id"] and contact["company_id"] in company_map:
            # Cold outreach — contact from FundingIntelAgent
            company = company_map[contact["company_id"]]
            company_context = (
                f"{company['name']}\n"
                f"Funding: {company['funding_stage']} — {company['amount_raised']}\n"
                f"{company['notes'][:300]}"
            )
        else:
            # Job application outreach — find matching scored job
            for sj in scored_jobs:
                if sj["job"]["company"].lower() in contact.get("company_id", "").lower():
                    scored_job = sj
                    break

        draft = draft_outreach(
            contact=contact,
            company_context=company_context,
            scored_job=scored_job,
        )

        if draft:
            # Set job_id if this is job application outreach
            draft["job_id"] = scored_job["job"]["id"] if scored_job else ""
            # Set company_id from contact (already has it)
            # Note: contact.company_id is set by ContactFinderAgent
            
            drafts.append(draft)
            print(f"    ✅ Draft created — subject: {draft['email_subject']}")

    print(f"\n✅ OutreachAgent complete — {len(drafts)} drafts created")
    print("  ⏸  Pipeline pausing for human review...")

    return {
        "outreach_drafts": drafts,
        "pipeline_status": "paused",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }