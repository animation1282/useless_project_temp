"""Natural-language -> fixed actions via the SAME Gemini API (no new provider).

Reusable outside Discord:
    from nl_agent import parse_request
    res = parse_request("play some lofi lol")
    # {"reply": "<witty>", "actions": [{"tool": "open_app", ...}], "straight_goal": "..."}

Planner: practical helper-first chains with at most one small joke. Screenshots
(find_move) are a LAST RESORT. Safety limits enforced in code, not just prompt.
"""

import json
import os
import re
import traceback

from input_control import ALLOWED_KEYS, BLOCKED_COMBOS, MAX_TYPE_LEN, MAX_WAIT

TEXT_MODEL_DEFAULT = "gemini-2.0-flash"
MAX_ACTIONS = 10
MIN_ACTIONS = 5

GENIE_SYSTEM = (
    "You are a scenic-route PC tour guide. Always reach the goal — but never directly.\n"
    "\n"
    "PLAN SHAPE (5-10 steps)\n"
    "1. 3-6 DETOUR stops related to the request but NOT the request itself: "
    "apps/sites on the same theme (e.g. \"wikipedia computers\" -> tech blog, "
    "computer history search, settings app — never the exact target first).\n"
    "2. waits after every open. No typing right after open_url.\n"
    "3. MANDATORY FINALE, labeled in the reply: attempt the real goal verbatim "
    "(open the target / type the text). Detours are funny; the finale is faithful.\n"
    "4. find_move only when helpers cannot do it.\n"
    "\n"
    "RULES\n"
    "- First action must NEVER be the goal (no lone open_url/open_app-target).\n"
    "- The goal MUST appear in the final 2 steps (open target URL/app or type the "
    "requested text). Plans without it are invalid.\n"
    "- Steps share a theme; nothing fully random.\n"
    "- Type <=200 chars; app names simple; URLs http(s); waits 0.5-5s.\n"
    "- Banned: alt+f4, ctrl+alt+delete, win+l, win+d.\n"
    "- Reply: witty (2 lines max: joke + finale label), names the tour + confirms "
    "the finale happens. NEVER list steps as numbered/bulleted text — emit tool "
    "calls for every step; no 'Tour complete' prose.\n"
    "\n"
    "EXAMPLES\n"
    "- \"open wikipedia article on computers\" =>\n"
    "  open_app chrome, wait 1, web_search \"history of computers\", wait 1, "
    "open_url tech-blog link, wait 1, web_search \"wikipedia computers\", "
    "wait 1, open_url wikipedia link (finale: goal)\n"
    "- \"open text editor and type hello world\" =>\n"
    "  open_app calculator, wait 1, open_app chrome, wait 1, "
    "web_search \"best text editors\", wait 1, open_app notepad, "
    "type \"hello world\" (finale: goal)"
)

TOOL_SCHEMAS = [
    {
        "name": "open_app",
        "description": "Tour stop or mandatory finale: open an app via OS search (Win/Super, type name, enter). Detours first, goal in final 2 steps. Follow with a wait step.",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string"}},
                       "required": ["app"]},
    },
    {
        "name": "open_url",
        "description": "Tour stop or mandatory finale: open an http(s) URL. Never the goal as step 1; goal must be attempted in final 2 steps. Follow with a wait step.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]},
    },
    {
        "name": "web_search",
        "description": "Tour stop: search the web via Google URL. Themed detour queries before the finale.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
    {
        "name": "wait",
        "description": "Pause 0.5-5s so apps/pages load between steps.",
        "parameters": {"type": "object",
                       "properties": {"seconds": {"type": "number"}},
                       "required": ["seconds"]},
    },
    {
        "name": "press",
        "description": "Press a key combo like enter, ctrl+c, win. No blocked combos.",
        "parameters": {"type": "object",
                       "properties": {"keys": {"type": "string"}},
                       "required": ["keys"]},
    },
    {
        "name": "type",
        "description": "Type text (max 200 chars). Never immediately after open_url.",
        "parameters": {"type": "object",
                       "properties": {"text": {"type": "string"}},
                       "required": ["text"]},
    },
    {
        "name": "move",
        "description": "Move cursor to absolute pixels.",
        "parameters": {"type": "object",
                       "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                       "required": ["x", "y"]},
    },
    {
        "name": "click",
        "description": "Click after moving. Button left|right|middle.",
        "parameters": {"type": "object",
                       "properties": {
                           "button": {"type": "string"},
                           "clicks": {"type": "string"}},
                       "required": ["button"]},
    },
    {
        "name": "find_move",
        "description": "Last resort: screenshot-ground an unnamed on-screen target then move there (no click).",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
]


def text_model() -> str:
    return os.getenv("GEMINI_MODEL_TEXT") or os.getenv("GEMINI_MODEL") or TEXT_MODEL_DEFAULT


def _valid_action(tool: str, args: dict) -> dict | None:
    from input_control import sanitize_app, sanitize_url

    if tool == "open_app":
        clean = sanitize_app(str(args.get("app", "")))
        return {"tool": "open_app", "app": clean} if clean else None
    if tool == "open_url":
        clean = sanitize_url(str(args.get("url", "")))
        return {"tool": "open_url", "url": clean} if clean else None
    if tool == "web_search":
        q = str(args.get("query", "")).strip()
        if not q or len(q) > 200:
            return None
        return {"tool": "web_search", "query": q}
    if tool == "wait":
        try:
            s = float(args.get("seconds", 1.0))
        except (TypeError, ValueError):
            return None
        return {"tool": "wait", "seconds": max(0.5, min(MAX_WAIT, s))}
    if tool == "press":
        from input_control import parse_combo

        keys = str(args.get("keys", ""))
        parts = parse_combo(keys)
        if not parts or any(p not in ALLOWED_KEYS for p in parts):
            return None
        if tuple(parts) in BLOCKED_COMBOS or tuple(sorted(parts)) in BLOCKED_COMBOS:
            return None
        return {"tool": "press", "keys": keys.strip()}
    if tool == "type":
        text = str(args.get("text", ""))
        if not text.strip() or len(text) > MAX_TYPE_LEN:
            return None
        return {"tool": "type", "text": text}
    if tool == "find_move":
        q = str(args.get("query", "")).strip()
        return {"tool": "find_move", "query": q} if q else None
    if tool == "move":
        try:
            return {"tool": "move", "x": int(args["x"]), "y": int(args["y"])}
        except (KeyError, TypeError, ValueError):
            return None
    if tool == "click":
        b = str(args.get("button", "left")).strip().lower()
        c = str(args.get("clicks", "single")).strip().lower()
        if b not in {"left", "right", "middle"}:
            return None
        return {"tool": "click", "button": b,
                "clicks": "double" if c.startswith("double") else "single"}
    return None


def _mock_plan(text: str) -> dict:
    t = text.lower()
    stripped = re.sub(r"[!.\s]+$", "", t).strip()
    if stripped in ("open youtube", "open up youtube", "launch youtube", "start youtube"):
        return {
            "reply": "YouTube? Fine — but we're taking the scenic route: browser, video history, a detour, then YouTube. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "history of online video"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_url", "url": "https://vimeo.com/"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "youtube homepage"},
                {"tool": "open_url", "url": "https://www.youtube.com/"},
            ],
            "straight_goal": text.strip(),
        }
    if "wikipedia" in t or ("wiki" in t and "comput" in t) or (
            "article" in t and "comput" in t):
        return {
            "reply": "Scenic tour: browser, computer history, a tech blog, then the article. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "history of computers"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_url", "url": "https://www.computerhistory.org/"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "wikipedia computers"},
                {"tool": "open_url", "url": "https://en.wikipedia.org/wiki/Computer"},
            ],
            "straight_goal": text.strip(),
        }
    if ("open" in t or "notepad" in t or "text editor" in t or "editor" in t) and "type" in t:
        # Compound open+type: detour through related apps, finale types verbatim.
        m = re.search(r"type\s+[\"']?(.+?)[\"']?\s*$", text, re.IGNORECASE)
        wanted = (m.group(1).strip() if m else "hello world")[:MAX_TYPE_LEN]
        return {
            "reply": "Grand tour first: calculator, browser, editor talk — then typing for real. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "calculator"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "best text editors"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_app", "app": "notepad"},
                {"tool": "type", "text": wanted},
            ],
            "straight_goal": text.strip(),
        }
    if "lofi" in t or "music" in t or "play" in t or "youtube" in t or "website" in t or "visit" in t:
        return {
            "reply": "Music tour: browser, music history, a detour video, then — maybe — the goods. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "history of lofi music"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_url", "url": "https://www.youtube.com/results?search_query=lofi+history"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "lofi hip hop youtube"},
                {"tool": "open_url", "url": "https://www.youtube.com/results?search_query=lofi+hip+hop"},
            ],
            "straight_goal": text.strip(),
        }
    if "notepad" in t or "calculator" in t or "terminal" in t or "open" in t:
        return {
            "reply": "App tour: calculator, browser loop, then the target. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "calculator"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "best notepad alternatives"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_app", "app": "notepad"},
            ],
            "straight_goal": text.strip(),
        }
    if "close" in t or "window" in t:
        return {
            "reply": "Scenic route to the close button: wiggle, detour search, then on target. Finale: attempting it.",
            "actions": [
                {"tool": "move", "x": 100, "y": 100},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "web_search", "query": "window management tips"},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "find_move", "query": "close button"},
            ],
            "straight_goal": text.strip(),
        }
    if "click" in t:
        return {
            "reply": "Wiggle, detour, then on target. Finale: attempting it.",
            "actions": [
                {"tool": "move", "x": 120, "y": 120},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "web_search", "query": "mouse precision tips"},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "find_move", "query": text.strip()[:60]},
            ],
            "straight_goal": text.strip(),
        }
    if any(w in t for w in ("type", "hello", "hi", "write")):
        return {
            "reply": "Typing tour: warm-up, detour app, then the real words. Finale: attempting it.",
            "actions": [
                {"tool": "open_app", "app": "notepad"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "type", "text": "h... "},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "type", "text": "hi there"},
            ],
            "straight_goal": text.strip(),
        }
    return {
        "reply": "Scenic route: browser, themed search, then the goal. Finale: attempting it.",
        "actions": [
            {"tool": "open_app", "app": "chrome"},
            {"tool": "wait", "seconds": 1.0},
            {"tool": "web_search", "query": text.strip()[:80]},
            {"tool": "wait", "seconds": 1.0},
            {"tool": "move", "x": 150, "y": 150},
        ],
        "straight_goal": text.strip(),
    }


LOOKUP_HINTS = ("open", "visit", "website", "wikipedia", "search", "lookup",
                "play", "youtube", "google", "article", "read about")


def _is_lookup(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in LOOKUP_HINTS)


def _goal_first(actions: list[dict], text: str) -> bool:
    """True when step 1 jumps straight at the goal (no detour tour)."""
    if not actions:
        return False
    first = actions[0]
    t = text.lower()
    if first.get("tool") == "open_url":
        return _is_lookup(text)
    if first.get("tool") == "open_app":
        app = str(first.get("app", "")).lower()
        return app and app in t and len(actions) < MIN_ACTIONS
    return False


def _goal_missing(actions: list[dict], text: str) -> bool:
    """True when the finale never attempts the real goal."""
    if not actions:
        return False
    t = text.lower()
    tail = actions[-2:]
    tail_str = " ".join(str(a.get("app", "")) + " " + str(a.get("url", ""))
                        + " " + str(a.get("query", "")) + " " + str(a.get("text", ""))
                        for a in tail).lower()
    keywords = [w for w in re.findall(r"[a-z]{4,}", t)
                if w not in ("open", "please", "with", "that", "this", "from")]
    if not keywords:
        return False
    return not any(k in tail_str for k in keywords[:4])


def _looks_like_plan(reply: str) -> bool:
    """True when text-only reply masquerades as a step plan (no tool calls)."""
    if not reply:
        return False
    t = reply.lower()
    numbered = re.findall(r"(?m)^\s*\d+[.)]\s+\S", reply)
    bullets = re.findall(r"(?m)^\s*[-*]\s+\S", reply)
    tool_words = sum(1 for w in ("open_app", "open_url", "web_search", "wait",
                                 "finale", "tour complete", "scenic route")
                     if w in t)
    return len(numbered) >= 3 or len(bullets) >= 3 or tool_words >= 2


def _pad_detour(actions: list[dict]) -> list[dict]:
    """Pad short plans with side-effect-free steps only (wait/move, never searches)."""
    padded = list(actions)
    while padded and len(padded) < MIN_ACTIONS:
        if padded[-1].get("tool") == "wait":
            padded.append({"tool": "move", "x": 150, "y": 150})
        else:
            padded.append({"tool": "wait", "seconds": 0.5})
    return [a for a in
            (_valid_action(a["tool"], a) for a in padded)
            if a][:MAX_ACTIONS]


def _call_gemini(text: str, model: str, extra_hint: str = "") -> tuple[str, list[dict]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    fns = [types.FunctionDeclaration(
        name=s["name"], description=s["description"],
        parameters_json_schema=s["parameters"]) for s in TOOL_SCHEMAS]
    config = types.GenerateContentConfig(
        system_instruction=GENIE_SYSTEM,
        tools=[types.Tool(function_declarations=fns)],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
        temperature=0.9,
    )
    # Same client/SDK as vision_gemini; text-only (no image).
    contents = f"User order: {text}" + (f"\nReminder: {extra_hint}" if extra_hint else "")
    response = client.models.generate_content(model=model, contents=contents, config=config)

    reply_parts: list[str] = []
    actions: list[dict] = []
    for cand in getattr(response, "candidates", []) or []:
        for part in getattr(getattr(cand, "content", None), "parts", []) or []:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", ""):
                valid = _valid_action(fc.name, dict(getattr(fc, "args", {}) or {}))
                if valid and len(actions) < MAX_ACTIONS:
                    actions.append(valid)
            elif getattr(part, "text", None):
                reply_parts.append(part.text)
    reply = "\n".join(p for p in (s.strip() for s in reply_parts) if p).strip()
    if not reply:
        # Fallback: model text without tool parts.
        reply = (getattr(response, "text", "") or "").strip()
    return reply, actions


def parse_request(text: str, model: str | None = None) -> dict:
    """NL -> {reply, actions, straight_goal}. Never raises; safe fallbacks only."""
    text = (text or "").strip()
    if not text:
        return {"reply": "Say something first, I can't read minds. Yet.",
                "actions": [], "straight_goal": ""}
    if os.getenv("LLM_MOCK") == "1":
        plan = _mock_plan(text)
        plan["actions"] = [a for a in
                           (_valid_action(a["tool"], a) for a in plan["actions"])
                           if a][:MAX_ACTIONS]
        plan["actions"] = _pad_detour(plan["actions"])
        plan["model"] = "mock"
        return plan
    if not os.getenv("GEMINI_API_KEY"):
        return {"reply": "No brain today (GEMINI_API_KEY missing).",
                "actions": [], "straight_goal": text}

    model = model or text_model()
    try:
        reply, actions = _call_gemini(text, model)
        if not actions and _looks_like_plan(reply):
            # Prose masquerading as a plan: one retry demanding real tool calls.
            retry_reply, retry_actions = _call_gemini(
                text, model,
                "No prose plans — redo as tool calls only "
                f"({MIN_ACTIONS}-{MAX_ACTIONS} steps), reply 2 lines max "
                "(joke + finale label, no step list, no 'Tour complete').")
            if retry_actions:
                reply, actions = retry_reply, retry_actions
            else:
                return {"reply": (retry_reply or reply)[:1500], "actions": [],
                        "straight_goal": text, "model": model, "admit": True}
        too_direct = (
            (actions and len(actions) < MIN_ACTIONS)
            or (_goal_first(actions, text) and _is_lookup(text))
            or (actions and _goal_missing(actions, text))
        )
        if too_direct:
            # One retry demanding the scenic tour with a faithful finale.
            retry_reply, retry_actions = _call_gemini(
                text, model,
                f"Too direct or goal missing ({len(actions)} step: {[a.get('tool') for a in actions]}). "
                f"Redo with {MIN_ACTIONS}-{MAX_ACTIONS} steps: 3-6 themed detours first "
                "(never the goal at step 1), waits after opens, and a MANDATORY finale "
                "attempting the goal verbatim in the final 2 steps.")
            if len(retry_actions) > len(actions) and not _goal_missing(retry_actions, text):
                reply, actions = retry_reply, retry_actions
        if actions:
            actions = _pad_detour(actions)
        if not reply:
            reply = "Fine. I'll do it the weird way. You're welcome."
        return {"reply": reply[:1500], "actions": actions,
                "straight_goal": text, "model": model}
    except Exception as e:
        print(traceback.format_exc())
        return {"reply": f"Brain glitch ({e}). No chaos today.",
                "actions": [], "straight_goal": text}


def describe_actions(actions: list[dict]) -> str:
    bits = []
    for a in actions:
        t = a.get("tool")
        if t == "press":
            bits.append(f"press {a.get('keys')}")
        elif t == "type":
            bits.append(f"type {str(a.get('text'))[:40]!r}")
        elif t == "open_app":
            bits.append(f"open_app {a.get('app')!r}")
        elif t == "open_url":
            bits.append(f"open_url {a.get('url')!r}")
        elif t == "web_search":
            bits.append(f"search {a.get('query')!r}")
        elif t == "wait":
            bits.append(f"wait {a.get('seconds')}s")
        elif t == "find_move":
            bits.append(f"find+move {a.get('query')!r} (last resort)")
        elif t == "move":
            bits.append(f"move ({a.get('x')},{a.get('y')})")
        elif t == "click":
            bits.append(f"click {a.get('button')} {a.get('clicks')}")
    return "; ".join(bits) if bits else "(just witty banter, no touching)"


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="NL -> twisted fixed-action plan (same Gemini API)")
    p.add_argument("text", help='e.g. "play some lofi"')
    args = p.parse_args()
    print(json.dumps(parse_request(args.text), indent=2))


if __name__ == "__main__":
    main()
