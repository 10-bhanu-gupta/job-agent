# dashboard/pages_companies.py

import streamlit as st
import pandas as pd
from db.database import get_db
from db.models import CompanyRecord, ContactRecord


@st.cache_data(ttl=60)
def load_companies():
    with get_db() as db:
        companies = db.query(CompanyRecord).order_by(
            CompanyRecord.created_at.desc()
        ).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "funding_stage": c.funding_stage,
                "amount_raised": c.amount_raised,
                "funding_date": c.funding_date,
                "source_url": c.source_url,
                "notes": c.notes or "",
            }
            for c in companies
        ]


@st.cache_data(ttl=60)
def load_contacts():
    with get_db() as db:
        contacts = db.query(ContactRecord).all()
        return {
            c.company_id: {
                "name": c.name,
                "title": c.title,
                "email": c.email,
                "linkedin_url": c.linkedin_url,
            }
            for c in contacts
            if c.company_id
        }


def render_companies_page():
    st.title("🏢 Companies")
    st.markdown("Recently funded AI companies — your cold outreach targets.")
    st.markdown("---")

    companies = load_companies()
    contacts_map = load_contacts()

    if not companies:
        st.info("No companies yet — run the pipeline to discover funded companies.")
        return

    for company in companies:
        contact = contacts_map.get(company["id"])
        contact_label = f"👤 {contact['name']}" if contact else "👤 No contact found"

        with st.expander(
            f"**{company['name']}** — {company['funding_stage']} {company['amount_raised']}  |  {contact_label}"
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Stage:** {company['funding_stage']}")
                st.markdown(f"**Raised:** {company['amount_raised']}")
                st.markdown(f"**Date:** {company['funding_date']}")
                if company["source_url"]:
                    st.markdown(f"[Source article ↗]({company['source_url']})")
            with col2:
                if contact:
                    st.markdown(f"**Contact:** {contact['name']}")
                    st.markdown(f"**Title:** {contact['title']}")
                    if contact['email']:
                        st.markdown(f"**Email:** {contact['email']}")
                    if contact['linkedin_url']:
                        st.markdown(f"[LinkedIn ↗]({contact['linkedin_url']})")

            if company["notes"]:
                st.markdown("**Notes:**")
                st.caption(company["notes"][:300])