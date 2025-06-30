# main.py
import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="!", intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

client.run(os.getenv("BOT_TOKEN"))
