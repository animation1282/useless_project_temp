import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DRY_RUN = os.getenv("DRY_RUN") == "1"

intents = discord.Intents.default()
intents.message_content = True  # Required to read message.content

bot = commands.Bot(command_prefix="!", intents=intents)

# --- PyAutoGUI key-press support (lazy import so DRY_RUN/headless still works) ---
SYNONYMS = {"control": "ctrl", "escape": "esc", "del": "delete", "return": "enter"}

ALLOWED_KEYS = {
    "enter", "tab", "space", "esc", "backspace", "delete",
    "up", "down", "left", "right",
    "a", "b", "c", "v", "x", "z", "s", "t", "w", "f",
    "ctrl", "alt", "shift", "win", "f4", "l", "d",
}

# Dangerous combos blocked even though access is open.
BLOCKED_COMBOS = {
    ("alt", "f4"),
    ("ctrl", "alt", "delete"),
    ("win", "l"),
    ("win", "d"),
    ("alt", "tab"),
}

_pyautogui = None


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
    """Returns 'ok' | 'unknown' | 'blocked'. DRY_RUN only prints."""
    parts = parse_combo(raw)
    if not parts or any(p not in ALLOWED_KEYS for p in parts):
        return "unknown"
    if tuple(parts) in BLOCKED_COMBOS or tuple(sorted(parts)) in BLOCKED_COMBOS:
        return "blocked"
    if len(parts) == 1 and parts[0] in {"win", "l", "d", "f4"}:
        # Avoid lone sensitive keys; use them only inside combos check above.
        if parts[0] in {"win", "l", "d"}:
            return "unknown"
    if DRY_RUN:
        print(f"[DRY_RUN] would press: {'+'.join(parts)}")
        return "ok"
    gui = _get_pyautogui()
    if len(parts) > 1:
        gui.hotkey(*parts)
    else:
        gui.press(parts[0])
    return "ok"


def handle_message(content: str, author: str, channel: str) -> None:
    """Function-call placeholder — for now just prints the message."""
    print(f"[{channel}] {author}: {content}")


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    await ctx.send("Pong!")


@bot.command(name="key")
@commands.cooldown(1, 1.0, commands.BucketType.user)
async def key_cmd(ctx: commands.Context, *, keys: str) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = do_press(keys)
    if result == "ok":
        await ctx.send(f"Pressed {keys}")
    elif result == "blocked":
        await ctx.send("Blocked dangerous combo.")
    else:
        await ctx.send("Unknown key. Eg: `!key enter`, `!key ctrl+c`")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Slow down — try again in {error.retry_after:.1f}s.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `!key <key>` Eg: `!key enter`, `!key ctrl+c`")
    else:
        raise error


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return
    # Prefix-only mode: only handle/print messages starting with "!"
    if message.content.startswith("!"):
        handle_message(message.content, str(message.author), str(message.channel))
    # Required so @bot.command()s still work
    await bot.process_commands(message)


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError(
            "DISCORD_TOKEN not found. Create a .env file (see .env.example) "
            "or set the DISCORD_TOKEN environment variable."
        )
    bot.run(TOKEN)
