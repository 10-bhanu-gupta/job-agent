# tools/gmail_sender.py
#
# Gmail API integration for sending approved cold emails.
#
# CONCEPT — OAuth 2.0 flow
# Gmail API uses OAuth 2.0 for authentication. The flow is:
#   1. First run: opens browser, you log in and grant permission
#   2. Google returns a token, saved to gmail_token.json
#   3. Every subsequent run: loads token from file, refreshes if expired
#   4. No browser needed after the first time
#
# CONCEPT — Why Desktop app OAuth vs Service Account?
# Service accounts are for server-to-server auth (no human involved).
# Desktop OAuth is for "act on behalf of a human's Gmail account".
# Since we're sending from YOUR Gmail, Desktop OAuth is correct.
#
# SENDING SAFETY:
#   - Hard cap of MAX_EMAILS_PER_DAY
#   - Randomised delay between sends (EMAIL_SEND_DELAY_MIN/MAX seconds)
#   - Email verification before sending (checks contact has email)
#   - Dry run mode for testing without actually sending

import os
import time
import random
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.settings import (
    EMAIL_SEND_DELAY_MIN,
    EMAIL_SEND_DELAY_MAX,
    MAX_EMAILS_PER_DAY,
)

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

CREDENTIALS_FILE = Path("config/gmail_credentials.json")
TOKEN_FILE       = Path("config/gmail_token.json")

# Gmail API scope — send only, no read access needed
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Sender email — your secondary Gmail account
# Set this in .env as GMAIL_SENDER_EMAIL
SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "")


# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------

def get_gmail_service():
    """
    Authenticates with Gmail API and returns a service object.

    CONCEPT — Token caching
    The first time this runs, it opens a browser for OAuth consent.
    After that, the token is saved to gmail_token.json and reused.
    The token auto-refreshes when it expires (every ~1 hour).

    Returns a Gmail API service object, or None if credentials missing.
    """
    if not CREDENTIALS_FILE.exists():
        print("  ⚠️  gmail_credentials.json not found — Gmail sending disabled")
        print("  ℹ️  Follow setup instructions in tools/gmail_sender.py")
        return None

    creds = None

    # Load existing token if available
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If no valid credentials, run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired — refresh silently
            creds.refresh(Request())
        else:
            # First time — open browser for consent
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# BUILD EMAIL MESSAGE
# ---------------------------------------------------------------------------

def build_message(
    to_email: str,
    subject: str,
    body: str,
    sender: str = None,
) -> dict:
    """
    Builds a Gmail API message object from email components.

    CONCEPT — MIME format
    Emails are sent in MIME format (Multipurpose Internet Mail Extensions).
    MIMEMultipart allows both plain text and HTML versions.
    We send plain text only — simpler, less likely to trigger spam filters,
    and more personal-feeling for cold outreach.

    The message must be base64-encoded for the Gmail API.
    """
    sender = sender or SENDER_EMAIL

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"]    = sender
    message["To"]      = to_email

    # Plain text part
    text_part = MIMEText(body, "plain")
    message.attach(text_part)

    # Encode to base64 as required by Gmail API
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": encoded}


# ---------------------------------------------------------------------------
# SEND SINGLE EMAIL
# ---------------------------------------------------------------------------

def send_email(
    service,
    to_email: str,
    subject: str,
    body: str,
    dry_run: bool = False,
) -> bool:
    """
    Sends a single email via Gmail API.

    Args:
        service:   Gmail API service object from get_gmail_service()
        to_email:  recipient email address
        subject:   email subject line
        body:      plain text email body
        dry_run:   if True, logs but does not actually send

    Returns:
        True if sent successfully, False otherwise

    CONCEPT — dry_run mode
    Always test with dry_run=True first. This lets you verify the
    email content and recipient without actually sending anything.
    Only switch to dry_run=False when you're confident in the output.
    """
    if dry_run:
        print(f"  [DRY RUN] Would send to: {to_email}")
        print(f"  [DRY RUN] Subject: {subject}")
        return True

    if not service:
        print("  ⚠️  Gmail service not available — skipping send")
        return False

    if not to_email:
        print("  ⚠️  No recipient email — skipping")
        return False

    try:
        message = build_message(to_email, subject, body)
        service.users().messages().send(
            userId="me",
            body=message
        ).execute()
        print(f"  ✅ Sent to {to_email} — {subject[:50]}...")
        return True

    except HttpError as e:
        print(f"  ⚠️  Gmail API error sending to {to_email}: {e}")
        return False
    except Exception as e:
        print(f"  ⚠️  Unexpected error sending to {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# BATCH SEND — the main function called from the dashboard
# ---------------------------------------------------------------------------

def send_approved_emails(
    drafts: list[dict],
    dry_run: bool = False,
) -> dict:
    """
    Sends all approved email drafts with rate limiting.

    This is called from the Streamlit dashboard when you click
    "Send All Approved". It:
    1. Authenticates with Gmail
    2. Filters drafts that have an email address
    3. Sends each one with a randomised delay
    4. Returns a summary of sent/skipped/failed

    Args:
        drafts:  list of dicts with keys:
                 id, email, subject, body, contact_name
        dry_run: if True, logs but does not send

    Returns:
        dict with sent, skipped, failed counts and list of sent IDs

    CONCEPT — Rate limiting with randomised delays
    Sending 13 emails in 13 seconds looks like spam to Gmail's systems.
    Randomised delays (2-5 minutes) between sends mimic human behaviour
    and protect your sender reputation.
    For a daily batch of ~10 emails, total send time is 20-50 minutes.
    We return immediately and update statuses as sends complete.
    """
    results = {
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "sent_ids": [],
        "skipped_ids": [],
    }

    # Cap at daily limit
    sendable = [d for d in drafts if d.get("email")]
    no_email = [d for d in drafts if not d.get("email")]

    results["skipped"] = len(no_email)
    results["skipped_ids"] = [d["id"] for d in no_email]

    if not sendable:
        print("  ⚠️  No drafts with email addresses — nothing to send")
        print(f"  ℹ️  {len(no_email)} drafts have no email (LinkedIn DM only)")
        return results

    # Enforce daily cap
    if len(sendable) > MAX_EMAILS_PER_DAY:
        print(f"  ⚠️  {len(sendable)} emails exceeds daily cap of {MAX_EMAILS_PER_DAY}")
        print(f"  ℹ️  Sending first {MAX_EMAILS_PER_DAY} only")
        sendable = sendable[:MAX_EMAILS_PER_DAY]

    # Authenticate
    service = get_gmail_service() if not dry_run else None

    print(f"\n📧 Sending {len(sendable)} emails{'(DRY RUN)' if dry_run else ''}...")
    print(f"   Estimated time: {len(sendable) * EMAIL_SEND_DELAY_MIN // 60}-{len(sendable) * EMAIL_SEND_DELAY_MAX // 60} minutes")

    for i, draft in enumerate(sendable, 1):
        contact_name = draft.get("contact_name", "Unknown")
        print(f"\n  [{i}/{len(sendable)}] {contact_name} <{draft['email']}>")

        success = send_email(
            service=service,
            to_email=draft["email"],
            subject=draft["subject"],
            body=draft["body"],
            dry_run=dry_run,
        )

        if success:
            results["sent"] += 1
            results["sent_ids"].append(draft["id"])
        else:
            results["failed"] += 1

        # Rate limiting delay between sends (skip after last email)
        if i < len(sendable):
            delay = random.randint(EMAIL_SEND_DELAY_MIN, EMAIL_SEND_DELAY_MAX)
            print(f"  ⏳ Waiting {delay}s before next send...")
            if not dry_run:
                time.sleep(delay)

    print(f"\n✅ Batch send complete")
    print(f"   Sent    : {results['sent']}")
    print(f"   Skipped : {results['skipped']} (no email address)")
    print(f"   Failed  : {results['failed']}")

    return results