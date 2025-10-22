# price.py
from flask import Blueprint, render_template, jsonify

price_bp = Blueprint("price", __name__)

COURSE_INFO = {
    "slug": "one-on-one-tailored-training",
    "title": "One on one Tailored Training Session",
    "subtitle": (
        "Private sessions customized to your goals, supported by a guided portal "
        "that documents the workflow step‑by‑step."
    ),
    "price_eur": None,  # populated from the first bootcamp session
    "currency": "EUR",
    "cover_url": None,  # optional override for hero image
}


def _currency_symbol(code: str) -> str:
    """Return a currency symbol for the given ISO code."""

    mapping = {
        "EUR": "€",
        "USD": "$",
        "GBP": "£",
    }
    return mapping.get(code.upper(), code.upper())


BOOTCAMP_SESSIONS = [
    {
        "id": "erbil-2026-01",
        "city": "Erbil",
        "country": "Iraq",
        "location": "Erbil",
        "label": "Erbil · January 2026",
        "start_date": "January 2026",
        "price_eur": 350,
        "currency": "EUR",
        "price_symbol": _currency_symbol("EUR"),
        "spots_label": "Per seat",
    }
]

if BOOTCAMP_SESSIONS:
    COURSE_INFO["price_eur"] = BOOTCAMP_SESSIONS[0]["price_eur"]
    COURSE_INFO["currency"] = BOOTCAMP_SESSIONS[0]["currency"]

@price_bp.get("/")          # <-- relative to /price
def price_page():
    return render_template(
        "price.html",
        course=COURSE_INFO,
        PRICE_SYMBOL=_currency_symbol(COURSE_INFO["currency"]),
        bootcamp_sessions=BOOTCAMP_SESSIONS,
    )

@price_bp.get("/api")       # <-- becomes /price/api
def price_api():
    return jsonify(
        {
            "title": COURSE_INFO["title"],
            "subtitle": COURSE_INFO["subtitle"],
            "price": COURSE_INFO["price_eur"],
            "currency": COURSE_INFO["currency"],
            "sessions": BOOTCAMP_SESSIONS,
        }
    )
