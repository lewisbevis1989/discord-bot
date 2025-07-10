"""
Discord Voice Rating Bot
========================
Full, self‑contained bot that fulfils the feature list we discussed.
• Tracks users in admin‑selected VCs
• Posts a fresh rate‑sheet every 30 min, keeps history 2 h, leaderboard 24 h
• Confirmation modal for 1‑vote
• Low‑score alert (<2.5 after ≥5 votes) + recovery notice
• /myratings (last 10) and /showratings (last 72 h)
• Sleeps 00:00‑12:00 UK
• Persists json to /data so the bot can restart safely on Render

-------------------------------------
Save this file as **main.py** (or any entry‑point) and push to GitHub.
Add `discord.py`, `python‑dotenv`, `pytz` to your `requirements.txt`.
Set env‑vars `DISCORD_TOKEN` (secret) and optional `GUILD_ID` in Render.
-------------------------------------
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pytz import timezone as pytz_timezone

# ───────────────────────────────── CONFIG ────────────────────────────────── #

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")  # votes a user RECEIVED
NOTIFIED_FILE = os.path.join(DATA_DIR, "notified.json")  # low‑score state per user
CONFIG_FILE = os.path.join(DATA_DIR, "botconfig.json")   # channel / VC IDs
VOICE_SEEN_FILE = os.path.join(DATA_DIR, "voice_seen.json")

# Tunables
RATING_POST_INTERVAL_MIN = 30      # how often to refresh the rate‑sheet
RECENT_VOICE_WINDOW_HOURS = 2      # consider a member "present" for 2 h after we last saw them
LEADERBOARD_WINDOW_HOURS = 24      # scores considered for the leaderboard
SHOW_RATINGS_LOOKBACK_HOURS = 72   # /showratings window
LOW_SCORE_THRESHOLD = 2.5
LOW_SCORE_MIN_VOTES = 5

# Sleep window (Europe/London clock)
SLEEP_START_HOUR = 0   # 00:00
SLEEP_END_HOUR = 12    # 12:00

uk_tz = pytz_timezone("Europe/London")

# ────────────────────────────── persistence helpers ──────────────────────── #

def _load(path: str, default):
    try:
        with open(path, "r", encoding="utf‑8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _save(path: str, data):
    with open(path, "w", encoding="utf‑8") as f:
        json.dump(data, f, indent=2)

ratings: Dict[str, Dict[str, Tuple[int, str]]] = _load(RATINGS_FILE, {})     # {user_id: {rater_id: (score, iso_ts)}}
notified: Dict[str, str] = _load(NOTIFIED_FILE, {})                         # "ok" | "below"
config: Dict[str, any] = _load(CONFIG_FILE, {
    "voice_channels": [],
    "ratings_channel": None,
    "leaderboard_channel": None,
    "warnings_channel": None
})
voice_last_seen: Dict[str, str] = _load(VOICE_SEEN_FILE, {})  # {user_id: iso_ts}

# ────────────────────────────── misc helpers ─────────────────────────────── #

def utc_now_iso() -> str:
    return datetime.utcnow().isoformat()

def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)

def within_hours(iso_ts: str, hours: int) -> bool:
    return datetime.utcnow() - iso_to_dt(iso_ts) <= timedelta(hours=hours)

def is_sleep_time() -> bool:
    now_uk = datetime.now(uk_tz)
    return SLEEP_START_HOUR <= now_uk.hour < SLEEP_END_HOUR

def rating_average(user_id: str) -> Tuple[float, int]:
    user = ratings.get(user_id, {})
    if not user:
        return 0.0, 0
    vals = [v[0] for v in user.values()]
    return sum(vals) / len(vals), len(vals)

# ─────────────────────────────── Discord setup ───────────────────────────── #

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─────────────────────────────── Voice tracking ──────────────────────────── #

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    tracked_vcs = set(config["voice_channels"])
    if not tracked_vcs:
        return

    def in_tracked(vs: discord.VoiceState):
        return vs and vs.channel and vs.channel.id in tracked_vcs

    if in_tracked(before) or in_tracked(after):
        voice_last_seen[str(member.id)] = utc_now_iso()
        _save(VOICE_SEEN_FILE, voice_last_seen)

# ───────────────────────────── Voting confirmation ───────────────────────── #

class ConfirmOne(discord.ui.View):
    def __init__(self, target_id: str, rater_id: str):
        super().__init__(timeout=15)
        self.target_id = target_id
        self.rater_id = rater_id

    @discord.ui.button(label="✅ Yes, give 1", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _):
        await record_vote(self.target_id, self.rater_id, 1)
        await interaction.response.edit_message(content="✅ 1 recorded.", view=None)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.message.delete()

# ───────────────────────────── Vote storage & alerts ─────────────────────── #

async def record_vote(target_id: str, rater_id: str, score: int):
    if target_id == rater_id:
        return  # self‑vote rejected elsewhere, extra guard

    ratings.setdefault(target_id, {})[rater_id] = (score, utc_now_iso())
    _save(RATINGS_FILE, ratings)
    await check_low_score_alert(target_id)

async def check_low_score_alert(user_id: str):
    avg, count = rating_average(user_id)
    warn_channel_id = config.get("warnings_channel")
    if not warn_channel_id:
        return
    channel = bot.get_channel(warn_channel_id)
    if not channel:
        return

    state = notified.get(user_id, "ok")
    # Fall below threshold
    if avg < LOW_SCORE_THRESHOLD and count >= LOW_SCORE_MIN_VOTES and state != "below":
        await channel.send(f"⚠️ <@{user_id}>’s average plunged to {avg:.2f} ({count} votes) — please review.")
        notified[user_id] = "below"
        _save(NOTIFIED_FILE, notified)

    # Recover above threshold
    if avg >= LOW_SCORE_THRESHOLD and state == "below":
        await channel.send(f"✅ <@{user_id}> has recovered above {LOW_SCORE_THRESHOLD} (now {avg:.2f}).")
        notified[user_id] = "ok"
        _save(NOTIFIED_FILE, notified)

# ───────────────────────────── Periodic posts ────────────────────────────── #

@tasks.loop(minutes=RATING_POST_INTERVAL_MIN)
async def periodic_posts():
    if is_sleep_time():
        return

    guild = bot.get_guild(GUILD_ID) if GUILD_ID else bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    # Build recent member list
    members: List[discord.Member] = []
    for uid, iso_ts in voice_last_seen.items():
        if within_hours(iso_ts, RECENT_VOICE_WINDOW_HOURS):
            m = guild.get_member(int(uid))
            if m:
                members.append(m)
    if not members:
        return

    ratings_chan = bot.get_channel(config.get("ratings_channel")) if config.get("ratings_channel") else None
    if not ratings_chan:
        return

    # Delete previous bot message to keep channel tidy
    async for m in ratings_chan.history(limit=10):
        if m.author == bot.user:
            try:
                await m.delete()
            except discord.HTTPException:
                pass

    # Build dynamic button grid
    view = discord.ui.View(timeout=None)
    for member in members:
        for score in range(1, 6):
            style = discord.ButtonStyle.danger if score == 1 else discord.ButtonStyle.primary
            cid = f"rate:{member.id}:{score}"
            view.add_item(discord.ui.Button(label=str(score), style=style, custom_id=cid))

    embed = discord.Embed(title="🗳 Rate the squad", description="\n".join(m.mention for m in members), color=discord.Color.blue())
    await ratings_chan.send(embed=embed, view=view)

    # Leaderboard
    lb_chan = bot.get_channel(config.get("leaderboard_channel")) if config.get("leaderboard_channel") else None
    if lb_chan:
        async for m in lb_chan.history(limit=10):
            if m.author == bot.user:
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
        cutoff = datetime.utcnow() - timedelta(hours=LEADERBOARD_WINDOW_HOURS)
        board: List[Tuple[str, float]] = []
        for uid, votes in ratings.items():
            recent = [v[0] for v in votes.values() if iso_to_dt(v[1]) >= cutoff]
            if recent:
                board.append((uid, sum(recent) / len(recent)))
        board.sort(key=lambda t: t[1], reverse=True)
        lines = [f"{i+1}. <@{uid}> — {avg:.2f}" for i, (uid, avg) in enumerate(board[:20])]
        embed_lb = discord.Embed(title=f"🏆 Leaderboard – last {LEADERBOARD_WINDOW_HOURS} h", description="\n".join(lines) or "No data yet.", color=discord.Color.gold())
        await lb_chan.send(embed=embed_lb)

@periodic_posts.before_loop
async def _wait_until_ready():
    await bot.wait_until_ready()

periodic_posts.start()

# ───────────────────────────── Interaction handler ───────────────────────── #

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # Handle rating button presses
    data = interaction.data or {}
    cid: str | None = data.get("custom_id")
    if cid and cid.startswith("rate:"):
        _, target_id, score_s = cid.split(":")
        score = int(score_s)
        rater_id = str(interaction.user.id)

        if target_id == rater_id:
            await interaction.response.send_message("❌ You can’t rate yourself.", ephemeral=True)
            return

        if score == 1:
            await interaction.response.send_message(f"Are you sure you want to give <@{target_id}> a **1**?", view=ConfirmOne(target_id, rater_id), ephemeral=True)
        else:
            await record_vote(target_id, rater_id, score)
            await interaction.response.send_message("✅ Vote recorded.", ephemeral=True)

# ───────────────────────────── Slash‑command helpers ─────────────────────── #

def admin_check():
    async def predicate(i: discord.Interaction):
        return i.user.guild_permissions.administrator
    return app_commands.check(predicate)

# ---------- config commands ----------- #

@tree.command(name="setratingschannel", description="Set the channel where the bot posts the rating list")
@admin_check()
async def _set_ratings(i: discord.Interaction, channel: discord.TextChannel):
    config["ratings_channel"] = channel.id
    _save(CONFIG_FILE, config)
    await i.response.send_message(f"Ratings channel set to {channel.mention}", ephemeral=True)

@tree.command(name="setleaderboardchannel", description="Set the leaderboard channel")
@admin_check()
async def _set_lb(i: discord.Interaction, channel: discord.TextChannel):
    config["leaderboard_channel"] = channel.id
    _save(CONFIG_FILE, config)
    await i.response.send_message(f"Leaderboard channel set.", ephemeral=True)

@tree.command(name="setwarningschannel", description="Set the low‑score warnings channel")
@admin_check()
async def _set_warn(i: discord.Interaction, channel: discord.TextChannel):
    config["warnings_channel"] = channel.id
    _save(CONFIG_FILE, config)
    await i.response.send_message("Warnings channel set.", ephemeral=True)

@tree.command(name="addvoicechannel", description="Add a voice channel to track")
@admin_check()
async def _add_vc(i: discord.Interaction, channel: discord.VoiceChannel):
    if channel.id not in config["voice_channels"]:
        config["voice_channels"].append(channel.id)
        _save(CONFIG_FILE, config
