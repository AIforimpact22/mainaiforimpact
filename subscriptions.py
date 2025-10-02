"""Subscription management endpoints."""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, redirect, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
    status = "subscribed"
    source = payload.get("source") or "web_form"
    reason_unsub = None

    ip_address = _best_client_ip()
    user_agent = request.headers.get("User-Agent")

    params = dict(
        email=email,
        plan_code=plan_code or None,
        status=status,
        source=source,
        double_opt_in_token=token,
        confirmed_at=now,
        unsubscribed_at=None,
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

    try:
        with engine.begin() as conn:
            existing = conn.execute(select_sql, {"email": email}).mappings().first()
            if existing:
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
    if _want_json():
        return jsonify(payload)

    target = request.referrer or request.url_root or "/"
    return redirect(target)
