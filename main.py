import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pytz import timezone as pytz_timezone

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

# Timezone for UK
UK_TZ = pytz_timezone('Europe/London')

# File paths
VOICE_SESSIONS_FILE = 'voice_sessions.json'
RATINGS_FILE = 'ratings.json'
VOTES_LOG_CHANNEL_FILE = 'votes_log_channel.json'
CONFIG_FILE = 'config.json'

# Helper to load/save JSON
def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    else:
        return default


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# Load persistent data
voice_sessions = load_json(VOICE_SESSIONS_FILE, {})
ratings = load_json(RATINGS_FILE, {})
config = load_json(CONFIG_FILE, {})

# Bot setup
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

def guild_obj():
    return discord.Object(id=GUILD_ID) if GUILD_ID else None

# Sync slash commands on ready
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    if GUILD_ID:
        await bot.tree.sync(guild=guild_obj())
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    auto_post.start()

# Utility: check admin

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.manage_guild

# Admin commands to configure channels
def register_admin_command(name, description):
    def decorator(func):
        return bot.tree.command(
            name=name,
            description=description,
            guilds=[guild_obj()]
        )(app_commands.check(is_admin)(func))
    return decorator

@register_admin_command('set_ratings_channel', 'Set channel for rating posts')
async def set_ratings_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config['ratings_channel_id'] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f'Ratings channel set to {channel.mention}', ephemeral=True)

@register_admin_command('set_votes_log_channel', 'Set channel to log votes')
async def set_votes_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config['votes_log_channel_id'] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f'Votes log channel set to {channel.mention}', ephemeral=True)

@register_admin_command('set_warnings_channel', 'Set channel for warnings')
async def set_warnings_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config['warnings_channel_id'] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f'Warnings channel set to {channel.mention}', ephemeral=True)

@register_admin_command('set_leaderboard_channel', 'Set channel for leaderboard')
async def set_leaderboard_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config['leaderboard_channel_id'] = channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f'Leaderboard channel set to {channel.mention}', ephemeral=True)

# Voice session tracking
@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.now(UK_TZ).isoformat()
    sessions = voice_sessions.setdefault(str(member.id), [])
    if not before.channel and after.channel:
        sessions.append({'join': now, 'leave': None, 'channel': after.channel.id})
    elif before.channel and not after.channel:
        for s in reversed(sessions):
            if s['leave'] is None and s['channel'] == before.channel.id:
                s['leave'] = now
                break
    save_json(VOICE_SESSIONS_FILE, voice_sessions)

# Helper to collect active players in last 2h
def get_active_players():
    cutoff = datetime.now(UK_TZ) - timedelta(hours=2)
    active = set()
    for uid, sessions in voice_sessions.items():
        for s in sessions:
            join = datetime.fromisoformat(s['join'])
            leave = datetime.fromisoformat(s['leave']) if s['leave'] else datetime.now(UK_TZ)
            if join <= datetime.now(UK_TZ) and leave >= cutoff:
                active.add(int(uid))
                break
    return active

# Voting UI
class VoteView(discord.ui.View):
    def __init__(self, target_id):
        super().__init__(timeout=None)
        self.target_id = target_id

    @discord.ui.button(label='1', style=discord.ButtonStyle.danger, custom_id=lambda view: f'vote_1_{view.target_id}')
    async def vote1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ConfirmModal(self.target_id, 1))

    @discord.ui.button(label='2', style=discord.ButtonStyle.primary, custom_id=lambda view: f'vote_2_{view.target_id}')
    async def vote2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.target_id, 2)

    @discord.ui.button(label='3', style=discord.ButtonStyle.primary, custom_id=lambda view: f'vote_3_{view.target_id}')
    async def vote3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.target_id, 3)

    @discord.ui.button(label='4', style=discord.ButtonStyle.primary, custom_id=lambda view: f'vote_4_{view.target_id}')
    async def vote4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.target_id, 4)

    @discord.ui.button(label='5', style=discord.ButtonStyle.success, custom_id=lambda view: f'vote_5_{view.target_id}')
    async def vote5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_vote(interaction, self.target_id, 5)

class ConfirmModal(discord.ui.Modal, title='Confirm Rating'):
    def __init__(self, target_id, score):
        super().__init__()
        self.target_id = target_id
        self.score = score
        self.add_item(discord.ui.InputText(label='Type CONFIRM to proceed', placeholder='CONFIRM'))

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.data['components'][0]['components'][0]['value'].upper() == 'CONFIRM':
            await handle_vote(interaction, self.target_id, self.score)
        else:
            await interaction.response.send_message('Rating cancelled.', ephemeral=True)

async def handle_vote(interaction, target_id, score):
    voter = interaction.user.id
    if voter == target_id:
        return await interaction.response.send_message('You cannot vote for yourself.', ephemeral=True)
    # TODO: check shared sessions before allowing vote
    user_ratings = ratings.setdefault(str(target_id), [])
    user_ratings = [r for r in user_ratings if r['voter'] != voter]
    user_ratings.append({'voter': voter, 'score': score, 'time': datetime.now(UK_TZ).isoformat()})
    ratings[str(target_id)] = user_ratings
    save_json(RATINGS_FILE, ratings)
    if config.get('votes_log_channel_id'):
        ch = bot.get_channel(config['votes_log_channel_id'])
        if ch:
            await ch.send(f'<@{voter}> voted {score} for <@{target_id}>')
    await interaction.response.send_message(f'Your vote of {score} has been recorded.', ephemeral=True)

# Scheduled task
@tasks.loop(minutes=30)
async def auto_post():
    now = datetime.now(UK_TZ)
    if now.hour < 12:
        return
    active = get_active_players()
    for uid in list(ratings.keys()):
        if int(uid) not in active:
            ratings.pop(uid)
    save_json(RATINGS_FILE, ratings)
    if config.get('ratings_channel_id'):
        ch = bot.get_channel(config['ratings_channel_id'])
        if ch:
            await ch.send('Current players: ' + ', '.join(str(uid) for uid in active))
            for uid in active:
                view = VoteView(uid)
                await ch.send(f'Rate <@{uid}>', view=view)

# User commands
@bot.tree.command(name='myratings', description='Show your last 10 received ratings', guilds=[guild_obj()])
async def myratings(interaction: discord.Interaction):
    user_ratings = ratings.get(str(interaction.user.id), [])[-10:]
    if not user_ratings:
        return await interaction.response.send_message('No ratings available.', ephemeral=True)
    scores = [r['score'] for r in user_ratings]
    await interaction.response.send_message('Your last ratings: ' + ', '.join(str(s) for s in scores), ephemeral=True)

@bot.tree.command(name='showratings', description='Show your last 10 votes', guilds=[guild_obj()])
async def showratings(interaction: discord.Interaction):
    sent = []
    for recs in ratings.values():
        for r in recs:
            if r['voter'] == interaction.user.id:
                sent.append(r['score'])
    if not sent:
        return await interaction.response.send_message('No ratings sent.', ephemeral=True)
    await interaction.response.send_message('Your votes: ' + ', '.join(str(s) for s in sent[-10:]), ephemeral=True)

# Run bot
bot.run(TOKEN)
