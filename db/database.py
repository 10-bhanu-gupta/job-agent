# db/database.py
#
# Database connection and session management.
#
# CONCEPT — SQLAlchemy Sessions
# A "session" is a unit of work with the database.
# You open a session, make changes, commit them, then close it.
# If anything goes wrong, you roll back — all changes are undone.
# This is the same concept as a database transaction.
#
# CONCEPT — get_db() as a context manager
# We use Python's contextlib to create a context manager:
#   with get_db() as db:
#       db.add(record)
#       db.commit()
# This guarantees the session is always closed, even if an error occurs.
# No leaked connections, no resource exhaustion.

from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from config.settings import DATABASE_URL, is_placeholder
from db.models import Base


# ---------------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------------
# The engine is the core connection pool to PostgreSQL.
# We create it once at module level — it's expensive to create
# and designed to be shared across the entire application.
#
# pool_pre_ping=True: before using a connection, test it's still alive.
# This prevents errors from stale connections after a DB restart.
#
# For local development (no DATABASE_URL set), we use SQLite as fallback.
# SQLite is file-based, needs no server, perfect for local testing.

def get_engine():
    from config.settings import is_placeholder
    if is_placeholder(DATABASE_URL):
        print("  ⚠️  DATABASE_URL not set — using local SQLite for development")
        return create_engine(
            "sqlite:///./job_agent_dev.db",
            connect_args={"check_same_thread": False},
        )
    return create_engine(DATABASE_URL, pool_pre_ping=True)


engine = get_engine()

# SessionLocal is a factory that creates new Session objects
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# INITIALISE TABLES
# ---------------------------------------------------------------------------

def init_db():
    """
    Creates all tables if they don't exist.

    CONCEPT — Base.metadata.create_all()
    SQLAlchemy reads all the models registered with Base and creates
    the corresponding tables in the database. If a table already exists,
    it's left untouched (not dropped and recreated).

    In production we'd use Alembic migrations instead (more controlled),
    but create_all() is perfect for development and initial deployment.
    """
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables initialised")


# ---------------------------------------------------------------------------
# SESSION CONTEXT MANAGER
# ---------------------------------------------------------------------------

@contextmanager
def get_db() -> Session:
    """
    Yields a database session and ensures it's closed after use.

    Usage:
        with get_db() as db:
            db.add(some_record)
            db.commit()

    If an exception occurs inside the with block, the session is
    rolled back automatically before being closed.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()