# agents/contact_finder_agent.py
#
# The ContactFinderAgent finds hiring managers and founders at target companies.
# It runs after both ScrapeAgent and FundingIntelAgent, and operates on two
# input sources:
#   1. Companies from FundingIntelAgent (cold outreach targets)
#   2. Companies from scored jobs in ScoringAgent (warm application targets)
#
# FOR EACH COMPANY IT:
#   1. Uses Tavily to search for the company's LinkedIn page and key people
#   2. Uses Proxycurl to fetch full profile data (if Proxycurl key is set)
#   3. Uses Hunter.io to find and verify email addresses
#   4. Returns a list of Contact objects ready for OutreachAgent
#
# CONCEPT — Why find contacts at all?
# Applying through a job portal puts you in a queue with hundreds of others.
# A personalised email directly to the hiring manager or CTO bypasses the
# queue entirely. Response rates for good cold emails are 10-30% vs <5%
# for portal applications. This is the highest-leverage part of the pipeline.

import uuid
from datetime import datetime, timezone

import httpx
from tavily import TavilyClient

from graph.state import AgentState, ScoredJob, Company, Contact
from config.settings import (
    TAVILY_API_KEY,
    PROXYCURL_API_KEY,
    HUNTER_API_KEY,
    is_placeholder,
)

import re


# ---------------------------------------------------------------------------
# CLIENTS
# ---------------------------------------------------------------------------

tavily = TavilyClient(api_key=TAVILY_API_KEY)

# HTTP timeout for all external calls
REQUEST_TIMEOUT = 10

def normalise_linkedin_url(url: str) -> str:
    """
    Normalises LinkedIn URLs to the format Proxycurl requires.

    Proxycurl only accepts: https://www.linkedin.com/in/slug
    Tavily often returns regional variants like:
      https://in.linkedin.com/in/slug   (India)
      https://uk.linkedin.com/in/slug   (UK)
      https://www.linkedin.com/in/slug/ (trailing slash)

    We strip the regional subdomain and trailing slash.
    """
    import re
    # Replace any regional subdomain with www
    url = re.sub(r'https://[a-z]{2}\.linkedin\.com', 'https://www.linkedin.com', url)
    # Remove trailing slash
    url = url.rstrip("/")
    # Remove query parameters
    url = url.split("?")[0]
    return url

# ---------------------------------------------------------------------------
# TARGET TITLES
# These are the job titles we look for at each company.
# Order matters — we prefer founders/CTOs over generic engineering managers.
# ---------------------------------------------------------------------------

TARGET_TITLES = [
    "Co-founder",
    "Founder",
    "CTO",
    "Chief Technology Officer",
    "VP Engineering",
    "Head of Engineering",
    "Head of AI",
    "AI Lead",
    "Engineering Manager",
    "Hiring Manager",
]


# ---------------------------------------------------------------------------
# STEP 1 — Find LinkedIn Info via Tavily
# ---------------------------------------------------------------------------

def find_linkedin_profile(company_name: str) -> dict:
    """
    Uses Tavily to find a key person's LinkedIn profile at a company.
    Returns a dict with url, name, and title extracted from the page title.

    LinkedIn page titles follow the pattern:
    "Firstname Lastname - Job Title - Company | LinkedIn"
    We parse this directly from the Tavily result title.
    """
    for title_query in TARGET_TITLES[:4]:
        query = f'"{company_name}" {title_query} site:linkedin.com/in'
        try:
            response = tavily.search(
                query=query,
                search_depth="basic",
                max_results=3,
            )
            for result in response.get("results", []):
                url = result.get("url", "")
                if "linkedin.com/in/" not in url:
                    continue

                # Extract name and title from the page title
                # Format: "Name - Title - Company | LinkedIn"
                page_title = result.get("title", "")
                extracted_name = ""
                extracted_title = ""

                if " - " in page_title:
                    parts = [p.strip() for p in page_title.split(" - ")]
                    # Remove "| LinkedIn" or "| LinkedIn Profile" suffix from last part
                    parts[-1] = parts[-1].replace("| LinkedIn", "").replace("LinkedIn", "").strip()
                    # Remove empty parts
                    parts = [p for p in parts if p]

                    # Format: "Name - Title - Company | LinkedIn" (3+ parts)
                    # Format: "Name - Company | LinkedIn" (2 parts — no title available)
                    extracted_name = parts[0].strip()
                    if len(parts) >= 3:
                        extracted_title = parts[1].strip()
                    else:
                        extracted_title = ""  # don't use company name as title

                return {
                    "url": url,
                    "name": extracted_name,
                    "title": extracted_title,
                }
        except Exception:
            continue

    return {"url": "", "name": "", "title": ""}


# ---------------------------------------------------------------------------
# STEP 2 — Fetch full profile via Proxycurl (optional)
# ---------------------------------------------------------------------------

def fetch_proxycurl_profile(linkedin_url: str) -> dict:
    """
    Fetches full LinkedIn profile data using the Proxycurl API.

    CONCEPT — When to use Proxycurl vs Tavily
    Tavily finds the LinkedIn URL (cheap, ~1 credit).
    Proxycurl fetches the full profile — name, title, email, experience (~1 credit).
    We only call Proxycurl if:
      a) We found a LinkedIn URL via Tavily
      b) PROXYCURL_API_KEY is configured

    This two-step approach minimises cost — we only pay for Proxycurl
    when we have a valid URL to fetch.

    Returns a dict with profile data, or empty dict if unavailable.
    """
    if not PROXYCURL_API_KEY or not linkedin_url:
        return {}

    try:
        response = httpx.get(
            "https://nubela.co/proxycurl/api/v2/linkedin",
            params={
                "linkedin_profile_url": linkedin_url,
                "personal_email": "include",   # ask Proxycurl to find their email
                "personal_contact_number": "exclude",
            },
            headers={"Authorization": f"Bearer {PROXYCURL_API_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"    ⚠️  Proxycurl error: {e}")
        return {}


# ---------------------------------------------------------------------------
# STEP 3 — Find email via Hunter.io
# ---------------------------------------------------------------------------

def find_email_hunter(
    first_name: str,
    last_name: str,
    company_domain: str
) -> str:
    """
    Uses Hunter.io to find and verify a professional email address.

    CONCEPT — How Hunter.io works
    Hunter.io has indexed millions of professional email addresses.
    Given a name + company domain, it predicts the email format
    (e.g. first.last@company.com) and verifies it's deliverable.

    We only call Hunter if we have both a name and a domain.
    An unverified email is worse than no email — it hurts sender reputation.

    Returns verified email string, or empty string if not found.
    """
    if is_placeholder(HUNTER_API_KEY) or not first_name or not company_domain:
        return ""

    try:
        response = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain": company_domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": HUNTER_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        email_data = data.get("data", {})
        email = email_data.get("email", "")
        confidence = email_data.get("score", 0)

        # Only return emails with confidence >= 70%
        # Low-confidence emails are likely to bounce
        if email and confidence >= 70:
            return email

    except Exception as e:
        print(f"    ⚠️  Hunter.io error: {e}")

    return ""


# ---------------------------------------------------------------------------
# HELPER — Extract domain from company name or URL
# ---------------------------------------------------------------------------

def extract_domain(company_name: str, source_url: str = "") -> str:
    """
    Uses Tavily to find the real company domain rather than guessing.

    Searches for '{company_name} contact email' which reliably surfaces
    the company's official website or contact page in the top results.
    We extract the domain from the first result that isn't a known
    aggregator site.

    Falls back to string manipulation if Tavily finds nothing useful.
    """
    AGGREGATOR_DOMAINS = [
        "linkedin.com", "crunchbase.com", "tracxn.com",
        "entrackr.com", "techcrunch.com", "twitter.com",
        "glassdoor.com", "indeed.com", "ambitionbox.com",
        "zoominfo.com", "apollo.io",
    ]

    try:
        response = tavily.search(
            query=f"{company_name} contact email",
            search_depth="basic",
            max_results=5,
        )
        for result in response.get("results", []):
            url = result.get("url", "")
            if not url:
                continue
            from urllib.parse import urlparse
            parsed = urlparse(url)
            # Strip www and other subdomains (docs., app., api., etc.)
            netloc = parsed.netloc
            parts = netloc.split(".")
            # Keep only last two parts: sarvam.ai, not docs.sarvam.ai
            if len(parts) > 2:
                domain = ".".join(parts[-2:])
            else:
                domain = netloc.replace("www.", "")
            # Skip aggregators — we want the company's own domain
            if not any(agg in domain for agg in AGGREGATOR_DOMAINS):
                return domain
    except Exception:
        pass

    # Fallback — simple string cleanup (last resort)
    domain_guess = company_name.lower()
    domain_guess = domain_guess.replace("@", "").replace(" ", "").replace("-", "")
    domain_guess = "".join(c for c in domain_guess if c.isalnum())
    return f"{domain_guess}.com" if domain_guess else ""


# ---------------------------------------------------------------------------
# FIND CONTACT FOR ONE COMPANY
# ---------------------------------------------------------------------------

def find_contact_for_company(
    company_name: str,
    source_url: str,
    user_id: str,
    company_id: str,
    job_id: str = "",
) -> Contact | None:
    """
    Orchestrates the three-step contact discovery process for one company.

    Step 1: Tavily → find LinkedIn URL
    Step 2: Proxycurl → fetch full profile (if URL found)
    Step 3: Hunter.io → find email (if name + domain available)

    Returns a Contact object, or None if we couldn't find useful data.
    """
    print(f"    🔍 Finding contact at {company_name}...")

    # Step 1 — LinkedIn URL
    profile_result = find_linkedin_profile(company_name)
    linkedin_url = normalise_linkedin_url(profile_result["url"]) if profile_result["url"] else ""
    name = profile_result["name"]
    title = profile_result["title"]

    if linkedin_url:
        print(f"    ✅ Found LinkedIn: {linkedin_url[:60]}...")
        if name:
            print(f"    ✅ Name from Tavily title: {name} — {title}")
    else:
        print(f"    ➖ No LinkedIn URL found for {company_name}")

    # Step 2 — Enrich with Proxycurl if available (overrides Tavily data)
    first_name = ""
    last_name = ""

    if linkedin_url and not is_placeholder(PROXYCURL_API_KEY):
        profile = fetch_proxycurl_profile(linkedin_url)
        if profile:
            # Proxycurl overrides Tavily name/title if available — more reliable
            px_first = profile.get("first_name", "")
            px_last = profile.get("last_name", "")
            if px_first:
                first_name = px_first
                last_name = px_last
                name = f"{px_first} {px_last}".strip()
            if profile.get("occupation"):
                title = profile.get("occupation", "")
            print(f"    ✅ Proxycurl enriched: {name} — {title}")

    # Last resort — extract from URL slug if we still have no name
    if not name and linkedin_url and "linkedin.com/in/" in linkedin_url:
        slug = linkedin_url.split("linkedin.com/in/")[-1].strip("/").split("?")[0]
        slug_clean = re.sub(r'\d+$', '', slug)
        parts = slug_clean.replace("-", " ").split()
        if len(parts) >= 2 and len(parts[-1]) > 1:
            first_name = parts[0].capitalize()
            last_name = parts[-1].capitalize()
            name = f"{first_name} {last_name}"
            print(f"    ℹ️  Name from slug (last resort): {name}")

    # Step 3 — Email via Hunter.io
    domain = extract_domain(company_name, source_url)
    email = ""
    # Split name into first/last for Hunter.io
    if name and " " in name:
        name_parts = name.split()
        first_name = name_parts[0]
        last_name = name_parts[-1]
    elif name:
        first_name = name
        last_name = ""
        
    if first_name and domain:
        # Skip single-character last names — Hunter.io rejects them
        clean_last = last_name if len(last_name) > 1 else ""
        email = find_email_hunter(first_name, clean_last, domain)
        if email:
            print(f"    ✅ Hunter.io: {email}")

    # Only return a contact if we have at least a LinkedIn URL or email
    if not linkedin_url and not email:
        print(f"    ➖ Skipping {company_name} — no contact data found")
        return None

    return Contact(
        id=str(uuid.uuid4()),
        user_id=user_id,
        company_id=company_id,
        name=name or "See LinkedIn",
        title=title or "See LinkedIn",
        email=email,
        linkedin_url=linkedin_url,
        source="tavily" if not PROXYCURL_API_KEY else "proxycurl",
    )


# ---------------------------------------------------------------------------
# FIND MULTIPLE CONTACTS FOR ONE COMPANY (NEW)
# ---------------------------------------------------------------------------

def find_multiple_contacts_for_company(
    company_name: str,
    source_url: str,
    user_id: str,
    company_id: str,
    job_id: str = "",
    max_contacts: int = 4,  # Find up to 4 people per company
) -> list[Contact]:
    """
    Finds multiple diverse contacts at a company (3-5 people with different roles).
    
    Instead of returning 1 contact, this searches for different target roles:
      1. Founder/Co-founder
      2. CTO/VP Engineering
      3. Head of AI / AI Lead
      4. Hiring Manager / Engineering Manager
      5. (Optional) People Lead / HR
    
    WHY MULTIPLE CONTACTS?
    - Increases chance of reaching someone with decision-making power
    - Different roles respond to different angles:
      * Founder: "You're solving X problem, here's how I can help"
      * CTO: "Your tech stack is X, I have experience with Y"
      * Hiring Manager: "I'm interested in this role you're hiring for"
    - Reduces risk if one person ignores your email
    
    RETURNS: List of Contact objects (could be 0-4 depending on what's found)
    """
    print(f"    🔍 Finding contacts at {company_name} (target: {max_contacts} people)...")
    
    contacts = []
    found_titles = set()  # Track which titles we've already found to avoid duplicates
    
    # Try each target title in order, but keep going until we have max_contacts
    for target_title in TARGET_TITLES:
        if len(contacts) >= max_contacts:
            break
        
        # Skip if we already found someone with this title
        if any(target_title.lower() in title.lower() for title in found_titles):
            continue
        
        # Also check if we already have this LinkedIn URL
        if any(url == c.linkedin_url for c in contacts):
            continue
        
        query = f'"{company_name}" {target_title} site:linkedin.com/in'
        try:
            response = tavily.search(
                query=query,
                search_depth="basic",
                max_results=3,  # Try top 3 results
            )
            for result in response.get("results", []):
                if len(contacts) >= max_contacts:
                    break
                    
                url = result.get("url", "")
                if "linkedin.com/in/" not in url:
                    continue
                
                # Extract name and title from page title
                page_title = result.get("title", "")
                extracted_name = ""
                extracted_title = ""
                
                if " - " in page_title:
                    parts = [p.strip() for p in page_title.split(" - ")]
                    parts[-1] = parts[-1].replace("| LinkedIn", "").replace("LinkedIn", "").strip()
                    parts = [p for p in parts if p]
                    
                    extracted_name = parts[0].strip()
                    if len(parts) >= 3:
                        extracted_title = parts[1].strip()
                
                linkedin_url = normalise_linkedin_url(url)
                name = extracted_name
                title = extracted_title
                
                # Step 2 — Enrich with Proxycurl
                first_name = ""
                last_name = ""
                
                if linkedin_url and not is_placeholder(PROXYCURL_API_KEY):
                    profile = fetch_proxycurl_profile(linkedin_url)
                    if profile:
                        px_first = profile.get("first_name", "")
                        px_last = profile.get("last_name", "")
                        if px_first:
                            first_name = px_first
                            last_name = px_last
                            name = f"{px_first} {px_last}".strip()
                        if profile.get("occupation"):
                            title = profile.get("occupation", "")
                
                # Extract name from slug as fallback
                if not name and linkedin_url and "linkedin.com/in/" in linkedin_url:
                    slug = linkedin_url.split("linkedin.com/in/")[-1].strip("/").split("?")[0]
                    slug_clean = re.sub(r'\d+$', '', slug)
                    parts = slug_clean.replace("-", " ").split()
                    if len(parts) >= 2 and len(parts[-1]) > 1:
                        first_name = parts[0].capitalize()
                        last_name = parts[-1].capitalize()
                        name = f"{first_name} {last_name}"
                
                # Step 3 — Email via Hunter.io
                domain = extract_domain(company_name, source_url)
                email = ""
                if name and " " in name:
                    name_parts = name.split()
                    first_name = name_parts[0]
                    last_name = name_parts[-1]
                elif name:
                    first_name = name
                    last_name = ""
                
                if first_name and domain:
                    clean_last = last_name if len(last_name) > 1 else ""
                    email = find_email_hunter(first_name, clean_last, domain)
                
                # Only add if we have at least LinkedIn URL or email
                if linkedin_url or email:
                    contact = Contact(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        company_id=company_id,
                        name=name or "See LinkedIn",
                        title=title or "See LinkedIn",
                        email=email,
                        linkedin_url=linkedin_url,
                        source="tavily" if not PROXYCURL_API_KEY else "proxycurl",
                    )
                    contacts.append(contact)
                    found_titles.add(contact.title or "")
                    print(f"      ✅ Found: {name} — {title}")
                    break  # Move to next target_title
        
        except Exception as e:
            print(f"      ⚠️  Error searching for {target_title}: {e}")
            continue
    
    if contacts:
        print(f"    ✅ Found {len(contacts)} contacts at {company_name}")
    else:
        print(f"    ➖ No contacts found at {company_name}")
    
    return contacts


# ---------------------------------------------------------------------------
# MAIN NODE FUNCTION
# ---------------------------------------------------------------------------

def contact_finder_agent(state: AgentState) -> dict:
    """
    LangGraph node function for the ContactFinderAgent.

    Processes two input lists from state:
      1. funded_companies — from FundingIntelAgent (cold outreach targets)
      2. jobs_scored — from ScoringAgent (warm application targets,
         recommended jobs only)

    For each company, runs the three-step contact discovery process.

    CONCEPT — Why process both funded companies AND scored jobs?
    Funded companies = proactive cold outreach ("I see you just raised,
    here's how I can help you grow your AI team")

    Scored jobs = targeted application outreach ("I'm applying for this
    specific role and wanted to reach out directly to the hiring manager")

    Both are valuable but require slightly different outreach angles.
    The OutreachAgent will handle the personalisation.
    """
    print("\n👤 ContactFinderAgent starting...")

    user_id = state["user_id"]
    contacts: list[Contact] = []

    # --- Source 1: Funded companies (cold outreach) ---
    funded_companies = state.get("funded_companies", [])
    print(f"\n  Processing {len(funded_companies)} funded companies...")

    for company in funded_companies[:10]:
        company_contacts = find_multiple_contacts_for_company(
            company_name=company["name"],
            source_url=company["source_url"],
            user_id=user_id,
            company_id=company["id"],
            max_contacts=4,  # Find up to 4 people per company
        )
        contacts.extend(company_contacts)  # Add all found contacts

    # --- Source 2: Recommended scored jobs (warm outreach) ---
    scored_jobs = state.get("jobs_scored", [])
    recommended = [j for j in scored_jobs if j["recommended"]]
    print(f"\n  Processing {len(recommended)} recommended jobs...")

    for scored_job in recommended[:5]:
        job = scored_job["job"]
        job_contacts = find_multiple_contacts_for_company(
            company_name=job["company"],
            source_url=job["url"],
            user_id=user_id,
            company_id="",
            job_id=job["id"],
            max_contacts=3,  # Find up to 3 people per job posting
        )
        contacts.extend(job_contacts)  # Add all found contacts

    print(f"\n✅ ContactFinderAgent complete — {len(contacts)} contacts found")

    return {
        "contacts_found": contacts,
        "pipeline_status": "running",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }