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
NOTIFIED_FILE = "notified.json"
vote_messages = {}
votes = {}
voice_log = {}
notified = {}
rating_channel_id = None
leaderboard_channel_id = None
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def load_data():
    global votes, voice_log, rating_channel_id, leaderboard_channel_id, notified
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, "r") as f:
            votes = json.load(f)
    if os.path.exists(VOICE_LOG):
        with open(VOICE_LOG, "r") as f:
            voice_log = json.load(f)
    if os.path.exists(NOTIFIED_FILE):
        with open(NOTIFIED_FILE, "r") as f:
            notified = json.load(f)
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
    with open(NOTIFIED_FILE, "w") as f:
        json.dump(notified, f)


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


async def check_player_feedback():
    await client.wait_until_ready()
    while not client.is_closed():
        for guild in client.guilds:
            recent_members = get_recent_and_current_voice_users(guild)
            for member in recent_members:
                player = member.display_name.lower()
                if player in votes and len(votes[player]) >= 3:
                    ratings = votes[player].values()
                    avg = sum(ratings) / len(ratings)

                    user_id = str(member.id)
                    if avg <= 2.0 and notified.get(user_id) != "warned":
                        try:
                            await member.send(
                                f"⚠️ From **{guild.name}**\n"
                                f"Your average player rating has dropped below 2.0 from more than 2 votes.\n\n"
                                f"Positioning is incredibly important in this club, so please try to maintain good positioning during games. "
                                f"Try to release the ball quickly and keep things simple with short passes.\n\n"
                                f"If you’d like feedback or help improving, feel free to ask in voice chat."
                            )
                            notified[user_id] = "warned"
                        except:
                            pass

                    elif avg > 2.5 and notified.get(user_id) == "warned":
                        try:
                            await member.send(
                                f"✅ From **{guild.name}**\n"
                                f"You've now achieved an average player rating above 2.5!\n\n"
                                f"That's fantastic — people are starting to notice improvements in your play. "
                                f"Keep going with the smart, simple play and great positioning.\n\n"
                                f"If you’d like advice to improve even further, feel free to ask in voice chat!"
                            )
                            notified[user_id] = "recovered"
                        except:
                            pass
        save_data()
        await discord.utils.sleep_until(datetime.utcnow() + timedelta(minutes=15))


client.loop.create_task(check_player_feedback())

@client.event
async def on_ready():
    load_data()
    await tree.sync()
    print(f"Logged in as {client.user}")


client.run(os.getenv("BOT_TOKEN"))
