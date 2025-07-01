import discord
from discord.ext import tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
import asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

VOTES_FILE = "votes.json"
VOICE_LOG = "voice_log.json"
CHANNEL_FILE = "rating_channel.json"
LEADERBOARD_CHANNEL_FILE = "leaderboard_channel.json"
vote_messages = {}
votes = {}
voice_log = {}
rating_channel_id = None
leaderboard_channel_id = None
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


@bot.event
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


@tree.command(name="postratings", description="Manually post ratings for voice-active players (admin only)")
async def postratings(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not rating_channel_id:
        await interaction.response.send_message("❌ Rating channel not set.", ephemeral=True)
        return
    guild = interaction.guild
    rating_channel = guild.get_channel(rating_channel_id)
    if not rating_channel:
        await interaction.response.send_message("❌ Could not find the rating channel.", ephemeral=True)
        return
    recent_members = get_recent_and_current_voice_users(guild)
    global vote_messages
    vote_messages.clear()
    for member in recent_members:
        msg = await rating_channel.send(f"📋 Rate Player: **{member.display_name}**")
        for emoji in EMOJIS:
            await msg.add_reaction(emoji)
        vote_messages[str(msg.id)] = member.display_name.lower()
    save_data()
    await interaction.response.send_message("✅ Rating posts have been posted.", ephemeral=True)


@tree.command(name="postleaderboard", description="Manually post leaderboard")
async def postleaderboard(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    await post_leaderboard(interaction.channel)


async def post_leaderboard(channel):
    print("📊 Posting leaderboard...")
    if not votes:
        msg = await channel.send("No ratings yet.")
        await asyncio.sleep(10)
        await msg.delete()
        return
    summary = []
    guild = channel.guild
    recent_members = get_recent_and_current_voice_users(guild)
    for member in recent_members:
        name = member.display_name.lower()
        if name in votes:
            ratings = votes[name].values()
            if ratings:
                avg = sum(ratings) / len(ratings)
                summary.append((member.display_name, round(avg, 2)))
    summary.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="🏆 Player Ratings Leaderboard (Last 24 Hours)", color=discord.Color.gold())
    for idx, (name, avg) in enumerate(summary, start=1):
        embed.add_field(name=f"{idx}. {name}", value=f"⭐ {avg}", inline=False)
    await channel.send(embed=embed)


@tasks.loop(minutes=30)
async def auto_post_and_leaderboard():
    print("⏰ Running auto_post_and_leaderboard...")
    if not rating_channel_id or not leaderboard_channel_id:
        return
    now = datetime.utcnow()
    uk_hour = (now + timedelta(hours=1)).hour  # UK time (BST)
    if 1 <= uk_hour < 10:
        print("⏳ Skipping due to quiet hours (1am-10am UK time)")
        return
    guild = bot.guilds[0]
    rating_channel = guild.get_channel(rating_channel_id)
    leaderboard_channel = guild.get_channel(leaderboard_channel_id)
    vote_messages.clear()
    recent_members = get_recent_and_current_voice_users(guild)
    for member in recent_members:
        msg = await rating_channel.send(f"📋 Rate Player: **{member.display_name}**")
        for emoji in EMOJIS:
            await msg.add_reaction(emoji)
        vote_messages[str(msg.id)] = member.display_name.lower()
    save_data()
    await post_leaderboard(leaderboard_channel)


@tree.command(name="sync", description="Force slash command sync")
async def sync(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        await tree.sync()
        await interaction.response.send_message("✅ Slash commands synced!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Admins only", ephemeral=True)


@bot.event
async def on_ready():
    load_data()
    await tree.sync()
    print("✅ Bot is ready and commands are synced.")
    auto_post_and_leaderboard.start()


bot.run(os.getenv("BOT_TOKEN"))
