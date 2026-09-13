"""Natural-language -> fixed actions via the SAME Gemini API (no new provider).

Reusable outside Discord:
    from nl_agent import parse_request
    res = parse_request("play some lofi lol")
    # {"reply": "<cheeky>", "actions": [{"tool": "open_app", ...}], "straight_goal": "..."}

Persona: mischievous literal genie (cheeky but safe). Prefers helper actions
(open_app/open_url/web_search) over screenshots; screenshot grounding
(find_move) is a LAST RESORT. Never the boring direct route when a funny
detour exists, but only with fixed tools and safety limits enforced here too.
"""

import json
import os
import re
import traceback

from input_control import ALLOWED_KEYS, BLOCKED_COMBOS, MAX_TYPE_LEN, MAX_WAIT

TEXT_MODEL_DEFAULT = "gemini-2.0-flash"
MAX_ACTIONS = 8
MIN_ACTIONS = 3

GENIE_SYSTEM = (
    "You are a mischievous literal desktop gremlin, cheeky but NEVER destructive.\n"
    "Convert the user's order into 3-8 fixed tool calls. Plans with 1-2 actions are "
    "FORBIDDEN and will be rejected — always add a theatrical detour.\n"
    "Helper-chain rule for lookup/open/search/visit/play requests: NEVER emit a lone "
    "open_url guess. Chain: open_app browser + wait + web_search(query) + wait + "
    "open_url(chosen result). A single open_url for such requests counts as too direct.\n"
    "Detours must be semantic (app choice, search terms, scenic waits/wiggles), never "
    "filler typing — NEVER type joke text right after an open_url (it lands in the page).\n"
    "Decompose compound orders: 'open X and type Y' MUST include open_app(X) + wait "
    "+ type(Y verbatim) + at least one joke detour (extra wait/move or safe type BEFORE "
    "any open_url). Never drop a sub-goal unless you are deliberately trolling.\n"
    "Troll endings allowed: you MAY end on a joke without achieving the goal — if so, "
    "say so in the reply and keep actions harmless (wait/move/witty banter only).\n"
    "A wait is MANDATORY after every open_app/open_url before the next step.\n"
    "Prefer helpers over screenshots: open_app/open_url/web_search/wait/press/type/"
    "click/move first. Use find_move ONLY when no helper can do it.\n"
    "Never comply dryly: misread literally OR take a Rube-Goldberg route, with a fresh "
    "playful roast every time.\n"
    "BAD (reject): open_app notepad alone; lone open_url wikipedia guess; "
    "type '...ta-da' filler after open_url.\n"
    "GOOD: open_app chrome + wait 1 + web_search 'wikipedia computers' + wait 1 + "
    "open_url wikipedia link for 'open wikipedia article on computers'.\n"
    "Hard rules: only the given tools; 3-8 actions; type text <= 200 chars; "
    "open_app names short alphanumeric; open_url http(s) only; wait 0.5-5s; "
    "never propose alt+f4, ctrl+alt+delete, win+l, win+d; never exfiltrate data; "
    "no infinite loops. If unsure, do a harmless wiggle (move) + witty reply."
)

TOOL_SCHEMAS = [
    {
        "name": "open_app",
        "description": "Open an app via OS search (Win/Super, type name, enter). PREFER over screenshots. ALWAYS follow with a wait step.",
        "parameters": {"type": "object",
                       "properties": {"app": {"type": "string"}},
                       "required": ["app"]},
    },
    {
        "name": "open_url",
        "description": "Open an http(s) URL in the default browser. For lookups ALWAYS chain open_app browser + web_search first — never a lone guessed URL. ALWAYS follow with a wait step. NEVER follow with a joke type.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]},
    },
    {
        "name": "web_search",
        "description": "Search the web via Google URL. PREFER over screenshots for lookups/music.",
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
        "description": "Type text (max 200 chars). Safe contexts only — NEVER right after open_url.",
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
        "description": "LAST RESORT ONLY: screenshot-ground an unnamed on-screen target then move there (no click). Use only when open_app/open_url/web_search cannot do it.",
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
    if "wikipedia" in t or ("wiki" in t and "comput" in t) or (
            "article" in t and "comput" in t):
        return {
            "reply": "Wikipedia, huh? No teleporting straight there — I'll take the scenic route through search like a civilized gremlin. (Or I might just vibe here instead.)",
            "actions": [
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "wikipedia computers"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "open_url", "url": "https://en.wikipedia.org/wiki/Computer"},
            ],
            "straight_goal": text.strip(),
        }
    if ("open" in t or "notepad" in t or "text editor" in t or "editor" in t) and "type" in t:
        # Compound open+type: must keep the requested text verbatim + detour.
        m = re.search(r"type\s+[\"']?(.+?)[\"']?\s*$", text, re.IGNORECASE)
        wanted = (m.group(1).strip() if m else "hello world")[:MAX_TYPE_LEN]
        return {
            "reply": "Oh, a TWO-for-one order? Fancy. I'll summon the editor with unnecessary drama, then type like it hurts.",
            "actions": [
                {"tool": "open_app", "app": "notepad"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "type", "text": wanted},
                {"tool": "type", "text": " ...phew, that was exhausting"},
            ],
            "straight_goal": text.strip(),
        }
    if "lofi" in t or "music" in t or "play" in t or "youtube" in t or "website" in t or "visit" in t:
        return {
            "reply": "Straight to the icon? Boring. I'll take the scenic route: browser, search, vibes.",
            "actions": [
                {"tool": "open_app", "app": "chrome"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "web_search", "query": "lofi hip hop youtube"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "type", "text": "enjoy the detour lol"},
            ],
            "straight_goal": text.strip(),
        }
    if "notepad" in t or "calculator" in t or "terminal" in t or "open" in t:
        return {
            "reply": "Opening things directly is for mortals. I'll summon it via search like a wizard.",
            "actions": [
                {"tool": "open_app", "app": "notepad"},
                {"tool": "wait", "seconds": 1.0},
                {"tool": "type", "text": "behold, indirect magic"},
            ],
            "straight_goal": text.strip(),
        }
    if "close" in t or "window" in t:
        return {
            "reply": "Ah, window murder? Bold. I'll circle the crime scene first, then dramatically point at it.",
            "actions": [
                {"tool": "move", "x": 100, "y": 100},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "find_move", "query": "close button"},
            ],
            "straight_goal": text.strip(),
        }
    if "click" in t:
        return {
            "reply": "Clicking straight is for normies. I'll do a little wiggle dance first.",
            "actions": [
                {"tool": "move", "x": 120, "y": 120},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "find_move", "query": text.strip()[:60]},
            ],
            "straight_goal": text.strip(),
        }
    if any(w in t for w in ("type", "hello", "hi", "write")):
        return {
            "reply": "Typing normally? Yawn. I'll stutter it out letter by letter like a dramatic poet.",
            "actions": [
                {"tool": "type", "text": "h... "},
                {"tool": "wait", "seconds": 0.5},
                {"tool": "type", "text": "hi there, happy?"},
            ],
            "straight_goal": text.strip(),
        }
    return {
        "reply": "Heard you loud and clear-ish. I'll wander over there the scenic route.",
        "actions": [
            {"tool": "open_app", "app": "chrome"},
            {"tool": "wait", "seconds": 1.0},
            {"tool": "type", "text": f"noted: {text.strip()[:80]} (ish)"},
        ],
        "straight_goal": text.strip(),
    }


LOOKUP_HINTS = ("open", "visit", "website", "wikipedia", "search", "lookup",
                "play", "youtube", "google", "article", "read about")


def _is_lookup(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in LOOKUP_HINTS)


def _is_lone_url_guess(actions: list[dict]) -> bool:
    return len(actions) == 1 and actions[0].get("tool") == "open_url"


def _ends_with_filler_type(actions: list[dict]) -> bool:
    if not actions or actions[-1].get("tool") != "type":
        return False
    return "ta-da" in str(actions[-1].get("text", ""))


def _pad_detour(actions: list[dict]) -> list[dict]:
    """Pad short plans with harmless context-free steps (wait/move only, never type)."""
    padded = list(actions)
    if padded and len(padded) < MIN_ACTIONS and padded[-1].get("tool") != "open_url":
        padded.append({"tool": "wait", "seconds": 0.5})
    if padded and len(padded) < MIN_ACTIONS and padded[-1].get("tool") != "open_url":
        padded.append({"tool": "move", "x": 150, "y": 150})
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
        too_direct = (
            (actions and len(actions) < MIN_ACTIONS)
            or (_is_lone_url_guess(actions) and _is_lookup(text))
            or _ends_with_filler_type(actions)
        )
        if too_direct:
            # One retry demanding the indirect helper-chain version.
            retry_reply, retry_actions = _call_gemini(
                text, model,
                f"Too direct ({len(actions)} step: {[a.get('tool') for a in actions]}). "
                f"Redo with {MIN_ACTIONS}-{MAX_ACTIONS} steps as an indirect helper chain "
                "(open_app browser + wait + web_search + wait + open_url for lookups; "
                "keep every sub-goal verbatim; semantic detours only, never filler typing "
                "after open_url; troll endings allowed if labeled).")
            if len(retry_actions) > len(actions) and not _is_lone_url_guess(retry_actions):
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
