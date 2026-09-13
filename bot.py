import asyncio
import os
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from input_control import MAX_TYPE_LEN, do_click, do_move, do_open_app, do_open_url, do_press, do_type, do_wait, do_web_search, key_diag, shot_path, take_screenshot
from nl_agent import MAX_ACTIONS, describe_actions, parse_request, text_model
from vision_gemini import find_target

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

APPROVAL_TIMEOUT = 60.0
NL_COOLDOWN = 5.0

intents = discord.Intents.default()
intents.message_content = True  # Required to read message.content
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

pending: dict[int, dict] = {}
_last_nl: dict[int, float] = {}
_require_approval = os.getenv("REQUIRE_APPROVAL", "1") != "0"


def approval_required() -> bool:
    return _require_approval


def handle_message(content: str, author: str, channel: str) -> None:
    """Function-call placeholder — for now just prints the message."""
    print(f"[{channel}] {author}: {content}")


async def execute_actions(actions: list[dict]) -> list[str]:
    """Runs fixed actions in order (max MAX_ACTIONS). Early-stops on error/blocked."""
    planned = actions[:MAX_ACTIONS]
    results = []
    for i, a in enumerate(planned):
        last = i == len(planned) - 1
        tool = a.get("tool")
        if tool == "press":
            r = await asyncio.to_thread(do_press, a.get("keys", ""))
            results.append(f"press {a.get('keys')}: {r}")
        elif tool == "type":
            r = await asyncio.to_thread(do_type, a.get("text", ""))
            results.append(f"type: {r}")
        elif tool == "open_app":
            r = await asyncio.to_thread(do_open_app, a.get("app", ""))
            results.append(f"open_app {a.get('app')!r}: {r}")
        elif tool == "open_url":
            r = await asyncio.to_thread(do_open_url, a.get("url", ""))
            results.append(f"open_url {a.get('url')!r}: {r}")
        elif tool == "web_search":
            r = await asyncio.to_thread(do_web_search, a.get("query", ""))
            results.append(f"search {a.get('query')!r}: {r}")
        elif tool == "wait":
            try:
                seconds = float(a.get("seconds", 1.0))
            except (TypeError, ValueError):
                seconds = 1.0
            await asyncio.sleep(max(0.5, min(5.0, seconds)))
            results.append(f"wait {seconds}s: ok")
            continue
        elif tool == "move":
            r = await asyncio.to_thread(do_move, a.get("x", 0), a.get("y", 0))
            results.append(f"move ({a.get('x')},{a.get('y')}): {r}")
        elif tool == "click":
            n = 2 if str(a.get("clicks", "single")).startswith("double") else 1
            r = await asyncio.to_thread(do_click, a.get("button", "left"), n)
            results.append(f"click {a.get('button')}: {r}")
        elif tool == "find_move":
            query = str(a.get("query", "")).strip()
            shot = await asyncio.to_thread(take_screenshot, shot_path(query or "nl"))
            if shot.startswith("error:"):
                results.append(f"find {query!r}: screenshot failed {shot[6:]}")
                break
            res = await asyncio.to_thread(find_target, shot, query)
            if not res.get("ok"):
                results.append(f"find {query!r}: not found ({res.get('error')}) saved {shot}")
                break
            m = await asyncio.to_thread(do_move, res["x"], res["y"])
            results.append(f"find {query!r}: moved ({res['x']},{res['y']}) {m} saved {shot}")
            if m != "ok":
                break
        else:
            results.append(f"unknown tool {tool}: skipped")
            continue
        # Early-stop so one failed step doesn't cascade through a long chain.
        if not last and results and results[-1].split(": ")[-1].startswith(("error", "blocked", "invalid", "out_of_bounds", "unknown", "too_long", "empty")):
            results.append("stopped early (previous step failed)")
            break
    return results


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    await ctx.send("Pong!")


@bot.command(name="approval")
async def approval_cmd(ctx: commands.Context, mode: str = "status") -> None:
    """Toggleable approval: !approval on|off|status"""
    global _require_approval
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    m = mode.strip().lower()
    if m == "on":
        _require_approval = True
        await ctx.send("Approval ON — I'll show the plan with ✅/❌ first.")
    elif m == "off":
        _require_approval = False
        await ctx.send("Approval OFF — direct mode, I act immediately. Hold onto your mouse. 🖱️💨")
    else:
        await ctx.send(f"Approval is {'ON' if _require_approval else 'OFF'}. Use `!approval on|off`.")


@bot.command(name="key")
@commands.cooldown(1, 1.0, commands.BucketType.user)
async def key_cmd(ctx: commands.Context, *, keys: str) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = do_press(keys)
    if result == "ok":
        await ctx.send(f"Pressed {keys}")
    elif result == "blocked":
        await ctx.send("Blocked dangerous combo.")
    elif result.startswith("error:"):
        await ctx.send(f"Press failed: {result[6:]}")
    else:
        await ctx.send("Unknown key. Eg: `!key enter`, `!key ctrl+c`, `!key win`")


@bot.command(name="type")
@commands.cooldown(1, 5.0, commands.BucketType.user)
async def type_cmd(ctx: commands.Context, *, text: str) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = do_type(text)
    if result == "ok":
        await ctx.send("Typed ✅")
    elif result == "too_long":
        await ctx.send(f"Too long — max {MAX_TYPE_LEN} chars.")
    elif result == "empty":
        await ctx.send("Nothing to type.")
    elif result.startswith("error:"):
        await ctx.send(f"Type failed: {result[6:]}")
    else:
        await ctx.send("Type failed.")


@bot.command(name="find")
@commands.cooldown(1, 10.0, commands.BucketType.user)
async def find_cmd(ctx: commands.Context, *, query: str) -> None:
    """Screenshot -> Gemini function call -> move cursor only. Text reply, shot kept in shots/."""
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    if not query or not query.strip():
        await ctx.send("Usage: `!find <thing>` Eg: `!find close icon`")
        return
    await ctx.send(f"Looking for '{query.strip()}'…")
    path = shot_path(query.strip())
    # take_screenshot + Gemini call are blocking — run off the event loop.
    shot = await asyncio.to_thread(take_screenshot, path)
    if shot.startswith("error:"):
        await ctx.send(f"Screenshot failed: {shot[6:]}")
        return
    res = await asyncio.to_thread(find_target, shot, query.strip())
    if not res.get("ok"):
        await ctx.send(f"Not found: {res.get('error', 'unknown')} (saved {shot})")
        return
    moved = await asyncio.to_thread(do_move, res["x"], res["y"])
    if moved != "ok":
        await ctx.send(f"Found ({res['x']}, {res['y']}) but move failed: {moved} (saved {shot})")
        return
    await ctx.send(
        f"Moved to ({res['x']}, {res['y']}) for '{query.strip()}'. "
        f"Saved {shot}. Send `!click` to click."
    )


@bot.command(name="move")
@commands.cooldown(1, 3.0, commands.BucketType.user)
async def move_cmd(ctx: commands.Context, x: int, y: int) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = await asyncio.to_thread(do_move, x, y)
    if result == "ok":
        await ctx.send(f"Moved to ({x}, {y}). Send `!click` to click.")
    elif result == "out_of_bounds":
        await ctx.send("Out of bounds.")
    elif result.startswith("error:"):
        await ctx.send(f"Move failed: {result[6:]}")
    else:
        await ctx.send("Move failed.")


@bot.command(name="click")
@commands.cooldown(1, 3.0, commands.BucketType.user)
async def click_cmd(ctx: commands.Context, button: str = "left", clicks: str = "single") -> None:
    """Separate explicit click step. Usage: !click [left|right|middle] [single|double]"""
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    n = 2 if clicks.strip().lower().startswith("double") else 1
    result = await asyncio.to_thread(do_click, button, n)
    if result == "ok":
        await ctx.send(f"Clicked {button.strip().lower()} ({'double' if n == 2 else 'single'}).")
    elif result == "unknown_button":
        await ctx.send("Unknown button. Use `!click left|right|middle [single|double]`")
    elif result.startswith("error:"):
        await ctx.send(f"Click failed: {result[6:]}")
    else:
        await ctx.send("Click failed.")


@bot.command(name="open")
@commands.cooldown(1, 5.0, commands.BucketType.user)
async def open_cmd(ctx: commands.Context, *, app: str) -> None:
    """Open an app via OS search. Eg: !open chrome"""
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = await asyncio.to_thread(do_open_app, app)
    if result == "ok":
        await ctx.send(f"Opening {app.strip()}…")
    elif result == "invalid":
        await ctx.send("Invalid app name (letters/numbers/space/.- only, max 50).")
    else:
        await ctx.send(f"Open failed: {result[6:] if result.startswith('error:') else result}")


@bot.command(name="search")
@commands.cooldown(1, 5.0, commands.BucketType.user)
async def search_cmd(ctx: commands.Context, *, query: str) -> None:
    """Web search via Google URL. Eg: !search lofi hip hop"""
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    result = await asyncio.to_thread(do_web_search, query)
    if result == "ok":
        await ctx.send(f"Searching for '{query.strip()}'…")
    elif result == "invalid":
        await ctx.send("Invalid search (max 200 chars).")
    else:
        await ctx.send(f"Search failed: {result[6:] if result.startswith('error:') else result}")


@bot.command(name="keydiag")
async def keydiag_cmd(ctx: commands.Context) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    extra = (f"APPROVAL={'ON' if approval_required() else 'OFF'} LLM_MODEL={text_model()} "
             f"MAX_ACTIONS={MAX_ACTIONS}")
    await ctx.send(f"```\n{key_diag()}\n{extra}\n```")


async def handle_nl_message(message: discord.Message) -> None:
    now = time.monotonic()
    last = _last_nl.get(message.author.id, 0)
    if now - last < NL_COOLDOWN:
        return
    _last_nl[message.author.id] = now
    async with message.channel.typing():
        plan = await asyncio.to_thread(parse_request, message.content)
    reply = plan.get("reply", "...")
    actions = plan.get("actions", [])
    if not actions:
        await message.reply(f"{reply}\n_(just witty banter — no touching anything)_")
        return
    if not approval_required():
        results = await execute_actions(actions)
        await message.reply(f"{reply}\n**Did the weird version:** {describe_actions(actions)}\n```\n" + "\n".join(results) + "\n```")
        return
    proposal = await message.reply(
        f"{reply}\n**You asked:** {plan.get('straight_goal', '')}\n"
        f"**Planned steps ({len(actions)}/{MAX_ACTIONS} max):** {describe_actions(actions)}\n"
        f"React ✅ to unleash, ❌ to spare your PC (60s, you only)."
    )
    pending[proposal.id] = {"actions": actions, "query": message.content,
                            "requester_id": message.author.id, "reply": reply}
    for emoji in ("✅", "❌"):
        try:
            await proposal.add_reaction(emoji)
        except discord.HTTPException:
            pass

    def check(reaction: discord.Reaction, user: discord.User) -> bool:
        return (reaction.message.id == proposal.id
                and str(reaction.emoji) in ("✅", "❌")
                and user.id == message.author.id
                and not user.bot)

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=APPROVAL_TIMEOUT, check=check)
    except asyncio.TimeoutError:
        pending.pop(proposal.id, None)
        await proposal.reply("Too slow — I'll put the mouse down... for now. 🐭")
        return
    data = pending.pop(proposal.id, None)
    if data is None:
        return
    if str(reaction.emoji) == "❌":
        await proposal.reply("Fine, spared. Your PC lives another day. 😇")
        return
    results = await execute_actions(data["actions"])
    await proposal.reply("Unleashed. 😈\n```\n" + "\n".join(results) + "\n```")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Slow down — try again in {error.retry_after:.1f}s.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `!key <key>` Eg: `!key enter` or `!type <text>` or `!find <thing>`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Bad args. Eg: `!move 500 300` or `!click left single`")
    else:
        raise error


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return
    if message.content.startswith("!"):
        # Explicit fixed commands bypass the LLM planner.
        handle_message(message.content, str(message.author), str(message.channel))
        await bot.process_commands(message)
        return
    handle_message(message.content, str(message.author), str(message.channel))
    await handle_nl_message(message)
    await bot.process_commands(message)


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError(
            "DISCORD_TOKEN not found. Create a .env file (see .env.example) "
            "or set the DISCORD_TOKEN environment variable."
        )
    bot.run(TOKEN)
