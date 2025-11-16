from __future__ import annotations
import os, re, json, logging
from typing import Any, Dict, List, Tuple
from flask import Blueprint, request, jsonify, render_template

# ---------- Logging ----------
log = logging.getLogger("promptui")
if not log.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# Optional OpenAI import so the app still boots if package isn't installed
try:
    from openai import OpenAI  # openai>=1.x
except Exception:
    OpenAI = None  # type: ignore

# =========================
# Config
# =========================
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")   # set in app.yaml / env

# Fail-fast client: short timeout, no retries -> avoids gunicorn timeouts
if OpenAI and OPENAI_API_KEY:
    try:
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            timeout=12.0,   # total I/O timeout
            max_retries=0,  # no backoff delays
        )
    except Exception as e:
        log.warning("OpenAI client init failed, using local fallback only: %s", e)
        client = None
else:
    client = None

# Blueprint
promptui_bp = Blueprint("promptui", __name__, template_folder="templates")

# =========================
# Model instruction (generic, no domain bias)
# =========================
SCHEMA_GUIDE = """
You are a UI generator. Return ONLY one JSON object (no prose, no backticks).
Use EXACTLY this schema and ONLY these block types:

{
  "page": {"title": string, "layout": "wide" | "centered"},
  "blocks": [
    { "type": "heading", "level": 1|2|3, "text": string },
    { "type": "text", "text": string },
    { "type": "metric", "label": string, "value": string, "delta": string? },
    { "type": "card", "title": string?, "body": string?, "children": [<blocks>]? },
    { "type": "table", "columns": [string], "rows": [[string|number|boolean,...], ...] },
    { "type": "chart", "kind": "line"|"bar", "data": {"x":[number|string], "y":[number]} },
    { "type": "input", "inputType": "text"|"number"|"password", "label": string, "id": string, "placeholder": string?, "value": string|number? },
    { "type": "select", "label": string, "id": string, "options": [{"label": string, "value": string}], "value": string? },
    { "type": "button", "text": string, "id": string },
    { "type": "columns", "ratio": [number, ...], "columns": [ [<blocks>], ... ] }
  ]
}

Rules:
- Produce valid JSON only.
- Use numeric values explicitly present in the request (e.g., “1000 meters”) for labels/inputs if relevant.
- If a data series or table is requested but values are unspecified, emit empty arrays (e.g., {"x":[], "y":[]} or rows: []).
- Keep output compact and faithful to the request.
"""

# =========================
# Helpers
# =========================
DEPTH_PAT = re.compile(
    r"\b(\d{1,6}(?:\.\d+)?)\s*(m|meter|meters|km|kilometer|kilometers|ft|feet)\b",
    re.IGNORECASE,
)

def extract_depth(prompt: str) -> Tuple[float|None, str|None]:
    m = DEPTH_PAT.search(prompt or "")
    if not m:
        return None, None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("km"):  # normalize to meters
        return val * 1000.0, "m"
    if unit in ("m", "meter", "meters"):
        return val, "m"
    if unit in ("ft", "feet"):
        return val, "ft"
    return val, unit

def wants_geology(prompt: str) -> bool:
    p = (prompt or "").lower()
    return any(k in p for k in ("geolog", "rock", "stratig", "litholog", "formation"))

def wants_chart(prompt: str) -> bool:
    p = (prompt or "").lower()
    return any(k in p for k in ("chart", "plot", "graph", "visual", "profile", "curve", "trend", "line", "bar"))

def wants_table(prompt: str) -> bool:
    p = (prompt or "").lower()
    return any(k in p for k in ("table", "tabular", "rows", "columns", "list of"))

def wants_inputs(prompt: str) -> bool:
    p = (prompt or "").lower()
    return any(k in p for k in ("input", "form", "field", "enter", "edit", "configure", "parameter"))

def mentions_geothermal(prompt: str) -> bool:
    p = (prompt or "").lower()
    return "geothermal" in p

def _extract_json(text: str) -> Dict[str, Any] | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except Exception:
                    return None
    return None

def _sanitize_schema(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strict schema sanitizer. Trims structure; keeps only allowed fields/types.
    """
    if not isinstance(obj, dict):
        return {"page": {"title":"Generated UI","layout":"wide"}, "blocks":[]}
    page = obj.get("page") or {}
    blocks = obj.get("blocks") or []
    out: Dict[str, Any] = {
        "page": {
            "title": str(page.get("title") or "Generated UI")[:120],
            "layout": "centered" if page.get("layout") == "centered" else "wide",
        },
        "blocks": []
    }
    def txt(x, n=4000): return ("" if x is None else str(x))[:n]
    def short(x, n=120): return ("" if x is None else str(x))[:n]
    def safe_id(s): return (re.sub(r"[^a-zA-Z0-9_.-]", "_", s or "") or "id")[:60]

    blocks = blocks[:100] if isinstance(blocks, list) else []

    for b in blocks:
        if not isinstance(b, dict): continue
        t = (b.get("type") or "").lower()

        if t == "heading":
            lvl = 1 if b.get("level")==1 else 3 if b.get("level")==3 else 2
            out["blocks"].append({"type":"heading","level":lvl,"text":txt(b.get("text"))})

        elif t == "text":
            out["blocks"].append({"type":"text","text":txt(b.get("text"))})

        elif t == "metric":
            out["blocks"].append({
                "type":"metric",
                "label": short(b.get("label")),
                "value": short(b.get("value")),
                "delta": short(b.get("delta") or "")
            })

        elif t == "card":
            node = {"type":"card","title":short(b.get("title") or ""), "body":txt(b.get("body") or "")}
            if isinstance(b.get("children"), list):
                node["children"] = _sanitize_schema({"page":{}, "blocks":b["children"]})["blocks"]
            out["blocks"].append(node)

        elif t == "table":
            cols = [short(c) for c in (b.get("columns") or [])][:24]
            rows = []
            for r in (b.get("rows") or [])[:500]:
                if isinstance(r, list):
                    rows.append([short(x, 200) for x in r[:len(cols)]])
            out["blocks"].append({"type":"table","columns":cols,"rows":rows})

        elif t == "chart":
            kind = "bar" if b.get("kind") == "bar" else "line"
            data = b.get("data") or {}
            X = (data.get("x") or [])[:500]
            Y: List[float] = []
            for y in (data.get("y") or [])[:500]:
                try:
                    Y.append(float(y))
                except Exception:
                    continue
            out["blocks"].append({"type":"chart","kind":kind,"data":{"x":X,"y":Y}})

        elif t == "input":
            it = b.get("inputType") if b.get("inputType") in ("text","number","password") else "text"
            out["blocks"].append({
                "type":"input",
                "inputType": it,
                "label": short(b.get("label")),
                "id":    safe_id(b.get("id") or "input"),
                "placeholder": short(b.get("placeholder") or ""),
                "value": b.get("value")
            })

        elif t == "select":
            opts = []
            for o in (b.get("options") or [])[:100]:
                if isinstance(o, dict) and "label" in o and "value" in o:
                    opts.append({"label":short(o["label"]), "value":short(o["value"])})
            val = b.get("value") or (opts[0]["value"] if opts else "")
            out["blocks"].append({
                "type":"select",
                "label": short(b.get("label")),
                "id":    safe_id(b.get("id") or "select"),
                "options": opts,
                "value": short(val)
            })

        elif t == "button":
            out["blocks"].append({"type":"button","text":short(b.get("text") or "Submit"), "id":safe_id(b.get("id") or "action")})

        elif t == "columns":
            ratio = b.get("ratio") or [1,1]
            if not isinstance(ratio, list) or not ratio: ratio = [1,1]
            cols = b.get("columns") or [[] for _ in ratio]
            new_cols = []
            for col in cols[:len(ratio)]:
                if isinstance(col, list):
                    new_cols.append(_sanitize_schema({"page":{}, "blocks":col})["blocks"])
            out["blocks"].append({"type":"columns","ratio":[int(x) for x in ratio][:8], "columns": new_cols})

        # ignore anything else
    return out

def dedupe_heading_equal_to_title(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Remove a top heading equal to page.title to avoid duplicate title rendering."""
    title = (schema.get("page", {}).get("title") or "").strip().lower()
    blocks = schema.get("blocks") or []
    new_blocks = []
    removed = False
    for b in blocks:
        if not removed and (b.get("type") == "heading"):
            if (b.get("text") or "").strip().lower() == title:
                removed = True
                continue
        new_blocks.append(b)
    schema["blocks"] = new_blocks
    return schema

# =========================
# Local, prompt-driven data & UI (no AI)
# =========================
def build_depth_series(depth_val: float, unit: str) -> Tuple[List[str], List[float]]:
    """Deterministic temperature vs depth series. unit is 'm' or 'ft' (labels in given unit)."""
    n = 21
    if depth_val <= 0:
        return [], []
    step = depth_val / (n - 1)
    # Temperature gradient: 30°C/km => 0.03 °C/m
    x_labels: List[str] = []
    y_vals: List[float] = []
    for i in range(n):
        d = i * step
        d_m = d if unit == "m" else d * 0.3048
        T = 15.0 + 0.03 * d_m  # surface 15°C
        x_labels.append(f"{round(d)}" if unit == "m" else f"{round(d)}")
        y_vals.append(round(T, 1))
    return x_labels, y_vals

def build_geology_layers(depth_val: float, unit: str, geothermal: bool) -> List[List[Any]]:
    """Deterministic layers spanning 0 -> depth_val in requested unit."""
    if depth_val <= 0:
        return []
    # Breakpoints (fixed proportions)
    bp = [0.05, 0.25, 0.65, 1.00]
    cuts = [0] + [round(depth_val * p) for p in bp]
    # Ensure strictly increasing and end at depth
    cuts = [cuts[0]] + [max(cuts[i], cuts[i-1]+1) for i in range(1, len(cuts))]
    cuts[-1] = int(round(depth_val))
    # Rock labels
    if geothermal:
        rocks = ["Topsoil", "Sedimentary (sandstone)", "Limestone", "Basalt / Granite"]
    else:
        rocks = ["Topsoil", "Clay/Silt", "Sandstone", "Shale/Granite"]
    rows: List[List[Any]] = []
    for i in range(len(cuts)-1):
        rows.append([cuts[i], cuts[i+1], rocks[i]])
    return rows

def local_ui_for_prompt(prompt: str) -> Dict[str, Any]:
    """
    Heuristic UI generator that responds to the user's prompt.
    Produces structure + deterministic data derived from the prompt (no randomness).
    """
    p = (prompt or "").strip()
    title = p if p else "Generated UI"

    depth_val, unit = extract_depth(p)
    mentions_depth = "depth" in p.lower() or (depth_val is not None)
    geo = wants_geology(p)
    is_geo_thermal = mentions_geothermal(p)

    # Decide which components we need
    need_chart = wants_chart(p) or mentions_depth or is_geo_thermal
    need_table = wants_table(p) or geo
    need_inputs = wants_inputs(p) or mentions_depth or geo

    # Default unit & value if depth mentioned w/o number
    unit = unit or "m"
    if depth_val is None and mentions_depth:
        depth_val = 1000.0  # deterministic fallback when depth requested but not specified

    # Inputs card
    inputs_children: List[Dict[str, Any]] = []
    if need_inputs:
        if depth_val is not None:
            if unit == "ft":
                inputs_children.append({"type":"input","inputType":"number","label":"Target depth (ft)","id":"target_depth_ft","value":round(depth_val)})
                unit_value = "ft"
            else:
                inputs_children.append({"type":"input","inputType":"number","label":"Target depth (m)","id":"target_depth_m","value":round(depth_val)})
                unit_value = "m"
        else:
            inputs_children.append({"type":"input","inputType":"number","label":"Target depth","id":"target_depth","placeholder":"e.g., 1000"})
            unit_value = "m"
        inputs_children.append({
            "type":"select","label":"Unit","id":"depth_unit",
            "options":[{"label":"Meters","value":"m"},{"label":"Feet","value":"ft"}],
            "value": unit_value
        })

    # Layers table
    layers_table: Dict[str, Any] | None = None
    if need_table:
        col_unit = unit
        rows = build_geology_layers(depth_val or 0, col_unit, geothermal=is_geo_thermal) if (depth_val or 0) > 0 else []
        layers_table = {
            "type":"table",
            "columns":[f"From ({col_unit})", f"To ({col_unit})", "Rock type"],
            "rows": rows
        }

    # Chart
    chart_block: Dict[str, Any] | None = None
    if need_chart:
        X, Y = build_depth_series(depth_val or 0, unit) if (depth_val or 0) > 0 else ([], [])
        chart_block = {"type":"chart","kind":"line","data":{"x": X, "y": Y}}

    # Compose layout (no duplicate heading; we rely on page.title)
    left_col: List[Dict[str, Any]] = []
    right_col: List[Dict[str, Any]] = []

    if inputs_children:
        left_col.append({"type":"card","title":"Inputs","children":inputs_children})

    if layers_table:
        right_col.append({"type":"card","title":"Geological layers","children":[layers_table]})

    if chart_block:
        right_col.append({"type":"card","title":"Depth profile (Temperature vs Depth)","children":[chart_block]})

    blocks: List[Dict[str, Any]] = []
    if left_col or right_col:
        blocks.append({"type":"columns","ratio":[1,2], "columns":[left_col or [], right_col or []]})
    else:
        blocks.append({"type":"text","text":"Add details like 'depth 1000 m', 'geological rocks', 'table', or 'chart'."})

    return {"page":{"title":title,"layout":"wide"},"blocks":blocks}

def enrich_schema_with_context(schema: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    """
    If the AI result omitted data, fill chart/table with deterministic, prompt-derived content.
    Also remove heading equal to page.title to avoid duplicate titles.
    """
    schema = dedupe_heading_equal_to_title(schema)

    depth_val, unit = extract_depth(prompt)
    mentions_depth = "depth" in (prompt or "").lower() or (depth_val is not None)
    geo = wants_geology(prompt)
    is_geo_thermal = mentions_geothermal(prompt)
    need_chart = wants_chart(prompt) or mentions_depth or is_geo_thermal
    need_table = wants_table(prompt) or geo
    unit = unit or "m"

    blocks = schema.get("blocks") or []

    # Track presence
    has_chart = False
    has_table = False
    chart_filled = False
    table_filled = False

    for b in blocks:
        if b.get("type") == "chart":
            has_chart = True
            data = b.get("data") or {}
            X = data.get("x") or []
            Y = data.get("y") or []
            if (not X or not Y) and (depth_val or 0) > 0:
                Xc, Yc = build_depth_series(depth_val, unit)
                b["data"] = {"x": Xc, "y": Yc}
                chart_filled = True

        if b.get("type") == "table":
            has_table = True
            rows = b.get("rows") or []
            cols = b.get("columns") or []
            looks_like_layers = any(isinstance(c, str) and "from" in c.lower() for c in cols) and any(isinstance(c, str) and "to" in c.lower() for c in cols)
            if looks_like_layers and not rows and (depth_val or 0) > 0:
                b["rows"] = build_geology_layers(depth_val, unit, geothermal=is_geo_thermal)
                table_filled = True

        if b.get("type") == "columns":
            for col in b.get("columns", []):
                for bb in col:
                    if bb.get("type") == "chart":
                        has_chart = True
                        data = bb.get("data") or {}
                        X = data.get("x") or []
                        Y = data.get("y") or []
                        if (not X or not Y) and (depth_val or 0) > 0:
                            Xc, Yc = build_depth_series(depth_val, unit)
                            bb["data"] = {"x": Xc, "y": Yc}
                            chart_filled = True
                    if bb.get("type") == "table":
                        has_table = True
                        rows = bb.get("rows") or []
                        cols = bb.get("columns") or []
                        looks_like_layers = any(isinstance(c, str) and "from" in c.lower() for c in cols) and any(isinstance(c, str) and "to" in c.lower() for c in cols)
                        if looks_like_layers and not rows and (depth_val or 0) > 0:
                            bb["rows"] = build_geology_layers(depth_val, unit, geothermal=is_geo_thermal)
                            table_filled = True

    # If the AI omitted a chart/table but they are clearly implied, append cards.
    if need_chart and not has_chart and (depth_val or 0) > 0:
        Xc, Yc = build_depth_series(depth_val, unit)
        blocks.append({"type":"card","title":"Depth profile (Temperature vs Depth)","children":[{"type":"chart","kind":"line","data":{"x":Xc,"y":Yc}}]})

    if need_table and not has_table and (depth_val or 0) > 0:
        rows = build_geology_layers(depth_val, unit, geothermal=is_geo_thermal)
        blocks.append({"type":"card","title":"Geological layers","children":[{"type":"table","columns":[f"From ({unit})",f"To ({unit})","Rock type"],"rows":rows}]})

    schema["blocks"] = blocks
    return schema

# =========================
# Routes
# =========================
@promptui_bp.get("")
@promptui_bp.get("/")
def index():
    return render_template("promptui.html")

@promptui_bp.after_app_request
def _no_store(resp):
    p = request.path or ""
    if "/play/promptui/api/" in p:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

@promptui_bp.post("/api/interpret", endpoint="api_interpret")
def api_interpret():
    """
    OpenAI-first, then deterministic local UI + data based on the prompt.
    Also de-dupes headings that repeat page.title.
    """
    try:
        payload = request.get_json(silent=True) or {}
        prompt = (payload.get("prompt") or "").strip()

        # Fast path if no client
        if not client:
            schema = local_ui_for_prompt(prompt)
            return jsonify({"schema": schema}), 200

        raw = ""
        try:
            resp = client.responses.create(
                model=OPENAI_MODEL,
                instructions=SCHEMA_GUIDE,
                input=f"User request:\n{prompt}\n\nReturn ONLY the JSON UI object.",
                max_output_tokens=700,
                timeout=12.0,
            )
            raw = getattr(resp, "output_text", "") or ""
            if not raw and hasattr(resp, "content"):
                parts = []
                for item in (resp.content or []):
                    text_part = getattr(item, "text", None)
                    if isinstance(text_part, list):
                        parts.extend(getattr(t, "value", "") or "" for t in text_part)
                    elif isinstance(text_part, str):
                        parts.append(text_part)
                raw = "".join(parts)
        except Exception as e:
            log.warning("OpenAI call failed/timeout; using local UI. err=%s", e)
            raw = ""

        obj = _extract_json(raw)
        if obj:
            schema = _sanitize_schema(obj)
            schema = enrich_schema_with_context(schema, prompt)
        else:
            schema = local_ui_for_prompt(prompt)

        return jsonify({"schema": schema}), 200

    except Exception as e:
        log.exception("api_interpret crashed: %s", e)
        return jsonify({"schema": local_ui_for_prompt("")}), 200

@promptui_bp.post("/api/submit", endpoint="api_submit")
def api_submit():
    payload = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "echo": payload}), 200
