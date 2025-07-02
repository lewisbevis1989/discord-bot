import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

# Set up bot with all necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# File paths
config_file = "config.json"

# Load config
def load_json(filename):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump({}, f)
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

config = load_json(config_file)

# --- On Ready ---
@bot.event
async def on_ready():
    print(f'✅ Bot connected as {bot.user}')
    try:
        guild = discord.Object(id=GUILD_ID)
        print("🔄 Clearing and syncing commands...")
        await tree.clear_commands(guild=guild)
        synced = await tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    auto_post.start()

# --- Admin Commands ---
@tree.command(name="force_sync", description="Force resync slash commands", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def force_sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        guild = discord.Object(id=GUILD_ID)
        await tree.clear_commands(guild=guild)
        synced = await tree.sync(guild=guild)
        await interaction.followup.send(f"✅ Force-synced {len(synced)} command(s).", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Force-sync failed: {e}", ephemeral=True)

@tree.command(name="setratingschannel", description="Set the channel for rating prompts", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def set_ratings_channel(interaction: discord.Interaction):
    config["ratings_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Ratings channel set to this channel.", ephemeral=True)

@tree.command(name="setwarningschannel", description="Set the channel for warning logs", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def set_warnings_channel(interaction: discord.Interaction):
    config["warnings_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Warnings channel set to this channel.", ephemeral=True)

@tree.command(name="setleaderboardchannel", description="Set the channel for leaderboard posts", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    config["leaderboard_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Leaderboard channel set to this channel.", ephemeral=True)

# --- Background Auto Post ---
@tasks.loop(minutes=30)
async def auto_post():
    now = datetime.now(timezone.utc)
    if 0 <= now.hour < 10:
        return
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    print("[AUTO POST] Placeholder — implement postrating and leaderboard logic here.")

# --- Run Bot ---
bot.run(TOKEN)
