import discord
from discord.ext import commands
from .utils import load_config, save_config

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setvoicechannels(self, ctx, *channel_ids):
        config = load_config()
        config['voice_channels'] = [int(cid) for cid in channel_ids]
        save_config(config)
        await ctx.send(f"Voice channels set: {channel_ids}")

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setratingschannel(self, ctx, channel_id: int):
        config = load_config()
        config['ratings_channel'] = channel_id
        save_config(config)
        await ctx.send(f"Ratings channel set: {channel_id}")

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setleaderboardchannel(self, ctx, channel_id: int):
        config = load_config()
        config['leaderboard_channel'] = channel_id
        save_config(config)
        await ctx.send(f"Leaderboard channel set: {channel_id}")

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setalertschannel(self, ctx, channel_id: int):
        config = load_config()
        config['alerts_channel'] = channel_id
        save_config(config)
        await ctx.send(f"Alerts channel set: {channel_id}")

    @commands.has_permissions(administrator=True)
    @commands.command()
    async def setvoteschannel(self, ctx, channel_id: int):
        config = load_config()
        config['votes_channel'] = channel_id
        save_config(config)
        await ctx.send(f"Votes channel set: {channel_id}")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
