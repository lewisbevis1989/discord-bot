import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pytz import timezone as pytz_timezone

# Load environment
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

# File paths
RATINGS_FILE = "ratings.json"
VOICE_LOG_FILE = "voice_log.json"
VOICE_SESSIONS_FILE = "voice_sessions.json"
CONFIG_FILE = "config.json"
NOTIFIED_FILE = "notified.json"

# Utilities for JSON
def load_json(fn):
    if not os.path.exists(fn):
        with open(fn, "w") as f:
            json.dump({}, f)
    with open(fn, "r") as f:
        return json.load(f)

def save_json(fn, data):
    with open(fn, "w") as f:
        json.dump(data, f, indent=4)

# Load data
ratings = load_json(RATINGS_FILE)       # { target_id: { rater_id: {score, timestamp} } }
voice_log = load_json(VOICE_LOG_FILE)   # { user_id: last_join_timestamp }
voice_sessions = load_json(VOICE_SESSIONS_FILE)  # { user_id: [ {channel_id, start, end} ] }
config = load_json(CONFIG_FILE)         # holds channel IDs and voice_channels list
notified = load_json(NOTIFIED_FILE)     # { target_id: {low: bool, recovered: bool} }

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Helper Functions ---

def prune_voice_log():
    """Remove users from voice_log if last join >2h ago"""
    now = datetime.now(timezone.utc)
    to_del = []
    for uid, ts in voice_log.items():
        dt = datetime.fromisoformat(ts)
        if now - dt > timedelta(hours=2):
            to_del.append(uid)
    for uid in to_del:
        voice_log.pop(uid)
    if to_del:
        save_json(VOICE_LOG_FILE, voice_log)


def prune_voice_sessions():
    """Prune session entries older than 2h"""
    now = datetime.now(timezone.utc)
    changed = False
    for uid, sessions in list(voice_sessions.items()):
        new_sessions = []
        for s in sessions:
            start = datetime.fromisoformat(s['start'])
            end = datetime.fromisoformat(s['end']) if s.get('end') else now
            if end + timedelta(hours=0) >= now - timedelta(hours=2):
                new_sessions.append(s)
        if len(new_sessions) != len(sessions):
            voice_sessions[uid] = new_sessions
            changed = True
    if changed:
        save_json(VOICE_SESSIONS_FILE, voice_sessions)


def is_eligible(rater_id: str, target_id: str) -> bool:
    """Check if rater and target have overlapping sessions in a monitored channel"""
    cfg_ch = config.get("voice_channels", [])
    now = datetime.now(timezone.utc)
    s1_list = voice_sessions.get(rater_id, [])
    s2_list = voice_sessions.get(target_id, [])
    for s1 in s1_list:
        for s2 in s2_list:
            if s1['channel_id'] != s2['channel_id']:
                continue
            if cfg_ch and s1['channel_id'] not in cfg_ch:
                continue
            # parse times
            start1 = datetime.fromisoformat(s1['start'])
            end1 = datetime.fromisoformat(s1['end']) if s1.get('end') else now
            start2 = datetime.fromisoformat(s2['start'])
            end2 = datetime.fromisoformat(s2['end']) if s2.get('end') else now
            latest_start = max(start1, start2)
            earliest_end = min(end1, end2)
            if earliest_end > latest_start:
                return True
    return False

# --- Events & Tasks ---

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID)) if GUILD_ID else await tree.sync()
        print('Commands synced')
    except Exception as e:
        print(f'Sync error: {e}')
    auto_post.start()

@bot.event
async def on_voice_state_update(member, before, after):
    user_id = str(member.id)
    now = datetime.now(timezone.utc).isoformat()
    vchans = config.get("voice_channels", [])
    # joined monitored
    if after.channel and after.channel.id in vchans and (not before.channel or before.channel.id not in vchans):
        # record last join
        voice_log[user_id] = now
        save_json(VOICE_LOG_FILE, voice_log)
        # start session
        voice_sessions.setdefault(user_id, []).append({
            'channel_id': after.channel.id,
            'start': now,
            'end': None
        })
        save_json(VOICE_SESSIONS_FILE, voice_sessions)
    # left monitored
    if before.channel and before.channel.id in vchans and (not after.channel or after.channel.id not in vchans):
        # end session
        sessions = voice_sessions.get(user_id, [])
        for s in reversed(sessions):
            if s['channel_id'] == before.channel.id and s.get('end') is None:
                s['end'] = now
                break
        save_json(VOICE_SESSIONS_FILE, voice_sessions)

# Confirmation View for vote=1
class ConfirmView(discord.ui.View):
    def __init__(self, target_id, rater_id):
        super().__init__(timeout=60)
        self.target_id = target_id
        self.rater_id = rater_id

        self.add_item(discord.ui.Button(label="Confirm 1", style=discord.ButtonStyle.danger,
                                        custom_id=f"confirm_vote:{target_id}:{rater_id}:1"))
        self.add_item(discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary,
                                        custom_id=f"cancel_vote:{target_id}:{rater_id}"))

    @discord.ui.button(label="", style=discord.ButtonStyle.blurple, custom_id="unused", disabled=True)
    async def dummy(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type.name != 'component':
        return
    data = interaction.data or {}
    cid = data.get('custom_id', '')
    parts = cid.split(":")
    # Vote button clicked
    if parts[0] == 'rate':
        _, target_id, score = parts
        rater_id = str(interaction.user.id)
        # self-vote check
        if rater_id == target_id:
            return await interaction.response.send_message("🚫 You cannot vote for yourself.", ephemeral=True)
        # confirm if score==1
        if score == '1':
            view = ConfirmView(target_id, rater_id)
            return await interaction.response.send_message(
                "⚠️ You're about to give a score of 1. Are you sure?", view=view, ephemeral=True
            )
        # process direct vote
        return await process_vote(interaction, target_id, rater_id, int(score))
    # Confirmed 1
    if parts[0] == 'confirm_vote':
        _, target_id, rater_id, score = parts
        # ensure only original rater
        if str(interaction.user.id) != rater_id:
            return await interaction.response.send_message("🚫 Not your confirmation.", ephemeral=True)
        return await process_vote(interaction, target_id, rater_id, int(score))
    # Cancel
    if parts[0] == 'cancel_vote':
        _, target_id, rater_id = parts
        if str(interaction.user.id) != rater_id:
            return await interaction.response.send_message("🚫 Not your cancellation.", ephemeral=True)
        return await interaction.response.send_message("❌ Vote cancelled.", ephemeral=True)

async def process_vote(interaction: discord.Interaction, target_id: str, rater_id: str, score: int):
    # eligibility
    if not is_eligible(rater_id, target_id):
        return await interaction.response.send_message(
            "🚫 You did not share a monitored voice channel with this player.", ephemeral=True
        )
    # record
    ts = datetime.now(timezone.utc).isoformat()
    ratings.setdefault(target_id, {})[rater_id] = {'score': score, 'timestamp': ts}
    save_json(RATINGS_FILE, ratings)
    # log in votes channel
    vc = config.get('votes_channel')
    if vc:
        ch = bot.get_channel(vc)
        if ch:
            await ch.send(f"🗳️ {interaction.user.display_name} rated "
                          f"<@{target_id}>: {score} (at {ts})")
    # notify admins if thresholds
    scores = [r['score'] for r in ratings[target_id].values()]
    cnt = len(scores)
    avg = sum(scores)/cnt if cnt else 0.0
    warn_ch = bot.get_channel(config.get('warnings_channel')) if config.get('warnings_channel') else None
    user_notifs = notified.setdefault(target_id, {})
    # low
    if cnt >= 5 and avg < 2.5 and not user_notifs.get('low'):
        if warn_ch:
            await warn_ch.send(
                f"⚠️ **Alert:** <@{target_id}> has an average rating of {avg:.2f} "
                f"based on {cnt} votes."
            )
        user_notifs['low'] = True
        save_json(NOTIFIED_FILE, notified)
    # recovered
    if user_notifs.get('low') and avg >= 2.5 and not user_notifs.get('recovered'):
        if warn_ch:
            await warn_ch.send(
                f"✅ **Update:** <@{target_id}>'s average rating has recovered to {avg:.2f}."
            )
        user_notifs['recovered'] = True
        save_json(NOTIFIED_FILE, notified)
    # ack
    await interaction.response.send_message("✅ Your vote has been recorded.", ephemeral=True)

# --- Slash Commands ---

@tree.command(name="setratingschannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_ratings_channel(interaction: discord.Interaction):
    config['ratings_channel'] = interaction.channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Ratings channel set.", ephemeral=True)

@tree.command(name="setwarningschannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_warnings_channel(interaction: discord.Interaction):
    config['warnings_channel'] = interaction.channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Warnings channel set.", ephemeral=True)

@tree.command(name="setleaderboardchannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    config['leaderboard_channel'] = interaction.channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Leaderboard channel set.", ephemeral=True)

@tree.command(name="setvoteschannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_votes_channel(interaction: discord.Interaction):
    config['votes_channel'] = interaction.channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message("✅ Votes log channel set.", ephemeral=True)

@tree.command(name="addvoicechannel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="Voice channel to monitor")
async def add_voice_channel(interaction: discord.Interaction, channel: discord.VoiceChannel):
    vc_list = config.setdefault('voice_channels', [])
    if channel.id in vc_list:
        return await interaction.response.send_message("⚠️ Channel already monitored.", ephemeral=True)
    vc_list.append(channel.id)
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"✅ Now monitoring voice channel: {channel.name}", ephemeral=True)

@tree.command(name="removevoicechannel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="Voice channel to stop monitoring")
async def remove_voice_channel(interaction: discord.Interaction, channel: discord.VoiceChannel):
    vc_list = config.get('voice_channels', [])
    if channel.id not in vc_list:
        return await interaction.response.send_message("⚠️ Channel not monitored.", ephemeral=True)
    vc_list.remove(channel.id)
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"✅ Stopped monitoring: {channel.name}", ephemeral=True)

@tree.command(name="listvoicechannels")
@app_commands.checks.has_permissions(administrator=True)
async def list_voice_channels(interaction: discord.Interaction):
    vc_list = config.get('voice_channels', [])
    if not vc_list:
        return await interaction.response.send_message("ℹ️ No voice channels monitored.", ephemeral=True)
    names = []
    for cid in vc_list:
        ch = bot.get_channel(cid)
        if ch:
            names.append(ch.name)
    await interaction.response.send_message(
        f"🎙️ Monitored channels: {', '.join(names)}", ephemeral=True
    )

@tree.command(name="myratings")
async def my_ratings(interaction: discord.Interaction):
    member_id = str(interaction.user.id)
    user_rats = ratings.get(member_id, {})
    if not user_rats:
        return await interaction.response.send_message("ℹ️ No ratings available.", ephemeral=True)
    # sort by timestamp desc
    entries = sorted(user_rats.values(), key=lambda x: x['timestamp'], reverse=True)[:10]
    scores = [str(e['score']) for e in entries]
    await interaction.response.send_message(
        f"📊 Your last ratings: {', '.join(scores)}", ephemeral=True
    )

@tree.command(name="showratings")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(player="Player to view sent ratings for")
async def show_ratings(interaction: discord.Interaction, player: discord.Member):
    rater_id = str(player.id)
    sent = []
    for tgt, raters in ratings.items():
        if rater_id in raters:
            sent.append(raters[rater_id])
    if not sent:
        return await interaction.response.send_message(
            f"ℹ️ {player.display_name} has not sent any ratings.", ephemeral=True
        )
    entries = sorted(sent, key=lambda x: x['timestamp'], reverse=True)[:10]
    lines = [f"{e['score']} (at {e['timestamp']})" for e in entries]
    await interaction.response.send_message(
        f"📤 Ratings sent by {player.display_name}:\n" + "\n".join(lines),
        ephemeral=True
    )

@tree.command(name="sync")
@app_commands.checks.has_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction):
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    await interaction.response.send_message("✅ Commands synced.", ephemeral=True)

@tasks.loop(minutes=30)
async def auto_post():
    try:
        # sleep 00:00-12:00 UK
        uk = datetime.now(pytz_timezone("Europe/London"))
        if 0 <= uk.hour < 12:
            return
        # prune logs
        prune_voice_log()
        prune_voice_sessions()
        # ratings channel
        rc = config.get('ratings_channel')
        if rc:
            ch = bot.get_channel(rc)
            if ch:
                # delete old prompts
                async for m in ch.history(limit=100):
                    if m.author == bot.user and m.components:
                        await m.delete()
                # post for each active user
                now = datetime.now(timezone.utc)
                for uid, ts in voice_log.items():
                    joined = datetime.fromisoformat(ts)
                    if now - joined > timedelta(hours=2):
                        continue
                    member = ch.guild.get_member(int(uid))
                    if member:
                        view = discord.ui.View()
                        for i in range(1,6):
                            view.add_item(discord.ui.Button(
                                label=str(i), style=discord.ButtonStyle.primary,
                                custom_id=f"rate:{uid}:{i}"
                            ))
                        await ch.send(f"Rate {member.display_name}", view=view)
        # leaderboard
        await generate_leaderboard()
    except Exception as e:
        print(f"[ERROR] auto_post: {e}")

async def generate_leaderboard():
    lc = config.get('leaderboard_channel')
    if not lc:
        return
    ch = bot.get_channel(lc)
    if not ch:
        return
    # clear old
    async for m in ch.history(limit=20):
        if m.author == bot.user and m.embeds:
            await m.delete()
            break
    # compute last 24h leaderboard
    now = datetime.now(timezone.utc)
    scores = {}
    for tgt, raters in ratings.items():
        for r in raters.values():
            ts = datetime.fromisoformat(r['timestamp'])
            if now - ts <= timedelta(hours=24):
                scores.setdefault(tgt, []).append(r['score'])
    # build embed
    if not scores:
        embed = discord.Embed(title="🏆 Leaderboard (24h)", description="No ratings.", color=0x888888)
    else:
        board = []
        for uid, scs in scores.items():
            avg = sum(scs)/len(scs)
            member = ch.guild.get_member(int(uid))
            if member:
                board.append((member.display_name, avg))
        board.sort(key=lambda x: x[1], reverse=True)
        lines = [f"**{n}**: {v:.2f}" for n,v in board]
        embed = discord.Embed(title="🏆 Leaderboard (24h)", description="\n".join(lines), color=0x00ff00)
    await ch.send(embed=embed)

# Run bot
bot.run(TOKEN)
