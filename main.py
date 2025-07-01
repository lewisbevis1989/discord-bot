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

# Load or create necessary files
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

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID)) if GUILD_ID else await tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(f"Sync error: {e}")
    auto_post.start()

def is_recent(member_id):
    now = datetime.now(timezone.utc)
    joined = voice_log.get(str(member_id))
    if joined:
        joined_time = datetime.fromisoformat(joined)
        return now - joined_time <= timedelta(hours=24)
    return False

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and not before.channel:
        voice_log[str(member.id)] = datetime.now(timezone.utc).isoformat()
        save_json(log_file, voice_log)

@tree.command(name="setratingschannel", description="Set the channel for posting ratings")
@app_commands.checks.has_permissions(administrator=True)
async def set_ratings_channel(interaction: discord.Interaction):
    config["ratings_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Ratings channel has been set to this channel.", ephemeral=True)

@tree.command(name="setleaderboardchannel", description="Set the channel for posting leaderboard")
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    config["leaderboard_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Leaderboard channel has been set to this channel.", ephemeral=True)

@tree.command(name="postratings", description="Manually post ratings")
async def post_ratings(interaction: discord.Interaction):
    if not config.get("ratings_channel"):
        await interaction.response.send_message("❌ Ratings channel not set.", ephemeral=True)
        return

    channel = bot.get_channel(config["ratings_channel"])
    for user_id in list(voice_log):
        if is_recent(user_id):
            user = interaction.guild.get_member(int(user_id))
            if user:
                msg = await channel.send(f"Rate {user.mention}: 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣")
                for emoji in ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"):
                    await msg.add_reaction(emoji)
    await interaction.response.send_message("✅ Rating posts have been posted.", ephemeral=True)

@tree.command(name="postleaderboard", description="Manually post leaderboard")
async def post_leaderboard(interaction: discord.Interaction):
    await generate_leaderboard()
    await interaction.response.send_message("✅ Leaderboard posted.", ephemeral=True)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message.author != bot.user:
        return
    if reaction.emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]:
        score = int(reaction.emoji[0])
        mentioned = reaction.message.mentions[0] if reaction.message.mentions else None
        if mentioned:
            uid = str(mentioned.id)
            ratings.setdefault(uid, []).append(score)
            save_json(ratings_file, ratings)
            await reaction.message.remove_reaction(reaction.emoji, user)

async def generate_leaderboard():
    if not config.get("leaderboard_channel"):
        return

    channel = bot.get_channel(config["leaderboard_channel"])
    now = datetime.now(timezone.utc)
    leaderboard = []

    for user_id, scores in ratings.items():
        if not is_recent(user_id):
            continue
        avg_score = sum(scores) / len(scores)
        leaderboard.append((user_id, avg_score))

    leaderboard.sort(key=lambda x: x[1], reverse=True)

    if not leaderboard:
        await channel.send("No ratings yet.")
        return

    lines = []
    for user_id, avg in leaderboard:
        member = channel.guild.get_member(int(user_id))
        if member:
            lines.append(f"{member.display_name}: {avg:.2f}")

    embed = discord.Embed(title="🏆 Leaderboard (last 24h)", description="\n".join(lines), color=0x00ff00)
    await channel.send(embed=embed)

@tasks.loop(minutes=30)
async def auto_post():
    hour = datetime.now(timezone.utc).hour
    if hour < 1 or hour >= 10:
        ctx = type('obj', (object,), {'guild': bot.get_guild(GUILD_ID)})
        await post_ratings(ctx)
        await generate_leaderboard()

bot.run(TOKEN)
