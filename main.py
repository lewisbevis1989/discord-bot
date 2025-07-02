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


def is_recent(member_id):
    now = datetime.now(timezone.utc)
    joined = voice_log.get(str(member_id))
    if joined:
        joined_time = datetime.fromisoformat(joined)
        return now - joined_time <= timedelta(hours=24)
    return False


@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID)) if GUILD_ID else await tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(f"Sync error: {e}")
    auto_post.start()


@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and not before.channel:
        voice_log[str(member.id)] = datetime.now(timezone.utc).isoformat()
        save_json(log_file, voice_log)


@tree.command(name="setratingschannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_ratings_channel(interaction: discord.Interaction):
    config["ratings_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Ratings channel set.", ephemeral=True)


@tree.command(name="setwarningschannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_warnings_channel(interaction: discord.Interaction):
    config["warnings_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Warnings log channel set.", ephemeral=True)


@tree.command(name="setleaderboardchannel")
@app_commands.checks.has_permissions(administrator=True)
async def set_leaderboard_channel(interaction: discord.Interaction):
    config["leaderboard_channel"] = interaction.channel.id
    save_json(config_file, config)
    await interaction.response.send_message("✅ Leaderboard channel set.", ephemeral=True)


@tree.command(name="postratings")
async def post_ratings(interaction: discord.Interaction):
    if not config.get("ratings_channel"):
        await interaction.response.send_message("❌ Ratings channel not set.", ephemeral=True)
        return

    channel = bot.get_channel(config["ratings_channel"])
    sorted_users = sorted(voice_log.items(), key=lambda x: x[1])
    now = datetime.now(timezone.utc)

    for user_id, timestamp in sorted_users:
        time_diff = now - datetime.fromisoformat(timestamp)
        if time_diff > timedelta(hours=24):
            continue

        member = interaction.guild.get_member(int(user_id))
        if member:
            view = discord.ui.View()
            for i in range(1, 6):
                view.add_item(discord.ui.Button(label=str(i), style=discord.ButtonStyle.primary, custom_id=f"rate:{user_id}:{i}"))
            await channel.send(f"Rate {member.mention}", view=view)

    await interaction.response.send_message("✅ Rating prompts posted.", ephemeral=True)


@tree.command(name="postleaderboard")
async def post_leaderboard(interaction: discord.Interaction):
    await generate_leaderboard()
    await interaction.response.send_message("✅ Leaderboard posted.", ephemeral=True)


@tree.command(name="sync")
@app_commands.checks.has_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction):
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    await interaction.response.send_message("✅ Commands synced.", ephemeral=True)


class RateButtonHandler(discord.ui.View):
    @discord.ui.button(label="1", style=discord.ButtonStyle.primary, custom_id="rate_button_1")
    async def button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # Handled via on_interaction

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type.name == 'component':
        custom_id = interaction.data['custom_id']
        if custom_id.startswith("rate:"):
            _, user_id, score = custom_id.split(":")
            score = int(score)
            rater_id = str(interaction.user.id)

            ratings.setdefault(user_id, {})[rater_id] = score
            save_json(ratings_file, ratings)

            await interaction.response.send_message("✅ Your vote has been saved anonymously.", ephemeral=True)

            # DM warning or encouragement
            rated_scores = ratings.get(user_id, {}).values()
            avg = sum(rated_scores) / len(rated_scores)

            recipient = bot.get_user(int(user_id))
            if recipient:
                has_warned = notified.get(user_id, {})

                if avg <= 2.0 and len(rated_scores) >= 2 and not has_warned.get("warned"):
                    try:
                        await recipient.send("👋 Just a heads-up! Your current average rating is a bit low. Focus on quick, simple passes and good positioning. If you're unsure, hop into voice chat and ask for help—we're all here to improve together!")
                        if config.get("warnings_channel"):
                            logchan = bot.get_channel(config["warnings_channel"])
                            await logchan.send(f"⚠️ {recipient.name} received a low rating warning (avg: {avg:.2f})")
                        notified.setdefault(user_id, {})["warned"] = True
                        save_json(notified_file, notified)
                    except:
                        pass

                elif avg > 2.5 and has_warned.get("warned") and not has_warned.get("encouraged"):
                    try:
                        await recipient.send("✅ Great job! Your rating has gone up. Keep playing smart with quick passes and stay involved. Reach out if you want help pushing even higher!")
                        if config.get("warnings_channel"):
                            logchan = bot.get_channel(config["warnings_channel"])
                            await logchan.send(f"✅ {recipient.name} recovered to avg: {avg:.2f} — encouragement sent.")
                        notified[user_id]["encouraged"] = True
                        save_json(notified_file, notified)
                    except:
                        pass


async def generate_leaderboard():
    if not config.get("leaderboard_channel"):
        return

    channel = bot.get_channel(config["leaderboard_channel"])
    old = None
    async for msg in channel.history(limit=10):
        if msg.author == bot.user and msg.embeds:
            old = msg
            break

    leaderboard = []
    for user_id, scores in ratings.items():
        if not is_recent(user_id):
            continue
        avg_score = sum(scores.values()) / len(scores)
        member = channel.guild.get_member(int(user_id))
        if member:
            leaderboard.append((member.display_name, avg_score))

    if not leaderboard:
        embed = discord.Embed(title="🏆 Leaderboard", description="No ratings yet.", color=0x888888)
    else:
        leaderboard.sort(key=lambda x: x[1], reverse=True)
        lines = [f"**{name}**: {avg:.2f}" for name, avg in leaderboard]
        embed = discord.Embed(title="🏆 Leaderboard (last 24h)", description="\n".join(lines), color=0x00ff00)

    if old:
        await old.delete()
    await channel.send(embed=embed)


@tasks.loop(minutes=30)
async def auto_post():
    now = datetime.now(timezone.utc)
    if now.hour < 0 or now.hour >= 10:
        return  # Sleep hours: midnight to 10am UTC
    ctx = type('obj', (object,), {'guild': bot.get_guild(GUILD_ID)})
    await post_ratings(ctx)
    await generate_leaderboard()

bot.run(TOKEN)
