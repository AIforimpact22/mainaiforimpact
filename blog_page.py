"""Blog listing blueprint."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from flask import Blueprint, abort, current_app, render_template
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

blog_bp = Blueprint("blog", __name__)

_POSTS_SQL = text(
    """
    SELECT
        id,
        slug,
        title,
        html_content,
        excerpt,
        cover_image_url,
        author_name,
        published_at,
        created_at
    FROM blog_posts
    WHERE status = 'published'
    ORDER BY COALESCE(published_at, created_at) DESC, id DESC
    """
)

_POST_BY_SLUG_SQL = text(
    """
    SELECT
        id,
        slug,
        title,
        html_content,
        excerpt,
        cover_image_url,
        author_name,
        published_at,
        created_at
    FROM blog_posts
    WHERE status = 'published' AND slug = :slug
    LIMIT 1
    """
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _build_excerpt(row: Dict[str, Any]) -> str:
    explicit = (row.get("excerpt") or "").strip()
    if explicit:
        return explicit

    html = row.get("html_content") or ""
    text_content = _TAG_RE.sub(" ", html)
    text_content = _WS_RE.sub(" ", text_content).strip()
    if len(text_content) > 220:
        return text_content[:197].rstrip() + "…"
    return text_content


def _format_date(value: Any) -> str:
    if not value:
        return ""
    try:
        return value.strftime("%b %d, %Y")  # type: ignore[attr-defined]
    except Exception:
        return str(value)


def _format_iso(value: Any) -> str:
    if not value:
        return ""
    try:
        return value.isoformat()  # type: ignore[attr-defined]
    except Exception:
        return str(value)


@blog_bp.route("/", methods=["GET"], strict_slashes=False)
def blog_index():
    engine = current_app.config.get("DB_ENGINE")
    posts: List[Dict[str, Any]] = []
    error_message = ""

    if not engine:
        error_message = "Database connection is not configured."
    else:
        try:
            with engine.begin() as conn:
                rows = conn.execute(_POSTS_SQL).mappings().all()
                for row in rows:
                    published_raw = row.get("published_at") or row.get("created_at")
                    posts.append(
                        {
                            "id": row.get("id"),
                            "title": row.get("title") or "Untitled post",
                            "slug": row.get("slug") or "",
                            "excerpt": _build_excerpt(row),
                            "cover_image_url": row.get("cover_image_url") or "",
                            "author": row.get("author_name") or "",
                            "published": _format_date(published_raw),
                            "published_iso": _format_iso(published_raw),
                        }
                    )
        except SQLAlchemyError as exc:  # pragma: no cover - defensive path
            current_app.logger.exception("Failed to load blog posts: %s", exc)
            error_message = "We couldn't load the blog posts right now. Please try again later."

    return render_template(
        "blog_index.html",
        posts=posts,
        error_message=error_message,
    )


@blog_bp.route("/<slug>/", methods=["GET"], strict_slashes=False)
def blog_detail(slug: str):
    engine = current_app.config.get("DB_ENGINE")
    if not engine:
        abort(404)

    normalized_slug = (slug or "").strip()
    if not normalized_slug:
        abort(404)

    try:
        with engine.begin() as conn:
            row = conn.execute(_POST_BY_SLUG_SQL, {"slug": normalized_slug}).mappings().first()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive path
        current_app.logger.exception("Failed to load blog post %s: %s", slug, exc)
        abort(500)

    if not row:
        abort(404)

    published_raw = row.get("published_at") or row.get("created_at")
    post = {
        "id": row.get("id"),
        "title": row.get("title") or "Untitled post",
        "slug": row.get("slug") or "",
        "cover_image_url": row.get("cover_image_url") or "",
        "author": row.get("author_name") or "",
        "published": _format_date(published_raw),
        "published_iso": _format_iso(published_raw),
        "html_content": row.get("html_content") or "",
    }

    return render_template("blog_post.html", post=post)
