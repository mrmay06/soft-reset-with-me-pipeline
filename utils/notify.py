import smtplib
import os
from email.mime.text import MIMEText
from datetime import datetime


SUBJECT_PREFIX = "Soft Reset"


def _send_email(subject: str, body: str):
    email_from = os.environ.get("ALERT_EMAIL_FROM")
    email_to   = os.environ.get("ALERT_EMAIL_TO")
    email_pass = os.environ.get("ALERT_EMAIL_PASSWORD")
    if not all([email_from, email_to, email_pass]):
        print(f"[notify] Email not configured — skipping: {subject}")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_from, email_pass)
            server.send_message(msg)
        print(f"[notify] Email sent → {email_to}: {subject}")
    except Exception as e:
        print(f"[notify] Email failed: {e}")


def send_success_alert(video_id: str, title: str, youtube_url: str, timings: dict):
    timing_lines = "\n".join(f"  {k:<32} {v}s" for k, v in timings.items())
    total = sum(timings.values())
    body = f"""
✅ Video Published — {video_id}
{'='*40}
Title:     {title}
URL:       {youtube_url}
Time:      {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
Duration:  {total}s ({total/60:.1f} min)
{'='*40}
Timing breakdown:
{timing_lines}
"""
    _send_email(f"{SUBJECT_PREFIX} Published: {title[:50]}", body)


def send_auth_expiry_alert(service: str):
    """Alert when a YouTube OAuth refresh token has expired or been revoked."""
    body = f"""
YouTube OAuth Token Expired — {service}
{'='*40}
Service:   {service}
Time:      {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

The refresh token for {service} has expired or been revoked.
Videos generated after this point will NOT be uploaded until you re-authenticate.

Steps to fix:
1. Run:  python tools/get_youtube_token.py
2. Update YOUTUBE_REFRESH_TOKEN in your .env / GitHub Secrets
3. Re-run the pipeline

This is a CRITICAL issue — the channel is effectively paused.
"""
    _send_email(f"{SUBJECT_PREFIX} ⚠️ AUTH EXPIRED — manual action needed", body)


def send_failure_alert(video_id: str, error_msg: str, traceback_str: str):
    run_url = (
        f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'unknown/repo')}"
        f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '0')}"
    )

    body = f"""
Pipeline FAILED — {video_id}
{'='*40}
Video ID:  {video_id}
Time:      {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
Error:     {error_msg}
Run logs:  {run_url}
{'='*40}
Traceback:
{traceback_str}
"""

    _send_email(f"{SUBJECT_PREFIX} Pipeline failed - {video_id}", body)
