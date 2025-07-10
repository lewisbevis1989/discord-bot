import discord
from discord.ext import commands
from discord import app_commands
from .utils import load_config, save_config
import os

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setvoicechannels", description="Set voice channels to monitor")
    @app_commands.describe(channels="Select one or more voice channels")
    async def setvoicechannels(self, interaction: discord.Interaction, channels: list[discord.VoiceChannel]):
        config = load_config()
        config["voice_channels"] = [ch.id for ch in channels]
        save_config(config)
        await interaction.response.send_message(f"✅ Voice channels set: {', '.join(ch.name for ch in channels)}", ephemeral=True)

    @app_commands.command(name="setratingschannel", description="Set the channel where ratings are posted")
    async def setratingschannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config["ratings_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Ratings channel set: {channel.name}", ephemeral=True)

    @app_commands.command(name="setleaderboardchannel", description="Set the channel for the leaderboard")
    async def setleaderboardchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config["leaderboard_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Leaderboard channel set: {channel.name}", ephemeral=True)

    @app_commands.command(name="setalertschannel", description="Set the channel for alerts")
    async def setalertschannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config["alerts_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Alerts channel set: {channel.name}", ephemeral=True)

    @app_commands.command(name="setvoteschannel", description="Set the log channel for votes")
    async def setvoteschannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        config["votes_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Votes channel set: {channel.name}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
    bot.tree.copy_global_to(guild=discord.Object(id=int(os.getenv("GUILD_ID"))))
    await bot.tree.sync(guild=discord.Object(id=int(os.getenv("GUILD_ID"))))
