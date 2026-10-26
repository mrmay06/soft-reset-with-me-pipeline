import unittest
from unittest.mock import patch

from utils.notify import send_auth_expiry_alert


class ReauthEmailTests(unittest.TestCase):
    def test_alert_uses_project_python(self):
        with patch("utils.notify._send_email") as send:
            send_auth_expiry_alert("Shorts uploader")
        subject, body = send.call_args.args
        self.assertIn("AUTH EXPIRED", subject)
        self.assertIn("cd /Users/mayurdusane/Documents/Relation-shots", body)
        self.assertIn("./venv/bin/python tools/start_youtube_reauth.py", body)
        self.assertNotIn("python3 tools/start_youtube_reauth.py", body)
        self.assertIn("click Allow", body)
