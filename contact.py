"""Contact page blueprint and form handler."""

from __future__ import annotations

import re
from typing import Dict

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from bootcamp import send_email_notification

CONTACT_RECIPIENT = "connect@aiforimpact.net"
CONTACT_CODE_WORD = "IMPACT"
MESSAGE_LIMIT = 500
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

contact_bp = Blueprint("contact", __name__)


def _wants_json_response() -> bool:
    if request.is_json:
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    if not best:
        return False
    return best == "application/json" and (
        request.accept_mimetypes.get(best, 0)
        >= request.accept_mimetypes.get("text/html", 0)
    )


def _contact_form_payload() -> Dict[str, str]:
    return {
        "name": (request.form.get("name") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
        "message": (request.form.get("message") or "").strip(),
        "code_word": (request.form.get("code_word") or "").strip(),
    }


@contact_bp.route("/", methods=["GET"], strict_slashes=False)
def contact_page():
    status = request.args.get("status", "").lower()
    message = request.args.get("message") or ""
    success = status == "sent"
    error_message = message if status == "error" else ""

    return render_template(
        "contact.html",
        contact_status=status if status in {"sent", "error"} else "",
        contact_success=success,
        contact_error=error_message,
        contact_recipient=CONTACT_RECIPIENT,
        contact_code_word=CONTACT_CODE_WORD,
        message_limit=MESSAGE_LIMIT,
    )


@contact_bp.post("/submit")
def submit_contact_form():
    form = _contact_form_payload()

    errors = []
    if not form["email"]:
        errors.append("Email is required.")
    elif not _EMAIL_RE.match(form["email"]):
        errors.append("Enter a valid email address.")

    if not form["message"]:
        errors.append("Message is required.")
    elif len(form["message"]) > MESSAGE_LIMIT:
        errors.append(f"Message must be {MESSAGE_LIMIT} characters or fewer.")

    if not form["code_word"]:
        errors.append("Enter the verification code word to submit the form.")
    elif form["code_word"].lower() != CONTACT_CODE_WORD.lower():
        errors.append(
            f"The verification code word didn't match. Please type {CONTACT_CODE_WORD}."
        )

    if errors:
        if _wants_json_response():
            return jsonify({"success": False, "errors": errors}), 400

        first_error = errors[0]
        return redirect(
            url_for(
                "contact.contact_page",
                status="error",
                message=first_error,
            )
        )

    name = form["name"]
    subject = "Website contact form submission"
    if name:
        subject = f"Website contact — {name}"

    body_lines = [
        "A visitor submitted the contact form.",
        "",
        f"Name: {name or 'N/A'}",
        f"Email: {form['email']}",
        "",
        form["message"],
        "",
        "Sent from https://aiforimpact.net/contact/.",
    ]

    email_sent = send_email_notification(
        subject,
        "\n".join(body_lines),
        CONTACT_RECIPIENT,
        reply_to=form["email"],
    )

    if not email_sent:
        failure_message = "We couldn't send your message right now. Please try again later."
        if _wants_json_response():
            return (
                jsonify({"success": False, "errors": [failure_message]}),
                503,
            )
        return redirect(
            url_for(
                "contact.contact_page",
                status="error",
                message=failure_message,
            )
        )

    if _wants_json_response():
        return jsonify({"success": True, "message": "Message sent."}), 200

    return redirect(url_for("contact.contact_page", status="sent"))
