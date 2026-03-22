# db/models.py
#
# SQLAlchemy ORM models — these define the database tables.
#
# CONCEPT — What is an ORM?
# ORM = Object Relational Mapper. Instead of writing raw SQL like:
#   INSERT INTO jobs (id, title, company) VALUES ('...', '...', '...')
# you write Python:
#   db.add(JobRecord(id='...', title='...', company='...'))
#
# SQLAlchemy translates your Python objects into SQL automatically.
# This means:
#   - No SQL injection risk (parameters are always escaped)
#   - Database-agnostic code (swap PostgreSQL for SQLite with one line)
#   - Python autocomplete works on your DB columns
#
# CONCEPT — Why user_id on every table?
# This is the multi-tenancy design we decided on early.
# Every row belongs to a user. When we add authentication later,
# every query will filter by user_id automatically.
# Right now only one user exists, but the schema is ready.

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, Text,
    DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class UserRecord(Base):
    """
    Users table — supports multi-tenancy.
    Currently only one user (you), but schema is ready for more.
    """
    __tablename__ = "users"

    id          = Column(String, primary_key=True)
    email       = Column(String, unique=True, nullable=False)
    name        = Column(String, nullable=False)
    created_at  = Column(DateTime, default=func.now())

    # Relationships — SQLAlchemy uses these for JOIN queries
    jobs        = relationship("JobRecord", back_populates="user")
    companies   = relationship("CompanyRecord", back_populates="user")
    contacts    = relationship("ContactRecord", back_populates="user")
    outreaches  = relationship("OutreachRecord", back_populates="user")


class JobRecord(Base):
    """
    Jobs table — stores all discovered job listings.

    CONCEPT — Why store jobs in DB vs just in LangGraph state?
    LangGraph state lives in memory (or the checkpointer) during a run.
    The DB is the permanent record. When you open the dashboard tomorrow,
    it reads from the DB — not from last night's pipeline run state.
    """
    __tablename__ = "jobs"

    id          = Column(String, primary_key=True)
    user_id     = Column(String, ForeignKey("users.id"), nullable=False)
    title       = Column(String, nullable=False)
    company     = Column(String, nullable=False)
    location    = Column(String)
    description = Column(Text)
    url         = Column(String)
    source      = Column(String)    # "hn_hiring", "greenhouse", "linkedin_apify"
    status      = Column(String, default="new")
    score       = Column(Integer)   # from ScoringAgent (0-100)
    reasoning   = Column(Text)      # Claude's scoring explanation
    recommended = Column(Boolean, default=False)
    date_found  = Column(DateTime, default=func.now())
    created_at  = Column(DateTime, default=func.now())
    updated_at  = Column(DateTime, default=func.now(), onupdate=func.now())

    user        = relationship("UserRecord", back_populates="jobs")

    # Index on user_id + status for fast dashboard queries
    # e.g. "show me all recommended jobs for this user"
    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_user_score", "user_id", "score"),
    )


class CompanyRecord(Base):
    """
    Companies table — funded companies for cold outreach.
    """
    __tablename__ = "companies"

    id              = Column(String, primary_key=True)
    user_id         = Column(String, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    funding_stage   = Column(String)
    amount_raised   = Column(String)
    funding_date    = Column(String)
    source_url      = Column(String)
    website         = Column(String)
    notes           = Column(Text)
    created_at      = Column(DateTime, default=func.now())

    user            = relationship("UserRecord", back_populates="companies")
    contacts        = relationship("ContactRecord", back_populates="company")

    __table_args__ = (
        Index("ix_companies_user", "user_id"),
    )


class ContactRecord(Base):
    """
    Contacts table — people at target companies.
    """
    __tablename__ = "contacts"

    id              = Column(String, primary_key=True)
    user_id         = Column(String, ForeignKey("users.id"), nullable=False)
    company_id      = Column(String, ForeignKey("companies.id"), nullable=True)
    name            = Column(String)
    title           = Column(String)
    email           = Column(String)
    linkedin_url    = Column(String)
    source          = Column(String)
    created_at      = Column(DateTime, default=func.now())

    user            = relationship("UserRecord", back_populates="contacts")
    company         = relationship("CompanyRecord", back_populates="contacts")
    outreaches      = relationship("OutreachRecord", back_populates="contact")

    __table_args__ = (
        Index("ix_contacts_user", "user_id"),
    )


class OutreachRecord(Base):
    """
    Outreach table — cold email and LinkedIn DM drafts + send status.

    CONCEPT — Status lifecycle
    pending_approval → approved → sent
                    → rejected (if you decline in dashboard)

    This gives you a full audit trail of every outreach attempt.
    """
    __tablename__ = "outreach"

    id              = Column(String, primary_key=True)
    user_id         = Column(String, ForeignKey("users.id"), nullable=False)
    contact_id      = Column(String, ForeignKey("contacts.id"), nullable=True)
    job_id          = Column(String, nullable=True)
    email_subject   = Column(String)
    email_body      = Column(Text)
    linkedin_dm     = Column(Text)
    status          = Column(String, default="pending_approval")
    created_at      = Column(DateTime, default=func.now())
    sent_at         = Column(DateTime, nullable=True)
    approved_at     = Column(DateTime, nullable=True)

    user            = relationship("UserRecord", back_populates="outreaches")
    contact         = relationship("ContactRecord", back_populates="outreaches")

    __table_args__ = (
        Index("ix_outreach_user_status", "user_id", "status"),
    )