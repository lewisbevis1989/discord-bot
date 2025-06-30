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
LEADERBOARD_MESSAGE_FILE = "leaderboard_message.json"
vote_messages = {}
votes = {}
voice_log = {}
rating_channel_id = None
leaderboard_channel_id = None
leaderboard_message_id = None
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

def load_data():
    global votes, voice_log, rating_channel_id, leaderboard_channel_id, leaderboard_message_id
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
    if os.path.exists(LEADERBOARD_MESSAGE_FILE):
        with open(LEADERBOARD_MESSAGE_FILE, "r") as f:
            leaderboard_message_id = json.load(f).get("message_id")

def save_data():
    with open(VOTES_FILE, "w") as f:
        json.dump(votes, f)
    with open(VOICE_LOG, "w") as f:
        json.dump(voice_log, f)

def save_channel(channel_id, filename):
    with open(filename, "w") as f:
        json.dump({"channel_id": channel_id}, f)

def save_leaderboard_message_id(message_id):
    with open(LEADERBOARD_MESSAGE_FILE, "w") as f:
        json.dump({"message_id": message_id}, f)

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

@client.event
async def on_raw_reaction_remove(payload):
    message_id = str(payload.message_id)
    emoji = payload.emoji.name
    if message_id in vote_messages and emoji in EMOJIS:
        player = vote_messages[message_id]
        user_id = str(payload.user_id)
        if player in votes and user_id in votes[player]:
            del votes[player][user_id]
            save_data()

@tree.command(name="setratingchannel", description="Set the channel for auto-rating posts")
async def setratingchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)
        return
    save_channel(interaction.channel_id, CHANNEL_FILE)
    global rating_channel_id
    rating_channel_id = interaction.channel_id
    await interaction.response.send_message("✅ Rating channel set.")

@tree.command(name="setleaderboardchannel", description="Set the channel for leaderboard posts")
async def setleaderboardchannel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)
        return
    save_channel(interaction.channel_id, LEADERBOARD_CHANNEL_FILE)
    global leaderboard_channel_id
    leaderboard_channel_id = interaction.channel_id
    await interaction.response.send_message("✅ Leaderboard channel set.")

async def post_leaderboard(channel):
    global leaderboard_message_id

    if not votes:
        await channel.send("No ratings yet.")
        return

    summary = []
    guild = channel.guild
    recent_members = get_recent_and_current_voice_users(guild)

    for member in recent_members:
        player_name = member.display_name.lower()
        if player_name in votes:
            ratings = votes[player_name]
            if ratings:
                avg = sum(ratings.values()) / len(ratings)
                summary.append((player_name.title(), round(avg, 2)))

    summary.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="⚽ Player Ratings Leaderboard (Last 24 Hours - VC Join)", color=discord.Color.blue())

    for idx, (name, avg) in enumerate(summary, start=1):
        embed.add_field(name=f"{idx}. {name}", value=f"⭐ {avg}", inline=False)

    if leaderboard_message_id:
        try:
            old_msg = await channel.fetch_message(leaderboard_message_id)
            await old_msg.delete()
        except:
            pass

    new_msg = await channel.send(embed=embed)
    leaderboard_message_id = new_msg.id
    save_leaderboard_message_id(leaderboard_message_id)

@tasks.loop(minutes=30)
async def auto_post_and_leaderboard():
    if not rating_channel_id or not leaderboard_channel_id:
        return

    now = datetime.utcnow()
    if 1 <= (now + timedelta(hours=1)).hour < 10:
        return  # UK quiet hours

    guild = client.guilds[0]
    rating_channel = guild.get_channel(rating_channel_id)
    leaderboard_channel = guild.get_channel(leaderboard_channel_id)

    recent_members = get_recent_and_current_voice_users(guild)
    global vote_messages

    # Delete old messages
    async for msg in rating_channel.history(limit=100):
        if msg.author == client.user and msg.id in [int(mid) for mid in vote_messages.keys()]:
            await msg.delete()

    vote_messages.clear()
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

