"""Shared course configuration pulled from environment variables."""
import os

def _bool_env(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

BOOTCAMP_CODE = os.getenv("BOOTCAMP_CODE", "BOOT-AI-2024")
BOOTCAMP_PRICE_EUR = int(os.getenv("BOOTCAMP_PRICE_EUR", "350"))
BOOTCAMP_SEAT_CAP = int(os.getenv("BOOTCAMP_SEAT_CAP", "20"))
BOOTCAMP_PUBLIC_REGISTRATION = _bool_env("BOOTCAMP_PUBLIC_REGISTRATION", "true")
