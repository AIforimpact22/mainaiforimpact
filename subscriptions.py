"""Subscription management endpoints."""

import logging
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import Blueprint, current_app, jsonify, redirect, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "smtp").strip().lower()

# Reuse the SMTP configuration that powers registration email notifications so the
# subscription welcome email is delivered with the same credentials. The
# environment can override these defaults at runtime, which is how production
# should inject secrets securely.
try:
    from registration import (
        SMTP_HOST as REG_SMTP_HOST,
        SMTP_PORT as REG_SMTP_PORT,
        SMTP_USERNAME as REG_SMTP_USERNAME,
        SMTP_PASSWORD as REG_SMTP_PASSWORD,
        SMTP_FROM as REG_SMTP_FROM,
    )
except Exception:  # pragma: no cover - defensive import guard
    REG_SMTP_HOST = None
    REG_SMTP_PORT = None
    REG_SMTP_USERNAME = None
    REG_SMTP_PASSWORD = None
    REG_SMTP_FROM = None

SMTP_HOST = os.getenv("SMTP_HOST") or REG_SMTP_HOST or "smtp.zoho.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or REG_SMTP_PORT or 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME") or REG_SMTP_USERNAME or ""
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or REG_SMTP_PASSWORD or ""
SMTP_FROM = os.getenv("SMTP_FROM") or REG_SMTP_FROM or "Ai For Impact <connect@aiforimpact.net>"
BRAND_NAME = os.getenv("BRAND_NAME", "Ai For Impact")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "https://i.imgur.com/STm5VaG.png")
PRIMARY_ACCENT = os.getenv("BRAND_ACCENT", "#5ca9ff")

log = logging.getLogger("aiforimpact-subscriptions")

subscription_bp = Blueprint("subscription", __name__, url_prefix="/subscribe")


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return None


def _best_client_ip() -> Optional[str]:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate
    remote = request.remote_addr
    return remote.strip() if remote else None


def _want_json() -> bool:
    if request.is_json:
        return True
    accept = request.accept_mimetypes
    if accept and accept.best == "application/json":
        return True
    if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
        return True
    return False


@subscription_bp.post("/")
def create_subscription():
    """Create or update a subscription record for the provided email."""
    engine = current_app.config.get("DB_ENGINE")
    if engine is None:
        log.error("Database engine unavailable when creating subscription")
        return jsonify({"ok": False, "error": "unavailable"}), 500

    payload: Dict[str, Any]
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict(flat=False)
        payload = {k: (v[0] if isinstance(v, list) else v) for k, v in payload.items()}

    email = (payload.get("email") or "").strip().lower()
    plan_code = (payload.get("plan_code") or payload.get("plan") or "newsletter").strip()
    locale = (payload.get("locale") or request.accept_languages.best or "").strip() or None
    consent_marketing = _coerce_bool(payload.get("consent_marketing"))
    tags = payload.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, (list, tuple)):
        tags = None

    if not email or "@" not in email:
        msg = "Please provide a valid email address."
        if _want_json():
            return jsonify({"ok": False, "error": msg}), 400
        return redirect(request.referrer or request.url or "/")

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(18)

    def _normalize_status(raw_status: Optional[str]) -> str:
        """Return a database-safe subscription status value."""

        allowed_config = current_app.config.get("SUBSCRIPTION_ALLOWED_STATUSES")
        if allowed_config:
            # Preserve declaration order while ensuring uniqueness.
            seen = set()
            allowed_order = []
            for status_value in allowed_config:
                lowered = status_value.lower()
                if lowered not in seen:
                    seen.add(lowered)
                    allowed_order.append(status_value)
        else:
            allowed_order = ["pending", "confirmed", "unsubscribed"]

        if not allowed_order:
            allowed_order = ["confirmed"]

        lookup = {value.lower(): value for value in allowed_order}

        default_config = current_app.config.get("SUBSCRIPTION_DEFAULT_STATUS")
        if default_config:
            default_status = lookup.get(default_config.lower(), default_config)
        else:
            default_status = lookup.get("confirmed") or allowed_order[0]

        if raw_status:
            key = str(raw_status).strip().lower()
            if key in lookup:
                return lookup[key]
            if key in {"subscribe", "subscribed"} and "confirmed" in lookup:
                return lookup["confirmed"]

        return default_status

    status = _normalize_status(payload.get("status") or payload.get("subscription_status"))
    normalized_status = status.lower()
    is_confirmed = normalized_status == "confirmed"
    is_unsubscribed = normalized_status == "unsubscribed"
    confirmed_at = now if is_confirmed else None
    unsubscribed_at = now if is_unsubscribed else None
    reason_unsub = payload.get("reason_unsub") if is_unsubscribed else None
    double_opt_in_token = None if is_confirmed else token
    source = payload.get("source") or "web_form"

    ip_address = _best_client_ip()
    user_agent = request.headers.get("User-Agent")

    params = dict(
        email=email,
        plan_code=plan_code or None,
        status=status,
        source=source,
        double_opt_in_token=double_opt_in_token,
        confirmed_at=confirmed_at,
        unsubscribed_at=unsubscribed_at,
        reason_unsub=reason_unsub,
        consent_marketing=consent_marketing,
        locale=locale,
        ip_signup=ip_address,
        user_agent_signup=user_agent,
        tags=tags,
        created_at=now,
        updated_at=now,
    )

    select_sql = text(
        """
        SELECT id, plan_code, status
        FROM subscriptions
        WHERE lower(email) = :email
        ORDER BY created_at DESC
        LIMIT 1
        """
    )

    insert_sql = text(
        """
        INSERT INTO subscriptions (
            email, plan_code, status, source, double_opt_in_token,
            confirmed_at, unsubscribed_at, reason_unsub, consent_marketing,
            locale, ip_signup, user_agent_signup, tags, created_at, updated_at
        ) VALUES (
            :email, :plan_code, :status, :source, :double_opt_in_token,
            :confirmed_at, :unsubscribed_at, :reason_unsub, :consent_marketing,
            :locale, :ip_signup, :user_agent_signup, :tags, :created_at, :updated_at
        )
        RETURNING id
        """
    )

    update_sql = text(
        """
        UPDATE subscriptions
        SET plan_code = :plan_code,
            status = :status,
            source = :source,
            double_opt_in_token = :double_opt_in_token,
            confirmed_at = :confirmed_at,
            unsubscribed_at = :unsubscribed_at,
            reason_unsub = :reason_unsub,
            consent_marketing = :consent_marketing,
            locale = :locale,
            ip_signup = :ip_signup,
            user_agent_signup = :user_agent_signup,
            tags = :tags,
            updated_at = :updated_at
        WHERE id = :id
        RETURNING id
        """
    )

    existing_status: Optional[str] = None
    try:
        with engine.begin() as conn:
            existing = conn.execute(select_sql, {"email": email}).mappings().first()
            if existing:
                raw_status = existing.get("status") if isinstance(existing, dict) else existing["status"]
                if raw_status:
                    existing_status = str(raw_status).strip().lower()
                params_with_id = dict(params)
                params_with_id["id"] = existing["id"]
                result = conn.execute(update_sql, params_with_id)
                sub_id = result.scalar_one_or_none() or existing["id"]
                created = False
            else:
                result = conn.execute(insert_sql, params)
                sub_id = result.scalar_one()
                created = True
    except SQLAlchemyError as exc:
        log.exception("Subscription write failed: %s", exc)
        if _want_json():
            return jsonify({"ok": False, "error": "internal_error"}), 500
        return redirect(request.referrer or request.url or "/")

    payload = {"ok": True, "id": sub_id, "created": created}

    should_send_welcome = False
    if not is_unsubscribed:
        if created:
            should_send_welcome = True
        elif existing_status not in {"confirmed"} and normalized_status == "confirmed":
            should_send_welcome = True

    email_sent = True
    if should_send_welcome:
        try:
            email_sent = _send_subscription_welcome_email(
                recipient=email,
                plan_code=plan_code,
                locale=locale,
                request_host=request.url_root,
            )
        except Exception:
            email_sent = False
            log.exception("Welcome email send failed")

    if should_send_welcome and not email_sent:
        error_code = "email_send_failed"
        error_message = "We couldn't send the confirmation email. Please try again later."
        if _want_json():
            return (
                jsonify({"ok": False, "error": error_code, "message": error_message}),
                502,
            )

        target = request.referrer or request.url_root or "/"
        parsed = urlparse(target)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_params["subscribe_error"] = error_code
        query_params["subscribe_message"] = error_message
        new_query = urlencode(query_params)
        target = urlunparse(parsed._replace(query=new_query))
        return redirect(target)

    if _want_json():
        return jsonify(payload)

    target = request.referrer or request.url_root or "/"
    return redirect(target)


def _send_subscription_welcome_email(
    recipient: str,
    plan_code: Optional[str],
    locale: Optional[str],
    request_host: Optional[str],
) -> bool:
    """Send a branded welcome email to the new subscriber."""

    if EMAIL_BACKEND != "smtp":
        log.warning(
            "EMAIL_BACKEND=%s (expected 'smtp'); skipping welcome email", EMAIL_BACKEND
        )
        return False
    if not (SMTP_USERNAME and SMTP_PASSWORD and recipient):
        log.warning("SMTP welcome email skipped: incomplete configuration or recipient")
        return False

    plan_display = _plan_display_name(plan_code)
    if BRAND_NAME:
        subject = f"Thanks for subscribing to {BRAND_NAME}"
    else:
        subject = "Thanks for subscribing"

    site_url = (request_host or "").strip()
    if site_url.endswith("/"):
        site_url = site_url[:-1]

    context = dict(
        brand_name=BRAND_NAME or "Ai For Impact",
        brand_logo_url=BRAND_LOGO_URL,
        accent_color=PRIMARY_ACCENT,
        plan_display=plan_display,
        site_url=site_url or "https://aiforimpact.net",
        recipient_email=recipient,
        locale=locale,
    )

    html_body = render_template("email/subscription_welcome.html", **context)
    text_body = render_template("email/subscription_welcome.txt", **context)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM or SMTP_USERNAME
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()
            ) as smtp:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        log.info("Sent subscription welcome email to %s", recipient)
        return True
    except Exception:
        log.exception("Failed to send subscription welcome email to %s", recipient)
        return False


def _plan_display_name(plan_code: Optional[str]) -> str:
    """Return a human-friendly plan name for the welcome email."""

    if not plan_code:
        return "our updates"

    normalized = str(plan_code).strip().lower()
    friendly_map = {
        "newsletter": "our newsletter",
        "insights": "the Insights updates",
        "bootcamp": "the Bootcamp interest list",
    }

    if normalized in friendly_map:
        return friendly_map[normalized]

    return f"the {plan_code} plan" if plan_code else "our updates"
