# /home/aiforimpact22/mainapp/workflow.py
import os
import re
import json
import logging
from flask import Blueprint, request, jsonify, render_template

# ---------- Logging ----------
log = logging.getLogger("workflow")
if not log.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

# Optional OpenAI import so the app still boots if package isn't installed
try:
    from openai import OpenAI  # openai>=1.x
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

# ---------- Config ----------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # set via app.yaml or secrets

# Optional OpenAI client (AI mode) — only if both package + key are present
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

# Branding (watermark)
BRAND_LOGO_URL = "https://i.imgur.com/STm5VaG.png"
BRAND_NAME = "Ai For Impact"
BRAND_SITE = "www.aiforimpact.net"

# Blueprint
workflow_bp = Blueprint("workflow", __name__, template_folder="templates")

# ----------------- Local prompt → nodes[] (no LLM) -----------------
STOPWORDS = set("""
a an and the to for of with into from by our your their his her its on in over under at as is are be been were was do does did
then next after before finally also so that which who whom whose this those these it they we you i
system app module service ai agent process workflow task stage phase item node data info information
""".split())

GROUP_KEYWORDS = [
    ("input",       r"(ingest|capture|record|collect|scan|load|update|read|write|sync|import|export|fetch)"),
    ("analysis",    r"(analy|calculat|compute|score|cluster|classif|detect|match|rank|measure|metric|velocity|average|trend)"),
    ("model",       r"(train|fit|learn|model|regress|classif|predict|inference|forecast)"),
    ("po",          r"(po|purchase|order|reorder|supplier|vendor|procure|quote|tender)"),
    ("validation",  r"(validate|approve|review|audit|monitor|observe|control|budget|policy|sign.?off|qa|qc|verify)"),
    ("communication", r"(notify|message|email|sms|webhook|post|publish|send|alert|broadcast)"),
    ("ops",         r"(deploy|operate|scale|backup|restore|schedule|cron|retry|queue|cache|index)"),
]

def _sentences(prompt: str):
    parts = re.split(r"(?:\n+|[.;:]+|\bthen\b|\band then\b|\bnext\b|\bafter\b|→|=>|->)", prompt, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip()]

def _clean_words(s: str):
    raw = re.split(r"[^A-Za-z0-9_]+", s.lower())
    return [w for w in raw if w and (w not in STOPWORDS) and re.search(r"[a-z]", w)]

def _pascal_from_words(words, cap=6):
    if not words: return "Step"
    picked = words[:cap]
    pascal = "".join(w[:1].upper() + w[1:] for w in picked)
    if not re.match(r"^[A-Za-z]", pascal):
        pascal = "Step" + pascal
    return pascal

def _guess_group(text: str):
    for group, pat in GROUP_KEYWORDS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return group
    return "flow"

def _stable_size(name: str):
    s = sum(ord(c) for c in name)
    return 350 + (s % 551)  # 350..900

def _extract_arrow_edges(prompt: str):
    pairs = []
    for m in re.finditer(r"([A-Za-z0-9 _\-\/]{2,}?)\s*(?:->|→|=>)\s*([A-Za-z0-9 _\-\/]{2,})", prompt):
        a = m.group(1).strip(); b = m.group(2).strip()
        if a and b: pairs.append((a, b))
    return pairs

def _local_nodes_from_prompt(prompt: str):
    sents = _sentences(prompt)
    if len(sents) < 3:
        extra = re.split(r"\band\b|,|\u2013|\u2014", prompt, flags=re.IGNORECASE)
        sents = [x.strip() for x in extra if x.strip()]

    nodes, seen = [], set()
    for s in sents:
        words = _clean_words(s)
        if not words:
            continue
        step = _pascal_from_words(words, cap=6)
        if step.lower() == "step":
            continue
        group = _guess_group(s)
        dotted = f"method.{group}.{step}"
        if dotted in seen:
            continue
        seen.add(dotted)
        nodes.append({"name": dotted, "size": _stable_size(dotted), "imports": []})

    # Arrow hints A -> B
    arrow_pairs = _extract_arrow_edges(prompt)
    if arrow_pairs and nodes:
        def fuzzy_find(txt):
            tw = _clean_words(txt)
            if not tw: return None
            needle = re.escape(tw[0])
            for n in nodes:
                if re.search(needle, n["name"], re.IGNORECASE):
                    return n["name"]
            return None
        for a_txt, b_txt in arrow_pairs:
            a = fuzzy_find(a_txt); b = fuzzy_find(b_txt)
            if a and b and a != b:
                for n in nodes:
                    if n["name"] == a and b not in n["imports"]:
                        n["imports"].append(b)

    # If no edges present, chain to improve visibility
    if sum(len(n["imports"]) for n in nodes) == 0 and len(nodes) >= 2:
        for i in range(1, len(nodes)):
            prev = nodes[i - 1]["name"]
            if prev not in nodes[i]["imports"]:
                nodes[i]["imports"].append(prev)

    # Validate dotted names and imports
    dotted_ok = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
    names = {n["name"] for n in nodes if dotted_ok.match(n["name"])}
    out = []
    for n in nodes:
        if n["name"] not in names:
            continue
        n["imports"] = [i for i in dict.fromkeys(n.get("imports", [])) if i in names and i != n["name"]]
        out.append(n)
    return out

# ----------------- Optional AI path -----------------
def _extract_nodes_array(text: str):
    if not text: return None
    try:
        obj = json.loads(text)
        if isinstance(obj, list): return obj
        if isinstance(obj, dict) and isinstance(obj.get("nodes"), list): return obj["nodes"]
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, list): return obj
            if isinstance(obj, dict) and isinstance(obj.get("nodes"), list): return obj["nodes"]
        except Exception:
            pass
    arrays = re.findall(r"\[[\s\S]*\]", text)
    arrays.sort(key=len, reverse=True)
    for arr in arrays:
        try:
            obj = json.loads(arr)
            if isinstance(obj, list): return obj
        except Exception:
            continue
    return None

def _coerce_and_validate_nodes(nodes):
    if not isinstance(nodes, list): return []
    dotted_ok = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
    out, seen = [], set()
    for n in nodes:
        if not isinstance(n, dict): continue
        name = n.get("name"); size = n.get("size", 600); imports = n.get("imports", [])
        if not isinstance(name, str) or not dotted_ok.match(name): continue
        try: size = int(size)
        except Exception: size = 600
        if not isinstance(imports, list): imports = []
        imports = [i for i in imports if isinstance(i, str) and dotted_ok.match(i)]
        if name in seen: continue
        seen.add(name)
        out.append({"name": name, "size": max(1, min(100000, size)), "imports": imports})
    names = {n["name"] for n in out}
    for n in out:
        n["imports"] = [i for i in n["imports"] if i in names and i != n["name"]]
    if sum(len(n["imports"]) for n in out) == 0 and len(out) >= 2:
        for i in range(1, len(out)):
            prev = out[i - 1]["name"]
            if prev not in out[i]["imports"]:
                out[i]["imports"].append(prev)
    return out

def _ai_nodes_from_prompt(prompt: str):
    # If client is missing or key not set, transparently fall back to local
    if not client:
        return _local_nodes_from_prompt(prompt)

    system_msg = (
        "You are a workflow graph generator. Output ONLY a JSON array of nodes. "
        "Each node is {\"name\": string, \"size\": integer, \"imports\": string[]}. "
        "Flat array of ~8–24 leaf nodes; names are dotted paths with 3+ segments; "
        "imports reference other names in the SAME array; no prose."
    )
    user_msg = (
        f"Description:\n{prompt}\n\n"
        "Return ONLY the JSON array like:\n"
        "[{\"name\":\"method.input.PrepareData\",\"size\":800,\"imports\":[]}, ...]"
    )

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_msg},
                      {"role": "user", "content": user_msg}],
            max_completion_tokens=2048,
        )
        content = (resp.choices[0].message.content or "").strip()
        nodes = _extract_nodes_array(content) or _local_nodes_from_prompt(prompt)
        nodes = _coerce_and_validate_nodes(nodes)
        if len(nodes) < 3:
            return _local_nodes_from_prompt(prompt)
        return nodes
    except Exception as e:  # Any OpenAI error → local fallback
        log.warning("OpenAI failed; using local fallback: %s", e)
        return _local_nodes_from_prompt(prompt)

# ----------------- Routes -----------------
# Serve both /play/workflow and /play/workflow/ so relative links behave consistently.
@workflow_bp.get("")
@workflow_bp.get("/")
def index():
    return render_template(
        "workflow.html",
        brand_logo_url=BRAND_LOGO_URL,
        brand_name=BRAND_NAME,
        brand_site=BRAND_SITE,
        model_name=OPENAI_MODEL,
        ai_available=bool(client)
    )

@workflow_bp.post("/api/generate", endpoint="api_generate")
def api_generate():
    """
    Robust generator endpoint:
    - Default mode is 'ai'
    - Falls back safely to local generation
    - Never 500s on normal errors; logs exceptions
    """
    try:
        body = request.get_json(silent=True) or {}
        prompt = (body.get("prompt") or "").strip()
        # Default to AI unless explicitly forced to 'local'
        mode = (body.get("mode") or "ai").lower()

        if not prompt:
            return jsonify({"error": "Missing 'prompt'"}), 400

        # Generate nodes (AI → local fallback inside helper)
        nodes = _ai_nodes_from_prompt(prompt) if mode == "ai" else _local_nodes_from_prompt(prompt)

        # If parsing yielded too few nodes, try local, then last‑resort synthetic chain
        if len(nodes) < 3:
            nodes = _local_nodes_from_prompt(prompt)
        if len(nodes) < 3:
            # Never leave the UI empty — return a minimal visible chain
            nodes = [
                {"name": "method.flow.Start",   "size": 600, "imports": []},
                {"name": "method.flow.Process", "size": 600, "imports": ["method.flow.Start"]},
                {"name": "method.flow.End",     "size": 600, "imports": ["method.flow.Process"]},
            ]

        return jsonify({"nodes": nodes}), 200

    except Exception as e:  # Absolute last resort
        log.exception("api_generate crashed: %s", e)
        return jsonify({"error": "Internal error while generating workflow."}), 500
