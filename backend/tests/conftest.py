"""Test env vars must be set before any app/pipeline module is imported -- app/db.py reads
DATABASE_URL at import time (os.environ[...], not .get()), and app/auth.py/main.py do the
same for JWT_SECRET/INTERNAL_SHARED_SECRET. conftest.py is collected before any test module,
so this is the one place guaranteed to run first."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("INTERNAL_SHARED_SECRET", "test-internal-secret")
os.environ.setdefault("ENCRYPTION_KEY", "MPPfSF__T2imodK6RNJ7jjKl1e1jI5x2C0mSRw9dAYo=")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from pipeline import config as pipeline_config


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite schema per test, bound into pipeline.config's contextvar the
    same way app/main.py's bind_db_session_for_pipeline middleware does for a real request --
    call sites under test (filter/postings_store) read the session that way, not via a
    parameter."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    pipeline_config.set_session(session)
    try:
        yield session
    finally:
        pipeline_config.set_session(None)
        session.close()
        engine.dispose()
