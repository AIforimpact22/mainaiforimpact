# register.py (Blueprint: register)
# Full module with email notification after successful registration commit.
# DSN-first with HARD-CODED fallback to your local Postgres.

import os
import re
import logging
import smtplib
import ssl
from decimal import Decimal
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from course_settings import (
    BOOTCAMP_CODE,
    BOOTCAMP_PRICE_EUR,
    BOOTCAMP_PUBLIC_REGISTRATION,
    BOOTCAMP_SEAT_CAP,
)
from bootcamp import _fetch_bootcamp_seat_prices, summarize_bootcamp_price  # type: ignore[attr-defined]
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import URL
from sqlalchemy.sql import text

register_bp = Blueprint("register", __name__, template_folder="templates")

# ───────────────────────────────────────────────────────────────
# Email (Gmail SMTP or compatible)
# ───────────────────────────────────────────────────────────────
REG_NOTIFY_ENABLED = (os.getenv("REG_NOTIFY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "y"})
REG_NOTIFY_TO = os.getenv("REG_NOTIFY_TO", "connect@aiforimpact.net")
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "smtp").strip().lower()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "connect@aiforimpact.net")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "rgbvcjfocqpmjipy")
SMTP_FROM = os.getenv("SMTP_FROM", "AiForImpact <connect@aiforimpact.net>")

logger = logging.getLogger(__name__)

class SeatCapReached(Exception):
    """Raised when a course has reached its seat capacity."""

def _compose_reg_email_payload(p: Dict[str, Any]) -> tuple[str, str, str | None]:
    created_at = p.get("created_at")
    if isinstance(created_at, datetime):
        created_str = created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    else:
        created_str = str(created_at) if created_at else "N/A"

    name = p.get("name") or "Unknown"
    email = p.get("email") or "N/A"
    company = p.get("company") or "N/A"
    session_code = p.get("session_code") or "N/A"
    referral = p.get("referral") or "N/A"

    subject = f"New registration — {name} ({email})"
    text_body = (
        "A new customer has registered.\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Company: {company}\n"
        f"Session: {session_code}\n"
        f"Referral: {referral}\n"
        f"Created: {created_str}\n\n"
        "— AiForImpactPortal"
    )
    return subject, text_body, None

def _send_email_smtp(subject: str, text_body: str, html_body: str | None = None) -> bool:
    if EMAIL_BACKEND != "smtp":
        logger.warning("EMAIL_BACKEND=%s (expected 'smtp'); skipping SMTP send", EMAIL_BACKEND)
        return False
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.warning("SMTP not configured: missing SMTP_USERNAME or SMTP_PASSWORD")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_USERNAME
    msg["To"] = REG_NOTIFY_TO
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as s:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        logger.info("Registration email sent to %s via SMTP", REG_NOTIFY_TO)
        return True
    except Exception:
        logger.exception("SMTP send failed")
        return False

def _send_registration_email(reg: Dict[str, Any]) -> None:
    if not REG_NOTIFY_ENABLED:
        return
    try:
        full_name = " ".join([v for v in [reg.get("first_name"), reg.get("last_name")] if v]).strip()
        payload = {
            "name": full_name or "Unknown",
            "email": reg.get("user_email"),
            "company": reg.get("company"),
            "session_code": reg.get("course_session_code"),
            "referral": reg.get("referral_source"),
            "created_at": reg.get("created_at"),
        }
        subject, text_body, html_body = _compose_reg_email_payload(payload)
        ok = _send_email_smtp(subject, text_body, html_body)
        if not ok:
            logger.warning("Registration email send returned False (subject=%r)", subject)
    except Exception:
        logger.exception("Registration email failed (non-fatal)")

# ───────────────────────────────────────────────────────────────
# Product / UI constants
# ───────────────────────────────────────────────────────────────
COURSE_NAME = os.getenv("COURSE_NAME", "Ai For Impact")
BRAND_NAME = os.getenv("BRAND_NAME", "Ai For Impact")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "https://i.imgur.com/STm5VaG.png")
POWERED_BY = os.getenv("POWERED_BY", "Climate Fundraising Platform B.V.")
COURSE_ACCESS_CODE = os.getenv("COURSE_ACCESS_CODE", "letmein")

BASE_PRICE_EUR = int(os.getenv("BASE_PRICE_EUR", "900"))
PROMO_CODE = os.getenv("PROMO_CODE", "IMPACT-439")
PROMO_PRICE_EUR = int(os.getenv("PROMO_PRICE_EUR", "439"))
PROMO_CODE_FREE = os.getenv("PROMO_CODE_FREE", "IMPACT-100")
PROMO_PRICE_FREE_EUR = int(os.getenv("PROMO_PRICE_FREE_EUR", "0"))

DEFAULT_ENROLLMENT_STATUS = os.getenv("DEFAULT_ENROLLMENT_STATUS", "pending").strip() or "pending"

_BOOTCAMP_PRICE_INFO = _resolve_bootcamp_price_info()
BOOTCAMP_PRICE_AMOUNT = _BOOTCAMP_PRICE_INFO.get("amount") or BOOTCAMP_PRICE_EUR
BOOTCAMP_CURRENCY = (_BOOTCAMP_PRICE_INFO.get("currency") or "USD").upper()
BOOTCAMP_PRICE_DISPLAY = _BOOTCAMP_PRICE_INFO.get("display") or None

COURSES = [
    {
        "code": "AAI-RTD",
        "title": "One on one Tailored Training Session",
        "price_eur": BASE_PRICE_EUR,
        "currency": "EUR",
        "seat_cap": None,
        "requires_access_code": True,
    },
    {
        "code": BOOTCAMP_CODE,
        "title": f"AI Implementation Bootcamp ({BOOTCAMP_SEAT_CAP} seats)",
        "price_eur": BOOTCAMP_PRICE_AMOUNT,
        "currency": BOOTCAMP_CURRENCY,
        "seat_cap": BOOTCAMP_SEAT_CAP,
        "requires_access_code": not BOOTCAMP_PUBLIC_REGISTRATION,
        "price_display": BOOTCAMP_PRICE_DISPLAY,
    },
]

JOB_ROLES = [
    "Student","Software Engineer / Developer","Data Analyst / Data Scientist","Product Manager",
    "Researcher / Academic","Business Owner / Founder","Marketing / Growth","Operations / Supply Chain",
    "Finance / Analyst","Other",
]

REFERRAL_CHOICES = [
    "Search","YouTube","TikTok/Instagram","X/Twitter","LinkedIn",
    "Friend/Colleague","Event/Conference","Partner","Newsletter","Other"
]

# ───────────────────────────────────────────────────────────────
# DB engine (Core) — DSN-first with HARD-CODED fallback
# ───────────────────────────────────────────────────────────────
def _is_dsn(s: str) -> bool:
    if not s:
        return False
    s = s.strip().lower()
    return s.startswith("postgresql://") or s.startswith("postgresql+psycopg2://") or s.startswith("postgresql+pg8000://")

# Your DSN (fallback if envs not set)
_HARDCODED_DSN = "postgresql+psycopg2://postgres:Garnet87@127.0.0.1:5432/aiforimpact"
_SQLITE_FALLBACK_URL = "sqlite:///local_registrations.db"

def _sqlalchemy_url() -> str | URL:
    # 1) DATABASE_URL wins
    db_url = os.getenv("DATABASE_URL")
    if db_url and _is_dsn(db_url):
        return db_url

    # 2) DSN in INSTANCE_CONNECTION_NAME (keeps the [cloudsql] style if you want)
    inst = os.getenv("INSTANCE_CONNECTION_NAME", "")
    if inst and _is_dsn(inst):
        return inst

    # 3) Traditional TCP params (optional)
    user = os.getenv("DB_USER")
    pwd  = os.getenv("DB_PASS") or os.getenv("DB_PASSWORD")
    name = os.getenv("DB_NAME")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    if host and user and pwd and name:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=user,
            password=pwd,
            host=host,
            port=int(port) if port else None,
            database=name,
        )

    # 4) Final fallback: your hardcoded DSN (ensures it just works)
    return _HARDCODED_DSN


def _create_engine_with_fallback():
    url = _sqlalchemy_url()
    try:
        eng = create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng
    except Exception:
        logger.exception("Primary database unavailable; falling back to SQLite at %s", _SQLITE_FALLBACK_URL)
        return create_engine(_SQLITE_FALLBACK_URL, future=True)


def _build_sqlite_registration_table(meta: MetaData) -> Table:
    return Table(
        "registrations",
        meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_email", String(255), nullable=False),
        Column("first_name", String(120)),
        Column("middle_name", String(120)),
        Column("last_name", String(120)),
        Column("age", Integer),
        Column("gender", String(50)),
        Column("gender_other_note", Text),
        Column("phone", String(120)),
        Column("address_line1", Text),
        Column("address_line2", Text),
        Column("city", String(120)),
        Column("state", String(120)),
        Column("postal_code", String(120)),
        Column("country", String(120)),
        Column("job_title", String(255)),
        Column("company", String(255)),
        Column("ai_current_involvement", Text),
        Column("ai_goals_wish_to_achieve", Text),
        Column("ai_datasets_available", Text),
        Column("referral_source", String(120)),
        Column("referral_details", Text),
        Column("reason_choose_us", Text),
        Column("enrollment_status", String(50)),
        Column("invoice_name", String(255)),
        Column("invoice_company", String(255)),
        Column("invoice_vat_id", String(255)),
        Column("invoice_email", String(255)),
        Column("invoice_phone", String(120)),
        Column("invoice_addr_line1", Text),
        Column("invoice_addr_line2", Text),
        Column("invoice_city", String(120)),
        Column("invoice_state", String(120)),
        Column("invoice_postal_code", String(120)),
        Column("invoice_country", String(120)),
        Column("course_session_code", String(120)),
        Column("notes", Text),
        Column("consent_contact_ok", Boolean),
        Column("consent_marketing_ok", Boolean),
        Column("data_processing_ok", Boolean),
        Column("created_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True)),
    )


def _init_engine_and_table() -> tuple[Any, MetaData, Table]:
    eng = _create_engine_with_fallback()
    meta = MetaData()
    try:
        insp = inspect(eng)
        dialect = eng.dialect.name
        target_schema = os.getenv("DB_SCHEMA", "public")

        if dialect == "postgresql":
            tables_public = set(insp.get_table_names(schema=target_schema))
            tables_default = set(insp.get_table_names())
            if "registrations" in tables_public:
                resolved_schema = target_schema
            elif "registrations" in tables_default:
                resolved_schema = None
            else:
                raise RuntimeError(
                    "Table 'registrations' not found in Postgres.\n"
                    f"  Checked schema '{target_schema}': {sorted(tables_public)}\n"
                    f"  Default search_path tables: {sorted(tables_default)}\n"
                    "Ensure you're pointing at the correct DB and schema (set DB_SCHEMA if needed)."
                )
        else:
            names = set(insp.get_table_names())
            if "registrations" in names:
                resolved_schema = None
            else:
                raise RuntimeError(f"Table 'registrations' not found. Visible tables: {sorted(names)}")

        table = Table("registrations", meta, schema=resolved_schema, autoload_with=eng)
        return eng, meta, table
    except Exception:
        logger.exception("Unable to reflect registrations table; switching to SQLite fallback")
        # Switch to SQLite fallback engine and ensure table exists
        eng = create_engine(_SQLITE_FALLBACK_URL, future=True)
        meta = MetaData()
        table = _build_sqlite_registration_table(meta)
        meta.create_all(eng, checkfirst=True)
        return eng, meta, table


engine, metadata, registrations = _init_engine_and_table()

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────
def _slug(s: str | None) -> str | None:
    if not s: return None
    s = s.strip().lower()
    s = re.sub(r"[\s/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return re.sub(r"_+", "_", s).strip("_") or None


def _currency_symbol(code: str | None) -> str | None:
    if not code:
        return None

    code = code.strip().upper()
    symbols = {
        "EUR": "€",
        "USD": "$",
        "GBP": "£",
        "INR": "₹",
    }
    return symbols.get(code, code)


def _parse_price_amount(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _resolve_bootcamp_price_info() -> Dict[str, Any]:
    """Resolve the bootcamp price from the seat prices table (USD expected)."""

    price_info: Dict[str, Any] = {}
    try:
        seat_prices = _fetch_bootcamp_seat_prices()
        summary = summarize_bootcamp_price(seat_prices) if seat_prices else None
    except Exception:
        logger.exception("Failed to load bootcamp seat prices; falling back to defaults")
        seat_prices = []
        summary = None

    primary_group = seat_prices[0] if seat_prices else None
    if isinstance(primary_group, dict):
        price_info["currency"] = (primary_group.get("currency") or "USD").strip().upper()
        raw_amount = (
            primary_group.get("regular_price")
            or primary_group.get("early_bird_price")
        )
        if raw_amount is None:
            offers = primary_group.get("offers") if isinstance(primary_group.get("offers"), list) else []
            if offers:
                raw_amount = offers[0].get("price")
        parsed_amount = _parse_price_amount(raw_amount)
        if parsed_amount is not None:
            price_info["amount"] = parsed_amount

    if summary:
        for key in ("regular", "early_bird"):
            offer = summary.get(key) if isinstance(summary, dict) else None
            if offer and offer.get("price_display"):
                price_info["display"] = offer.get("price_display")
                break

    if not price_info.get("display") and price_info.get("amount") is not None:
        symbol = _currency_symbol(price_info.get("currency")) or ""
        price_info["display"] = f"{symbol}{price_info['amount']}"

    return price_info

def _load_enum_labels(name: str) -> List[str]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT e.enumlabel
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                WHERE t.typname = :name
                ORDER BY e.enumsortorder
            """), {"name": name}).fetchall()
            return [r[0] for r in rows]
    except Exception:
        return []

GENDER_ENUM_LABELS = _load_enum_labels("gender") or ["female","male","other","prefer_not_to_say"]
REFERRAL_ENUM_LABELS = _load_enum_labels("referral_source") or [_slug(x) for x in REFERRAL_CHOICES if _slug(x)]

def _normalizer(allowed: List[str]):
    m = {_slug(lbl): lbl for lbl in allowed if _slug(lbl)}
    def norm(raw: str | None) -> str | None:
        s = _slug(raw)
        return m.get(s) if s else None
    return norm

normalize_gender = _normalizer(GENDER_ENUM_LABELS)
normalize_referral = _normalizer(REFERRAL_ENUM_LABELS)

def _s(x):
    if x is None: return None
    x = x.strip()
    return x or None

def _bool(v, default=False):
    if v is None: return default
    if isinstance(v, bool): return v
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def _clip(x, n=500):
    x = _s(x)
    return x[:n] if x and len(x) > n else x

def _course_by_code(code: str | None) -> Dict[str, Any] | None:
    if not code:
        return None
    for c in COURSES:
        if c.get("code") == code:
            return c
    return None

def _course_allows_open_registration(code: str | None) -> bool:
    course = _course_by_code(code)
    if not course:
        return False
    return not course.get("requires_access_code", True)

def _compute_price(promo_input, base_price=None):
    base = base_price if base_price is not None else BASE_PRICE_EUR
    if promo_input:
        code = promo_input.strip().lower()
        if PROMO_CODE and code == PROMO_CODE.lower() and PROMO_PRICE_EUR < base:
            return PROMO_PRICE_EUR, PROMO_CODE, (PROMO_PRICE_EUR == 0)
        if PROMO_CODE_FREE and code == PROMO_CODE_FREE.lower() and PROMO_PRICE_FREE_EUR <= base:
            return PROMO_PRICE_FREE_EUR, PROMO_CODE_FREE, True
    return base, None, False

def _require_signed_in(course_code: str | None = None):
    if _course_allows_open_registration(course_code):
        return True
    if not session.get("signed_in"):
        flash("Please sign in with the course access code.", "error")
        return False
    return True

# ───────────────────────────────────────────────────────────────
# Views
# ───────────────────────────────────────────────────────────────
@register_bp.get("/")
def page():
    submitted = request.args.get("submitted") == "1"
    selected_course_code = _s(request.args.get("course"))
    selected_course = _course_by_code(selected_course_code)
    base_price = selected_course["price_eur"] if selected_course else 0
    signed_in = session.get("signed_in", False) or _course_allows_open_registration(selected_course_code)
    return render_template(
        "register.html",
        brand_name=BRAND_NAME,
        brand_logo_url=BRAND_LOGO_URL,
        powered_by=POWERED_BY,
        course_name=COURSE_NAME,
        signed_in=signed_in,
        user_email=session.get("user_email"),
        errors=[],
        submitted=submitted,
        referrals=REFERRAL_CHOICES,
        courses=COURSES,
        job_roles=JOB_ROLES,
        base_price_eur=base_price,
        promo_price_eur=PROMO_PRICE_EUR,
        promo_price_free_eur=PROMO_PRICE_FREE_EUR,
        selected_course_code=selected_course_code,
        selected_course_note=selected_course.get("note") if selected_course else None,
        selected_course_currency=selected_course.get("currency") if selected_course else None,
        selected_course_currency_symbol=_currency_symbol(selected_course.get("currency") if selected_course else None),
        selected_course_price_display=selected_course.get("price_display") if selected_course else None,
    )

@register_bp.post("/signin")
def signin():
    code = (request.form.get("access_code") or "").strip()
    email = _s(request.form.get("user_email"))
    course_param = _s(request.form.get("course"))
    if code == COURSE_ACCESS_CODE:
        session["signed_in"] = True
        session["user_email"] = email
        flash("Signed in. Please complete your registration.", "success")
    else:
        flash("Invalid course access code.", "error")
    if course_param:
        return redirect(url_for("register.page", course=course_param))
    return redirect(url_for("register.page"))

@register_bp.get("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("register.page"))

@register_bp.route("/price-preview", methods=["GET", "POST"])
def price_preview():
    code = request.values.get("code") or (request.json.get("code") if request.is_json else None)
    course_code = _s(request.values.get("course") if not request.is_json else request.json.get("course"))
    course = _course_by_code(course_code)
    base_price = course["price_eur"] if course else BASE_PRICE_EUR
    price, applied, is_free = _compute_price(code, base_price)
    return jsonify({
        "price_eur": int(price),
        "promo_applied": bool(applied),
        "is_free": bool(is_free),
        "base_price_eur": int(base_price),
    }), 200

@register_bp.post("/submit")
def submit():
    course_session_code = _s(request.form.get("course_session_code"))
    if not _require_signed_in(course_session_code):
        if course_session_code:
            return redirect(url_for("register.page", course=course_session_code))
        return redirect(url_for("register.page"))

    errors = []

    user_email = _s(request.form.get("user_email")) or session.get("user_email")
    if not user_email:
        errors.append("Email is required.")

    first = _s(request.form.get("first_name"))
    last  = _s(request.form.get("last_name"))
    if not first: errors.append("First name is required.")
    if not last:  errors.append("Last name is required.")

    age = None
    age_raw = _s(request.form.get("age"))
    if age_raw:
        try:
            age = int(age_raw)
            if not (10 <= age <= 120):
                errors.append("Age must be between 10 and 120.")
        except ValueError:
            errors.append("Age must be a whole number.")

    gender = normalize_gender(_s(request.form.get("gender")))
    gender_other_note = _clip(request.form.get("gender_other_note")) if gender == "other" else None

    selected_course = _course_by_code(course_session_code)
    if not selected_course:
        errors.append("Please select a valid course.")
    else:
        seat_cap = selected_course.get("seat_cap")
        if seat_cap:
            try:
                with engine.connect() as conn:
                    count_stmt = select(func.count()).select_from(registrations).where(
                        registrations.c.course_session_code == course_session_code
                    )
                    existing = conn.execute(count_stmt).scalar_one()
            except Exception:
                logger.exception("Seat availability check failed for %s", course_session_code)
                errors.append("We couldn’t verify availability for that course. Please try again or contact us.")
            else:
                if existing >= seat_cap:
                    errors.append("This cohort is full. Please choose a different session or contact us.")

    promo_input = _s(request.form.get("promo_code"))
    base_price_for_course = selected_course["price_eur"] if selected_course else BASE_PRICE_EUR
    base_price_for_summary = selected_course["price_eur"] if selected_course else 0
    final_price_eur, applied_promo, is_free = _compute_price(promo_input, base_price_for_course)
    final_price_eur = int(final_price_eur)

    data_processing_ok = _bool(request.form.get("data_processing_ok"))
    if not data_processing_ok:
        errors.append("You must consent to data processing to register.")

    job_title = request.form.get("job_title") or "Other"
    referral_source = normalize_referral(_s(request.form.get("referral_source")))

    if errors:
        return render_template(
            "register.html",
            brand_name=BRAND_NAME,
            brand_logo_url=BRAND_LOGO_URL,
            powered_by=POWERED_BY,
            course_name=COURSE_NAME,
            signed_in=session.get("signed_in", False) or _course_allows_open_registration(course_session_code),
            user_email=session.get("user_email"),
            errors=errors,
            submitted=False,
            referrals=REFERRAL_CHOICES,
            courses=COURSES,
            job_roles=JOB_ROLES,
            base_price_eur=base_price_for_summary,
            promo_price_eur=PROMO_PRICE_EUR,
            promo_price_free_eur=PROMO_PRICE_FREE_EUR,
            selected_course_code=course_session_code,
            selected_course_note=selected_course.get("note") if selected_course else None,
            selected_course_currency=selected_course.get("currency") if selected_course else None,
            selected_course_currency_symbol=_currency_symbol(selected_course.get("currency") if selected_course else None),
            selected_course_price_display=selected_course.get("price_display") if selected_course else None,
            form_data=request.form,
        ), 400

    data = dict(
        user_email=user_email,
        first_name=first,
        middle_name=_s(request.form.get("middle_name")),
        last_name=last,
        age=age,
        gender=gender,
        gender_other_note=gender_other_note,
        phone=_s(request.form.get("phone")),

        address_line1=_s(request.form.get("address_line1")),
        address_line2=_s(request.form.get("address_line2")),
        city=_s(request.form.get("city")),
        state=_s(request.form.get("state")),
        postal_code=_s(request.form.get("postal_code")),
        country=_s(request.form.get("country")),

        job_title=job_title,
        company=_s(request.form.get("company")),

        ai_current_involvement=_clip(request.form.get("ai_current_involvement")),
        ai_goals_wish_to_achieve=_clip(request.form.get("ai_goals_wish_to_achieve")),
        ai_datasets_available=_clip(request.form.get("ai_datasets_available")),

        referral_source=referral_source,
        referral_details=(
            f"PROMO_APPLIED:1;FREE:{1 if is_free else 0};PRICE_EUR:{final_price_eur}"
            if applied_promo else f"PRICE_EUR:{final_price_eur}"
        ),
        reason_choose_us=_clip(request.form.get("reason_choose_us")),

        enrollment_status=_s(request.form.get("enrollment_status")) or DEFAULT_ENROLLMENT_STATUS,

        invoice_name=_s(request.form.get("invoice_name")),
        invoice_company=_s(request.form.get("invoice_company")),
        invoice_vat_id=_s(request.form.get("invoice_vat_id")),
        invoice_email=_s(request.form.get("invoice_email")),
        invoice_phone=_s(request.form.get("invoice_phone")),
        invoice_addr_line1=_s(request.form.get("invoice_addr_line1")),
        invoice_addr_line2=_s(request.form.get("invoice_addr_line2")),
        invoice_city=_s(request.form.get("invoice_city")),
        invoice_state=_s(request.form.get("invoice_state")),
        invoice_postal_code=_s(request.form.get("invoice_postal_code")),
        invoice_country=_s(request.form.get("invoice_country")),

        course_session_code=course_session_code,
        notes=_clip(request.form.get("notes")),

        consent_contact_ok=_bool(request.form.get("consent_contact_ok"), True),
        consent_marketing_ok=_bool(request.form.get("consent_marketing_ok"), False),
        data_processing_ok=data_processing_ok,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Billing same-as-personal autofill
    if _bool(request.form.get("billing_same_as_personal"), True):
        full_name = " ".join([v for v in [data["first_name"], data["last_name"]] if v])
        data["invoice_name"]        = data["invoice_name"]        or full_name
        data["invoice_email"]       = data["invoice_email"]       or data["user_email"]
        data["invoice_phone"]       = data["invoice_phone"]       or data["phone"]
        data["invoice_addr_line1"]  = data["invoice_addr_line1"]  or data["address_line1"]
        data["invoice_addr_line2"]  = data["invoice_addr_line2"]  or data["address_line2"]
        data["invoice_city"]        = data["invoice_city"]        or data["city"]
        data["invoice_state"]       = data["invoice_state"]       or data["state"]
        data["invoice_postal_code"] = data["invoice_postal_code"] or data["postal_code"]
        data["invoice_country"]     = data["invoice_country"]     or data["country"]

    try:
        with engine.begin() as conn:
            if selected_course and selected_course.get("seat_cap"):
                cap = selected_course["seat_cap"]
                count_stmt = select(func.count()).select_from(registrations).where(
                    registrations.c.course_session_code == course_session_code
                )
                current = conn.execute(count_stmt).scalar_one()
                if current >= cap:
                    raise SeatCapReached()
            conn.execute(registrations.insert().values(**data))
        try:
            _send_registration_email(data)
        except Exception:
            logger.exception("Post-commit registration email block failed unexpectedly")

        flash("Thank you! Your registration has been recorded.", "success")
        if course_session_code:
            return redirect(url_for("register.page", submitted=1, course=course_session_code))
        return redirect(url_for("register.page", submitted=1))
    except SeatCapReached:
        flash("This cohort is now full. Please choose another session or contact us.", "error")
        return redirect(url_for("register.page", course=course_session_code))
    except Exception:
        logger.exception("Database insert failed")
        flash("Sorry, something went wrong saving your registration.", "error")
        return redirect(url_for("register.page"))
