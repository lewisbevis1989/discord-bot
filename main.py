import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import json
import os
from typing import Dict, List, Tuple
from pytz import timezone as pytz_timezone
from dotenv import load_dotenv

########################
#  🔧  CONFIGURATION   #
########################

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")         # votes received
NOTIFIED_FILE = os.path.join(DATA_DIR, "notified.json")       # low‑score alert flags
CONFIG_FILE = os.path.join(DATA_DIR, "botconfig.json")        # admin‑set channel / VC ids

# Default windows (can be tweaked in one place)
RATING_POST_INTERVAL_MIN = 30
RECENT_VOICE_WINDOW_HOURS = 2
LEADERBOARD_WINDOW_HOURS = 24
SHOW_RATINGS_LOOKBACK_HOURS = 72
LOW_SCORE_THRESHOLD = 2.5
LOW_SCORE_MIN_VOTES = 5

# Sleep window (UK = Europe/London)
SLEEP_START_HOUR_UK = 0   # 00:00
SLEEP_END_HOUR_UK = 12    # 12:00

########################
#  🛠  UTILITIES       #
########################

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)

ratings: Dict[str, Dict[str, Tuple[int, str]]] = load_json(RATINGS_FILE, {})
notified: Dict[str, str] = load_json(NOTIFIED_FILE, {})  # 'below' or 'ok'
config: Dict[str, any] = load_json(CONFIG_FILE, {
    "voice_channels": [],
    "ratings_channel": None,
    "leaderboard_channel": None,
    "warnings_channel": None
})

voice_last_seen: Dict[str, str] = {}  # user_id -> ISO str timestamp

def utc_now_iso() -> str:
    return datetime.utcnow().isoformat()

def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)

def within_hours(iso_time: str, hours: int) -> bool:
    return datetime.utcnow() - iso_to_dt(iso_time) <= timedelta(hours=hours)

uk_tz = pytz_timezone("Europe/London")

def is_sleep_time() -> bool:
    now_uk = datetime.now(uk_tz)
    return SLEEP_START_HOUR_UK <= now_uk.hour < SLEEP_END_HOUR_UK

def rating_average(user_id: str) -> Tuple[float, int]:
    user_ratings = ratings.get(user_id, {})
    if not user_ratings:
        return (0.0, 0)
    scores = [data[0] for data in user_ratings.values()]
    return (sum(scores) / len(scores), len(scores))

########################
#  🤖  BOT SETUP       #
########################

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

########################
#  📼  VOICE TRACKING   #
########################

@bot.event
async def on_voice_state_update(member: discord.Member,
                                before: discord.VoiceState,
                                after: discord.VoiceState):
    # Ignore if no VC configured
    voice_ids = set(config["voice_channels"])
    if not voice_ids:
        return

    # Was the member in or is now in a tracked VC?
    def is_tracked(vc):
        return vc and vc.channel and vc.channel.id in voice_ids

    if is_tracked(before) or is_tracked(after):
        voice_last_seen[str(member.id)] = utc_now_iso()
        # Persist lazily
        save_json(os.path.join(DATA_DIR, "voice_seen.json"), voice_last_seen)

########################
#  🗳  VOTING VIEWS     #
########################

class ConfirmOne(discord.ui.View):
    def __init__(self, user_id: str, rater_id: str):
        super().__init__(timeout=15)
        self.user_id = user_id
        self.rater_id = rater_id

    @discord.ui.button(label="✅ Yes, give 1", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _):
        await record_vote(self.user_id, self.rater_id, 1)
        await interaction.response.edit_message(content="✅ 1 recorded.", view=None)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.message.delete()

async def record_vote(target_id: str, rater_id: str, score: int):
    # Members cannot vote for themselves
    if target_id == rater_id:
        return
    user_ratings = ratings.setdefault(target_id, {})
    user_ratings[rater_id] = (score, utc_now_iso())
    save_json(RATINGS_FILE, ratings)

    # announcement check
    await check_low_score_alert(target_id)

async def check_low_score_alert(user_id: str):
    avg, count = rating_average(user_id)
    status = notified.get(user_id, "ok")
    channel_id = config.get("warnings_channel")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    # Falling below
    if avg < LOW_SCORE_THRESHOLD and count >= LOW_SCORE_MIN_VOTES and status != "below":
        await channel.send(f"⚠️ <@{user_id}>’s average plunged to {avg:.2f} ({count} votes) — please review.")
        notified[user_id] = "below"
        save_json(NOTIFIED_FILE, notified)

    # Recovering above
    if avg >= LOW_SCORE_THRESHOLD and status == "below":
        await channel.send(f"✅ <@{user_id}> has recovered above {LOW_SCORE_THRESHOLD} (now {avg:.2f}) — nice turnaround!")
        notified[user_id] = "ok"
        save_json(NOTIFIED_FILE, notified)

########################
#  ⏲️  PERIODIC TASKS   #
########################

@tasks.loop(minutes=RATING_POST_INTERVAL_MIN)
async def periodic_post_task():
    if is_sleep_time():
        return
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    ################# Build member list #################
    recent_members: List[discord.Member] = []
    for user_id, iso_ts in voice_last_seen.items():
        if within_hours(iso_ts, RECENT_VOICE_WINDOW_HOURS):
            member = guild.get_member(int(user_id))
            if member:
                recent_members.append(member)

    if not recent_members:
        return

    ################# Ratings Channel #################
    channel_id = config.get("ratings_channel")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    # Remove previous bot message to keep channel clean
    async for msg in channel.history(limit=10):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except discord.HTTPException:
                pass

    # Build view with buttons for each member
    view = discord.ui.View(timeout=None)
    for member in recent_members:
        row = len(view.children) // 5  # each row holds 5 buttons
        for score in range(1, 6):
            style = discord.ButtonStyle.danger if score == 1 else discord.ButtonStyle.primary
            label = f"{score}"
            custom_id = f"rate:{member.id}:{score}"
            view.add_item(discord.ui.Button(label=label, row=row, style=style, custom_id=custom_id))

    member_lines = [member.mention for member in recent_members]
    embed = discord.Embed(
        title="🗳 Rate the Squad",
        description="\n".join(member_lines),
        color=discord.Color.blue()
    )
    await channel.send(embed=embed, view=view)

    ################# Leaderboard Channel #################
    lb_channel_id = config.get("leaderboard_channel")
    if lb_channel_id:
        lb_channel = bot.get_channel(lb_channel_id)
        if lb_channel:
            # Clear last bot message
            async for msg in lb_channel.history(limit=10):
                if msg.author == bot.user:
                    try:
                        await msg.delete()
                    except discord.HTTPException:
                        pass
            cutoff = datetime.utcnow() - timedelta(hours=LEADERBOARD_WINDOW_HOURS)
            board: List[Tuple[str, float]] = []
            for user_id, votes in ratings.items():
                # filter votes within window
                recent_scores = [v[0] for v in votes.values() if iso_to_dt(v[1]) >= cutoff]
                if recent_scores:
                    avg = sum(recent_scores) / len(recent_scores)
                    board.append((user_id, avg))
            board.sort(key=lambda t: t[1], reverse=True)
            lines = [f"{i+1}. <@{uid}> — {avg:.2f}" for i, (uid, avg) in enumerate(board[:20])]
            embed_lb = discord.Embed(
                title=f"🏆 Leaderboard – last {LEADERBOARD_WINDOW_HOURS} h",
                description="\n".join(lines) if lines else "No data yet.",
                color=discord.Color.gold()
            )
            await lb_channel.send(embed=embed_lb)

@periodic_post_task.before_loop
async def before_periodic():
    await bot.wait_until_ready()

periodic_post_task.start()

########################
#  🎛️  ADMIN COMMANDS   #
########################

def admin_check():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@tree.command(name="setvoicechannels", description="Select voice channels for the bot to track")
@admin_check()
async def set_voice_channels(interaction: discord.Interaction, voice_channels: commands.Greedy[
