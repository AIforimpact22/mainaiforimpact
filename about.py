# about.py
from flask import Blueprint, render_template

about_bp = Blueprint("about", __name__, template_folder="templates")

@about_bp.get("/")
def page():
    context = {
        "tutor_name": "Hawkar Ali Abdulhaq",
        "tutor_tagline": "PhD Candidate — Machine Learning for Geothermal Data",
        "origin_blurb": (
            "During my PhD I focused on reducing processing time in geothermal data by building machine learning models. "
            "Designing a surgeon model in that research led me to create this course: a practical, one-on-one pathway to ship real outcomes."
        ),

        "linkedin_url": "https://www.linkedin.com/in/habdulhaq/",
        "scholar_url": "https://scholar.google.com/citations?hl=en&user=aaBj5v8AAAAJ&view_op=list_works&sortby=pubdate",
        "research_count": 26,

        "value_props": [
            "Tailored 1-on-1 sessions",
            "Limited seats",
            "Proven impact (25 alumni)",
            "PhD-backed method",
            "Backed by a step-by-step learning portal",
            "Certificate offered upon completion & satisfaction",
        ],

        "price_eur": 900,
        "philosophy": (
            "Deliver the best-quality learning experience that transforms how you handle problems "
            "and how you set strategy—so you can operate with clarity, not noise."
        ),
        "audience": (
            "Individuals aiming to upskill and corporate teams that want measurable progress without getting lost in AI."
        ),

        "climate_note": (
            "I believe in climate action. I support climate NGOs by offering reduced-rate seats to help them use AI "
            "to bolster their impact."
        ),
        "experience_blurb": (
            "I work across business, climate, energy, and academia—so I can understand your data context quickly "
            "and translate it into a practical workflow."
        ),

        "business_name": "Climate Resilience Fundraising Platform B.V.",
        "business_address": [
            "Fluwelen Burgwal 58",
            "The Hague",
            "The Netherlands",
            "2511CJ",
        ],
    }
    return render_template("about.html", **context)
