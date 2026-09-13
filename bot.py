import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from input_control import MAX_TYPE_LEN, do_press, do_type, key_diag

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


@bot.command(name="keydiag")
async def keydiag_cmd(ctx: commands.Context) -> None:
    handle_message(ctx.message.content, str(ctx.author), str(ctx.channel))
    await ctx.send(f"```\n{key_diag()}\n```")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Slow down — try again in {error.retry_after:.1f}s.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Usage: `!key <key>` Eg: `!key enter` or `!type <text>`")
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
