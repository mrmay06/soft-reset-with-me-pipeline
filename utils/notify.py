from __future__ import annotations

import smtplib
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


SUBJECT_PREFIX = "Soft Reset"


def _send_email(subject: str, body: str):
    _send_email_with_attachments(subject, body, [])


def _send_email_with_attachments(subject: str, body: str, attachments: list[str] | None = None):
    email_from = os.environ.get("ALERT_EMAIL_FROM")
    email_to   = os.environ.get("ALERT_EMAIL_TO")
    email_pass = os.environ.get("ALERT_EMAIL_PASSWORD")
    if not all([email_from, email_to, email_pass]):
        print(f"[notify] Email not configured — skipping: {subject}")
        return
    attachments = attachments or []
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body))
        for path in attachments:
            if not path or not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
            msg.attach(part)
    else:
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


def send_longform_upload_confirmation(
    video_id: str,
    title: str,
    youtube_url: str,
    metadata: dict,
    thumbnail_meta: dict,
    run_dir: str,
):
    primary_id = str(metadata.get("primary_variant_id", "")).upper() or "unknown"
    title_by_id = {
        str(item.get("id", "")).upper(): item
        for item in metadata.get("title_variants", [])
        if isinstance(item, dict)
    }
    thumb_by_id = {
        str(item.get("id", "")).upper(): item
        for item in metadata.get("thumbnail_variants", [])
        if isinstance(item, dict)
    }
    output_by_id = {
        str(item.get("id", "")).upper(): item
        for item in thumbnail_meta.get("variants", [])
        if isinstance(item, dict)
    }

    variant_lines = []
    attachments = []
    for variant_id in ("A", "B", "C"):
        title_item = title_by_id.get(variant_id, {})
        thumb_item = thumb_by_id.get(variant_id, {})
        output_item = output_by_id.get(variant_id, {})
        output_file = output_item.get("output_file") or f"07_longform_thumbnail_{variant_id}.png"
        output_path = os.path.join(run_dir, output_file)
        if os.path.exists(output_path):
            attachments.append(output_path)
        marker = "PRIMARY" if variant_id == primary_id else "ALT"
        line1 = thumb_item.get("line1", "")
        line2 = thumb_item.get("line2", "")
        thumb_copy = thumb_item.get("thumbnail_text", "")
        if line1 or line2:
            thumb_copy = f"{line1} / {line2}".strip(" /")
        variant_lines.append(
            f"""
Variant {variant_id} ({marker})
Title:     {title_item.get("title", "")}
Angle:     {title_item.get("angle", thumb_item.get("angle", ""))}
Thumbnail: {thumb_copy}
File:      {output_file}
"""
        )

    body = f"""
Longform Video Published — {video_id}
{'='*48}
Title:       {title}
URL:         {youtube_url}
Primary:     Variant {primary_id}
Time:        {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

YouTube Studio Test & Compare package:
Upload the attached A/B/C thumbnails in this order if you want to run native thumbnail testing.
YouTube's public API only sets one thumbnail, so the pipeline uploaded the primary variant and attached all variants here for manual Studio testing.

{'='*48}
Title + thumbnail variants:
{''.join(variant_lines)}
{'='*48}
Description preview:
{str(metadata.get("description", ""))[:700]}
"""
    _send_email_with_attachments(f"{SUBJECT_PREFIX} Longform Published: {title[:50]}", body, attachments)


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
1. On your Mac, run:
   cd /Users/mayurdusane/Documents/finance-shorts-pipeline
   python tools/start_youtube_reauth.py
2. Log in with the correct YouTube channel Google account and click Allow
3. Re-run the failed pipeline

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
