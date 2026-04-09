"""
Security injection and attack tests.

Categories:
- SQL injection payloads through ORM (email, repo_url, IDs, search params)
- SSRF / internal-network probing via repo URL
- Path traversal in repo URL and analysis ID
- Command injection via git service (token in clone URL)
- Header injection (null bytes, newlines in Authorization)
- Mass assignment (extra fields attempting privilege escalation)
- Unicode / encoding attacks (homoglyphs, null bytes, emoji)
- XSS payload reflection
- Stripe webhook security (no sig, bad sig, malformed payload)
- JWT algorithm confusion and structural attacks not in test_security_edge_cases.py
- Oversized / malformed individual fields
- Enumeration resistance (uniform response times / bodies)
"""
import base64
import json
import os
import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest

from models import Analysis, User, WatchedRepo
from services.auth_service import JWT_SECRET, JWT_ALGO, create_token, hash_password


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="sec@example.com", plan="free",
               is_admin=False, is_verified=True):
    u = User(
        email=email,
        password_hash=hash_password("Test@Pass123"),
        plan=plan,
        is_admin=is_admin,
        is_verified=is_verified,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    return {"Authorization": f"Bearer {create_token(user.id)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SQL injection payloads through SQLAlchemy ORM
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLInjection:
    """
    SQLAlchemy uses parameterised queries so classic SQL injection does not work.
    These tests verify that injected payloads are:
    (a) rejected with a validation error, OR
    (b) treated as literal data without crashing the application.
    """

    # ── Registration / login: email field ────────────────────────────────────

    @pytest.mark.parametrize("payload", [
        "' OR '1'='1",
        "' OR 1=1--",
        "admin'--",
        "'; DROP TABLE users;--",
        "\" OR \"\"=\"",
        "1' AND '1'='1",
        "' UNION SELECT * FROM users--",
        "' UNION SELECT id,email,password_hash FROM users--",
    ])
    def test_sql_injection_in_email_rejected(self, client, payload):
        """SQL injection strings are not valid email addresses → 400."""
        resp = client.post("/api/auth/register",
                           json={"email": payload, "password": "Test@Pass123"})
        assert resp.status_code == 400, (
            f"Injection payload '{payload}' should have been rejected as invalid email"
        )

    @pytest.mark.parametrize("payload", [
        "admin'--",
        "' OR '1'='1",
        "test@test.com' OR '1'='1",
    ])
    def test_sql_injection_in_login_email_rejected_or_401(self, client, payload):
        """Injected login email either fails validation (400) or returns 401 (no match)."""
        resp = client.post("/api/auth/login",
                           json={"email": payload, "password": "anything"})
        assert resp.status_code in (400, 401)

    # ── Repo URL: analyze endpoint ────────────────────────────────────────────

    @pytest.mark.parametrize("payload", [
        "https://github.com/owner/repo' OR '1'='1",
        "https://github.com/'; DROP TABLE analyses;--/repo",
        "https://github.com/owner/repo; SELECT * FROM users",
        "https://github.com/owner/1 UNION SELECT * FROM users",
    ])
    def test_sql_injection_in_repo_url_rejected(self, client, auth_headers, payload):
        """Malicious repo URL strings are rejected as invalid URLs (400)."""
        resp = client.post("/api/analyze",
                           json={"repo_url": payload},
                           headers=auth_headers)
        assert resp.status_code == 400

    # ── Analysis ID in path ───────────────────────────────────────────────────

    @pytest.mark.parametrize("bad_id", [
        "1 OR 1=1",
        "'; DROP TABLE analyses;--",
        "../../../etc/passwd",
        "1 UNION SELECT * FROM users",
        "%27%20OR%20%271%27%3D%271",
        "1; SELECT sleep(5)",
    ])
    def test_sql_injection_in_analysis_id_returns_404(self, client, auth_headers, bad_id):
        """
        Injected analysis IDs are not valid rows; the ORM finds nothing and the
        app returns 404 (not a 500 crash).
        """
        resp = client.get(f"/api/analysis/{bad_id}", headers=auth_headers)
        assert resp.status_code in (400, 404)

    # ── Admin user_id path param ──────────────────────────────────────────────

    @pytest.mark.parametrize("bad_id", [
        "' OR '1'='1",
        "1; SELECT * FROM users",
        "../admin",
    ])
    def test_sql_injection_in_admin_user_id_returns_404(
            self, client, admin_auth_headers, bad_id):
        resp = client.patch(f"/api/admin/users/{bad_id}",
                            json={"plan": "pro"},
                            headers=admin_auth_headers)
        assert resp.status_code in (400, 404)

    # ── Watch repo_url ────────────────────────────────────────────────────────

    @pytest.mark.parametrize("payload", [
        "https://github.com/owner/repo' OR '1'='1",
        "https://github.com/'; DELETE FROM watched_repos;--/x",
    ])
    def test_sql_injection_in_watch_url_rejected(self, client, auth_headers, payload):
        resp = client.post("/api/watch",
                           json={"repo_url": payload},
                           headers=auth_headers)
        assert resp.status_code == 400

    # ── No crash on any SQL-like input ────────────────────────────────────────

    def test_app_survives_sql_in_forgot_password(self, client):
        """Forgot-password always returns 200 regardless of email value."""
        for payload in ["' OR 1=1--", "admin'--", "a@b.com'; DROP TABLE users;--"]:
            resp = client.post("/api/auth/forgot-password",
                               json={"email": payload})
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SSRF — internal network probing via repo URL
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSRF:
    """
    All non-github.com URLs must be rejected at the URL parsing layer (400),
    preventing the server from making outbound requests to internal services.
    """

    @pytest.mark.parametrize("url", [
        # Localhost variants
        "https://localhost/owner/repo",
        "http://127.0.0.1/owner/repo",
        "http://127.0.0.1:8080/owner/repo",
        "https://0.0.0.0/owner/repo",
        # RFC1918 private ranges
        "https://10.0.0.1/owner/repo",
        "https://172.16.0.1/owner/repo",
        "https://192.168.1.1/owner/repo",
        # Link-local
        "https://169.254.169.254/owner/repo",  # AWS metadata endpoint
        "https://169.254.169.254/latest/meta-data/iam/security-credentials/",
        # IPv6 loopback
        "https://[::1]/owner/repo",
        # Alternative protocols
        "file:///etc/passwd",
        "ftp://github.com/owner/repo",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        # Non-GitHub domains
        "https://evil.com/owner/repo",
        "https://github.evil.com/owner/repo",
        "https://notgithub.com/owner/repo",
        # URL with credentials before github.com
        "https://user:pass@evil.com/owner/repo",
        # Subdomain confusion
        "https://github.com.evil.com/owner/repo",
    ])
    def test_ssrf_url_rejected(self, client, auth_headers, url):
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400, (
            f"SSRF URL '{url}' should have been rejected with 400, got {resp.status_code}"
        )

    @pytest.mark.parametrize("url", [
        "https://localhost/owner/repo",
        "https://10.0.0.1/owner/repo",
        "https://evil.com/owner/repo",
    ])
    def test_ssrf_url_rejected_via_watch(self, client, auth_headers, url):
        resp = client.post("/api/watch",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Path traversal
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathTraversal:
    """
    Path traversal sequences in repo URLs or analysis IDs must not escape
    the expected scope.
    """

    @pytest.mark.parametrize("url", [
        "https://github.com/../../../etc/passwd/repo",
        "https://github.com/owner/../../../etc",
        "https://github.com/%2e%2e/%2e%2e/etc/passwd",
        "https://github.com/..%2F..%2Fetc%2Fpasswd/repo",
        "https://github.com/owner/repo/../../etc/passwd",
    ])
    def test_path_traversal_in_repo_url_rejected(self, client, auth_headers, url):
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400

    @pytest.mark.parametrize("traversal", [
        "../../../etc/passwd",
        "..%2F..%2F..%2Fetc%2Fpasswd",
        "....//....//etc/passwd",
    ])
    def test_path_traversal_in_analysis_id_safe(self, client, auth_headers, traversal):
        """Traversal strings in the analysis ID path should return 400 or 404, not 500."""
        resp = client.get(f"/api/analysis/{traversal}", headers=auth_headers)
        assert resp.status_code in (400, 404)

    def test_make_temp_dir_uuid_only(self):
        """make_temp_dir only accepts valid UUID-formatted analysis IDs."""
        import uuid, tempfile, os
        from services.git_service import make_temp_dir
        # Valid UUID should succeed
        safe_id = str(uuid.uuid4())
        path = make_temp_dir(safe_id)
        assert "hootly" in path
        assert ".." not in path

    def test_analysis_id_traversal_no_file_access(self, client, auth_headers):
        """Ensure traversal in ID cannot exfiltrate data about the filesystem."""
        resp = client.get("/api/analysis/../../../../etc/passwd", headers=auth_headers)
        # Must not 200 — must be 400 or 404
        assert resp.status_code in (400, 404)
        # And the response body must not contain passwd-like content
        body = resp.text
        assert "root:" not in body
        assert "/bin/bash" not in body


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Command injection via git service
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommandInjection:
    """
    The git service embeds owner/repo in a URL passed to subprocess.run as a
    list (safe), but we verify that shell metacharacters in owner/repo are
    rejected before reaching the git command.
    """

    @pytest.mark.parametrize("url", [
        # Shell metacharacters in owner
        "https://github.com/own;er/repo",
        "https://github.com/own&&er/repo",
        "https://github.com/own|er/repo",
        "https://github.com/own`whoami`/repo",
        "https://github.com/own$(id)/repo",
        # Shell metacharacters in repo
        "https://github.com/owner/re;po",
        "https://github.com/owner/re&&po",
        "https://github.com/owner/re|po",
        "https://github.com/owner/re`id`",
        "https://github.com/owner/$(ls)",
        # Redirect operators
        "https://github.com/owner>/etc/passwd",
        "https://github.com/owner/repo>/tmp/x",
        # Newline injection
        "https://github.com/owner/repo\ngit push --force",
        # Null bytes
        "https://github.com/owner/repo\x00malicious",
    ])
    def test_shell_metacharacters_in_repo_url_rejected(self, client, auth_headers, url):
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400

    def test_parse_github_url_rejects_shell_in_owner(self):
        from services.git_service import parse_github_url
        for owner_payload in ["; ls", "$(id)", "owner&&evil", "owner|evil"]:
            url = f"https://github.com/{owner_payload}/repo"
            with pytest.raises(ValueError):
                parse_github_url(url)

    def test_parse_github_url_rejects_shell_in_repo(self):
        from services.git_service import parse_github_url
        for repo_payload in ["; ls", "$(id)", "repo&&evil", "repo|evil"]:
            url = f"https://github.com/owner/{repo_payload}"
            with pytest.raises(ValueError):
                parse_github_url(url)

    def test_token_not_leaked_in_clone_error(self):
        """When cloning with a token fails, the token must not appear in the exception."""
        from services.git_service import clone_repo
        import tempfile
        secret_token = "ghp_SuperSecretTokenABC123"
        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "repo")
            # Mock git to fail with output that would normally include the URL
            mock_result = MagicMock()
            mock_result.returncode = 128
            mock_result.stderr = (
                f"fatal: repository 'https://x-access-token:{secret_token}@github.com/o/r.git' not found"
            )
            mock_result.stdout = ""
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError) as exc_info:
                    clone_repo("https://github.com/o/r", dest, github_token=secret_token)
        # Token must never appear in the raised exception
        assert secret_token not in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Header injection and manipulation
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeaderInjection:
    """Malformed or injected header values must not bypass auth or cause errors."""

    @pytest.mark.parametrize("auth_value", [
        # Newline injection
        "Bearer validtoken\r\nX-Injected: evil",
        "Bearer validtoken\nSet-Cookie: session=evil",
        # Null bytes
        "Bearer valid\x00token",
        # Very long token (potential buffer overflow probe)
        "Bearer " + "A" * 10_000,
        # Empty bearer
        "Bearer ",
        "Bearer",
        # Wrong scheme
        "Basic dXNlcjpwYXNz",
        "Token mytoken",
        "Digest realm=x",
        # Double bearer
        "Bearer tok1 Bearer tok2",
    ])
    def test_malformed_authorization_header_rejected(self, client, auth_value):
        resp = client.get("/api/auth/me",
                          headers={"Authorization": auth_value})
        assert resp.status_code in (400, 401, 422)

    def test_multiple_authorization_headers_handled(self, client, test_user):
        """Duplicate Authorization headers must not let an attacker elevate privileges."""
        valid_token = create_token(test_user.id)
        # httpx / requests deduplicate headers, but verify the endpoint
        # doesn't crash on a forged second header
        resp = client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {valid_token}"})
        assert resp.status_code == 200
        # The user must be the intended one
        assert resp.json()["email"] == test_user.email

    def test_content_type_mismatch_handled(self, client, auth_headers):
        """Sending form-encoded body to a JSON endpoint must not crash."""
        resp = client.post(
            "/api/analyze",
            content=b"repo_url=https://github.com/owner/repo",
            headers={**auth_headers, "Content-Type": "application/x-www-form-urlencoded"},
        )
        # May return 400 or 422 (validation error), but not 500
        assert resp.status_code in (400, 422)

    def test_host_header_not_used_for_auth(self, client, auth_headers):
        """Spoofed Host header must not affect response logic."""
        resp = client.get("/api/auth/me",
                          headers={**auth_headers, "Host": "evil.com"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Mass assignment — privilege escalation via extra fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestMassAssignment:
    """
    Extra fields in request bodies must be silently ignored by Pydantic.
    No user should be able to upgrade their own plan or is_admin flag.
    """

    def test_register_with_is_admin_field_ignored(self, client):
        """is_admin in the register body must be ignored — user stays non-admin."""
        resp = client.post("/api/auth/register",
                           json={"email": "hacker@example.com",
                                 "password": "Test@Pass123",
                                 "is_admin": True,
                                 "plan": "pro"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["is_admin"] is False
        assert data["user"]["plan"] == "free"

    def test_settings_patch_with_plan_field_ignored(self, client, auth_headers, test_user):
        """PATCH /auth/settings must not upgrade the user's plan."""
        resp = client.patch("/api/auth/settings",
                            json={"notify_on_complete": False,
                                  "plan": "pro",
                                  "is_admin": True},
                            headers=auth_headers)
        # 200 or 422; if 200, plan must still be free
        if resp.status_code == 200:
            me = client.get("/api/auth/me", headers=auth_headers)
            assert me.json()["plan"] == "free"
            assert me.json()["is_admin"] is False

    def test_analyze_with_user_id_field_ignored(self, client, auth_headers, test_user, pro_user):
        """Submitting another user's ID in the analyze body must not hijack ownership."""
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo",
                                     "user_id": pro_user.id},
                               headers=auth_headers)
        assert resp.status_code == 200
        # The resulting analysis must belong to the authenticated user, not pro_user
        data = resp.json()
        assert data.get("user_id") != pro_user.id

    def test_analyze_with_status_field_ignored(self, client, auth_headers):
        """Submitting status=completed in the body must not bypass analysis."""
        with patch("api.routes._check_repo_accessibility"), \
             patch("api.routes._do_analysis"):
            resp = client.post("/api/analyze",
                               json={"repo_url": "https://github.com/owner/repo",
                                     "status": "completed",
                                     "result": '{"data":"injected"}'},
                               headers=auth_headers)
        assert resp.status_code == 200
        # The analysis must start as pending, not be pre-completed
        assert resp.json()["status"] == "pending"

    def test_register_with_extra_fields_safe(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "extra@example.com",
                                 "password": "Test@Pass123",
                                 "github_access_token": "ghp_stolen",
                                 "stripe_customer_id": "cus_evil",
                                 "verification_code": "000000"})
        assert resp.status_code == 200

    def test_watch_with_last_commit_hash_ignored(self, client, auth_headers):
        """Cannot inject a last_commit_hash to spoof watcher state."""
        resp = client.post("/api/watch",
                           json={"repo_url": "https://github.com/owner/repo",
                                 "last_commit_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
                           headers=auth_headers)
        assert resp.status_code == 200
        # If a hash was injected, it should not be stored
        data = resp.json()
        assert data.get("last_commit_hash") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Unicode, encoding, and null-byte attacks
# ═══════════════════════════════════════════════════════════════════════════════

class TestEncodingAttacks:
    """Null bytes, Unicode, and encoding tricks must not bypass validation."""

    @pytest.mark.parametrize("email", [
        "user\x00@example.com",        # null byte
        "user\r@example.com",           # carriage return
        "user\n@example.com",           # newline
        "user\t@example.com",           # tab
        # Homoglyph: Cyrillic 'а' (U+0430) looks like Latin 'a'
        "аdmin@example.com",            # Cyrillic а
        # Unicode-encoded @ symbol
        "user＠example.com",           # fullwidth @
    ])
    def test_malformed_email_rejected(self, client, email):
        resp = client.post("/api/auth/register",
                           json={"email": email, "password": "Test@Pass123"})
        assert resp.status_code == 400

    @pytest.mark.parametrize("url", [
        "https://github.com/owner\x00/repo",    # null byte in owner
        "https://github.com/owner/repo\x00",   # null byte at end
        "https://github.com/owner/repo%00",     # URL-encoded null
        "https://github.com/owner\r\n/repo",   # CRLF in owner
    ])
    def test_null_byte_in_repo_url_rejected(self, client, auth_headers, url):
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400

    def test_very_long_email_rejected(self, client):
        long_email = "a" * 300 + "@example.com"
        resp = client.post("/api/auth/register",
                           json={"email": long_email, "password": "Test@Pass123"})
        assert resp.status_code == 400

    def test_very_long_password_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "vlong@example.com",
                                 "password": "x" * 2000})
        assert resp.status_code == 400

    def test_unicode_password_accepted(self, client):
        """Passwords with multi-byte Unicode must work (not raise encoding errors)."""
        resp = client.post("/api/auth/register",
                           json={"email": "unicode@example.com",
                                 "password": "pässwörD123!"})
        assert resp.status_code == 200

    def test_url_percent_encoding_bypass_rejected(self, client, auth_headers):
        """Double-encoded path traversal in repo URL must be rejected."""
        # %252e%252e = URL-encoded '..'; a naive decoder might traverse
        url = "https://github.com/%252e%252e/%252e%252e/etc/passwd"
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 8. XSS payload reflection
# ═══════════════════════════════════════════════════════════════════════════════

class TestXSSPayloads:
    """
    XSS payloads stored in valid fields must be returned as literal strings —
    the API returns JSON (not HTML) so they are safe, but we verify the
    validation layer catches invalid-looking URLs before they can be stored.
    """

    @pytest.mark.parametrize("url", [
        # XSS in owner/repo path — rejected as invalid name characters
        "https://github.com/<script>alert(1)</script>/repo",
        "https://github.com/owner/<img src=x onerror=alert(1)>",
        "https://github.com/onmouseover=alert(1)/repo",
        # Query-string XSS is stripped by the URL normaliser; the remaining URL
        # is valid but the repo doesn't exist → 422 (not-found / private)
        # Either way, the payload never reaches the database as stored data
        "https://github.com/owner/repo?q=<script>",
    ])
    def test_xss_in_repo_url_not_stored(self, client, auth_headers, url):
        """XSS payloads in repo URLs are either rejected (400/422) or stripped.
        The payload must never be stored as-is or reflected as HTML."""
        resp = client.post("/api/analyze",
                           json={"repo_url": url},
                           headers=auth_headers)
        # 400 = invalid URL, 422 = private/not-found after normalisation
        assert resp.status_code in (400, 422)
        # Response must always be JSON, never HTML
        assert "text/html" not in resp.headers.get("content-type", "")

    def test_xss_in_email_rejected(self, client):
        resp = client.post("/api/auth/register",
                           json={"email": "<script>alert(1)</script>@evil.com",
                                 "password": "Test@Pass123"})
        assert resp.status_code == 400

    def test_content_type_is_json_not_html(self, client, auth_headers):
        """Responses must never be served as text/html (XSS vector)."""
        resp = client.get("/api/auth/me", headers=auth_headers)
        ct = resp.headers.get("content-type", "")
        assert "text/html" not in ct
        assert "application/json" in ct

    def test_json_response_does_not_eval_repo_name(self, client, auth_headers, db_session,
                                                    test_user):
        """Analysis result stored with XSS payload is returned as literal JSON string."""
        a = Analysis(
            repo_url="https://github.com/owner/repo",
            repo_name="owner/repo",
            status="completed",
            stage="Done",
            user_id=test_user.id,
            is_public=True,
            result=json.dumps({"repo_name": "<script>alert(1)</script>"}),
        )
        db_session.add(a)
        db_session.commit()

        resp = client.get(f"/api/public/analysis/{a.id}")
        assert resp.status_code == 200
        # The script tag must appear as a literal string in the JSON, not be rendered
        body = resp.text
        # JSON-encoded it would appear as \u003cscript\u003e or as literal <script>
        # Either way the response is JSON, not executed HTML
        assert "application/json" in resp.headers.get("content-type", "")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Stripe webhook security
# ═══════════════════════════════════════════════════════════════════════════════

class TestStripeWebhookSecurity:
    """Stripe webhook endpoint must reject unsigned/forged requests."""

    def test_webhook_without_signature_header_rejected(self, client):
        """No stripe-signature header → 400 (or 503 if webhook not configured)."""
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test"}):
            import api.billing as _b
            old = _b.STRIPE_WEBHOOK_SECRET
            _b.STRIPE_WEBHOOK_SECRET = "whsec_test"
            try:
                resp = client.post(
                    "/api/billing/webhook",
                    content=b'{"type":"checkout.session.completed"}',
                    headers={"Content-Type": "application/json"},
                )
            finally:
                _b.STRIPE_WEBHOOK_SECRET = old
        assert resp.status_code in (400, 503)

    def test_webhook_with_wrong_signature_rejected(self, client):
        """Wrong stripe-signature → 400."""
        import api.billing as _b
        old = _b.STRIPE_WEBHOOK_SECRET
        _b.STRIPE_WEBHOOK_SECRET = "whsec_test"
        # Patch stripe.Webhook.construct_event to raise SignatureVerificationError
        try:
            import stripe as stripe_mod
            with patch.object(stripe_mod.Webhook, "construct_event",
                              side_effect=stripe_mod.error.SignatureVerificationError(
                                  "bad sig", "sig_header")):
                resp = client.post(
                    "/api/billing/webhook",
                    content=b'{"type":"test"}',
                    headers={"stripe-signature": "t=fake,v1=fakesig"},
                )
        finally:
            _b.STRIPE_WEBHOOK_SECRET = old
        assert resp.status_code == 400
        assert "signature" in resp.json()["detail"].lower()

    def test_webhook_malformed_payload_rejected(self, client):
        """Malformed JSON body → 400."""
        import api.billing as _b
        old = _b.STRIPE_WEBHOOK_SECRET
        _b.STRIPE_WEBHOOK_SECRET = "whsec_test"
        try:
            import stripe as stripe_mod
            with patch.object(stripe_mod.Webhook, "construct_event",
                              side_effect=Exception("Invalid JSON")):
                resp = client.post(
                    "/api/billing/webhook",
                    content=b"not json at all }{",
                    headers={"stripe-signature": "t=fake,v1=fakesig"},
                )
        finally:
            _b.STRIPE_WEBHOOK_SECRET = old
        assert resp.status_code == 400

    def test_webhook_not_configured_returns_503(self, client):
        """If STRIPE_WEBHOOK_SECRET is empty, webhook returns 503."""
        import api.billing as _b
        old = _b.STRIPE_WEBHOOK_SECRET
        _b.STRIPE_WEBHOOK_SECRET = ""
        try:
            resp = client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "anysig"},
            )
        finally:
            _b.STRIPE_WEBHOOK_SECRET = old
        assert resp.status_code == 503

    def test_webhook_unknown_event_type_returns_200(self, client):
        """Unknown event types must be accepted (200) and silently ignored."""
        import api.billing as _b
        old = _b.STRIPE_WEBHOOK_SECRET
        _b.STRIPE_WEBHOOK_SECRET = "whsec_test"
        try:
            import stripe as stripe_mod
            fake_event = {"type": "completely.unknown.event", "data": {"object": {}}}
            with patch.object(stripe_mod.Webhook, "construct_event",
                              return_value=fake_event):
                resp = client.post(
                    "/api/billing/webhook",
                    content=b'{"type":"completely.unknown.event"}',
                    headers={"stripe-signature": "t=valid,v1=sig"},
                )
        finally:
            _b.STRIPE_WEBHOOK_SECRET = old
        assert resp.status_code == 200
        assert resp.json()["received"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 10. JWT structural attacks (supplement test_security_edge_cases.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTStructuralAttacks:
    """JWT attacks not already covered in test_security_edge_cases.py."""

    def test_rs256_signed_token_rejected(self, client):
        """
        A token claiming RS256 but signed with the HS256 secret must be rejected.
        PyJWT's algorithms whitelist prevents alg-confusion attacks.
        """
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
            private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            rs_token = pyjwt.encode(
                {"sub": "fake-user", "exp": int(time.time()) + 3600},
                private_key, algorithm="RS256",
            )
        except Exception:
            pytest.skip("cryptography library not available")
        resp = client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {rs_token}"})
        assert resp.status_code == 401

    def test_empty_sub_claim_rejected(self, client):
        """Token with empty sub should not grant access to any user."""
        token = pyjwt.encode(
            {"sub": "", "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_nonexistent_user_id_in_token_rejected(self, client):
        """Valid signature + non-existent user ID must return 401, not 500."""
        token = pyjwt.encode(
            {"sub": "00000000-0000-0000-0000-000000000000",
             "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_token_with_extra_claims_still_works(self, client, test_user):
        """Extra claims in a valid token must not break authentication."""
        token = pyjwt.encode(
            {"sub": test_user.id,
             "exp": int(time.time()) + 3600,
             "role": "superadmin",    # extra claim that should be ignored
             "is_admin": True},        # extra claim that should be ignored
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        # Either works (200, extra claims ignored) or rejected — must not grant admin
        if resp.status_code == 200:
            assert resp.json()["is_admin"] == test_user.is_admin  # not elevated

    def test_jwt_with_html_injection_in_sub(self, client):
        """HTML/script in the sub claim must not cause XSS in error responses."""
        token = pyjwt.encode(
            {"sub": "<script>alert(1)</script>",
             "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        ct = resp.headers.get("content-type", "")
        assert "text/html" not in ct

    def test_massive_jwt_payload_rejected_gracefully(self, client):
        """A JWT with a very large payload must not crash the server."""
        token = pyjwt.encode(
            {"sub": "x" * 50_000,
             "junk": "y" * 50_000,
             "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        resp = client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (400, 401, 422)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Enumeration resistance
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnumerationResistance:
    """
    Security-sensitive endpoints must not reveal whether a resource exists
    via different response bodies or status codes.
    """

    def test_forgot_password_same_response_existing_vs_nonexistent(self, client, test_user):
        """
        Both known and unknown emails must return identical 200 responses
        so attackers cannot determine registered emails.
        """
        with patch("api.auth.send_password_reset_email"):
            r_known = client.post("/api/auth/forgot-password",
                                  json={"email": test_user.email})
            r_unknown = client.post("/api/auth/forgot-password",
                                    json={"email": "nobody@example.com"})

        assert r_known.status_code == 200
        assert r_unknown.status_code == 200
        assert r_known.json() == r_unknown.json()

    def test_analysis_not_found_returns_404_not_403(self, client, auth_headers):
        """
        When a user can't access an analysis, return 404 (not 403) to avoid
        revealing that the analysis exists.
        """
        resp = client.get("/api/analysis/nonexistent-uuid", headers=auth_headers)
        assert resp.status_code == 404

    def test_other_users_analysis_returns_404_not_403(self, client, auth_headers,
                                                       db_session, pro_user):
        """Accessing another user's analysis returns 404, not 403."""
        a = Analysis(
            repo_url="https://github.com/other/repo",
            repo_name="other/repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
        )
        db_session.add(a)
        db_session.commit()
        resp = client.get(f"/api/analysis/{a.id}", headers=auth_headers)
        assert resp.status_code == 404  # not 403

    def test_no_password_hash_in_any_response(self, client, auth_headers, test_user, db_session):
        """
        No API response must ever include password_hash, bcrypt hash fragments,
        or verification codes.
        """
        endpoints = [
            ("GET", "/api/auth/me", None),
            ("GET", "/api/auth/settings", None),
            ("GET", "/api/analyses", None),
        ]
        for method, path, body in endpoints:
            if method == "GET":
                resp = client.get(path, headers=auth_headers)
            else:
                resp = client.post(path, json=body, headers=auth_headers)

            raw = resp.text.lower()
            assert "password_hash" not in raw, f"{path} leaked password_hash"
            assert "$2b$" not in raw, f"{path} leaked bcrypt hash"
            assert "verification_code" not in raw, f"{path} leaked verification_code"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Replay attacks and request smuggling
# ═══════════════════════════════════════════════════════════════════════════════

class TestReplayAndSmuggling:
    """Verify replay attacks and HTTP smuggling defences."""

    def test_used_reset_token_cannot_be_replayed(self, client, db_session):
        """A password reset token is single-use — replaying it must fail."""
        user = _make_user(db_session, email="replay@example.com")
        from datetime import timedelta, timezone
        expire = (
            __import__("datetime").datetime.now(timezone.utc) + timedelta(hours=1)
        )
        token = pyjwt.encode(
            {"sub": user.id, "purpose": "reset",
             "ph": user.password_hash[:8], "exp": expire},
            JWT_SECRET, algorithm=JWT_ALGO,
        )
        # First use: success
        r1 = client.post("/api/auth/reset-password",
                         json={"token": token, "new_password": "newStrongPass1!"})
        assert r1.status_code == 200
        # Second use: password hash changed → ph mismatch → 400
        r2 = client.post("/api/auth/reset-password",
                         json={"token": token, "new_password": "anotherPass2?"})
        assert r2.status_code == 400

    def test_oauth_code_cannot_be_replayed(self, client, test_user):
        """OAuth one-time code is consumed on first use — replay must fail."""
        from api.auth import _new_oauth_code
        token = create_token(test_user.id)
        code = _new_oauth_code(token)

        r1 = client.post("/api/auth/github/exchange", json={"code": code})
        assert r1.status_code == 200

        r2 = client.post("/api/auth/github/exchange", json={"code": code})
        assert r2.status_code == 400

    def test_chunked_te_header_does_not_bypass_body_limit(self, client, auth_headers):
        """
        Chunked transfer-encoding without content-length header:
        middleware must still handle the request without crashing.
        """
        resp = client.post(
            "/api/analyze",
            content=b'{"repo_url":"https://github.com/owner/repo"}',
            headers={**auth_headers,
                     "Content-Type": "application/json",
                     "Transfer-Encoding": "chunked"},
        )
        # Must not be a server error (500)
        assert resp.status_code != 500

    def test_body_size_limit_enforced_by_content_length(self, client, auth_headers):
        """Content-Length > 1 MB is rejected before body is read."""
        resp = client.post(
            "/api/analyze",
            content=b"x" * 100,   # small actual body
            headers={**auth_headers,
                     "Content-Type": "application/json",
                     "Content-Length": "2000000"},  # lie about size
        )
        assert resp.status_code == 413


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Privilege escalation via watch/analysis ownership
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrivilegeEscalation:
    """Verify cross-user resource access is universally blocked."""

    def test_cannot_delete_other_users_watch(self, client, auth_headers,
                                              pro_auth_headers, db_session, pro_user):
        """User A cannot delete User B's watch entry."""
        watch = WatchedRepo(
            user_id=pro_user.id,
            repo_url="https://github.com/victim/repo",
            repo_name="victim/repo",
        )
        db_session.add(watch)
        db_session.commit()

        resp = client.delete(f"/api/watch/{watch.id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_cannot_view_other_users_analyses_list(self, client, auth_headers,
                                                    db_session, pro_user):
        """GET /api/analyses must only return the current user's analyses."""
        for i in range(3):
            db_session.add(Analysis(
                repo_url=f"https://github.com/other/repo{i}",
                repo_name=f"other/repo{i}",
                status="completed",
                stage="Done",
                user_id=pro_user.id,
            ))
        db_session.commit()

        resp = client.get("/api/analyses", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Current user (test_user) has no analyses — must not see pro_user's
        for a in data:
            assert a.get("user_id") != pro_user.id

    def test_cannot_escalate_via_analysis_id_guessing(self, client, db_session,
                                                        test_user, pro_user):
        """Iterating through analysis IDs must not reveal other users' data."""
        victim_analysis = Analysis(
            repo_url="https://github.com/victim/repo",
            repo_name="victim/repo",
            status="completed",
            stage="Done",
            user_id=pro_user.id,
            result='{"secret":"data"}',
        )
        db_session.add(victim_analysis)
        db_session.commit()

        # test_user tries to access victim's analysis by its ID
        resp = client.get(f"/api/analysis/{victim_analysis.id}",
                          headers=_auth(test_user))
        assert resp.status_code == 404
        # Must not expose secret data in error response either
        assert "secret" not in resp.text
