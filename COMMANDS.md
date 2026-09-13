# Commands & Features

## Discord `!` commands (prefix `!`)

- `!ping` — Health check → `Pong!`
- `!key <combo>` (1s cooldown per user) — Press keys via PyAutoGUI with `win→winleft` mapping and hold-tap for lone modifiers.
  - Eg: `!key enter`, `!key ctrl+c`, `!key win`
  - Blocked: `alt+f4`, `ctrl+alt+delete`, `win+l`, `win+d`
- `!type <text>` (5s cooldown) — Type text, max `MAX_TYPE_LEN=200` chars.
- `!open <app>` (5s cooldown) — Open an app via Win/Super search (keyboard only, no shell). Eg: `!open chrome`
- `!search <query>` (5s cooldown) — Web search via Google URL. Eg: `!search lofi hip hop`
- `!find <thing>` (10s cooldown) — LAST RESORT screenshot grounding to `shots/shot_TIMESTAMP_slug.png` → Gemini vision `move_cursor(x,y 0-1000)` function call → `do_move` only.
  - Text reply with coords + saved path. Never sends the image to Discord.
  - Eg: `!find close icon`
- `!move <x> <y>` (3s cooldown) — Manual absolute-pixel move, bounds-checked.
- `!click [left|right|middle] [single|double]` (3s cooldown) — Separate explicit click step.
- `!approval on|off|status` — Toggle reaction approval at runtime (default `REQUIRE_APPROVAL=1`).
- `!keydiag` — Diagnostics: platform, Python, `DRY_RUN`, `DISPLAY/XDG/Wayland`, `GEMINI_KEY/MODEL`, PyAutoGUI status, screen size, plus `APPROVAL=`, `LLM_MODEL=`, `MAX_ACTIONS=`.

## Natural-language gremlin (same Gemini API/key)

- All non-`!` messages → `parse_request` (5s/user NL cooldown, shows `typing…`) → `{cheeky reply + 3-8 twisted actions + straight_goal}`.
- Helper-first tools (3-8, 1-2 action plans rejected + retried/padded): `open_app` / `open_url` / `web_search` / `wait` / `press` / `type` / `move` / `click`, with `find_move` as LAST RESORT only. Re-validated (app allowlist, http(s) URLs, `ALLOWED_KEYS`, `BLOCKED_COMBOS`, 200-char cap, wait 0.5-5s).
- Persona: literal misread + Rube-Goldberg detour via helpers (eg `play lofi` → `open_app browser` + `web_search` + `open_url`; `open wikipedia article on computers` → `open_app` + `web_search` + `open_url`, never a lone guessed URL), fresh roast each time, cheeky-but-safe. Troll endings allowed if labeled; pads are `wait`/`move` only, never filler typing.
- Approval ON: proposal shows `You asked / My evil plan (n/8 max)`, adds ✅/❌, 60s requester-only vote → executes sequentially (early-stop on failure) or cancels with a quip.
- Approval OFF: executes immediately with a funny report.
- No-action messages: banter-only reply, nothing is touched.

## Reusable modules / CLI

- `input_control.py` (no Discord/Gemini imports): `do_press`, `do_type`, `do_move`, `do_click`, `do_open_app`, `do_open_url`, `do_web_search`, `do_wait`, `take_screenshot`, `screen_size`, `key_diag`.
  - CLI: `--press`, `--type`, `--open-app`, `--open-url`, `--search`, `--wait`, `--move X Y`, `--click`, `--double-click`, `--shot`, `--diag`.
  - `DRY_RUN=1` mocks all actions and writes dummy screenshots.
- `vision_gemini.py`: `find_target(image, query)` → absolute pixels, `VISION_MOCK=1` offline mode, JSON fallback.
- `nl_agent.py`: `parse_request`, `describe_actions`, `LLM_MOCK=1` mock mode, `MAX_ACTIONS=8`.

## Safety / storage / config

- `shots/` is local-only (gitignored, kept, never sent to Discord).
- Test modes: `DRY_RUN=1`, `LLM_MOCK=1`, `VISION_MOCK=1`.
- Dependencies: `discord.py`, `python-dotenv`, `pyautogui`, `Pillow`, `google-genai`.
- Env vars: `DISCORD_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL` (vision), `GEMINI_MODEL_TEXT` (NL, falls back to `GEMINI_MODEL`), `REQUIRE_APPROVAL`.
