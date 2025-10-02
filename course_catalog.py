"""Shared course catalog configuration.

This module centralizes course metadata that needs to stay in sync across
marketing pages and transactional flows.
"""
from __future__ import annotations

import os

BOOTCAMP_CODE = "BOOT-AI-2024"
BOOTCAMP_PRICE_EUR = int(os.getenv("BOOTCAMP_PRICE_EUR", "350"))
BOOTCAMP_SEAT_CAP = int(os.getenv("BOOTCAMP_SEAT_CAP", "20"))

BOOTCAMP_COURSE = {
    "code": BOOTCAMP_CODE,
    "title": f"AI Implementation Bootcamp ({BOOTCAMP_SEAT_CAP} seats)",
    "price_eur": BOOTCAMP_PRICE_EUR,
    "seat_cap": BOOTCAMP_SEAT_CAP,
    "note": (
        "4-day cohort · {seat_cap} seats · €{price} per learner".format(
            seat_cap=BOOTCAMP_SEAT_CAP,
            price=BOOTCAMP_PRICE_EUR,
        )
    ),
    "open_enrollment": True,
}

OPEN_ENROLLMENT_CODES = {BOOTCAMP_CODE}

__all__ = [
    "BOOTCAMP_CODE",
    "BOOTCAMP_PRICE_EUR",
    "BOOTCAMP_SEAT_CAP",
    "BOOTCAMP_COURSE",
    "OPEN_ENROLLMENT_CODES",
]
