# agents/funding_intel_agent.py
#
# The FundingIntelAgent finds recently funded companies that are likely
# hiring AI Engineers. These are your best cold outreach targets.
#
# CONCEPT — Why target funded companies?
# A company that just raised Series A or B has two things:
#   1. Money to hire
#   2. Pressure to grow fast (investors expect it)
# This makes them far more likely to respond to a strong cold outreach
# than a company in steady state.
#
# HOW IT WORKS:
# We use Tavily to search Entrackr (India's leading startup funding tracker)
# and TechCrunch for recent AI startup funding announcements.
# Tavily returns clean, structured search results we can parse directly.
#
# CONCEPT — Tavily vs raw web search
# Tavily is an LLM-optimised search API. Unlike Google, it:
#   - Returns clean text snippets (no HTML to parse)
#   - Is designed specifically for use inside AI pipelines
#   - Supports "search_depth=advanced" for deeper content extraction
#   - Has a Python SDK that makes integration trivial

import uuid
import re
from datetime import datetime, timezone

from tavily import TavilyClient

from graph.state import AgentState, Company
from config.settings import (
    TAVILY_API_KEY,
)


# ---------------------------------------------------------------------------
# TAVILY CLIENT
# ---------------------------------------------------------------------------

tavily = TavilyClient(api_key=TAVILY_API_KEY)


# ---------------------------------------------------------------------------
# SEARCH QUERIES
# ---------------------------------------------------------------------------
# Each query targets a specific funding signal.
# We run multiple queries to cast a wide net then deduplicate.
#
# CONCEPT — Query design for funding intel
# Specific queries outperform generic ones. "AI startup funding India 2026"
# returns noise. "site:entrackr.com AI startup Series A 2026" returns
# exactly what we want. We mix broad and narrow queries for coverage.

FUNDING_QUERIES = [
    "site:entrackr.com AI startup funding 2026",
    "site:entrackr.com machine learning startup raised 2026",
    "site:entrackr.com generative AI company funding Series A 2026",
    "TechCrunch AI startup Series A funding India 2026",
    "Agentic AI startup seed funding raised 2026",
    "LLM startup Series B funding announced 2026",
]


# ---------------------------------------------------------------------------
# HELPER — Extract company info from a Tavily result
# ---------------------------------------------------------------------------

def parse_funding_result(result: dict, user_id: str) -> Company | None:
    """
    Parses a single Tavily search result into a Company object.

    CONCEPT — Defensive parsing
    API responses are messy. Fields may be missing, None, or in unexpected
    formats. We use .get() with defaults everywhere and return None if we
    can't extract enough useful information.

    A Company object we can't use (no name, no URL) is worse than no
    Company at all — it would pollute the dashboard with useless rows.

    Args:
        result: a single result dict from Tavily's search response
        user_id: the current user's ID

    Returns:
        A Company TypedDict, or None if the result isn't usable
    """
    title = result.get("title", "") or ""
    content = result.get("content", "") or ""
    url = result.get("url", "") or ""

    # Skip results with no useful content
    if not title or not content:
        return None

    # Skip aggregator pages, list articles, and tag pages
    # These contain multiple companies and aren't actionable individually
    SKIP_PATTERNS = [
        "top-startups", "list-of", "hottest-ai", "hub/", "/tag/",
        "to-watch", "by-valuation", "seed-funding-companies",
        "fundraiseinsider", "tracxn.com/d/sectors", "crunchbase.com/hub",
        "wellows.com", "topstartups.io",
        # TechCrunch section/tag pages (not individual company stories)
        "techcrunch.com/tag/", "techcrunch.com/category/",
        "india-doubles-down", "nvidia-deepens", "all-the-important-news",
        "ai-chips-vc-funding", "funding-and-acquisitions",
        "iifl-fintech-floats",
        "theregister.com", "demandgenreport.com", "bereaonline.com",
        "google-and-accel", "google-accel",
    ]
    # Real funding articles have meaningful content
    # Short snippets are usually navigation pages or stubs
    if len(content) < 100:
        return None
    if any(pattern in url.lower() for pattern in SKIP_PATTERNS):
        return None

    # Try to extract funding amount from the text
    # Looks for patterns like "$5M", "$12 million", "₹50 crore"
    amount_match = re.search(
        r'(\$[\d,.]+\s*(?:million|billion|M|B)?|₹[\d,.]+\s*(?:crore|lakh)?)',
        content,
        re.IGNORECASE
    )
    amount_raised = amount_match.group(0) if amount_match else "See article"

    # Try to extract funding stage
    stage_match = re.search(
        r'\b(Pre-?Seed|Seed|Series\s+[A-E]|Growth|IPO)\b',
        content,
        re.IGNORECASE
    )
    funding_stage = stage_match.group(0) if stage_match else "See article"

    # Extract company name from funding headline
    # Entrackr headlines follow patterns like:
    #   "CompanyName raises $X in Series A"
    #   "CompanyName secures $X led by VC"
    #   "VCName leads $X round in CompanyName"
    # Extract company name from funding headline
    company_name = ""

    # Pattern 1: "X raises/secures/closes $Y"
    match = re.match(r'^([A-Za-z0-9@\s\.\-]+?)\s+(?:raises|secures|closes|gets)\s+', title, re.IGNORECASE)
    if match:
        company_name = match.group(1).strip()

    # Pattern 2: "VC leads $X round in CompanyName"
    if not company_name:
        match = re.search(r'\bin\s+([A-Za-z0-9@\s\.\-]+?)(?:\s*$|\s*,)', title, re.IGNORECASE)
        if match:
            company_name = match.group(1).strip()

    # Fallback: first segment of title
    if not company_name:
        company_name = title.split("|")[0].split("-")[0].strip()

    # Must have a usable name
    if not company_name or len(company_name) < 2:
        return None

    # A real company name is short — headlines sneak through as names
    if len(company_name.split()) > 6:
        return None

    return Company(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=company_name,
        funding_stage=funding_stage,
        amount_raised=amount_raised,
        funding_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        source_url=url,
        website="",        # ContactFinderAgent will fill this in
        notes=content[:500],
    )


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def funding_intel_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the FundingIntelAgent.

    Searches for recently funded AI companies using Tavily,
    parses the results into Company objects, deduplicates,
    and returns them in the shared state.

    CONCEPT — search_depth parameter
    Tavily supports two search depths:
      "basic"    — fast, uses cached snippets, cheaper (1 credit/search)
      "advanced" — slower, fetches and parses full pages (2 credits/search)
    We use "basic" here since snippets contain enough for our parsing.
    Use "advanced" when you need the full article text.
    """
    print("\n💰 FundingIntelAgent starting...")

    if not TAVILY_API_KEY:
        print("  ⚠️  TAVILY_API_KEY not set — skipping")
        return {
            "funded_companies": [],
            "pipeline_status": "running",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    user_id = state["user_id"]
    all_companies: list[Company] = []
    seen_urls: set[str] = set()

    for query in FUNDING_QUERIES:
        print(f"  🔍 Searching: {query[:60]}...")

        try:
            response = tavily.search(
                query=query,
                search_depth="basic",
                max_results=5,
            )

            results = response.get("results", [])
            query_companies = 0

            for result in results:
                url = result.get("url", "")

                # Deduplicate by URL — same article from two queries = one company
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                company = parse_funding_result(result, user_id)
                if company:
                    all_companies.append(company)
                    query_companies += 1

            print(f"    ✅ Found {query_companies} new companies")

        except Exception as e:
            print(f"    ⚠️  Search failed: {e}")

    print(f"\n✅ FundingIntelAgent complete — {len(all_companies)} funded companies found")

    return {
        "funded_companies": all_companies,
        "pipeline_status": "running",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }