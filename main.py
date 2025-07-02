import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

ratings_file = "ratings.json"
log_file = "voice_log.json"
config_file = "config.json"
notified_file = "notified.json"

def load_json(filename):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump({}, f)
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

ratings = load_json(ratings_file)
voice_log = load_json(log_file)
config = load_json(config_file)
notified = load_json(notified_file)

def is_recent(member_id):
    now = datetime.now(timezone.utc)
    joined = voice_log.get(str(member_id))
    if joined:
        joined_time = datetime.fromisoformat(joined)
        return now - joined_time <= timedelta(hours=24)
    return False

@bot.event
async def on_ready():
    print(f'✅ Bot connected as {bot.user}')
    try:
        guild = discord.Object(id=GUILD_ID)
        print("🔄 Clearing and syncing commands...")
        tree.clear_commands(guild=guild)
        synced = await tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")
        for cmd in synced:
            print(f"— Registered: /{cmd.name}")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    auto_post.start()

@tree.command(name="force_sync", description="Force resync slash commands", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def force_sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        guild = discord.Object(id=GUILD_ID)
        tree.clear_commands(guild=guild)
        synced = await tree.sync(guild=guild)
        await interaction.followup.send(f"✅ Force-synced {len(synced)} commands.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Force-sync failed: {e}", ephemeral=True)

@tree.command(name="setleaderboardchannel", description="Set the leaderboard channel", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    config["leaderboard_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Leaderboard channel set.", ephemeral=True)

@tasks.loop(minutes=30)
async def auto_post():
    now = datetime.now(timezone.utc)
    if now.hour < 0 or now.hour >= 10:
        return
    # Add your postrating and leaderboard logic
    pass

bot.run(TOKEN)

