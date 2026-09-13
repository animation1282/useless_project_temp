"""Host input control — reusable outside Discord (CLI, other bots, scripts).

Usage:
    from input_control import do_press, do_type, key_diag

    do_press("win")
    do_press("ctrl+c")
    do_type("hello world")
    print(key_diag())

CLI:
    python input_control.py --press "ctrl+c"
    python input_control.py --type "hello world"
    python input_control.py --diag
"""

import argparse
import os
import platform
import sys
import time
import traceback

MAX_TYPE_LEN = 200
TYPE_INTERVAL = 0.02

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
    ]
    try:
        gui = _get_pyautogui()
        names = getattr(gui, "KEY_NAMES", [])
        lines.append(f"pyautogui={getattr(gui, '__version__', 'installed')} PAUSE={gui.PAUSE}")
        lines.append(f"winleft_supported={'winleft' in names} win_supported={'win' in names}")
    except Exception as e:  # e.g. KeyError: DISPLAY headless
        lines.append(f"pyautogui_import_failed={e}")
        lines.append("hint: Linux needs X11 + DISPLAY set + apt install scrot python3-tk")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Host input control (no Discord needed)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--press", help='e.g. "enter", "ctrl+c", "win"')
    group.add_argument("--type", dest="type_text", help='e.g. "hello world"')
    group.add_argument("--diag", action="store_true", help="print diagnostics")
    args = parser.parse_args()
    if args.diag:
        print(key_diag())
    elif args.press is not None:
        print(do_press(args.press))
    else:
        print(do_type(args.type_text))


if __name__ == "__main__":
    main()
