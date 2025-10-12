# register.py (Blueprint: register)
# Full module with email notification after successful registration commit.
# DSN-first with HARD-CODED fallback to your local Postgres.

import os
import re
import logging
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from course_settings import (
    BOOTCAMP_CODE,
    BOOTCAMP_PRICE_EUR,
    BOOTCAMP_PUBLIC_REGISTRATION,
    BOOTCAMP_SEAT_CAP,
)
from sqlalchemy import create_engine, MetaData, Table, inspect, select, func
from sqlalchemy.engine import URL
from sqlalchemy.sql import text
from werkzeug.security import check_password_hash, generate_password_hash

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
BASE_PRICE_EUR = int(os.getenv("BASE_PRICE_EUR", "900"))
PROMO_CODE = os.getenv("PROMO_CODE", "IMPACT-439")
PROMO_PRICE_EUR = int(os.getenv("PROMO_PRICE_EUR", "439"))
PROMO_CODE_FREE = os.getenv("PROMO_CODE_FREE", "IMPACT-100")
PROMO_PRICE_FREE_EUR = int(os.getenv("PROMO_PRICE_FREE_EUR", "0"))

COURSES = [
    {
        "code": "AAI-RTD",
        "title": "One on one Tailored Training Session",
        "price_eur": BASE_PRICE_EUR,
        "seat_cap": None,
        "note": "1-on-1 format · €%d" % BASE_PRICE_EUR,
    },
    {
        "code": BOOTCAMP_CODE,
        "title": f"AI Implementation Bootcamp ({BOOTCAMP_SEAT_CAP} seats)",
        "price_eur": BOOTCAMP_PRICE_EUR,
        "seat_cap": BOOTCAMP_SEAT_CAP,
        "note": "4-day cohort · %d seats · €%d per learner" % (BOOTCAMP_SEAT_CAP, BOOTCAMP_PRICE_EUR),
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
    if s.startswith("postgresql://") or s.startswith("postgresql+psycopg2://") or s.startswith("postgresql+pg8000://"):
        return True
    return s.startswith("sqlite://")

# Your DSN (fallback if envs not set)
_HARDCODED_DSN = "postgresql+psycopg2://postgres:Garnet87@127.0.0.1:5432/aiforimpact"

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

engine = create_engine(_sqlalchemy_url(), pool_pre_ping=True, pool_recycle=1800, future=True)
metadata = MetaData()

# Robust, dialect-aware reflection for application tables
TARGET_SCHEMA = os.getenv("DB_SCHEMA", "public")
insp = inspect(engine)
dialect = engine.dialect.name  # 'postgresql', 'sqlite', etc.


def _resolve_table_schema(table_name: str) -> Optional[str]:
    if dialect == "postgresql":
        tables_public = set(insp.get_table_names(schema=TARGET_SCHEMA))
        tables_default = set(insp.get_table_names())
        if table_name in tables_public:
            return TARGET_SCHEMA
        if table_name in tables_default:
            return None
        raise RuntimeError(
            f"Table '{table_name}' not found in Postgres.\n"
            f"  Checked schema '{TARGET_SCHEMA}': {sorted(tables_public)}\n"
            f"  Default search_path tables: {sorted(tables_default)}\n"
            "Ensure you're pointing at the correct DB and schema (set DB_SCHEMA if needed)."
        )

    names = set(insp.get_table_names())
    if table_name in names:
        return None
    raise RuntimeError(f"Table '{table_name}' not found. Visible tables: {sorted(names)}")


_registrations_schema = _resolve_table_schema("registrations")
registrations = Table("registrations", metadata, schema=_registrations_schema, autoload_with=engine)

_users_schema = _resolve_table_schema("users")
users = Table("users", metadata, schema=_users_schema, autoload_with=engine)

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────
def _slug(s: str | None) -> str | None:
    if not s: return None
    s = s.strip().lower()
    s = re.sub(r"[\s/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return re.sub(r"_+", "_", s).strip("_") or None

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


def _is_gmail_address(email: Optional[str]) -> bool:
    if not email:
        return False
    email = email.strip().lower()
    return bool(re.fullmatch(r"[a-z0-9._%+-]+@gmail\.com", email))


def load_user(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    normalized = email.strip().lower()
    with engine.connect() as conn:
        row = conn.execute(
            select(users).where(users.c.email == normalized)
        ).mappings().first()
        return dict(row) if row else None


def update_user_credentials(
    email: str,
    *,
    password_hash: Optional[str] = None,
    must_change_password: Optional[bool] = None,
) -> bool:
    if not email:
        return False
    values: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if password_hash is not None:
        values["password_hash"] = password_hash
    if must_change_password is not None:
        values["must_change_password"] = must_change_password
    if len(values) == 1:  # only updated_at
        return False
    with engine.begin() as conn:
        result = conn.execute(
            users.update()
            .where(users.c.email == email.strip().lower())
            .values(**values)
        )
    return result.rowcount > 0

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

def _compute_price(promo_input, base_price=None):
    base = base_price if base_price is not None else BASE_PRICE_EUR
    if promo_input:
        code = promo_input.strip().lower()
        if PROMO_CODE and code == PROMO_CODE.lower() and PROMO_PRICE_EUR < base:
            return PROMO_PRICE_EUR, PROMO_CODE, (PROMO_PRICE_EUR == 0)
        if PROMO_CODE_FREE and code == PROMO_CODE_FREE.lower() and PROMO_PRICE_FREE_EUR <= base:
            return PROMO_PRICE_FREE_EUR, PROMO_CODE_FREE, True
    return base, None, False

def _require_signed_in(_: str | None = None) -> bool:
    if session.get("user_email"):
        return True
    flash("Please sign in with your Gmail account before continuing.", "error")
    return False

# ───────────────────────────────────────────────────────────────
# Views
# ───────────────────────────────────────────────────────────────
@register_bp.get("/")
def page():
    submitted = request.args.get("submitted") == "1"
    selected_course_code = _s(request.args.get("course"))
    selected_course = _course_by_code(selected_course_code)
    base_price = selected_course["price_eur"] if selected_course else 0
    if session.get("require_password_change"):
        return redirect(url_for("register.change_password"))

    user_email = session.get("user_email")
    signed_in = bool(user_email)
    return render_template(
        "register.html",
        brand_name=BRAND_NAME,
        brand_logo_url=BRAND_LOGO_URL,
        powered_by=POWERED_BY,
        course_name=COURSE_NAME,
        signed_in=signed_in,
        user_email=user_email,
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
    )

@register_bp.post("/signin")
def signin():
    course_param = _s(request.form.get("course"))
    email = _s(request.form.get("user_email"))
    password = request.form.get("password") or ""

    if not _is_gmail_address(email):
        flash("Please use a Gmail address to sign in.", "error")
        if course_param:
            return redirect(url_for("register.page", course=course_param))
        return redirect(url_for("register.page"))

    user = load_user(email)
    if not user or not user.get("password_hash"):
        flash("Invalid email or password.", "error")
        if course_param:
            return redirect(url_for("register.page", course=course_param))
        return redirect(url_for("register.page"))

    if not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        if course_param:
            return redirect(url_for("register.page", course=course_param))
        return redirect(url_for("register.page"))

    session.clear()
    normalized_email = user["email"].strip().lower()
    session["user_email"] = normalized_email
    must_change = bool(user.get("must_change_password"))
    session["require_password_change"] = must_change

    if must_change:
        flash("Please choose a new password to continue.", "info")
        return redirect(url_for("register.change_password"))

    flash("Signed in. Please complete your registration.", "success")
    if course_param:
        return redirect(url_for("register.page", course=course_param))
    return redirect(url_for("register.page"))

@register_bp.get("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("register.page"))


@register_bp.route("/password/change", methods=["GET", "POST"])
def change_password():
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in to update your password.", "error")
        return redirect(url_for("register.page"))

    if not _is_gmail_address(user_email):
        session.clear()
        flash("Only Gmail accounts are supported for registration.", "error")
        return redirect(url_for("register.page"))

    user = load_user(user_email)
    if not user:
        session.clear()
        flash("We couldn't locate your account. Please contact support.", "error")
        return redirect(url_for("register.page"))

    errors: List[str] = []
    if request.method == "POST":
        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if len(new_password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if new_password != confirm_password:
            errors.append("Password confirmation does not match.")

        if not errors:
            hashed = generate_password_hash(new_password)
            updated = update_user_credentials(
                user_email,
                password_hash=hashed,
                must_change_password=False,
            )
            if not updated:
                errors.append("We couldn't update your password. Please try again or contact support.")
            else:
                session["require_password_change"] = False
                flash("Password updated. You can now continue with registration.", "success")
                return redirect(url_for("register.page"))

        for err in errors:
            flash(err, "error")

    return render_template(
        "password_change.html",
        user_email=user_email,
        errors=errors,
    )

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
    if session.get("require_password_change"):
        flash("Please update your password before completing the registration form.", "error")
        return redirect(url_for("register.change_password"))

    if not _require_signed_in(course_session_code):
        if course_session_code:
            return redirect(url_for("register.page", course=course_session_code))
        return redirect(url_for("register.page"))

    errors = []

    session_email = session.get("user_email")
    form_email = _s(request.form.get("user_email"))
    if not session_email:
        errors.append("You must be signed in to submit the registration form.")
        user_email = None
    else:
        normalized_session_email = session_email.strip().lower()
        user_email = normalized_session_email
        if form_email and form_email.strip().lower() != normalized_session_email:
            errors.append("The registration email must match the signed-in Gmail account.")
        if not _is_gmail_address(normalized_session_email):
            errors.append("Registrations require a Gmail address. Please sign out and sign in with Gmail.")

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
            signed_in=bool(session.get("user_email")),
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
