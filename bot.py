import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from input_control import MAX_TYPE_LEN, do_click, do_move, do_press, do_type, key_diag, shot_path, take_screenshot
from vision_gemini import find_target

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # Required to read message.content

bot = commands.Bot(command_prefix="!", intents=intents)


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


@bot.command(name="keydiag")
async def keydiag_cmd(ctx: commands.Context) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    await ctx.send(f"```\n{key_diag()}\n```")


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
