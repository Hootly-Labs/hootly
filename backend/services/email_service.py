"""Resend HTTP API email service."""
import html
import logging
import os

import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@hootlylabs.com")

logger = logging.getLogger(__name__)

# Keep SMTP_USER/SMTP_PASSWORD as empty strings so existing imports in auth.py don't break
SMTP_USER = ""
SMTP_PASSWORD = ""


def _send(to_email: str, subject: str, html_body: str) -> None:
    """Send an email via Resend API. Logs and returns silently on failure."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — skipping email to %s", to_email)
        return
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_EMAIL, "to": [to_email], "subject": subject, "html": html_body},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Email '%s' sent to %s", subject, to_email)
    except Exception as exc:
        logger.error("Failed to send email '%s' to %s: %s", subject, to_email, exc)


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    _send(to_email, "Reset your Hootly password", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      Reset your password
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      We received a request to reset the password for your Hootly account.
      Click the button below to set a new password. This link expires in <strong>1 hour</strong>.
    </p>
    <div style="text-align: center; margin-bottom: 28px;">
      <a href="{reset_url}"
         style="display: inline-block; background: #2563eb; color: #ffffff;
                text-decoration: none; font-weight: 600; font-size: 15px;
                padding: 14px 32px; border-radius: 10px;">
        Reset password
      </a>
    </div>
    <p style="color: #94a3b8; font-size: 13px; line-height: 1.6; margin: 0;">
      If you didn&rsquo;t request a password reset, you can safely ignore this email.
    </p>
  </div>
</body>
</html>
""")


def send_verification_email(to_email: str, code: str) -> None:
    _send(to_email, "Verify your Hootly email", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      Verify your email
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      Enter the 8-digit code below to verify your email address. It expires in <strong>2 hours</strong>.
    </p>
    <div style="text-align: center; margin-bottom: 28px;">
      <div style="display: inline-block; background: #f1f5f9; border: 1px solid #e2e8f0;
                  border-radius: 12px; padding: 20px 40px;">
        <span style="font-size: 36px; font-weight: 800; letter-spacing: 10px;
                     color: #1e40af; font-family: monospace;">{code}</span>
      </div>
    </div>
    <p style="color: #94a3b8; font-size: 13px; line-height: 1.6; margin: 0;">
      If you didn&rsquo;t create a Hootly account, you can safely ignore this email.
    </p>
  </div>
</body>
</html>
""")


def send_repo_changed_email(
    to_email: str, repo_name: str, analysis_url: str, commit_short: str
) -> None:
    repo_name = html.escape(repo_name)
    commit_short = html.escape(commit_short)
    _send(to_email, f"{repo_name} has new commits — fresh analysis ready", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      New commits detected
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 8px;">
      Your watched repo <strong style="font-family: monospace;">{repo_name}</strong> has
      new commits (latest: <code style="background:#f1f5f9; padding: 1px 5px; border-radius: 4px;">{commit_short}</code>).
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      A fresh analysis has been started automatically.
    </p>
    <div style="text-align: center; margin-bottom: 28px;">
      <a href="{analysis_url}"
         style="display: inline-block; background: #2563eb; color: #ffffff;
                text-decoration: none; font-weight: 600; font-size: 15px;
                padding: 14px 32px; border-radius: 10px;">
        View new analysis →
      </a>
    </div>
    <p style="color: #94a3b8; font-size: 13px; line-height: 1.6; margin: 0;">
      You&rsquo;re receiving this because you&rsquo;re watching this repo on Hootly.
    </p>
  </div>
</body>
</html>
""")


def send_failed_login_email(to_email: str, ip: str, attempt_count: int) -> None:
    ip = html.escape(ip)
    _send(to_email, "Suspicious login activity on your Hootly account", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      Suspicious login activity
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 12px;">
      We detected <strong>{attempt_count} failed login attempt(s)</strong> on your Hootly account.
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      IP address: <code style="background:#f1f5f9; padding: 1px 5px; border-radius: 4px;">{ip}</code>
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 12px;">
      If this was you, no action is needed. If you don&rsquo;t recognize this activity,
      we recommend changing your password immediately.
    </p>
    <p style="color: #94a3b8; font-size: 13px; line-height: 1.6; margin: 0;">
      Your account may be temporarily locked after 5 failed attempts.
    </p>
  </div>
</body>
</html>
""")


def send_suspicious_login_email(to_email: str, ip: str, new_country: str, old_country: str) -> None:
    ip = html.escape(ip)
    new_country = html.escape(new_country)
    old_country = html.escape(old_country)
    _send(to_email, "Login from a new location — Hootly", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      New login location
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 12px;">
      Your Hootly account was accessed from a new location.
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 8px;">
      <strong>New location:</strong> {new_country}<br />
      <strong>Previous location:</strong> {old_country}<br />
      <strong>IP address:</strong> <code style="background:#f1f5f9; padding: 1px 5px; border-radius: 4px;">{ip}</code>
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      If this was you, no action is needed. Otherwise, change your password immediately.
    </p>
  </div>
</body>
</html>
""")


def send_analysis_complete_email(to_email: str, repo_name: str, analysis_url: str) -> None:
    repo_name = html.escape(repo_name)
    _send(to_email, f"Your Hootly analysis of {repo_name} is ready", f"""
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
             background: #f8fafc; margin: 0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff;
              border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px;">
    <div style="text-align: center; margin-bottom: 32px;">
      <img src="https://www.hootlylabs.com/favicon.png" alt="Hootly" width="52" height="52"
           style="border-radius: 10px; display: block; margin: 0 auto 8px;" />
      <h2 style="margin: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Hootly</h2>
    </div>
    <h1 style="color: #0f172a; font-size: 22px; font-weight: 700; margin: 0 0 12px;">
      Analysis complete!
    </h1>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 8px;">
      Your analysis of <strong style="font-family: monospace;">{repo_name}</strong> is ready.
    </p>
    <p style="color: #475569; font-size: 15px; line-height: 1.6; margin: 0 0 28px;">
      View the architecture overview, key files, dependency graph, and full onboarding guide.
    </p>
    <div style="text-align: center; margin-bottom: 28px;">
      <a href="{analysis_url}"
         style="display: inline-block; background: #2563eb; color: #ffffff;
                text-decoration: none; font-weight: 600; font-size: 15px;
                padding: 14px 32px; border-radius: 10px;">
        View analysis →
      </a>
    </div>
  </div>
</body>
</html>
""")
