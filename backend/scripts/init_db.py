"""Creates all tables from app/models.py against DATABASE_URL. Run once against a fresh
Supabase Postgres instance: `python -m scripts.init_db` from backend/.

MVP bootstrap only -- swap for real Alembic migrations before the schema needs its first
change against data that matters (this project's own CLAUDE.md has plenty of examples of
why "non-destructive migration, read back to confirm" matters once there's real user data)."""

from app.db import Base, engine
from app.models import (  # noqa: F401
    ColdEmail,
    DailySummary,
    OAuthCredential,
    Posting,
    Profile,
    Secret,
    User,
    WizardDraft,
)

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
