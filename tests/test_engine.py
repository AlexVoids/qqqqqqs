import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine import (
    validate_url, url_overview, auth_like, safe_url_label,
    send_one, poll_delivery, validate_phone,
)

OAUTH_URL = (
    "https://oauth.telegram.org/auth/request?bot_id=466141824"
    "&origin=https%3A%2F%2Fmipped.com&embed=1"
    "&request_access=write"
    "&return_to=https%3A%2F%2Fmipped.com%2Ff%2Fregister%2Fconnected-accounts"
)


class EngineTests(unittest.TestCase):
    def test_oauth_long_url_accepted_without_reencoding(self):
        self.assertEqual(validate_url(OAUTH_URL), OAUTH_URL)
        self.assertEqual(url_overview(OAUTH_URL)["kind"], "browser")
        self.assertTrue(auth_like(OAUTH_URL))

    def test_no_oauth_requests(self):
        session = Mock()
        with self.assertRaises(ValueError):
            send_one(OAUTH_URL, "+12025550123", session=session)
        session.post.assert_not_called()

    def test_number_without_plus(self):
        self.assertEqual(validate_phone("33612345678").number, "+33612345678")
        self.assertEqual(validate_phone("+33612345678").number, "+33612345678")

    def test_own_api_form_post(self):
        session = Mock()
        session.post.return_value.status_code = 202
        session.post.return_value.json.return_value = {"message_id": "m123"}
        result = send_one(
            "https://sms.my-example.org/send?version=1&x=2",
            "+12025550123", session=session
        )
        self.assertEqual(result, {"status": 202, "accepted": True, "message_id": "m123"})
        kwargs = session.post.call_args.kwargs
        self.assertEqual(kwargs["data"], {"phone": "+12025550123"})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], 10)

    def test_digits_only_payload(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {}
        send_one("https://sms.my-example.org/send", "33612345678", session=session, without_plus=True)
        self.assertEqual(session.post.call_args.kwargs["data"], {"phone": "33612345678"})

    def test_delivery(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"status": "delivered"}
        result = poll_delivery("https://sms.my-example.org/status", "m123", session=session)
        self.assertEqual(result, "delivered")
        self.assertEqual(session.get.call_args.kwargs["params"], {"message_id": "m123"})

    def test_redact_query(self):
        self.assertEqual(safe_url_label("https://example.org/test?secret=123"), "example.org/test")

    def test_not_allow_http_or_userinfo(self):
        with self.assertRaises(ValueError):
            validate_url("http://example.com/test")
        with self.assertRaises(ValueError):
            validate_url("https://john:secret@example.com/test")


if __name__ == "__main__":
    unittest.main()
