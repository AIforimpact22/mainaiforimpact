import unittest
from datetime import datetime, timedelta, timezone

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


if __name__ == "__main__":
    unittest.main()
