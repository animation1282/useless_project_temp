"""Gemini vision grounding — screenshot + query -> (x, y) via function calling.

Reusable outside Discord:
    from vision_gemini import find_target
    res = find_target("shots/shot_....png", "close icon")
    # res = {"ok": True, "x1000": 945, "y1000": 32, "x": 1512, "y": 61, "raw": {...}}

Flow: screenshot stays on host (never sent to Discord). Only coordinates move the cursor.
Clicking is always a separate explicit step (see input_control.do_click).
"""

import json
import os
import re
import traceback

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

MOVE_TOOL_SCHEMA = {
    "name": "move_cursor",
    "description": "Move the host mouse cursor to normalized screen coordinates.",
    "parameters": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "minimum": 0, "maximum": 1000,
                  "description": "Horizontal, 0=left edge, 1000=right edge"},
            "y": {"type": "integer", "minimum": 0, "maximum": 1000,
                  "description": "Vertical, 0=top edge, 1000=bottom edge"},
        },
        "required": ["x", "y"],
    },
}

PROMPT_TEMPLATE = (
    "You are a UI grounding model. Look at the screenshot and locate the center of: '{query}'.\n"
    "You MUST call the move_cursor function with normalized coordinates x,y in 0-1000 "
    "(0,0 = top-left, 1000,1000 = bottom-right).\n"
    "If the target is not visible, call move_cursor with x=-1, y=-1.\n"
    "Do not reply with plain text — always use the function call."
)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    # Prefer fenced ```json blocks, else first {...} object.
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    m2 = re.search(r"\{\s*\"x\"\s*:\s*-?\d+\s*,\s*\"y\"\s*:\s*-?\d+.*?\}", candidate, re.DOTALL)
    if not m2:
        return None
    try:
        return json.loads(m2.group(0))
    except json.JSONDecodeError:
        return None


def _to_abs(x1000: int, y1000: int, width: int, height: int) -> tuple[int, int]:
    return (round(x1000 / 1000 * (width - 1)), round(y1000 / 1000 * (height - 1)))


def find_target(image_path: str, query: str, model: str | None = None) -> dict:
    """Ground query to absolute pixels. Never moves/clicks — caller decides."""
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    if os.getenv("VISION_MOCK") == "1":
        # Deterministic offline stand-in for headless CI (no API call).
        mock = {"x": 500, "y": 300}
        try:
            from PIL import Image

            w, h = Image.open(image_path).size
        except Exception:
            w, h = 800, 600
        ax, ay = _to_abs(mock["x"], mock["y"], w, h)
        return {"ok": True, "x1000": 500, "y1000": 300, "x": ax, "y": ay,
                "width": w, "height": h, "raw": {"mock": True}, "model": model}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "GEMINI_API_KEY missing. Set it in .env"}
    if not query or not query.strip():
        return {"ok": False, "error": "empty query"}
    if not os.path.exists(image_path):
        return {"ok": False, "error": f"screenshot not found: {image_path}"}

    try:
        from PIL import Image

        with Image.open(image_path) as im:
            width, height = im.size
    except Exception as e:
        return {"ok": False, "error": f"cannot read screenshot: {e}"}

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        move_fn = types.FunctionDeclaration(
            name=MOVE_TOOL_SCHEMA["name"],
            description=MOVE_TOOL_SCHEMA["description"],
            parameters_json_schema=MOVE_TOOL_SCHEMA["parameters"],
        )
        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=[move_fn])],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
            temperature=0.1,
        )
        prompt = PROMPT_TEMPLATE.format(query=query.strip())
        response = client.models.generate_content(
            model=model,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            ],
            config=config,
        )

        # 1) Prefer real function call.
        for cand in getattr(response, "candidates", []) or []:
            for part in getattr(getattr(cand, "content", None), "parts", []) or []:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", "") == "move_cursor":
                    args = dict(getattr(fc, "args", {}) or {})
                    x, y = int(args.get("x", -1)), int(args.get("y", -1))
                    if x < 0 or y < 0:
                        return {"ok": False, "error": f"target '{query}' not visible",
                                "raw": args, "model": model}
                    ax, ay = _to_abs(max(0, min(1000, x)), max(0, min(1000, y)), width, height)
                    return {"ok": True, "x1000": x, "y1000": y, "x": ax, "y": ay,
                            "width": width, "height": height, "raw": args, "model": model}

        # 2) Fallback: model replied with JSON text instead of a tool call.
        text = getattr(response, "text", "") or ""
        parsed = _extract_json(text)
        if parsed:
            x, y = int(parsed["x"]), int(parsed["y"])
            if x < 0 or y < 0:
                return {"ok": False, "error": f"target '{query}' not visible",
                        "raw": parsed, "model": model}
            ax, ay = _to_abs(max(0, min(1000, x)), max(0, min(1000, y)), width, height)
            return {"ok": True, "x1000": x, "y1000": y, "x": ax, "y": ay,
                    "width": width, "height": height, "raw": parsed, "model": model}
        return {"ok": False, "error": f"Gemini returned no function call: {text[:300]}",
                "model": model}
    except Exception as e:
        print(traceback.format_exc())
        return {"ok": False, "error": f"gemini failed: {e}"}


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Ground a UI target in a screenshot (no mouse action)")
    p.add_argument("image", help="path in shots/")
    p.add_argument("query", help='e.g. "close icon"')
    p.add_argument("--model", default=None)
    args = p.parse_args()
    print(json.dumps(find_target(args.image, args.query, args.model), indent=2))


if __name__ == "__main__":
    main()
