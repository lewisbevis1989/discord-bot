import discord
from discord.ext import commands
from discord import app_commands
import json
import os

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "ratings_data.json"
CHANNEL_CONFIG_FILE = "channel_config.json"

# Load existing rating data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        ratings_data = json.load(f)
else:
    ratings_data = {}

# Load channel configuration
if os.path.exists(CHANNEL_CONFIG_FILE):
    with open(CHANNEL_CONFIG_FILE, "r") as f:
        channel_config = json.load(f)
else:
    channel_config = {
        "rating_channel": None,
        "leaderboard_channel": None
    }

# Save functions
def save_ratings():
    with open(DATA_FILE, "w") as f:
        json.dump(ratings_data, f)

def save_channel_config():
    with open(CHANNEL_CONFIG_FILE, "w") as f:
        json.dump(channel_config, f)

# --- Slash Commands ---
@bot.tree.command(name="setratingchannel", description="Set the channel for player ratings")
@app_commands.checks.has_permissions(administrator=True)
async def set_rating_channel(interaction: discord.Interaction):
    channel_config["rating_channel"] = interaction.channel.id
    save_channel_config()
    await interaction.response.send_message("✅ Rating channel has been set.", ephemeral=True)

@bot.tree.command(name="setleaderboardchannel", description="Set the channel for leaderboard posts")
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    channel_config["leaderboard_channel"] = interaction.channel.id
    save_channel_config()
    await interaction.response.send_message("✅ Leaderboard channel has been set.", ephemeral=True)

@bot.tree.command(name="postratings", description="Post rating buttons in the rating channel")
async def post_ratings(interaction: discord.Interaction):
    channel_id = channel_config.get("rating_channel")
    if not channel_id:
        await interaction.response.send_message("⚠️ Rating channel not set.", ephemeral=True)
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        await interaction.response.send_message("⚠️ Could not find the rating channel.", ephemeral=True)
        return

    # Replace with player names and Discord user IDs
    players = [
        {"name": "Player A", "id": 111111111111111111},
        {"name": "Player B", "id": 222222222222222222},
        {"name": "Player C", "id": 333333333333333333}
    ]

    for player in players:
        view = RatingView(player_id=str(player["id"]), player_name=player["name"])
        await channel.send(f"Rate **{player['name']}**:", view=view)

    await interaction.response.send_message("✅ Rating posts have been posted.", ephemeral=True)

# --- Rating View ---
class RatingView(discord.ui.View):
    def __init__(self, player_id, player_name):
        super().__init__(timeout=None)
        self.player_id = player_id
        self.player_name = player_name
        for i in range(1, 6):
            self.add_item(RatingButton(i, self.player_id))

class RatingButton(discord.ui.Button):
    def __init__(self, rating, player_id):
        super().__init__(label=str(rating), style=discord.ButtonStyle.primary)
        self.rating = rating
        self.player_id = player_id

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)

        if self.player_id not in ratings_data:
            ratings_data[self.player_id] = []

        # Save anonymous rating
        ratings_data[self.player_id].append(self.rating)
        save_ratings()

        await interaction.response.send_message("✅ Your rating has been submitted anonymously.", ephemeral=True)

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Run bot
import dotenv
dotenv.load_dotenv()
bot.run(os.getenv("BOT_TOKEN"))
