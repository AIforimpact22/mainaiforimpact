"""Bootcamp landing page blueprint."""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import (
    Blueprint,
    render_template,
    jsonify,
    request,
    url_for,
    redirect,
    current_app,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
        "Two-day cohort focused on shipping AI-powered products with peers, guided by "
        "experts who work in production every day."
    ),
    "price_eur": BOOTCAMP_PRICE_EUR,
    "currency": "EUR",
    "seat_cap": BOOTCAMP_SEAT_CAP,
    "cover_url": "https://i.imgur.com/Amgeg9j.jpeg",
    "features": [
        "2 immersive days that blend morning theory with afternoon build labs.",
        "Hands-on practice with real tooling so you leave with working assets.",
        "Project-based learning culminating in a mentored capstone showcase.",
        "Certificate of completion highlighting your applied AI skills.",
        "Session recordings and templates you can revisit long after the cohort.",
    ],
    "audience": [
        "Researchers turning datasets into tools",
        "Entrepreneurs prototyping AI products",
        "Analysts/engineers upskilling to applied AI",
    ],
    "logistics": {
        "prereqs": "Basic Python helpful (not required).",
        "equipment": "Bring a laptop; accounts: GitHub.",
    },
    "daily_flow": [
        {
            "title": "Day 1 · Foundations to Deployment",
            "description": (
                "Kickoff, team formation, and Modules 1–6. We move from core collaboration habits "
                "through modular coding, advanced SQL, deployment, and real-time dashboards with guided labs."
            ),
        },
        {
            "title": "Day 2 · Intelligence & Capstone",
            "description": (
                "Modules 7–9 focus on machine learning predictions, operational LLM workflows, and an intensive "
                "capstone build sprint that culminates in peer demos and feedback."
            ),
        },
    ],
    "modules": [
        {
            "title": "Module 1: Ice Breaker for Coding",
            "description": "Intro activities that build confidence and collaboration.",
            "lessons_count": None,
        },
        {
            "title": "Module 2: Start Coding with AI",
            "description": "Practical workflows for working alongside assistants.",
            "lessons_count": None,
        },
        {
            "title": "Module 3: Modularity",
            "description": "Structuring clean, reusable components that scale.",
            "lessons_count": None,
        },
        {
            "title": "Module 4: Advanced SQL and Databases",
            "description": "Deep dives into querying and modeling data.",
            "lessons_count": None,
        },
        {
            "title": "Module 5: Deploy App with Server",
            "description": "Packaging and launching apps to live environments.",
            "lessons_count": None,
        },
        {
            "title": "Module 6: Data Visualization & Real-Time",
            "description": "Streaming insights and dashboards people actually use.",
            "lessons_count": None,
        },
        {
            "title": "Module 7: Machine Learning Prediction",
            "description": "Building, evaluating, and deploying predictive models.",
            "lessons_count": None,
        },
        {
            "title": "Module 8: Operational LLMs",
            "description": "Using large language models for explanation, extraction, and automation.",
            "lessons_count": None,
        },
        {
            "title": "Week 9: Capstone Project",
            "description": "Day 2 build sprint that blends every module into a shipped asset you can present immediately.",
            "lessons_count": None,
        },
    ],
    "faqs": [
        {
            "q": "Who is the Bootcamp designed for?",
            "a": "Engineers, analysts, operators, and founders who want to build AI-driven products quickly with real guidance.",
        },
        {
            "q": "What are the schedule and format?",
            "a": "We meet for two consecutive days with live theory, guided labs, and project clinics. Recordings are provided each day.",
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
    "testimonials": [],
}

DEFAULT_DAY_TITLES = (
    "Day 1 · Foundations to Deployment",
    "Day 2 · Intelligence & Capstone",
)


def _resolve_db_engine():
    try:
        engine = current_app.config.get("DB_ENGINE")  # type: ignore[attr-defined]
    except RuntimeError:
        engine = None

    if engine is None:
        try:
            from main import ENGINE as default_engine  # type: ignore
        except ImportError:
            default_engine = None
        engine = default_engine

    return engine


def _get_bootcamp_vm() -> Dict[str, object]:
    vm = copy.deepcopy(BOOTCAMP_INFO)
    curriculum = _fetch_curriculum_from_backend()
    if curriculum:
        modules = curriculum.get("modules")
        daily_flow = curriculum.get("daily_flow")
        if modules:
            vm["modules"] = modules
        if daily_flow:
            vm["daily_flow"] = daily_flow
    vm["testimonials"] = _fetch_bootcamp_testimonials()
    return vm


def _fetch_curriculum_from_backend() -> Optional[Dict[str, object]]:
    engine = _resolve_db_engine()

    if engine is None:
        return None

    lookup_title = os.getenv("BOOTCAMP_CURRICULUM_TITLE", "").strip()
    fallback_title = os.getenv("COURSE_TITLE", "").strip()
    lookup_title = lookup_title or fallback_title

    query = text(
        """
        SELECT id, title, structure
        FROM courses
        WHERE (:title = '' OR title ILIKE :title)
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
        """
    )
    published_fallback = text(
        """
        SELECT id, title, structure
        FROM courses
        WHERE is_published = TRUE
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
        """
    )

    try:
        with engine.begin() as conn:
            row = conn.execute(query, {"title": lookup_title}).mappings().first()
            if not row:
                row = conn.execute(published_fallback).mappings().first()
            if not row:
                return None
            structure_raw = row.get("structure")
    except SQLAlchemyError:
        log.exception("Failed to fetch bootcamp curriculum from backend")
        return None

    structure: Dict[str, object] = {}
    if isinstance(structure_raw, dict):
        structure = structure_raw
    elif isinstance(structure_raw, (bytes, bytearray, memoryview)):
        try:
            structure = json.loads(bytes(structure_raw).decode("utf-8"))
        except json.JSONDecodeError:
            log.warning("Bootcamp curriculum payload was not valid JSON")
    elif isinstance(structure_raw, str):
        try:
            structure = json.loads(structure_raw)
        except json.JSONDecodeError:
            log.warning("Bootcamp curriculum payload was not valid JSON")

    if not structure:
        return None

    sections = structure.get("sections") if isinstance(structure, dict) else []
    if not isinstance(sections, list):
        sections = []

    ordered_sections = sorted(
        (
            s
            for s in sections
            if isinstance(s, dict)
        ),
        key=lambda s: (s.get("order") is None, s.get("order", 0)),
    )

    modules: list[Dict[str, object]] = []
    for index, section in enumerate(ordered_sections, start=1):
        title = section.get("title") or f"Module {index}"
        title_str = str(title)
        display_title = (
            f"Module {index}: {title_str}"
            if not title_str.lower().startswith(("module ", "week "))
            else title_str
        )
        summary = section.get("summary") or section.get("description")
        lessons = section.get("lessons") or []
        lessons_count = None
        if isinstance(lessons, list):
            if lessons:
                lessons_count = len(lessons)
        else:
            raw_count = section.get("lessons_count")
            if isinstance(raw_count, int):
                lessons_count = raw_count

        modules.append(
            {
                "title": display_title,
                "description": summary.strip() if isinstance(summary, str) and summary.strip() else None,
                "lessons_count": lessons_count,
            }
        )

    if not modules:
        return None

    daily_flow = _build_daily_flow(modules)
    return {"modules": modules, "daily_flow": daily_flow}


def _format_certificate_date(value: Any) -> str:
    if not value:
        return ""
    try:
        return value.strftime("%b %Y")  # type: ignore[attr-defined]
    except Exception:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        else:
            return parsed.strftime("%b %Y")


def _fetch_bootcamp_testimonials(limit: int = 6) -> list[dict[str, str]]:
    engine = _resolve_db_engine()
    if engine is None:
        return []

    query = text(
        """
        SELECT id, full_name, credential, certificate_url, testimony, date_of_completion
        FROM training_certificates
        WHERE testimony IS NOT NULL AND btrim(testimony) <> ''
        ORDER BY date_of_completion DESC NULLS LAST, id DESC
        LIMIT :limit
        """
    )

    testimonials: list[dict[str, str]] = []

    try:
        with engine.begin() as conn:
            rows = conn.execute(query, {"limit": limit}).mappings().all()
    except SQLAlchemyError:
        log.exception("Failed to fetch bootcamp testimonials from backend")
        return []

    for row in rows:
        testimony_raw = row.get("testimony")
        testimony = str(testimony_raw).strip() if testimony_raw is not None else ""
        if not testimony:
            continue

        full_name_raw = row.get("full_name")
        credential_raw = row.get("credential")
        certificate_url_raw = row.get("certificate_url")
        completed_raw = row.get("date_of_completion")

        testimonials.append(
            {
                "full_name": (str(full_name_raw).strip() if full_name_raw else "Bootcamp graduate"),
                "credential": str(credential_raw).strip() if credential_raw else "",
                "certificate_url": str(certificate_url_raw).strip() if certificate_url_raw else "",
                "testimony": testimony,
                "completed": _format_certificate_date(completed_raw),
            }
        )

    return testimonials


def _join_titles(titles: list[str]) -> str:
    if not titles:
        return ""
    if len(titles) == 1:
        return titles[0]
    if len(titles) == 2:
        return f"{titles[0]} and {titles[1]}"
    return ", ".join(titles[:-1]) + f", and {titles[-1]}"


def _build_daily_flow(modules: list[Dict[str, object]]) -> list[Dict[str, str]]:
    day_one_modules = modules[:6]
    day_two_modules = modules[6:]

    flow: list[Dict[str, str]] = []

    if day_one_modules:
        names = []
        for module in day_one_modules:
            mt = module.get("title")
            if isinstance(mt, str):
                parts = mt.split(": ", 1)
                names.append(parts[1] if len(parts) == 2 else parts[0])
        desc_titles = _join_titles([n for n in names if n])
        description = (
            f"Kickoff, labs, and collaborative builds across {desc_titles}."
            if desc_titles
            else BOOTCAMP_INFO["daily_flow"][0]["description"]
        )
        flow.append({"title": DEFAULT_DAY_TITLES[0], "description": description})

    if day_two_modules:
        names = []
        for module in day_two_modules:
            mt = module.get("title")
            if isinstance(mt, str):
                parts = mt.split(": ", 1)
                names.append(parts[1] if len(parts) == 2 else parts[0])
        desc_titles = _join_titles([n for n in names if n])
        description = (
            f"Machine intelligence, automation, and capstone delivery covering {desc_titles}."
            if desc_titles
            else BOOTCAMP_INFO["daily_flow"][1]["description"]
        )
        flow.append({"title": DEFAULT_DAY_TITLES[1], "description": description})

    return flow


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
        bootcamp=_get_bootcamp_vm(),
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
    bootcamp = _get_bootcamp_vm()
    return jsonify({
        "title": bootcamp.get("title"),
        "subtitle": bootcamp.get("subtitle"),
        "price": bootcamp.get("price_eur"),
        "currency": bootcamp.get("currency"),
        "seat_cap": bootcamp.get("seat_cap"),
        "modules": bootcamp.get("modules"),
        "daily_flow": bootcamp.get("daily_flow"),
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


def send_email_notification(
    subject: str,
    text_body: str,
    to_address: str,
    reply_to: str | None = None,
) -> bool:
    """Send a plaintext email notification using the configured SMTP backend."""
    if EMAIL_BACKEND != "smtp":
        log.warning("Email notification skipped: EMAIL_BACKEND=%s", EMAIL_BACKEND)
        return False
    if not (SMTP_USERNAME and SMTP_PASSWORD and to_address):
        log.warning("Email notification skipped: SMTP not fully configured")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM or SMTP_USERNAME
    message["To"] = to_address
    if reply_to:
        message["Reply-To"] = reply_to
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
        log.info("Email notification sent to %s", to_address)
        return True
    except Exception:
        log.exception("Failed to send email notification")
        return False


def _send_bootcamp_request_email(payload: Dict[str, str]) -> bool:
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

    return send_email_notification(
        subject,
        text_body,
        BOOTCAMP_REQUEST_TO,
        reply_to=payload.get("contact_email") or None,
    )
