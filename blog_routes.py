"""Routes for the Ai For Impact blog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List

from flask import Blueprint, abort, render_template


@dataclass(frozen=True)
class BlogPost:
    """Metadata used to render and list a blog post."""

    slug: str
    title: str
    summary: str
    template: str
    hero_image: str
    hero_image_alt: str
    published_on: date
    read_time_minutes: int
    location: str


_POSTS: List[BlogPost] = [
    BlogPost(
        slug="our-next-focused-llm-is-in-erbil",
        title="Our Next Focused LLM is in Erbil",
        summary=(
            "Join us in January 2026 for a two-day, face-to-face build bootcamp "
            "dedicated to shipping operational LLM workflows in Erbil."
        ),
        template="blog/our_next_llm_focused.html",
        hero_image="https://i.imgur.com/Amgeg9j.jpeg",
        hero_image_alt="A sunrise skyline over Erbil with modern architecture in warm light",
        published_on=date(2025, 1, 16),
        read_time_minutes=6,
        location="Erbil",
    ),
]

_POST_LOOKUP: Dict[str, BlogPost] = {post.slug: post for post in _POSTS}

blog_bp = Blueprint("blog", __name__)


@blog_bp.get("/", strict_slashes=False)
def index() -> str:
    """Render the blog landing page."""

    posts = sorted(_POSTS, key=lambda p: p.published_on, reverse=True)
    return render_template("blog/index.html", posts=posts)


@blog_bp.get("/<slug>/", strict_slashes=False)
def detail(slug: str) -> str:
    """Render an individual blog post."""

    post = _POST_LOOKUP.get(slug)
    if not post:
        abort(404)
    return render_template(post.template, post=post)
