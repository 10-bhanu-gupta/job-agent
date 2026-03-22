# agents/scrape_agent.py
#
# The ScrapeAgent is the first node in our LangGraph pipeline.
# It discovers job listings from multiple sources and returns them
# as a list of Job objects into the shared AgentState.
#
# SOURCES (in priority order):
#   1. YC Jobs         — direct HTTP, free, no auth needed
#   2. Wellfound       — direct HTTP, free, partial API
#   3. Apify (LinkedIn, Naukri, IimJobs) — paid fallback
#
# CONCEPT — Why this order?
# We always try free, low-risk sources first. Apify costs money and
# involves third-party scraping infrastructure. We only invoke it when
# free sources don't return enough results (< MIN_JOBS_BEFORE_APIFY).
#
# CONCEPT — httpx vs requests
# httpx is the modern replacement for the classic `requests` library.
# It supports both sync and async HTTP, has a cleaner API, and handles
# connection pooling better. We use it synchronously here for simplicity,
# but the async version (httpx.AsyncClient) is a natural upgrade later.

import uuid
from datetime import datetime, timezone

import httpx
from apify_client import ApifyClient

from graph.state import AgentState, Job
from config.settings import (
    APIFY_API_TOKEN,
    JOB_SEARCH_KEYWORDS,
    JOB_SEARCH_LOCATIONS,
    MAX_JOBS_PER_SOURCE,
)


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# If free sources return fewer than this many jobs combined,
# we invoke Apify to fill the gap
MIN_JOBS_BEFORE_APIFY = 10

# HTTP request timeout in seconds
# Always set timeouts — without them, a slow server hangs your pipeline forever
REQUEST_TIMEOUT = 10


# ---------------------------------------------------------------------------
# HELPER — Job factory
# ---------------------------------------------------------------------------

def make_job(
    user_id: str,
    title: str,
    company: str,
    location: str,
    description: str,
    url: str,
    source: str,
) -> Job:
    """
    Creates a Job TypedDict with a generated ID and timestamp.

    CONCEPT — Why a factory function?
    Every Job needs a unique ID and a timestamp. Rather than repeating
    this logic in every scraper, we centralise it here. This is the
    DRY principle (Don't Repeat Yourself) in practice.

    We use uuid4() for IDs — these are random UUIDs, guaranteed unique
    across all records without needing a database sequence.
    """
    return Job(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        company=company,
        location=location,
        description=description,
        url=url,
        source=source,
        date_found=datetime.now(timezone.utc).isoformat(),
        status="new",
    )


# ---------------------------------------------------------------------------
# DEDUPLICATION
# ---------------------------------------------------------------------------

def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """
    Removes duplicate job listings.

    CONCEPT — How deduplication works here:
    We consider two jobs duplicates if they have the same company name
    AND the same job title (case-insensitive). This catches the common
    case where the same role appears on both LinkedIn and Wellfound.

    We use a set of (company, title) tuples as a "seen" tracker.
    Sets have O(1) lookup — much faster than comparing every pair.

    Args:
        jobs: list of Job dicts, potentially with duplicates

    Returns:
        list of Job dicts with duplicates removed (first occurrence kept)
    """
    seen = set()
    unique = []

    for job in jobs:
        # Normalise to lowercase to catch "AI Engineer" vs "ai engineer"
        key = (job["company"].lower().strip(), job["title"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)

    duplicates_removed = len(jobs) - len(unique)
    if duplicates_removed > 0:
        print(f"  🔄 Deduplication: removed {duplicates_removed} duplicate(s)")

    return unique


# ---------------------------------------------------------------------------
# SOURCE 1 — YC Jobs
# ---------------------------------------------------------------------------

def scrape_yc_jobs(user_id: str) -> list[Job]:
    """
    Fetches jobs from Hacker News 'Who is Hiring' monthly threads.

    FIXES FROM V1:
    - Search specifically for monthly threads (posted by 'whoishiring' bot)
    - Deduplicate comments across keyword searches before returning
      so we don't return the same comment 4 times for 4 keywords
    """
    print("  📡 Scraping HN Who is Hiring...")
    jobs = []

    try:
        # The official HN 'Who is Hiring' threads are posted by the
        # 'whoishiring' account every month — searching by author is
        # more reliable than searching by title
        # Use search_by_date to get the MOST RECENT thread, not the most popular
        # The relevance endpoint returns a 2020 thread because it has more points
        # search_by_date always returns newest first
        search_url = "https://hn.algolia.com/api/v1/search_by_date"
        params = {
            "query": "Who is hiring",
            "tags": "story,author_whoishiring",
            "hitsPerPage": 1,
        }
        response = httpx.get(search_url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        hits = response.json().get("hits", [])
        if not hits:
            print("  ⚠️  HN: Could not find 'Who is Hiring' thread")
            return jobs

        thread_id = hits[0]["objectID"]
        thread_title = hits[0].get("title", "")
        print(f"  ℹ️  Found thread: {thread_title} (ID: {thread_id})")

        # Track seen comment IDs across keyword searches
        # This prevents the same comment appearing once per keyword
        seen_comment_ids = set()

        for keyword in JOB_SEARCH_KEYWORDS[:4]:
            comments_params = {
                "query": keyword,
                "tags": f"comment,story_{thread_id}",
                "hitsPerPage": MAX_JOBS_PER_SOURCE,
            }
            comments_response = httpx.get(
                search_url,
                params=comments_params,
                timeout=REQUEST_TIMEOUT
            )
            comments_response.raise_for_status()

            comments = comments_response.json().get("hits", [])

            for comment in comments:
                comment_id = comment.get("objectID", "")

                # Skip if we've already added this comment from a previous keyword
                if comment_id in seen_comment_ids:
                    continue
                seen_comment_ids.add(comment_id)

                text = comment.get("comment_text", "") or ""

                job = make_job(
                    user_id=user_id,
                    title=keyword,
                    company="See description",
                    location="See description",
                    description=text[:2000],
                    url=f"https://news.ycombinator.com/item?id={comment_id}",
                    source="hn_hiring",
                )
                jobs.append(job)

            if len(jobs) >= MAX_JOBS_PER_SOURCE:
                break

        print(f"  ✅ HN Who is Hiring: found {len(jobs)} relevant comments")

    except httpx.TimeoutException:
        print("  ⚠️  HN: request timed out")
    except httpx.HTTPStatusError as e:
        print(f"  ⚠️  HN: HTTP error {e.response.status_code}")
    except Exception as e:
        print(f"  ⚠️  HN: unexpected error — {e}")

    return jobs


# ---------------------------------------------------------------------------
# SOURCE 2 — Wellfound (AngelList)
# ---------------------------------------------------------------------------

def scrape_wellfound(user_id: str) -> list[Job]:
    """
    Fetches AI Engineering jobs from Wellfound (formerly AngelList Talent).

    WHY WELLFOUND?
    Wellfound is the go-to job board for funded startups. Most AI-first
    startups post here. It has a partial public API we can use safely.

    NOTE ON RATE LIMITING:
    Wellfound's public endpoints tolerate reasonable request rates.
    We add a small delay and limit results to stay well within limits.

    WHAT YOU'RE LEARNING:
    - Query parameters in HTTP requests (params dict in httpx)
    - Handling paginated APIs (we only fetch page 1 for now)
    - Defensive coding with .get() — never assume a key exists in API responses
    """
    print("  📡 Scraping Wellfound...")
    jobs = []

    try:
        # Wellfound's job search endpoint
        # role_types[]=full_time filters for full-time roles
        base_url = "https://wellfound.com/jobs"

        # We'll search for each keyword separately and combine results
        for keyword in JOB_SEARCH_KEYWORDS[:3]:  # limit to top 3 to avoid hammering
            params = {
                "q": keyword,
                "remote": "true",
            }

            headers = {
                # Identify ourselves honestly — some sites block default httpx UA
                "User-Agent": "Mozilla/5.0 (compatible; job-search-bot/1.0)",
                "Accept": "application/json",
            }

            response = httpx.get(
                base_url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()

            # Wellfound returns HTML for browser requests, JSON for API requests
            # If we get HTML back, we'll handle that with Apify instead
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                print(f"  ℹ️  Wellfound returned HTML (not JSON) for '{keyword}' — will use Apify")
                break

            data = response.json()
            listings = data.get("jobs", data.get("results", []))

            for item in listings[:MAX_JOBS_PER_SOURCE]:
                job = make_job(
                    user_id=user_id,
                    title=item.get("title", ""),
                    company=item.get("startup", {}).get("name", "Unknown"),
                    location=item.get("location", "Remote"),
                    description=item.get("description", "")[:2000],
                    url=f"https://wellfound.com{item.get('slug', '')}",
                    source="wellfound",
                )
                jobs.append(job)

            if len(jobs) >= MAX_JOBS_PER_SOURCE:
                break

        print(f"  ✅ Wellfound: found {len(jobs)} jobs")

    except httpx.TimeoutException:
        print("  ⚠️  Wellfound: request timed out")
    except httpx.HTTPStatusError as e:
        print(f"  ⚠️  Wellfound: HTTP error {e.response.status_code}")
    except Exception as e:
        print(f"  ⚠️  Wellfound: unexpected error — {e}")

    return jobs

# ---------------------------------------------------------------------------
# SOURCE 2.5 — Greenhouse as Wellfound alternate
# ---------------------------------------------------------------------------

def scrape_greenhouse(user_id: str) -> list[Job]:
    """
    Fetches AI Engineering jobs from Greenhouse-powered company job boards.

    WHY GREENHOUSE?
    Greenhouse is an ATS (Applicant Tracking System) used by hundreds of
    AI-first startups. Every company on Greenhouse exposes a public JSON API
    at: https://boards-api.greenhouse.io/v1/boards/{company}/jobs

    This is completely official — Greenhouse publishes this API for exactly
    this use case. Zero scraping risk, zero auth needed.

    COMPANIES WE TARGET:
    A curated list of AI-first companies known to use Greenhouse.
    We can expand this list anytime — it's just strings.

    WHAT YOU'RE LEARNING:
    - Calling multiple endpoints in a loop
    - Graceful degradation — if one company's board fails, we continue
    - How ATS APIs work (useful real-world knowledge)
    """
    print("  📡 Scraping Greenhouse job boards...")
    jobs = []

    # AI-first companies that use Greenhouse
    # Format is their Greenhouse "board token" — usually their company name
    # Find more at: https://boards.greenhouse.io/{company}
    greenhouse_companies = [
        "huggingface",
        "cohere",
        "anthropic",
        "mistral",
        "perplexity",
        "together",
        "modal",
        "replicate",
        "scale",
        "labelbox",
        "weights-biases",
        "moveworks",
        "glean",
        "hebbia",
        "aisera",
        "observe",
        "cresta",
        "sierra",
    ]

    base_url = "https://boards-api.greenhouse.io/v1/boards"

    for company in greenhouse_companies:
        try:
            url = f"{base_url}/{company}/jobs"
            params = {"content": "true"}  # include job description in response

            response = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            data = response.json()
            listings = data.get("jobs", [])

            for item in listings:
                title = item.get("title", "")

                # Filter by our keywords
                is_relevant = any(
                    keyword.lower() in title.lower()
                    for keyword in JOB_SEARCH_KEYWORDS
                )
                if not is_relevant:
                    continue

                # Location — Greenhouse nests this
                location_obj = item.get("location", {})
                location = location_obj.get("name", "See listing") if location_obj else "See listing"

                # Description — strip basic HTML tags if present
                description = item.get("content", "") or ""
                description = description[:2000]

                job = make_job(
                    user_id=user_id,
                    title=title,
                    company=company.replace("-", " ").title(),
                    location=location,
                    description=description,
                    url=item.get("absolute_url", ""),
                    source="greenhouse",
                )
                jobs.append(job)

        except httpx.HTTPStatusError:
            # Some companies may have changed their board token — skip silently
            pass
        except Exception:
            pass

    print(f"  ✅ Greenhouse: found {len(jobs)} relevant jobs")
    return jobs

# ---------------------------------------------------------------------------
# SOURCE 3 — Apify (LinkedIn, Naukri, IimJobs)
# ---------------------------------------------------------------------------

def scrape_via_apify(user_id: str, keyword: str) -> list[Job]:
    """
    Uses Apify to scrape LinkedIn job listings.

    WHY APIFY FOR LINKEDIN?
    LinkedIn actively blocks direct scraping. Apify runs headless browsers
    with rotating residential proxies — we never touch LinkedIn directly.
    Our app calls Apify's API; Apify handles the scraping risk.

    APIFY ACTOR:
    We use the 'curious_coder/linkedin-jobs-scraper' actor.
    An "actor" in Apify is a pre-built scraper you can call via API.

    COST AWARENESS:
    Each Apify run consumes compute units from your account.
    We only call this when free sources return < MIN_JOBS_BEFORE_APIFY jobs.

    WHAT YOU'RE LEARNING:
    - The Apify Python SDK (ApifyClient)
    - How to run an Apify Actor and wait for results
    - The actor.call() pattern — starts the actor and blocks until done
    """
    print(f"  📡 Scraping LinkedIn via Apify for '{keyword}'...")
    jobs = []

    if not APIFY_API_TOKEN:
        print("  ⚠️  Apify: APIFY_API_TOKEN not set — skipping")
        return jobs

    try:
        client = ApifyClient(APIFY_API_TOKEN)

        # Run the LinkedIn Jobs Scraper actor
        # Each actor has a unique ID — this one is maintained by Apify
        run_input = {
            "queries": [f"{keyword} Bengaluru OR Remote"],
            "maxResults": MAX_JOBS_PER_SOURCE,
            "proxy": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],  # residential IPs = lower ban risk
            },
        }

        # actor("actor-id").call() runs the actor and waits for it to finish
        # This is synchronous — it blocks until the scrape is complete
        run = client.actor("curious_coder/linkedin-jobs-scraper").call(
            run_input=run_input
        )

        # Results are stored in Apify's dataset — fetch them
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            job = make_job(
                user_id=user_id,
                title=item.get("title", ""),
                company=item.get("companyName", "Unknown"),
                location=item.get("location", ""),
                description=item.get("description", "")[:2000],
                url=item.get("url", item.get("link", "")),
                source="linkedin_apify",
            )
            jobs.append(job)

        print(f"  ✅ Apify/LinkedIn: found {len(jobs)} jobs for '{keyword}'")

    except Exception as e:
        print(f"  ⚠️  Apify: error — {e}")

    return jobs


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def scrape_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the ScrapeAgent.

    This is the function registered as a node in graph/graph.py:
        workflow.add_node("scrape", scrape_agent)

    CONCEPT — Node function contract:
    - INPUT:  receives the full AgentState
    - OUTPUT: returns a DICT with only the keys it wants to update
              (NOT the full state — LangGraph merges this dict into state)

    The function:
    1. Tries free sources first (YC Jobs, Wellfound)
    2. Falls back to Apify if not enough results
    3. Deduplicates across all sources
    4. Returns jobs_found and updated pipeline_status
    """
    print("\n🔍 ScrapeAgent starting...")

    user_id = state["user_id"]
    all_jobs: list[Job] = []

    # --- Step 1: Free sources ---
    yc_jobs = scrape_yc_jobs(user_id)
    all_jobs.extend(yc_jobs)

    greenhouse_jobs = scrape_greenhouse(user_id)
    all_jobs.extend(greenhouse_jobs)

    # --- Step 2: Apify fallback ---
    # Only invoke Apify if free sources didn't return enough
    if len(all_jobs) < MIN_JOBS_BEFORE_APIFY:
        print(f"\n  ℹ️  Only {len(all_jobs)} jobs from free sources — invoking Apify fallback")
        for keyword in JOB_SEARCH_KEYWORDS[:2]:  # top 2 keywords only to manage cost
            apify_jobs = scrape_via_apify(user_id, keyword)
            all_jobs.extend(apify_jobs)
    else:
        print(f"\n  ✅ {len(all_jobs)} jobs from free sources — Apify not needed this run")

    # --- Step 3: Deduplicate ---
    unique_jobs = deduplicate_jobs(all_jobs)

    print(f"\n✅ ScrapeAgent complete — {len(unique_jobs)} unique jobs found")

    # --- Step 4: Return state update ---
    # IMPORTANT: we only return the keys we're updating.
    # LangGraph merges this dict into the existing state.
    # Because jobs_found uses Annotated[list, operator.add],
    # these jobs get APPENDED to any existing jobs_found list.
    return {
        "jobs_found": unique_jobs,
        "pipeline_status": "running",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }