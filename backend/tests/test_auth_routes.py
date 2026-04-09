"""Integration tests for auth endpoints: register, login, me, settings, password, account."""
import pytest
from unittest.mock import patch

from models import User
from services.auth_service import create_token, hash_password


class TestRegister:
    def test_register_success(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "Test@Pass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "new@example.com"
        assert data["user"]["plan"] == "free"
        assert data["user"]["is_admin"] is False

    def test_register_auto_verified_when_smtp_not_configured(self, client):
        with patch("api.auth._smtp_configured", return_value=False):
            resp = client.post(
                "/api/auth/register",
                json={"email": "verified@example.com", "password": "Test@Pass123"},
            )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_verified"] is True

    def test_register_duplicate_email(self, client, test_user):
        resp = client.post(
            "/api/auth/register",
            json={"email": test_user.email, "password": "Test@Pass123"},
        )
        assert resp.status_code == 400
        assert "Unable to create account" in resp.json()["detail"]

    def test_register_invalid_email(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "notanemail", "password": "Test@Pass123"},
        )
        assert resp.status_code == 400

    def test_register_password_too_short(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert resp.status_code == 400
        assert "10 characters" in resp.json()["detail"]

    def test_register_blank_password(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "blank@example.com", "password": "   "},
        )
        assert resp.status_code == 400

    def test_register_password_too_long(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "long@example.com", "password": "x" * 1025},
        )
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, client, test_user):
        resp = client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "Test@Pass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == test_user.email

    def test_login_wrong_password(self, client, test_user):
        resp = client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_login_unknown_email(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "Test@Pass123"},
        )
        assert resp.status_code == 401

    def test_login_case_insensitive_email(self, client, test_user):
        resp = client.post(
            "/api/auth/login",
            json={"email": test_user.email.upper(), "password": "Test@Pass123"},
        )
        assert resp.status_code == 200


class TestMe:
    def test_me_authenticated(self, client, test_user, auth_headers):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == test_user.email
        assert data["plan"] == "free"

    def test_me_unauthenticated(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401


class TestSettings:
    def test_get_settings(self, client, auth_headers):
        resp = client.get("/api/auth/settings", headers=auth_headers)
        assert resp.status_code == 200
        assert "notify_on_complete" in resp.json()

    def test_update_settings(self, client, auth_headers):
        resp = client.patch(
            "/api/auth/settings",
            json={"notify_on_complete": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Verify the change persisted
        resp2 = client.get("/api/auth/settings", headers=auth_headers)
        assert resp2.json()["notify_on_complete"] is True

    def test_settings_requires_auth(self, client):
        resp = client.get("/api/auth/settings")
        assert resp.status_code == 401


class TestChangePassword:
    def test_change_password_success(self, client, auth_headers):
        resp = client.patch(
            "/api/auth/change-password",
            json={"old_password": "Test@Pass123", "new_password": "New@Pass4567"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_change_password_wrong_old(self, client, auth_headers):
        resp = client.patch(
            "/api/auth/change-password",
            json={"old_password": "wrongpassword", "new_password": "New@Pass4567"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"]

    def test_change_password_new_too_short(self, client, auth_headers):
        resp = client.patch(
            "/api/auth/change-password",
            json={"old_password": "Test@Pass123", "new_password": "short"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_change_password_requires_auth(self, client):
        resp = client.patch(
            "/api/auth/change-password",
            json={"old_password": "a", "new_password": "b"},
        )
        assert resp.status_code == 401


class TestDeleteAccount:
    def test_delete_account(self, client, db_session):
        # Create a fresh user so the deletion doesn't break other fixtures
        user = User(
            email="todelete@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.delete("/api/auth/account", headers=headers)
        assert resp.status_code == 200

        # User should be gone from DB
        gone = db_session.query(User).filter(User.id == user.id).first()
        assert gone is None

    def test_delete_account_requires_auth(self, client):
        resp = client.delete("/api/auth/account")
        assert resp.status_code == 401


class TestForgotPassword:
    def test_forgot_password_always_200(self, client):
        with patch("api.auth.send_password_reset_email"):
            resp = client.post(
                "/api/auth/forgot-password",
                json={"email": "nobody@example.com"},
            )
        assert resp.status_code == 200

    def test_forgot_password_known_email_sends_email(self, client, test_user):
        with patch("api.auth.send_password_reset_email") as mock_send:
            resp = client.post(
                "/api/auth/forgot-password",
                json={"email": test_user.email},
            )
        assert resp.status_code == 200
        mock_send.assert_called_once()


class TestVerifyEmail:
    def test_verify_already_verified_user(self, client, auth_headers):
        # test_user fixture is already verified — should return 200
        resp = client.post(
            "/api/auth/verify-email",
            json={"code": "123456"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "Already verified" in resp.json()["detail"]

    def test_verify_invalid_code(self, client, db_session):
        user = User(
            email="unverified@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=False,
            verification_code="654321",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/auth/verify-email",
            json={"code": "000000"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    def test_verify_correct_code(self, client, db_session):
        user = User(
            email="unverified2@example.com",
            password_hash=hash_password("Test@Pass123"),
            plan="free",
            is_admin=False,
            is_verified=False,
            verification_code="123456",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/auth/verify-email",
            json={"code": "123456"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "verified" in resp.json()["detail"].lower()
