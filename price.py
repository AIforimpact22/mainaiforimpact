# price.py
from datetime import datetime
from flask import Blueprint, render_template, jsonify

price_bp = Blueprint("price", __name__)

COURSE_INFO = {
    "slug": "advanced-ai-utilization",
    "title": "Advanced AI Utilization and Real-Time Deployment",
    "subtitle": (
        "Private sessions customized to your goals, supported by a guided portal "
        "that documents the workflow step-by-step."
    ),
    "price_eur": 900,
    "currency": "EUR",
    "cover_url": None,  # optional override for hero image
    "early_bird_price": 750,
    "early_bird_deadline": "2025-12-20T00:00:00Z",
}

def _format_deadline(raw: str | None) -> str:
    """Convert a stored deadline string into a short friendly date."""
    if not raw:
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    candidate = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(candidate, fmt)
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return raw

def _currency_symbol(currency: str | None) -> str:
    lookup = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3", "CAD": "$", "AUD": "$"}
    if not currency:
        return ""
    return lookup.get(currency.upper(), currency.upper())

def _course_payload() -> dict:
    """Return a shallow copy of COURSE_INFO enriched with formatted dates."""
    data = dict(COURSE_INFO)
    if data.get("early_bird_deadline"):
        data["early_bird_deadline_display"] = _format_deadline(data.get("early_bird_deadline"))
    return data

@price_bp.get("/")          # <-- relative to /price
def price_page():
    course = _course_payload()
    return render_template(
        "price.html",
        course=course,
        PRICE_SYMBOL=_currency_symbol(course.get("currency")),
    )

@price_bp.get("/api")       # <-- becomes /price/api
def price_api():
    course = _course_payload()
    return jsonify({
        "title": course["title"],
        "subtitle": course["subtitle"],
        "price": course["price_eur"],
        "currency": course["currency"],
        "early_bird_price": course.get("early_bird_price"),
        "early_bird_deadline": course.get("early_bird_deadline"),
    })

