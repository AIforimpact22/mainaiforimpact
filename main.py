import os, json, re, logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
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
COURSE_TITLE = os.getenv("COURSE_TITLE", "Advanced AI Utilization and Real-Time Deployment")
COURSE_COVER_URL = os.getenv("COURSE_COVER_URL", "https://i.imgur.com/iIMdWOn.jpeg")
BASE_PATH = os.getenv("BASE_PATH", "")

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

def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y")
    if isinstance(value, date):
        return value.strftime("%b %d, %Y")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.strftime("%b %d, %Y")
        except ValueError:
            return str(value)
    return ""

def _normalize_price_type(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    if value in {"regular", "standard", "list"}:
        return "regular"
    if "early" in value:
        return "early_bird"
    return value

def _fetch_bootcamp_offerings() -> List[Dict[str, Any]]:
    sql = text(
        """
        SELECT id, bootcamp_name, location, event_date, seat_tier,
               price_type, price, currency, seats_total, seats_sold,
               seats_remaining, valid_from, valid_to, is_active, notes
        FROM public.bootcamp_seat_prices_view
        WHERE is_active IS DISTINCT FROM FALSE
        ORDER BY event_date NULLS LAST, seat_tier, price_type
        """
    )
    try:
        with ENGINE.begin() as conn:
            rows = conn.execute(sql).mappings().all()
    except SQLAlchemyError as exc:
        log.exception("Failed to load bootcamp prices: %s", exc)
        return []

    grouped: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        key = (row.get("bootcamp_name"), row.get("location"), row.get("event_date"), row.get("seat_tier"))
        bucket = grouped.setdefault(
            key,
            {
                "bootcamp_name": row.get("bootcamp_name") or "Bootcamp",
                "location": row.get("location") or "TBA",
                "event_date": row.get("event_date"),
                "event_date_display": _format_date(row.get("event_date")),
                "seat_tier": row.get("seat_tier") or "General",
                "currency": row.get("currency") or "EUR",
                "regular_price": None,
                "early_bird_price": None,
                "early_bird_deadline": None,
                "early_bird_deadline_display": "",
                "seats_total": row.get("seats_total"),
                "seats_remaining": row.get("seats_remaining"),
                "notes": row.get("notes"),
            },
        )

        price_type = _normalize_price_type(row.get("price_type"))
        if price_type == "regular":
            bucket["regular_price"] = row.get("price")
        elif price_type == "early_bird":
            bucket["early_bird_price"] = row.get("price")
            deadline = row.get("valid_to") or row.get("valid_from")
            bucket["early_bird_deadline"] = deadline
            bucket["early_bird_deadline_display"] = _format_date(deadline)

    offerings = list(grouped.values())
    offerings.sort(key=lambda item: (
        item.get("event_date") or date.max,
        item.get("seat_tier") or "",
    ))
    return offerings

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
    course = _fetch_course()
    if not course:
        return render_template("index.html", course=None, weeks=[], modules_count=0, lessons_count=0)
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
        course=vm, weeks=weeks, modules_count=modules, lessons_count=lessons)

@app.get("/learning")
def learning_page():
    bootcamps = _fetch_bootcamp_offerings()
    course = _fetch_course()
    course_vm = None
    if course:
        course_vm = {
            "id": course["id"],
            "title": COURSE_TITLE or course["title"],
            "slug": slugify(course["title"]),
        }
    return render_template("learning.html", course=course_vm, bootcamps=bootcamps)

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
        course=vm, weeks=weeks, modules_count=modules, lessons_count=lessons)

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
from price import price_bp
app.register_blueprint(price_bp, url_prefix="/price")

@app.get("/renovation")
def renovation():
    return render_template("renovation.html")

# ---------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=False)
