"""Shared fixtures for all test modules."""
import os
import pytest

# Set test env vars BEFORE any app imports so dotenv doesn't overwrite them
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-do-not-use-in-prod"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import Analysis, User, WatchedRepo  # noqa: F401 — registers models
from services.auth_service import create_token, hash_password
from services.rate_limiter import _lock, _requests, _keyed_requests


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    """Reset the IP rate limiter state between every test."""
    with _lock:
        _requests.clear()
        _keyed_requests.clear()
    yield
    with _lock:
        _requests.clear()
        _keyed_requests.clear()

_TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    # StaticPool ensures all connections share the same in-memory database
    eng = create_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """Fresh DB session per test; rolls back after each test."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.rollback()
    # Clean up all rows so tests don't bleed into each other
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture()
def client(db_session):
    """TestClient with the real app, DB overridden, watcher disabled."""
    with patch("services.watcher_service.start_watcher"), \
         patch("api.auth._check_pwned_password"):
        from main import app
        app.dependency_overrides[get_db] = lambda: db_session
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        app.dependency_overrides.clear()


@pytest.fixture()
def test_user(db_session):
    user = User(
        email="user@example.com",
        password_hash=hash_password("Test@Pass123"),
        plan="free",
        is_admin=False,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def pro_user(db_session):
    user = User(
        email="pro@example.com",
        password_hash=hash_password("Test@Pass123"),
        plan="pro",
        is_admin=False,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_user(db_session):
    user = User(
        email="admin@example.com",
        password_hash=hash_password("Test@Pass123"),
        plan="pro",
        is_admin=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def unverified_user(db_session):
    user = User(
        email="unverified@example.com",
        password_hash=hash_password("Test@Pass123"),
        plan="free",
        is_admin=False,
        is_verified=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def auth_headers(test_user):
    token = create_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def pro_auth_headers(pro_user):
    token = create_token(pro_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_auth_headers(admin_user):
    token = create_token(admin_user.id)
    return {"Authorization": f"Bearer {token}"}
