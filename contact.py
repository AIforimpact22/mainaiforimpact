"""Contact page blueprint and form handler."""

from __future__ import annotations

import random
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
MESSAGE_LIMIT = 500
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

contact_bp = Blueprint("contact", __name__)

_COLOR_CHALLENGES = (
    {
        "prompt": "Select BLUE",
        "answer": "blue",
        "options": (
            {"value": "blue", "label": "Blue", "color": "#3b82f6"},
            {"value": "red", "label": "Red", "color": "#ef4444"},
            {"value": "green", "label": "Green", "color": "#22c55e"},
        ),
    },
    {
        "prompt": "Select RED",
        "answer": "red",
        "options": (
            {"value": "yellow", "label": "Yellow", "color": "#facc15"},
            {"value": "red", "label": "Red", "color": "#ef4444"},
            {"value": "purple", "label": "Purple", "color": "#a855f7"},
        ),
    },
    {
        "prompt": "Select GREEN",
        "answer": "green",
        "options": (
            {"value": "orange", "label": "Orange", "color": "#fb923c"},
            {"value": "green", "label": "Green", "color": "#22c55e"},
            {"value": "blue", "label": "Blue", "color": "#3b82f6"},
        ),
    },
)


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
        "challenge_selection": (request.form.get("challenge_selection") or "").strip(),
        "challenge_answer": (request.form.get("challenge_answer") or "").strip(),
    }


@contact_bp.route("/", methods=["GET"], strict_slashes=False)
def contact_page():
    status = request.args.get("status", "").lower()
    message = request.args.get("message") or ""
    success = status == "sent"
    error_message = message if status == "error" else ""

    challenge = random.choice(_COLOR_CHALLENGES)

    return render_template(
        "contact.html",
        contact_status=status if status in {"sent", "error"} else "",
        contact_success=success,
        contact_error=error_message,
        contact_recipient=CONTACT_RECIPIENT,
        message_limit=MESSAGE_LIMIT,
        challenge_prompt=challenge["prompt"],
        challenge_answer=challenge["answer"],
        challenge_options=challenge["options"],
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

    challenge_selection = form["challenge_selection"].lower()
    challenge_answer = form["challenge_answer"].lower()
    if not challenge_selection or not challenge_answer:
        errors.append("Please complete the color confirmation step.")
    elif challenge_selection != challenge_answer:
        errors.append("The selected color doesn't match the prompt. Please try again.")

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
