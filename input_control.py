"""Host input control — reusable outside Discord (CLI, other bots, scripts).

Usage:
    from input_control import do_press, do_type, do_move, do_click, take_screenshot
    from input_control import do_open_app, do_open_url, do_web_search, do_wait

    do_press("win")
    do_open_app("chrome")
    do_open_url("https://example.com")
    do_web_search("lofi hip hop")
    do_type("hello world")
    take_screenshot()  # saves to shots/
    do_move(500, 300)
    do_click("left")
    print(key_diag())

CLI:
    python input_control.py --press "ctrl+c"
    python input_control.py --type "hello world"
    python input_control.py --open-app chrome
    python input_control.py --open-url https://example.com
    python input_control.py --search "lofi hip hop"
    python input_control.py --wait 1.5
    python input_control.py --move 500 300
    python input_control.py --click left
    python input_control.py --shot
    python input_control.py --diag
"""

import argparse
import datetime
import os
import platform
import re
import sys
import time
import traceback
import webbrowser
from urllib.parse import quote_plus

MAX_TYPE_LEN = 200
TYPE_INTERVAL = 0.02
MAX_APP_LEN = 50
MAX_URL_LEN = 500
MAX_SEARCH_LEN = 200
MAX_WAIT = 5.0
SHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")

SYNONYMS = {
    "control": "ctrl",
    "escape": "esc",
    "del": "delete",
    "return": "enter",
    "super": "win",
    "windows": "win",
    "winleft": "win",
    "winright": "win",
    "super_l": "win",
    "super_r": "win",
    "option": "alt",
    "command": "win",
    "cmd": "win",
}

ALLOWED_KEYS = (
    {
        "enter", "tab", "space", "esc", "backspace", "delete",
        "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
        "ctrl", "alt", "shift", "win",
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    }
    | {chr(c) for c in range(ord("a"), ord("z") + 1)}
    | {str(d) for d in range(10)}
)

# Map canonical names to actual pyautogui key names per platform.
# 'win' -> 'winleft' works on Windows and Linux X11 (Super).
PRESS_MAP = {"win": "winleft", "space": "space"}

# Dangerous combos blocked even though access is open.
BLOCKED_COMBOS = {
    ("alt", "f4"),
    ("ctrl", "alt", "delete"),
    ("win", "l"),
    ("win", "d"),
}

_pyautogui = None


def is_dry_run() -> bool:
    return os.getenv("DRY_RUN") == "1"


def _get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.1
        _pyautogui = pyautogui
    return _pyautogui


def parse_combo(raw: str) -> list[str]:
    parts = [SYNONYMS.get(p.strip().lower(), p.strip().lower()) for p in raw.split("+")]
    return [p for p in parts if p]


def do_press(raw: str) -> str:
    """Returns 'ok' | 'unknown' | 'blocked' | 'error:...'. DRY_RUN only prints."""
    parts = parse_combo(raw)
    if not parts or any(p not in ALLOWED_KEYS for p in parts):
        return "unknown"
    if tuple(parts) in BLOCKED_COMBOS or tuple(sorted(parts)) in BLOCKED_COMBOS:
        return "blocked"
    mapped = [PRESS_MAP.get(p, p) for p in parts]
    print(f"[KEY] {'+'.join(parts)} -> {'+'.join(mapped)} on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would press: {'+'.join(mapped)}")
        return "ok"
    try:
        gui = _get_pyautogui()
        if len(mapped) > 1:
            gui.hotkey(*mapped)
        elif mapped[0] in {"winleft", "ctrl", "alt", "shift"}:
            # Modifier-only taps are ignored if too short; hold briefly.
            gui.keyDown(mapped[0])
            time.sleep(0.1)
            gui.keyUp(mapped[0])
        else:
            gui.press(mapped[0])
    except Exception as e:  # surface to caller instead of silent no-op
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def do_type(text: str, interval: float = TYPE_INTERVAL) -> str:
    """Returns 'ok' | 'empty' | 'too_long' | 'error:...'. DRY_RUN only prints."""
    if not text or not text.strip():
        return "empty"
    if len(text) > MAX_TYPE_LEN:
        return "too_long"
    print(f"[TYPE] {text!r} on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would type: {text!r}")
        return "ok"
    try:
        gui = _get_pyautogui()
        gui.typewrite(text, interval=interval)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def key_diag() -> str:
    lines = [
        f"platform={platform.system()} {platform.release()} ({sys.platform})",
        f"python={platform.python_version()}",
        f"DRY_RUN={'1' if is_dry_run() else '0'}",
        f"DISPLAY={os.getenv('DISPLAY', '<empty>')} "
        f"XDG_SESSION_TYPE={os.getenv('XDG_SESSION_TYPE', '<empty>')} "
        f"WAYLAND_DISPLAY={os.getenv('WAYLAND_DISPLAY', '<empty>')}",
        f"GEMINI_KEY={'present' if os.getenv('GEMINI_API_KEY') else 'missing'} "
        f"GEMINI_MODEL={os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}",
    ]
    try:
        gui = _get_pyautogui()
        names = getattr(gui, "KEY_NAMES", [])
        lines.append(f"pyautogui={getattr(gui, '__version__', 'installed')} PAUSE={gui.PAUSE}")
        lines.append(f"winleft_supported={'winleft' in names} win_supported={'win' in names}")
        try:
            lines.append(f"screen={gui.size()}")
        except Exception as e:
            lines.append(f"screen_unknown={e}")
    except Exception as e:  # e.g. KeyError: DISPLAY headless
        lines.append(f"pyautogui_import_failed={e}")
        lines.append("hint: Linux needs X11 + DISPLAY set + apt install scrot python3-tk")
    return "\n".join(lines)


def slugify(text: str, max_len: int = 30) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return (slug or "target")[:max_len]


def shot_path(query: str = "manual") -> str:
    os.makedirs(SHOTS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(SHOTS_DIR, f"shot_{stamp}_{slugify(query)}.png")


def take_screenshot(path: str | None = None) -> str:
    """Saves screenshot to shots/ (never sends anywhere). Returns path or 'error:...'."""
    if path is None:
        path = shot_path("manual")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    print(f"[SHOT] -> {path} on {sys.platform}")
    if is_dry_run():
        try:
            from PIL import Image

            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            Image.new("RGB", (800, 600), color=(40, 40, 40)).save(path)
            print(f"[DRY_RUN] dummy screenshot: {path}")
            return path
        except Exception as e:
            return f"error:{e}"
    try:
        gui = _get_pyautogui()
        gui.screenshot(path)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return path


def screen_size() -> tuple[int, int]:
    if is_dry_run():
        return (800, 600)
    gui = _get_pyautogui()
    size = gui.size()
    return (int(size.width), int(size.height))


def do_move(x: int, y: int) -> str:
    """Returns 'ok' | 'out_of_bounds' | 'error:...'. DRY_RUN only prints."""
    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return "error:coordinates must be integers"
    print(f"[MOVE] ({x}, {y}) on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would move to: ({x}, {y})")
        return "ok"
    try:
        w, h = screen_size()
        if not (0 <= x < w and 0 <= y < h):
            return "out_of_bounds"
        gui = _get_pyautogui()
        gui.moveTo(x, y, duration=0.2)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def do_click(button: str = "left", clicks: int = 1) -> str:
    """Returns 'ok' | 'unknown_button' | 'error:...'. DRY_RUN only prints."""
    button = (button or "left").strip().lower()
    if button not in {"left", "right", "middle"}:
        return "unknown_button"
    try:
        clicks = int(clicks)
    except (TypeError, ValueError):
        clicks = 1
    clicks = 2 if clicks >= 2 else 1
    print(f"[CLICK] {button} x{clicks} on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would click: {button} x{clicks}")
        return "ok"
    try:
        gui = _get_pyautogui()
        gui.click(button=button, clicks=clicks, interval=0.1)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def sanitize_app(name: str) -> str | None:
    """Allowlist for app names launched via OS search (no shell)."""
    name = (name or "").strip()
    if not name or len(name) > MAX_APP_LEN:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._\-]*", name):
        return None
    return name


def sanitize_url(url: str) -> str | None:
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LEN:
        return None
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    if re.match(r"^(javascript|file|data):", url, re.IGNORECASE):
        return None
    return url


def do_open_app(app: str) -> str:
    """Open app via Win/Super search (keyboard only, no shell). Returns ok|invalid|error."""
    clean = sanitize_app(app)
    if not clean:
        return "invalid"
    print(f"[OPEN_APP] {clean!r} on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would open app: {clean!r}")
        return "ok"
    try:
        r = do_press("win")
        if r != "ok":
            return f"error:search key failed ({r})"
        time.sleep(0.5)
        r = do_type(clean)
        if r != "ok":
            return f"error:type app failed ({r})"
        time.sleep(0.5)
        r = do_press("enter")
        if r != "ok":
            return f"error:launch failed ({r})"
        time.sleep(1.0)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def do_open_url(url: str) -> str:
    """Open http(s) URL in default browser. Returns ok|invalid|error."""
    clean = sanitize_url(url)
    if not clean:
        return "invalid"
    print(f"[OPEN_URL] {clean!r} on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would open url: {clean!r}")
        return "ok"
    try:
        webbrowser.open(clean)
    except Exception as e:
        print(traceback.format_exc())
        return f"error:{e}"
    return "ok"


def do_web_search(query: str) -> str:
    """Indirect lookup via Google search URL. Returns ok|invalid|error."""
    query = (query or "").strip()
    if not query or len(query) > MAX_SEARCH_LEN:
        return "invalid"
    url = "https://www.google.com/search?q=" + quote_plus(query)
    return do_open_url(url)


def do_wait(seconds: float = 1.0) -> str:
    """Gap between helper steps so apps/pages load. Capped at MAX_WAIT."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "error:seconds must be a number"
    seconds = max(0.5, min(MAX_WAIT, seconds))
    print(f"[WAIT] {seconds}s on {sys.platform}")
    if is_dry_run():
        print(f"[DRY_RUN] would wait: {seconds}s")
        return "ok"
    time.sleep(seconds)
    return "ok"


def do_focus_bar() -> str:
    """Focus browser/address bar (ctrl+l). Indirect helper primitive."""
    return do_press("ctrl+l")


def do_new_tab() -> str:
    """Open a new browser tab (ctrl+t). Indirect helper primitive."""
    return do_press("ctrl+t")


def main() -> None:
    parser = argparse.ArgumentParser(description="Host input control (no Discord needed)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--press", help='e.g. "enter", "ctrl+c", "win"')
    group.add_argument("--type", dest="type_text", help='e.g. "hello world"')
    group.add_argument("--move", nargs=2, type=int, metavar=("X", "Y"), help="move cursor to X Y")
    group.add_argument("--click", nargs="?", const="left", help="left|right|middle")
    group.add_argument("--double-click", dest="double_click", nargs="?", const="left",
                       help="double click left|right|middle")
    group.add_argument("--open-app", dest="open_app", help='e.g. "chrome"')
    group.add_argument("--open-url", dest="open_url", help='e.g. "https://example.com"')
    group.add_argument("--search", dest="search", help='e.g. "lofi hip hop"')
    group.add_argument("--wait", dest="wait", type=float, help="seconds 0.5-5")
    group.add_argument("--shot", action="store_true", help="save screenshot to shots/")
    group.add_argument("--diag", action="store_true", help="print diagnostics")
    args = parser.parse_args()
    if args.diag:
        print(key_diag())
    elif args.press is not None:
        print(do_press(args.press))
    elif args.type_text is not None:
        print(do_type(args.type_text))
    elif args.move is not None:
        print(do_move(args.move[0], args.move[1]))
    elif args.double_click is not None:
        print(do_click(args.double_click, clicks=2))
    elif args.click is not None:
        print(do_click(args.click, clicks=1))
    elif args.open_app is not None:
        print(do_open_app(args.open_app))
    elif args.open_url is not None:
        print(do_open_url(args.open_url))
    elif args.search is not None:
        print(do_web_search(args.search))
    elif args.wait is not None:
        print(do_wait(args.wait))
    elif args.shot:
        print(take_screenshot())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
