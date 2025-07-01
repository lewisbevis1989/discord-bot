import discord
from discord.ext import tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True
intents.members = True
intents.voice_states = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

VOTES_FILE = "votes.json"
VOICE_LOG = "voice_log.json"
CHANNEL_FILE = "rating_channel.json"
LEADERBOARD_CHANNEL_FILE = "leaderboard_channel.json"
vote_messages = {}
votes = {}
voice_log = {}
rating_channel_id = None
leaderboard_channel_id = None
last_leaderboard_message = None
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

def load_data():
    global votes, voice_log, rating_channel_id, leaderboard_channel_id
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, "r") as f:
            votes = json.load(f)
    if os.path.exists(VOICE_LOG):
        with open(VOICE_LOG, "r") as f:
            voice_log = json.load(f)
    if os.path.exists(CHANNEL_FILE):
        with open(CHANNEL_FILE, "r") as f:
            rating_channel_id = json.load(f).get("channel_id")
    if os.path.exists(LEADERBOARD_CHANNEL_FILE):
        with open(LEADERBOARD_CHANNEL_FILE, "r") as f:
            leaderboard_channel_id = json.load(f).get("channel_id")

def save_data():
    with open(VOTES_FILE, "w") as f:
        json.dump(votes, f)
    with open(VOICE_LOG, "w") as f:
        json.dump(voice_log, f)

def save_channel(channel_id, filename):
    with open(filename, "w") as f:
        json.dump({"channel_id": channel_id}, f)

@client.event
async def on_voice_state_update(member, before, after):
    if after.channel and before.channel != after.channel:
        voice_log[str(member.id)] = datetime.utcnow().isoformat()
        save_data()

def get_recent_and_current_voice_users(guild):
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

@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return
    message_id = str(payload.message_id)
    emoji = payload.emoji.name
    if message_id in vote_messages and emoji in EMOJIS:
        player = vote_messages[message_id]
        user_id = str(payload.user_id)
        rating = EMOJIS.index(emoji) + 1
        if player not in votes:
            votes[player] = {}
        votes[player][user_id] = rating
        save_data()

        guild = client.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        member = guild.get_member(payload.user_id)
        await message.remove_reaction(payload.emoji, member)

@tree.command(name="setratingchannel", description="Set the channel for auto-rating posts (admin only)")
async def setratingchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)
        return
    save_channel(interaction.channel_id, CHANNEL_FILE)
    global rating_channel_id
    rating_channel_id = interaction.channel_id
    await interaction.response.send_message("✅ This channel is now set for rating posts.")

@tree.command(name="setleaderboardchannel", description="Set the channel for leaderboard posts (admin only)")
async def setleaderboardchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)
        return
    save_channel(interaction.channel_id, LEADERBOARD_CHANNEL_FILE)
    global leaderboard_channel_id
    leaderboard_channel_id = interaction.channel_id
    await interaction.response.send_message("✅ This channel is now set for leaderboard posts.")

async def post_leaderboard(channel):
    global last_leaderboard_message
    guild = channel.guild
    recent_members = get_recent_and_current_voice_users(guild)
    summary = []
    for member in recent_members:
        player_name = member.display_name.lower()
        if player_name in votes:
            ratings = votes[player_name]
            if ratings:
                avg = sum(ratings.values()) / len(ratings)
                summary.append((player_name.title(), round(avg, 2)))

    # Delete old leaderboard message
    async for msg in channel.history(limit=50):
        if msg.author == client.user and msg.embeds:
            if msg.embeds[0].title and "Player Ratings Leaderboard" in msg.embeds[0].title:
                await msg.delete()

    if not summary:
        msg = await channel.send("No ratings yet.")
        return

    summary.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="🏀 Player Ratings Leaderboard (Last 24 Hours - VC Join)", color=discord.Color.blue())
    for idx, (name, avg) in enumerate(summary, start=1):
        embed.add_field(name=f"{idx}. {name}", value=f"⭐ {avg}", inline=False)
    last_leaderboard_message = await channel.send(embed=embed)

@tasks.loop(minutes=30)
async def auto_post_and_leaderboard():
    now = datetime.utcnow()
    uk_hour = (now + timedelta(hours=1)).hour
    if 1 <= uk_hour < 10:
        return
    if not rating_channel_id or not leaderboard_channel_id:
        return
    guild = client.guilds[0]
    rating_channel = guild.get_channel(rating_channel_id)
    leaderboard_channel = guild.get_channel(leaderboard_channel_id)
    recent_members = get_recent_and_current_voice_users(guild)
    global vote_messages
    # Clear old vote messages
    vote_messages.clear()
    async for msg in rating_channel.history(limit=50):
        if msg.author == client.user and msg.content.startswith("📋 Rate Player"):
            await msg.delete()
    for member in recent_members:
        player_name = member.display_name.lower()
        msg = await rating_channel.send(f"📋 Rate Player: **{member.display_name}**")
        for emoji in EMOJIS:
            await msg.add_reaction(emoji)
        vote_messages[str(msg.id)] = player_name
    save_data()
    await post_leaderboard(leaderboard_channel)

@tree.command(name="sync", description="Force slash command sync")
async def sync(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        await tree.sync()
        await interaction.response.send_message("✅ Slash commands synced!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)

@client.event
async def on_ready():
    load_data()
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    auto_post_and_leaderboard.start()
    print(f"✅ Logged in as {client.user}")

client.run(os.getenv("BOT_TOKEN"))
