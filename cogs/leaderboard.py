import discord
from discord.ext import commands
from discord import app_commands
from .utils import load_votes

class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="myratings")
    async def myratings(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        votes = load_votes()
        scores = []
        for voter_dict in votes.values():
            if user_id in voter_dict:
                entry = voter_dict[user_id]
                scores.append((entry['score'], entry['timestamp']))
        scores = sorted(scores, key=lambda x: x[1], reverse=True)[:10]
        if not scores:
            await interaction.response.send_message("No ratings available.", ephemeral=True)
        else:
            msg = "\n".join([f"{score} ({timestamp})" for score, timestamp in scores])
            await interaction.response.send_message(f"Your last 10 ratings:\n{msg}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
