import os, json, re, logging, copy, csv
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from flask import Flask, render_template, abort, Response
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

# ---------------- App & config ----------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger("aiforimpact-default")

BRAND_NAME = os.getenv("BRAND_NAME", "Ai For Impact")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "https://i.imgur.com/STm5VaG.png")
COURSE_TITLE = os.getenv("COURSE_TITLE", "One on one Tailored Training Session")
COURSE_COVER_URL = os.getenv("COURSE_COVER_URL", "https://i.imgur.com/iIMdWOn.jpeg")
BASE_PATH = os.getenv("BASE_PATH", "")
DATA_DIR = Path(__file__).resolve().parent / "data"
MISSIONS_CSV = DATA_DIR / "mission.csv"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# -------------- DB connection --------------
def _is_dsn(s: str) -> bool:
    if not s:
        return False
    s = s.strip().lower()
    return s.startswith("postgresql://") or s.startswith("postgresql+psycopg2://") or s.startswith("postgresql+pg8000://")

def _sqlalchemy_url():
    # 1) Full DSN via DATABASE_URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    # 2) Full DSN via INSTANCE_CONNECTION_NAME (so you can keep the [cloudsql] structure)
    inst = os.getenv("INSTANCE_CONNECTION_NAME", "")
    if _is_dsn(inst):
        return inst

    # 3) Standard TCP params (optional)
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

    # 4) Cloud SQL unix socket style (project:region:instance)
    if inst and user and pwd and name:
        return URL.create(
            drivername="postgresql+psycopg2",
            username=user,
            password=pwd,
            host=None,
            database=name,
            query={"host": f"/cloudsql/{inst}"},
        )

    # 5) Fallback: local SQLite
    return "sqlite:///local.db"

ENGINE = create_engine(_sqlalchemy_url(), pool_pre_ping=True, future=True)
app.config["DB_ENGINE"] = ENGINE

# -------------- Template helpers --------------
@app.context_processor
def inject_helpers():
    def bp(path: str) -> str:
        base = (BASE_PATH or "").rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return (base + path) or "/"

    def page_allowed(name: str) -> bool:
        return name != "player"

    return dict(
        bp=bp,
        page_allowed=page_allowed,
        BASE_PATH=BASE_PATH,
        BRAND_NAME=BRAND_NAME,
        BRAND_LOGO_URL=BRAND_LOGO_URL,
        COURSE_COVER_URL=COURSE_COVER_URL,
    )

# -------------- Course helpers --------------
def _ensure_json(value: Any) -> Dict[str, Any]:
    if not value: return {}
    if isinstance(value, dict): return value
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            return json.loads(value)
    except Exception:
        return {}
    return {}

def _fetch_course() -> Optional[Dict[str, Any]]:
    sql = text("""
        SELECT id, title, is_published, published_at, created_at, structure
        FROM courses
        WHERE title ILIKE :t
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
    """)
    fallback = text("""
        SELECT id, title, is_published, published_at, created_at, structure
        FROM courses
        WHERE is_published = TRUE
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
    """)
    try:
        with ENGINE.begin() as conn:
            row = conn.execute(sql, {"t": COURSE_TITLE}).mappings().first()
            if not row:
                row = conn.execute(fallback).mappings().first()
            if not row:
                return None
            structure = _ensure_json(row["structure"])
            return {
                "id": row["id"],
                "title": row["title"] or COURSE_TITLE,
                "structure": structure,
            }
    except SQLAlchemyError as e:
        log.exception("DB error: %s", e)
        return None

def _summarize(structure: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, int]:
    sections = structure.get("sections") or []
    ordered = sorted(sections, key=lambda s: (s.get("order") is None, s.get("order", 0)))
    weeks: List[Dict[str, Any]] = []
    total = 0
    for s in ordered:
        lessons = s.get("lessons") or []
        total += len(lessons)
        weeks.append({"title": s.get("title") or "", "lessons_count": len(lessons)})
    return weeks, len(ordered), total


def _load_missions() -> List[Dict[str, str]]:
    missions: List[Dict[str, str]] = []
    if not MISSIONS_CSV.exists():
        log.warning("Mission CSV missing at %s", MISSIONS_CSV)
        return missions
    try:
        with open(MISSIONS_CSV, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                missions.append(
                    {
                        "mission_title": (row.get("Mission Title") or "").strip(),
                        "app_name": (row.get("App Name") or "").strip(),
                        "subtitle": (row.get("Subtitle") or "").strip(),
                        "goal": (row.get("Goal") or "").strip(),
                        "image_url": (row.get("Image URL") or "").strip(),
                        "link": (row.get("Link") or "").strip(),
                    }
                )
    except Exception as exc:
        log.exception("Failed to read missions CSV: %s", exc)
    return missions


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


def _fetch_recent_posts(limit: int = 3) -> List[Dict[str, Any]]:
    sql = text(
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
        LIMIT :limit
        """
    )
    posts: List[Dict[str, Any]] = []
    try:
        with ENGINE.begin() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
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
        log.exception("Failed to load recent blog posts: %s", exc)
    return posts


def _fetch_certificates(limit: int = 50) -> List[Dict[str, Any]]:
    sql = text(
        """
        SELECT id, full_name, date_of_joining, date_of_completion, credential, certificate_url
        FROM training_certificates
        ORDER BY date_of_completion DESC NULLS LAST, id DESC
        LIMIT :limit
        """
    )
    certificates: List[Dict[str, Any]] = []
    try:
        with ENGINE.begin() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
            for row in rows:
                joining = row.get("date_of_joining")
                completion = row.get("date_of_completion")

                def _fmt_date(value: Any) -> str:
                    try:
                        return value.strftime("%b %d, %Y")  # type: ignore[attr-defined]
                    except Exception:
                        return str(value) if value is not None else ""

                certificates.append(
                    {
                        "id": row.get("id"),
                        "full_name": row.get("full_name") or "",
                        "date_of_joining": _fmt_date(joining),
                        "date_of_completion": _fmt_date(completion),
                        "credential": row.get("credential") or "",
                        "certificate_url": row.get("certificate_url") or "",
                    }
                )
    except SQLAlchemyError as e:
        log.exception("DB error when fetching certificates: %s", e)
    return certificates

_slug_re = re.compile(r"[^a-z0-9\-]+")
def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    return _slug_re.sub("", s)

# -------------- Routes --------------
@app.get("/robots.txt")
def robots_txt() -> Response:
    return Response("User-agent: *\nDisallow:\n", mimetype="text/plain")

@app.get("/healthz")
def healthz():
    try:
        with ENGINE.begin() as c:
            c.execute(text("SELECT 1"))
        return "ok", 200
    except Exception:
        return "db error", 500

@app.get("/")
def home():
    from bootcamp import (  # type: ignore[attr-defined]
        BOOTCAMP_INFO,
        _fetch_bootcamp_seat_prices,
        summarize_bootcamp_price,
    )

    bootcamp_vm = copy.deepcopy(BOOTCAMP_INFO)
    bootcamp_vm.setdefault(
        "blurb",
        "A two-day, hands-on cohort built to help teams ship AI products alongside production experts.",
    )
    seat_prices = _fetch_bootcamp_seat_prices()
    if seat_prices:
        bootcamp_vm["seat_prices"] = seat_prices
        bootcamp_vm["price_summary"] = summarize_bootcamp_price(seat_prices)

    blog_posts = _fetch_recent_posts(limit=3)
    services = [
        {
            "name": "AI Bootcamp",
            "summary": "Hands-on, rapid upskilling for teams that need to apply AI to real operations in weeks, not months.",
            "href": "/bootcamp/",
            "cta": "Explore the bootcamp",
        },
        {
            "name": "Data Renovation",
            "summary": "Upgrade your data workflows and infrastructure so AI systems stay reliable and auditable in production.",
            "href": "/renovation",
            "cta": "Review renovation plans",
        },
    ]
    course = _fetch_course()
    missions = _load_missions()
    if not course:
        return render_template(
            "index.html",
            course=None,
            weeks=[],
            modules_count=0,
            lessons_count=0,
            services=services,
            bootcamp=bootcamp_vm,
            missions=missions,
            blog_posts=blog_posts,
        )
    structure = course.get("structure") or {}
    weeks, modules, lessons = _summarize(structure)
    vm = {
        "id": course["id"],
        "title": COURSE_TITLE or course["title"],
        "slug": slugify(course["title"]),
        "cover_url": COURSE_COVER_URL,
        "level": "Advanced",
        "category": "Real-Time AI Deployment",
    }
    return render_template("index.html",
        course=vm,
        weeks=weeks,
        modules_count=modules,
        lessons_count=lessons,
        services=services,
        bootcamp=bootcamp_vm,
        missions=missions,
        blog_posts=blog_posts,
    )


@app.get("/learning/")
def learning():
    from bootcamp import (
        BOOTCAMP_INFO,
        _fetch_bootcamp_seat_prices,
        summarize_bootcamp_price,
    )  # type: ignore[attr-defined]

    bootcamp_vm = copy.deepcopy(BOOTCAMP_INFO)
    bootcamp_vm.setdefault(
        "blurb",
        "A two-day, hands-on cohort built to help teams ship AI products alongside production experts.",
    )
    seat_prices = _fetch_bootcamp_seat_prices()
    if seat_prices:
        bootcamp_vm["seat_prices"] = seat_prices
        bootcamp_vm["price_summary"] = summarize_bootcamp_price(seat_prices)

    return render_template(
        "learning.html",
        bootcamp=bootcamp_vm,
    )

@app.get("/course/<int:cid>-<slug>")
def course_detail(cid: int, slug: str):
    course = _fetch_course()
    if not course or cid != course["id"] or slug != slugify(course["title"]):
        abort(404)
    structure = course.get("structure") or {}
    weeks, modules, lessons = _summarize(structure)
    vm = {
        "id": course["id"],
        "title": course["title"],
        "thumbnail_url": BRAND_LOGO_URL,
        "level": "Advanced",
        "category": "Real-Time AI Deployment",
    }
    return render_template("course_detail.html",
        course=vm,
        weeks=weeks,
        modules_count=modules,
        lessons_count=lessons,
        certificates=_fetch_certificates(),
    )

# ---- Blueprints ----
from registration import register_bp
app.register_blueprint(register_bp, url_prefix="/register")

from about import about_bp
app.register_blueprint(about_bp, url_prefix="/about")

# Mount PLAYGROUND hub
from playground import playground_bp
app.register_blueprint(playground_bp, url_prefix="/play")

# Mount PLAYGROUND subpage: WORKFLOW (blueprint)
from workflow import workflow_bp
app.register_blueprint(workflow_bp, url_prefix="/play/workflow")

# ---------- PROXY: keep the codespace endpoint working ----------
# So front-ends that still do fetch("/api/generate") hit the same generator
# that lives at /play/workflow/api/generate.
from workflow import api_generate as _wf_api_generate  # re-use the blueprint handler

@app.post("/api/generate")
def root_generate():
    # simply delegate to the workflow blueprint's view function
    return _wf_api_generate()

# --- PLAYGROUND subpage: PROMPT→UI (blueprint) ---
from promptui import promptui_bp, api_interpret as _pui_api_interpret, api_submit as _pui_api_submit
app.register_blueprint(promptui_bp, url_prefix="/play/promptui")

# Optional PROXIES for older clients that call /api/interpret or /api/submit directly
@app.post("/api/interpret")
def root_interpret():
    return _pui_api_interpret()

@app.post("/api/submit")
def root_submit():
    return _pui_api_submit()

# --- PRICE page (new) ---
from bootcamp import bootcamp_bp
app.register_blueprint(bootcamp_bp, url_prefix="/bootcamp")

from price import price_bp
app.register_blueprint(price_bp, url_prefix="/price")

from numen6 import numen6_bp
app.register_blueprint(numen6_bp, url_prefix="/numen6")

from subscriptions import subscription_bp
app.register_blueprint(subscription_bp)

from blog_page import blog_bp
app.register_blueprint(blog_bp, url_prefix="/blog")

@app.get("/renovation")
def renovation():
    return render_template("renovation.html")
from contact import contact_bp
app.register_blueprint(contact_bp, url_prefix="/contact")

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import request, redirect

# Trust Render’s proxy so scheme/host are correct
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

@app.before_request
def force_www():
    if request.host.lower() == "aiforimpact.net":
        return redirect(request.url.replace("://aiforimpact.net", "://www.aiforimpact.net", 1), 301)


# ---------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=False)
