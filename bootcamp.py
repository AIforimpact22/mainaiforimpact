"""Bootcamp landing page blueprint."""
from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict, Tuple

from flask import Blueprint, render_template, jsonify, request, url_for, redirect

from course_settings import (
    BOOTCAMP_CODE,
    BOOTCAMP_PRICE_EUR,
    BOOTCAMP_SEAT_CAP,
)

bootcamp_bp = Blueprint("bootcamp", __name__)

log = logging.getLogger(__name__)

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "smtp").strip().lower()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "connect@aiforimpact.net")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "rgbvcjfocqpmjipy")
SMTP_FROM = os.getenv("SMTP_FROM", "AiForImpact <connect@aiforimpact.net>")
BOOTCAMP_REQUEST_TO = os.getenv("BOOTCAMP_REQUEST_TO", "connect@aiforimpact.net")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
    status = request.args.get("request")
    success = status == "sent"
    return _render_bootcamp_page({}, [], success)


def _render_bootcamp_page(
    form_data: Dict[str, str],
    errors: Tuple[str, ...] | list[str],
    success: bool,
):
    return render_template(
        "bootcamp.html",
        bootcamp=BOOTCAMP_INFO,
        PRICE_SYMBOL="€",
        request_form=form_data or {},
        request_errors=list(errors or []),
        request_success=bool(success),
    )


@bootcamp_bp.post("/request")
def request_cohort_quote():
    form = {k: (request.form.get(k) or "").strip() for k in [
        "company_name",
        "contact_name",
        "contact_email",
        "team_size",
        "timeline",
        "goals",
        "notes",
    ]}

    errors = []
    if not form["company_name"]:
        errors.append("Company name is required.")
    if not form["contact_name"]:
        errors.append("Contact name is required.")
    if not form["contact_email"]:
        errors.append("Contact email is required.")
    elif not _EMAIL_RE.match(form["contact_email"]):
        errors.append("Contact email must be valid.")

    if form["team_size"] and not form["team_size"].isdigit():
        errors.append("Team size must be a number.")

    if errors:
        return _render_bootcamp_page(form, errors, False)

    email_ok = _send_bootcamp_request_email(form)
    if not email_ok:
        errors.append("We could not send your request right now. Please try again or email connect@aiforimpact.net.")
        return _render_bootcamp_page(form, errors, False)

    return redirect(url_for("bootcamp.bootcamp_page", request="sent"))


@bootcamp_bp.get("/api")
def bootcamp_api():
    return jsonify({
        "title": BOOTCAMP_INFO["title"],
        "subtitle": BOOTCAMP_INFO["subtitle"],
        "price": BOOTCAMP_INFO["price_eur"],
        "currency": BOOTCAMP_INFO["currency"],
        "seat_cap": BOOTCAMP_INFO["seat_cap"],
    })


def _send_bootcamp_request_email(payload: Dict[str, str]) -> bool:
    if EMAIL_BACKEND != "smtp":
        log.warning("Bootcamp request email skipped: EMAIL_BACKEND=%s", EMAIL_BACKEND)
        return False
    if not (SMTP_USERNAME and SMTP_PASSWORD and BOOTCAMP_REQUEST_TO):
        log.warning("Bootcamp request email skipped: SMTP not fully configured")
        return False

    subject = f"Bootcamp cohort request — {payload['company_name']}"
    team_size = payload.get("team_size") or "N/A"
    timeline = payload.get("timeline") or "N/A"
    goals = payload.get("goals") or "N/A"
    notes = payload.get("notes") or "N/A"

    text_body = (
        "A company submitted a bootcamp cohort request.\n\n"
        f"Company: {payload['company_name']}\n"
        f"Contact: {payload['contact_name']}\n"
        f"Email: {payload['contact_email']}\n"
        f"Team size: {team_size}\n"
        f"Timeline: {timeline}\n"
        f"Goals: {goals}\n"
        f"Notes: {notes}\n"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM or SMTP_USERNAME
    message["To"] = BOOTCAMP_REQUEST_TO
    message["Reply-To"] = payload["contact_email"]
    message.set_content(text_body)

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as smtp:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        log.info("Bootcamp cohort request email sent to %s", BOOTCAMP_REQUEST_TO)
        return True
    except Exception:
        log.exception("Failed to send bootcamp cohort request email")
        return False
