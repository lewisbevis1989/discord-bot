import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = "config.json"
RATINGS_FILE = "ratings.json"
FEEDBACK_FILE = "feedback_flags.json"

for file in [CONFIG_FILE, RATINGS_FILE, FEEDBACK_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump({}, f)

with open(CONFIG_FILE) as f:
    config = json.load(f)
with open(RATINGS_FILE) as f:
    ratings = json.load(f)
with open(FEEDBACK_FILE) as f:
    feedback_flags = json.load(f)

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Sync failed: {e}")
    leaderboard_loop.start()
    check_player_feedback.start()

@bot.tree.command(name="setratingchannel")
@app_commands.describe(channel="Channel where ratings will be logged")
async def set_rating_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild_id)
    config[gid] = config.get(gid, {})
    config[gid]["rating_channel"] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Rating channel set.", ephemeral=True)

@bot.tree.command(name="setleaderboardchannel")
@app_commands.describe(channel="Channel where leaderboard will be posted")
async def set_leaderboard_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild_id)
    config[gid] = config.get(gid, {})
    config[gid]["leaderboard_channel"] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Leaderboard channel set.", ephemeral=True)

# ---------------- LEADERBOARD ---------------- #
@tasks.loop(minutes=30)
async def leaderboard_loop():
    now = datetime.utcnow()
    if 1 <= now.hour < 10:
        return

    for gid, conf in config.items():
        guild = bot.get_guild(int(gid))
        if not guild:
            continue

        channel_id = conf.get("leaderboard_channel")
        if not channel_id:
            continue

        channel = guild.get_channel(channel_id)
        if not channel:
            continue

        guild_ratings = ratings.get(gid, {})
        cutoff = datetime.utcnow() - timedelta(hours=24)

        leaderboard = {}
        for uid, data in guild_ratings.items():
            new_votes = [(v, t) for v, t in data["votes"] if datetime.fromisoformat(t) > cutoff]
            if new_votes:
                avg = sum(v for v, _ in new_votes) / len(new_votes)
                leaderboard[uid] = avg
            data["votes"] = new_votes
        save_json(RATINGS_FILE, ratings)

        if leaderboard:
            sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            msg = "🏀 **Player Ratings Leaderboard (Last 24 Hours - VC Join)**\n"
            for idx, (uid, avg) in enumerate(sorted_board, 1):
                member = guild.get_member(int(uid))
                name = member.display_name if member else f"<@{uid}>"
                msg += f"{idx}. {name}\n⭐ {round(avg, 2)}\n\n"
        else:
            msg = "No ratings yet."

        # Delete previous leaderboard
        history = [m async for m in channel.history(limit=10)]
        for m in history:
            if m.author == bot.user and ("Leaderboard" in m.content or "No ratings yet" in m.content):
                await m.delete()

        await channel.send(msg)

# ---------------- FEEDBACK SYSTEM ---------------- #
@tasks.loop(minutes=30)
async def check_player_feedback():
    for gid, guild_data in ratings.items():
        guild = bot.get_guild(int(gid))
        if not guild:
            continue

        for uid, user_data in guild_data.items():
            if len(user_data["votes"]) < 3:
                continue

            avg_rating = sum(v for v, _ in user_data["votes"]) / len(user_data["votes"])
            key = f"{gid}-{uid}"
            user = guild.get_member(int(uid))
            if not user:
                continue

            # Send low rating warning once
            if avg_rating <= 2.0 and feedback_flags.get(key) != "low":
                try:
                    await user.send(
                        f"👋 Hey from **{guild.name}**!\n\n"
                        "We've noticed your average rating has dropped to 2.0 or below. "
                        "This isn't a big issue, but we'd love to help you out.\n\n"
                        "⚽ Try releasing the ball quickly and using simple, easy passing. "
                        "📌 Positioning is incredibly important in this club, so try to keep your shape during games.\n\n"
                        "If you'd like help improving, feel free to ask in voice chat anytime!"
                    )
                    feedback_flags[key] = "low"
                    save_json(FEEDBACK_FILE, feedback_flags)
                except:
                    pass

            # Send improvement message once
            if avg_rating > 2.5 and feedback_flags.get(key) == "low":
                try:
                    await user.send(
                        f"🔥 Great news from **{guild.name}**!\n\n"
                        "Your average rating has improved! People are starting to see positive changes in your play. "
                        "We're really proud of the effort you're putting in.\n\n"
                        "Keep going! And if you want tips on how to push even further, don’t hesitate to ask in voice chat. 💪"
                    )
                    feedback_flags[key] = "high"
                    save_json(FEEDBACK_FILE, feedback_flags)
                except:
                    pass

bot.run(os.getenv("BOT_TOKEN"))
