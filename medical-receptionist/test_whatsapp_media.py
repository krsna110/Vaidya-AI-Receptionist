import hashlib
import hmac
import os
import unittest

os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")

from whatsapp_routes import _is_allowed_media_url, _mime_type, _valid_signature


class WhatsAppMediaHelpersTest(unittest.TestCase):
    def test_mime_parameters_are_removed(self):
        self.assertEqual(_mime_type("audio/ogg; codecs=opus"), "audio/ogg")

    def test_media_url_accepts_https_meta_hosts(self):
        self.assertTrue(_is_allowed_media_url("https://lookaside.fbsbx.com/media/example"))

    def test_media_url_rejects_http_and_untrusted_hosts(self):
        self.assertFalse(_is_allowed_media_url("http://lookaside.fbsbx.com/media/example"))
        self.assertFalse(_is_allowed_media_url("https://evilfacebook.com/media/example"))
        self.assertFalse(_is_allowed_media_url("https://example.com/media/example"))

    def test_signature_accepts_correct_hmac(self):
        body = b'{"object":"whatsapp_business_account"}'
        signature = "sha256=" + hmac.new(
            b"test-secret", body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(_valid_signature(body, signature))

    def test_signature_rejects_wrong_hmac(self):
        self.assertFalse(_valid_signature(b"body", "sha256=not-the-right-signature"))

    def test_signature_requires_header(self):
        self.assertFalse(_valid_signature(b"body", None))


if __name__ == "__main__":
    unittest.main()
