import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

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
