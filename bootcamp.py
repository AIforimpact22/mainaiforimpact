"""Bootcamp landing page blueprint."""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Optional, Tuple

from flask import Blueprint, render_template, jsonify, request, url_for, redirect

from course_settings import (
    BOOTCAMP_CODE,
    BOOTCAMP_PRICE_EUR,
    BOOTCAMP_SEAT_CAP,
)

bootcamp_bp = Blueprint("bootcamp", __name__)

log = logging.getLogger(__name__)

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "smtp").strip().lower()


def _get_env_setting(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is None:
        return default.strip()
    return value.strip()


def _load_secret_file(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        log.warning("Unable to read secret file %s", path)
        return ""


SMTP_HOST = _get_env_setting("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_get_env_setting("SMTP_PORT", "465"))
SMTP_TIMEOUT_RAW = _get_env_setting("SMTP_TIMEOUT")
try:
    SMTP_TIMEOUT = float(SMTP_TIMEOUT_RAW) if SMTP_TIMEOUT_RAW else None
except ValueError:
    log.warning("Invalid SMTP_TIMEOUT value %s; ignoring", SMTP_TIMEOUT_RAW)
    SMTP_TIMEOUT = None
SMTP_USERNAME = _get_env_setting("SMTP_USERNAME", "connect@aiforimpact.net")

_smtp_password = _get_env_setting("SMTP_PASSWORD")
if not _smtp_password:
    _smtp_password = _load_secret_file(_get_env_setting("SMTP_PASSWORD_FILE"))
if not _smtp_password:
    _smtp_password = _get_env_setting("SMTP_APP_PASSWORD")
SMTP_PASSWORD = _smtp_password

SMTP_FROM = _get_env_setting("SMTP_FROM", "AiForImpact <connect@aiforimpact.net>")
BOOTCAMP_REQUEST_TO = _get_env_setting("BOOTCAMP_REQUEST_TO", "connect@aiforimpact.net")
_smtp_starttls_default = "true" if SMTP_PORT not in (25, 2525, 465) else "false"
SMTP_STARTTLS = _get_env_setting("SMTP_STARTTLS", _smtp_starttls_default).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SMTP_AUTH_METHOD = _get_env_setting("SMTP_AUTH_METHOD").upper()
_archive_path = os.getenv("BOOTCAMP_REQUEST_ARCHIVE", "instance/bootcamp_requests.jsonl").strip()
BOOTCAMP_REQUEST_ARCHIVE: Optional[Path] = Path(_archive_path) if _archive_path else None

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
        "timeline_start",
        "timeline_end",
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

    timeline_start_raw = form.get("timeline_start") or ""
    timeline_end_raw = form.get("timeline_end") or ""
    timeline_start = timeline_end = None
    if timeline_start_raw and not timeline_end_raw:
        errors.append("Please select an end date for your preferred timeline.")
    elif timeline_end_raw and not timeline_start_raw:
        errors.append("Please select a start date for your preferred timeline.")
    elif timeline_start_raw and timeline_end_raw:
        try:
            timeline_start = datetime.strptime(timeline_start_raw, "%Y-%m-%d").date()
            timeline_end = datetime.strptime(timeline_end_raw, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Preferred dates must be valid calendar dates.")
        else:
            if timeline_end < timeline_start:
                errors.append("Preferred end date must be on or after the start date.")
            else:
                form["timeline_start"] = timeline_start.isoformat()
                form["timeline_end"] = timeline_end.isoformat()

    if errors:
        return _render_bootcamp_page(form, errors, False)

    delivery_ok, email_sent = _deliver_bootcamp_request(form)
    if not delivery_ok:
        errors.append(
            "We could not record your request right now. Please try again or email connect@aiforimpact.net."
        )
        return _render_bootcamp_page(form, errors, False)

    if not email_sent:
        log.warning(
            "Bootcamp request email delivery failed; payload archived for manual follow-up."
        )

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


def _deliver_bootcamp_request(payload: Dict[str, str]) -> Tuple[bool, bool]:
    archived = _archive_bootcamp_request(payload)
    email_sent = _send_bootcamp_request_email(payload)

    if not archived and not email_sent:
        log.error("Bootcamp cohort request lost: unable to archive or send email.")

    return archived or email_sent, email_sent


def _archive_bootcamp_request(payload: Dict[str, str]) -> bool:
    try:
        if not BOOTCAMP_REQUEST_ARCHIVE:
            return False

        BOOTCAMP_REQUEST_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        with BOOTCAMP_REQUEST_ARCHIVE.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")

        log.debug("Bootcamp request archived to %s", BOOTCAMP_REQUEST_ARCHIVE)
        return True
    except Exception:
        log.exception("Failed to archive bootcamp cohort request locally")
        return False


def _format_preferred_dates(start_raw: str, end_raw: str) -> str:
    if not start_raw and not end_raw:
        return "N/A"

    def _humanize(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            return value

    if start_raw and end_raw:
        return f"{_humanize(start_raw)} → {_humanize(end_raw)}"
    if start_raw:
        return _humanize(start_raw)
    return _humanize(end_raw)


def _smtp_authenticate(session: smtplib.SMTP, username: str, password: str) -> None:
    session.user, session.password = username, password
    if SMTP_AUTH_METHOD:
        method = SMTP_AUTH_METHOD.replace("-", "_")
        auth_callable = getattr(session, f"auth_{method.lower()}", None)
        if not auth_callable:
            raise smtplib.SMTPException(
                f"SMTP auth method {SMTP_AUTH_METHOD} is not supported by smtplib"
            )
        session.auth(SMTP_AUTH_METHOD, auth_callable)
    else:
        session.login(username, password)


def _send_bootcamp_request_email(payload: Dict[str, str]) -> bool:
    if EMAIL_BACKEND != "smtp":
        log.warning("Bootcamp request email skipped: EMAIL_BACKEND=%s", EMAIL_BACKEND)
        return False
    if not (SMTP_USERNAME and SMTP_PASSWORD and BOOTCAMP_REQUEST_TO):
        log.warning("Bootcamp request email skipped: SMTP not fully configured")
        return False

    subject = f"Bootcamp cohort request — {payload['company_name']}"
    team_size = payload.get("team_size") or "N/A"
    timeline = _format_preferred_dates(
        payload.get("timeline_start") or "",
        payload.get("timeline_end") or "",
    )
    goals = payload.get("goals") or "N/A"
    notes = payload.get("notes") or "N/A"

    text_body = (
        "A company submitted a bootcamp cohort request.\n\n"
        f"Company: {payload['company_name']}\n"
        f"Contact: {payload['contact_name']}\n"
        f"Email: {payload['contact_email']}\n"
        f"Team size: {team_size}\n"
        f"Preferred dates: {timeline}\n"
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
            if SMTP_STARTTLS:
                log.debug(
                    "SMTP_STARTTLS is enabled but port is 465; implicit TLS connection will be used"
                )
            with smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=SMTP_TIMEOUT
            ) as smtp:
                _smtp_authenticate(smtp, SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
                if SMTP_STARTTLS:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                _smtp_authenticate(smtp, SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        log.info("Bootcamp cohort request email sent to %s", BOOTCAMP_REQUEST_TO)
        return True
    except Exception:
        log.exception("Failed to send bootcamp cohort request email")
        return False
