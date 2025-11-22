import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask

import registration


class EarlyBirdAutoApplyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(registration.register_bp, url_prefix="/register")
        self.client = self.app.test_client()
        registration._BOOTCAMP_PRICE_CACHE["value"] = None
        registration._BOOTCAMP_PRICE_CACHE["expires_at"] = None

    def _mock_price_info(self, deadline_delta_hours: int) -> dict:
        return {
            "currency": "USD",
            "amount": 350,
            "early_bird_deadline": datetime.now(timezone.utc) + timedelta(hours=deadline_delta_hours),
        }

    def test_auto_applies_early_bird_before_deadline(self):
        price_info = self._mock_price_info(2)
        with patch("registration._get_bootcamp_price_info", return_value=price_info):
            resp = self.client.post("/register/price-preview", data={"course": registration.BOOTCAMP_CODE})
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["promo_applied"])
        self.assertTrue(payload["auto_applied"])
        self.assertEqual(payload["price_eur"], price_info["amount"])

    def test_does_not_apply_after_deadline(self):
        price_info = self._mock_price_info(-2)
        with patch("registration._get_bootcamp_price_info", return_value=price_info):
            resp = self.client.post("/register/price-preview", data={"course": registration.BOOTCAMP_CODE})
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertFalse(payload["promo_applied"])
        self.assertFalse(payload["auto_applied"])
        self.assertEqual(payload["price_eur"], price_info["amount"])


if __name__ == "__main__":
    unittest.main()
