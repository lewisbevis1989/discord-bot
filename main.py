import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = 'ratings_data.json'
RATING_CHANNEL_FILE = 'rating_channel.json'

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w') as f:
        json.dump({}, f)

if not os.path.exists(RATING_CHANNEL_FILE):
    with open(RATING_CHANNEL_FILE, 'w') as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

def load_rating_channel():
    with open(RATING_CHANNEL_FILE, 'r') as f:
        return json.load(f)

def save_rating_channel(channel_data):
    with open(RATING_CHANNEL_FILE, 'w') as f:
        json.dump(channel_data, f)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands.')
    except Exception as e:
        print(e)

@bot.tree.command(name="setratingchannel", description="Set the channel where ratings will be posted")
@app_commands.checks.has_permissions(administrator=True)
async def set_rating_channel(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    channel_data = load_rating_channel()
    channel_data[str(interaction.guild_id)] = channel_id
    save_rating_channel(channel_data)
    await interaction.response.send_message("✅ Rating channel set.", ephemeral=True)

@bot.tree.command(name="postratings", description="Post rating buttons for players")
async def post_ratings(interaction: discord.Interaction):
    channel_data = load_rating_channel()
    guild_id = str(interaction.guild_id)
    if guild_id not in channel_data:
        await interaction.response.send_message("❌ Rating channel not set.", ephemeral=True)
        return

    channel = bot.get_channel(channel_data[guild_id])
    if not channel:
        await interaction.response.send_message("❌ Could not find the rating channel.", ephemeral=True)
        return

    # Example player list - replace with dynamic voice chat fetch if needed
    players = [member async for member in interaction.guild.fetch_members(limit=None) if not member.bot]

    for player in players:
        view = RatingView(player.id)
        await channel.send(f"**📝 Rate Player: {player.display_name}**", view=view)

    await interaction.response.send_message("✅ Rating posts have been posted.", ephemeral=True)

class RatingView(discord.ui.View):
    def __init__(self, player_id):
        super().__init__(timeout=None)
        self.player_id = player_id
        for i in range(1, 6):
            self.add_item(RatingButton(label=str(i), rating=i, player_id=player_id))

class RatingButton(discord.ui.Button):
    def __init__(self, label, rating, player_id):
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self.rating = rating
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        player_id = str(self.player_id)
        data = load_data()

        now = datetime.now(timezone.utc).isoformat()

        if player_id not in data:
            data[player_id] = []

        # Remove previous vote by this user for this player if exists
        data[player_id] = [entry for entry in data[player_id] if entry['voter_id'] != user_id]

        # Save new rating
        data[player_id].append({"voter_id": user_id, "rating": self.rating, "timestamp": now})
        save_data(data)

        await interaction.response.send_message(f"✅ Your rating of {self.rating} for <@{player_id}> has been recorded anonymously.", ephemeral=True)

bot.run(os.getenv("BOT_TOKEN"))
