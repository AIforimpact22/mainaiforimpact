"""Bootcamp landing page blueprint."""
from flask import Blueprint, render_template, jsonify

from course_settings import (
    BOOTCAMP_CODE,
    BOOTCAMP_PRICE_EUR,
    BOOTCAMP_SEAT_CAP,
)

bootcamp_bp = Blueprint("bootcamp", __name__)

BOOTCAMP_INFO = {
    "slug": "ai-implementation-bootcamp",
    "code": BOOTCAMP_CODE,
    "title": "AI Implementation Bootcamp",
    "subtitle": (
        "Four-day cohort focused on shipping AI-powered products with peers, guided by "
        "experts who work in production every day."
    ),
    "price_eur": BOOTCAMP_PRICE_EUR,
    "currency": "EUR",
    "seat_cap": BOOTCAMP_SEAT_CAP,
    "cover_url": None,
    "features": [
        "4 immersive days that blend morning theory with afternoon build labs.",
        "Hands-on practice with real tooling so you leave with working assets.",
        "Project-based learning culminating in a mentored capstone showcase.",
        "Certificate of completion highlighting your applied AI skills.",
        "Session recordings and templates you can revisit long after the cohort.",
    ],
    "daily_flow": [
        {
            "title": "Day 1 · Foundations & Collaboration",
            "copy": "Kickoff, ice breakers, and Modules 1–3. We align on goals and pair up for peer feedback.",
        },
        {
            "title": "Day 2 · Systems & Deployment",
            "copy": "Deep work on databases and shipping to servers (Modules 4–5) with guided labs.",
        },
        {
            "title": "Day 3 · Data Stories & Intelligence",
            "copy": "Visualizations, real-time dashboards, and machine learning predictions (Modules 6–7).",
        },
        {
            "title": "Day 4 · Operational LLMs & Capstone",
            "copy": "Operational LLM patterns (Module 8) plus a mentored capstone sprint and showcase before we close the cohort.",
        },
    ],
    "modules": [
        "Ice Breaker for Coding – intro activities that build confidence and collaboration.",
        "Start Coding with AI – practical workflows for working alongside assistants.",
        "Modularity – structuring clean, reusable components that scale.",
        "Advanced SQL and Databases – deep dives into querying and modeling data.",
        "Deploy App with Server – packaging and launching apps to live environments.",
        "Data Visualization & Real-Time – streaming insights and dashboards people actually use.",
        "Machine Learning Prediction – building, evaluating, and deploying predictive models.",
        "Operational LLMs – using large language models for explanation, extraction, and automation.",
        "Capstone Project – Day 4 build sprint that blends every module into a shipped asset you can present immediately.",
    ],
    "faqs": [
        {
            "q": "Who is the Bootcamp designed for?",
            "a": "Engineers, analysts, operators, and founders who want to build AI-driven products quickly with real guidance.",
        },
        {
            "q": "What are the schedule and format?",
            "a": "We meet for four consecutive days with live theory, guided labs, and project clinics. Recordings are provided each day.",
        },
        {
            "q": "Do I need prior AI experience?",
            "a": "You should be comfortable with basic scripting. We cover cutting-edge AI tooling step-by-step so you can ship confidently.",
        },
        {
            "q": "How do I secure a seat?",
            "a": (
                "Submit the registration form—seats are confirmed on a first-come basis and "
                f"we cap enrollment at {BOOTCAMP_SEAT_CAP} learners per cohort."
            ),
        },
    ],
}


@bootcamp_bp.get("/")
def bootcamp_page():
    return render_template("bootcamp.html", bootcamp=BOOTCAMP_INFO, PRICE_SYMBOL="€")


@bootcamp_bp.get("/api")
def bootcamp_api():
    return jsonify({
        "title": BOOTCAMP_INFO["title"],
        "subtitle": BOOTCAMP_INFO["subtitle"],
        "price": BOOTCAMP_INFO["price_eur"],
        "currency": BOOTCAMP_INFO["currency"],
        "seat_cap": BOOTCAMP_INFO["seat_cap"],
    })
