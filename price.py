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
    "price_eur": 900,
    "currency": "EUR",
    "cover_url": None,  # optional override for hero image
}

@price_bp.get("/")          # <-- relative to /price
def price_page():
    return render_template("price.html", course=COURSE_INFO, PRICE_SYMBOL="€")

@price_bp.get("/api")       # <-- becomes /price/api
def price_api():
    return jsonify({
        "title": COURSE_INFO["title"],
        "subtitle": COURSE_INFO["subtitle"],
        "price": COURSE_INFO["price_eur"],
        "currency": COURSE_INFO["currency"],
    })
