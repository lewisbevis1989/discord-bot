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
DM_TRACK_FILE = "dm_sent_log.json"

vote_messages = {}
votes = {}
voice_log = {}
dm_sent = {}
rating_channel_id = None
leaderboard_channel_id = None
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

def load_data():
    global votes, voice_log, rating_channel_id, leaderboard_channel_id, dm_sent
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, "r") as f:
            votes = json.load(f)
    if os.path.exists(VOICE_LOG):
        with open(VOICE_LOG, "r") as f:
            voice_log = json.load(f)
    if os.path.exists(DM_TRACK_FILE):
        with open(DM_TRACK_FILE, "r") as f:
            dm_sent = json.load(f)
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
    with open(DM_TRACK_FILE, "w") as f:
        json.dump(dm_sent, f)

def save_channel(channel_id, filename):
    with open(filename, "w") as f:
        json.dump({"channel_id": channel_id}, f)

@client.event
async def setup_hook():
    client.loop.create_task(check_player_feedback())

async def check_player_feedback():
    await client.wait_until_ready()
    while not client.is_closed():
        for guild in client.guilds:
            for member in guild.members:
                player_name = member.display_name.lower()
                if player_name in votes:
                    player_votes = votes[player_name]
                    avg_rating = sum(player_votes.values()) / len(player_votes)
                    vote_count = len(player_votes)
                    user_id = str(member.id)

                    # Send warning if under 2.0 and more than 2 votes
                    if avg_rating <= 2.0 and vote_count >= 3 and dm_sent.get(user_id) != "warned":
                        try:
                            await member.send(
                                f"Hey {member.display_name}, we've noticed your rating in **{guild.name}** has been a little low lately (⭐ {avg_rating:.2f}).\n\n"
                                "Positioning is incredibly important in this club so please try and keep your positioning during games.\n"
                                "Try to keep things simple, make easy passes, and release the ball quickly.\n\nIf you'd like help improving or want some feedback, feel free to ask in voice chat! 💬"
                            )
                            dm_sent[user_id] = "warned"
                            save_data()
                        except:
                            continue

                    # Send encouragement if previously warned and now improved
                    elif avg_rating > 2.5 and dm_sent.get(user_id) == "warned":
                        try:
                            await member.send(
                                f"Awesome work {member.display_name}! Your rating in **{guild.name}** has gone up to ⭐ {avg_rating:.2f}.\n\n"
                                "People are starting to see improvements in your play which is great — but we know you can keep going!\n"
                                "If you'd like to improve even more, feel free to ask for feedback in voice chat. Keep it up! 🚀"
                            )
                            dm_sent[user_id] = "recovered"
                            save_data()
                        except:
                            continue

        await discord.utils.sleep_until(datetime.utcnow() + timedelta(minutes=15))

# Your existing bot setup and commands here...

@client.event
async def on_ready():
    load_data()
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    print(f"✅ Logged in as {client.user}")

client.run(os.getenv("BOT_TOKEN"))
