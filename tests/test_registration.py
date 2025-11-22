import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import registration


class BootcampPromoTests(unittest.TestCase):
    def test_bootcamp_early_bird_active_before_deadline(self):
        now = datetime.now(timezone.utc)
        price_info = {"early_bird_deadline": now + timedelta(days=1)}

        self.assertTrue(registration._bootcamp_early_bird_is_active(price_info, now=now))

    def test_bootcamp_early_bird_inactive_after_deadline(self):
        now = datetime.now(timezone.utc)
        price_info = {"early_bird_deadline": now - timedelta(minutes=1)}

        self.assertFalse(registration._bootcamp_early_bird_is_active(price_info, now=now))

    def test_auto_apply_bootcamp_promo_respects_user_input(self):
        now = datetime.now(timezone.utc)
        price_info = {"early_bird_deadline": now + timedelta(days=1)}

        user_code = "USERCODE"
        self.assertEqual(
            registration._auto_apply_bootcamp_promo(user_code, registration.BOOTCAMP_CODE, price_info, now=now),
            user_code,
        )

    def test_auto_apply_bootcamp_promo_only_when_eligible(self):
        now = datetime.now(timezone.utc)
        active_price_info = {"early_bird_deadline": now + timedelta(days=1)}
        expired_price_info = {"early_bird_deadline": now - timedelta(days=1)}

        self.assertEqual(
            registration._auto_apply_bootcamp_promo(None, registration.BOOTCAMP_CODE, active_price_info, now=now),
            registration.PROMO_CODE,
        )

        self.assertIsNone(
            registration._auto_apply_bootcamp_promo(None, registration.BOOTCAMP_CODE, expired_price_info, now=now)
        )

    @patch("registration.summarize_bootcamp_price")
    @patch("registration._fetch_bootcamp_seat_prices")
    def test_resolve_bootcamp_price_uses_offer_deadline_when_group_missing(self, mock_fetch, mock_summarize):
        now = datetime.now(timezone.utc)
        early_valid_to = now + timedelta(days=3)
        early_offer = {
            "price_type_key": "early-bird",
            "price": 200,
            "price_display": "$200 early bird",
            "valid_from": now - timedelta(days=1),
            "valid_to": early_valid_to,
            "valid_to_display": "Mar 10, 2025",
        }

        mock_fetch.return_value = [
            {
                "currency": "USD",
                "early_bird_deadline": None,
                "offers": [early_offer],
            }
        ]
        mock_summarize.return_value = None

        price_info = registration._resolve_bootcamp_price_info()

        self.assertEqual(price_info.get("early_bird_deadline"), early_valid_to)
        self.assertEqual(price_info.get("early_bird_deadline_display"), "Mar 10, 2025")

    @patch("registration.summarize_bootcamp_price")
    @patch("registration._fetch_bootcamp_seat_prices")
    def test_resolve_bootcamp_price_prefers_group_deadline(self, mock_fetch, mock_summarize):
        now = datetime.now(timezone.utc)
        group_deadline = now + timedelta(days=5)
        early_offer = {
            "price_type_key": "early-bird",
            "price": 200,
            "valid_from": now - timedelta(days=1),
            "valid_to": now + timedelta(days=2),
        }

        mock_fetch.return_value = [
            {
                "currency": "USD",
                "early_bird_deadline": group_deadline,
                "offers": [early_offer],
            }
        ]
        mock_summarize.return_value = None

        price_info = registration._resolve_bootcamp_price_info()

        self.assertEqual(price_info.get("early_bird_deadline"), group_deadline)


if __name__ == "__main__":
    unittest.main()
