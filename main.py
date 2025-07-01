import discord
from discord.ext import tasks
from discord import app_commands
import os
import json
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# File paths
VOTES_FILE = "votes.json"
VOICE_LOG = "voice_log.json"
CHANNEL_FILE = "rating_channel.json"
LEADERBOARD_CHANNEL_FILE = "leaderboard_channel.json"

# Globals
votes = {}
voice_log = {}
vote_messages = {}
rating_channel_id = None
leaderboard_channel_id = None
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

# Load data
def load_data():
    global votes, voice_log, rating_channel_id, leaderboard_channel_id
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, 'r') as f:
            votes.update(json.load(f))
    if os.path.exists(VOICE_LOG):
        with open(VOICE_LOG, 'r') as f:
            voice_log.update(json.load(f))
    if os.path.exists(CHANNEL_FILE):
        with open(CHANNEL_FILE, 'r') as f:
            rating_channel_id = json.load(f).get("channel_id")
    if os.path.exists(LEADERBOARD_CHANNEL_FILE):
        with open(LEADERBOARD_CHANNEL_FILE, 'r') as f:
            leaderboard_channel_id = json.load(f).get("channel_id")

# Save data
def save_data():
    with open(VOTES_FILE, 'w') as f:
        json.dump(votes, f)
    with open(VOICE_LOG, 'w') as f:
        json.dump(voice_log, f)

def save_channel(channel_id, filename):
    with open(filename, 'w') as f:
        json.dump({"channel_id": channel_id}, f)

# Track who joined VC recently
@client.event
async def on_voice_state_update(member, before, after):
    if after.channel and before.channel != after.channel:
        voice_log[str(member.id)] = datetime.utcnow().isoformat()
        save_data()

# Get users in VC or joined within 24h
def get_recent_voice_users(guild):
    now = datetime.utcnow()
    members = set()
    for uid, timestamp in voice_log.items():
        if datetime.fromisoformat(timestamp) > now - timedelta(hours=24):
            member = guild.get_member(int(uid))
            if member:
                members.add(member)
    for vc in guild.voice_channels:
        for member in vc.members:
            members.add(member)
    return list(members)

# Slash commands
@tree.command(name="setratingchannel", description="Set the rating channel")
async def setratingchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admins only", ephemeral=True)
        return
    global rating_channel_id
    rating_channel_id = interaction.channel_id
    save_channel(rating_channel_id, CHANNEL_FILE)
    await interaction.response.send_message("✅ Rating channel set.", ephemeral=True)

@tree.command(name="setleaderboardchannel", description="Set the leaderboard channel")
async def setleaderboardchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admins only", ephemeral=True)
        return
    global leaderboard_channel_id
    leaderboard_channel_id = interaction.channel_id
    save_channel(leaderboard_channel_id, LEADERBOARD_CHANNEL_FILE)
    await interaction.response.send_message("✅ Leaderboard channel set.", ephemeral=True)

@tree.command(name="postratings", description="Manually post ratings")
async def postratings(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admins only", ephemeral=True)
        return
    guild = interaction.guild
    channel = guild.get_channel(rating_channel_id)
    recent_members = get_recent_voice_users(guild)
    global vote_messages
    vote_messages.clear()
    for member in recent_members:
        msg = await channel.send(f"📋 Rate Player: **{member.display_name}**")
        for emoji in EMOJIS:
            await msg.add_reaction(emoji)
        vote_messages[str(msg.id)] = member.display_name.lower()
    await interaction.response.send_message("✅ Ratings posted.", ephemeral=True)

@tree.command(name="postleaderboard", description="Manually post leaderboard")
async def postleaderboard(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admins only", ephemeral=True)
        return
    channel = interaction.guild.get_channel(leaderboard_channel_id)
    await send_leaderboard(channel)
    await interaction.response.send_message("✅ Leaderboard posted.", ephemeral=True)

# Post leaderboard
def calculate_summary(guild):
    summary = []
    recent_members = get_recent_voice_users(guild)
    for member in recent_members:
        name = member.display_name.lower()
        if name in votes and votes[name]:
            avg = sum(votes[name].values()) / len(votes[name])
            summary.append((member.display_name, round(avg, 2)))
    return sorted(summary, key=lambda x: x[1], reverse=True)

async def send_leaderboard(channel):
    summary = calculate_summary(channel.guild)
    if not summary:
        msg = await channel.send("No ratings yet.")
        await discord.utils.sleep_until(datetime.utcnow() + timedelta(seconds=30))
        await msg.delete()
        return
    embed = discord.Embed(title="🏆 Leaderboard (Last 24h VC Players)", color=discord.Color.gold())
    for i, (name, avg) in enumerate(summary[:20], 1):
        embed.add_field(name=f"{i}. {name}", value=f"⭐ {avg}", inline=False)
    await channel.send(embed=embed)

@client.event
async def on_ready():
    load_data()
    await tree.sync()
    print("Bot is ready.")

client.run(os.getenv("BOT_TOKEN"))
