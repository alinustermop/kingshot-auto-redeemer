import discord
from discord.ext import commands, tasks
import asyncio
import constants
import logging
from main import KingshotBot
from datetime import datetime, timezone

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

ks_bot = KingshotBot()

# --- LOGGING SETUP ---

class DiscordNameFilter(logging.Filter):
    def filter(self, record):
        if record.name.startswith("discord"):
            record.name = "BOT"
        return True


# --- INTERACTIVE VIEW FOR ADDING PLAYERS ---

class ConfirmView(discord.ui.View):
    def __init__(self, timeout=30):
        super().__init__(timeout=timeout)
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


# --- BACKGROUND TASKS ---

@tasks.loop(hours=24)
async def daily_redemption_task():
    # Runs the redemption cycle automatically in the background every 24 hours.
    await asyncio.to_thread(ks_bot.run_redemption_cycle)

@daily_redemption_task.before_loop
async def before_daily_redemption():
    await bot.wait_until_ready()

# --- BOT COMMANDS ---

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Bot is ready.")
    
    if not daily_redemption_task.is_running():
        daily_redemption_task.start()

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: `{latency}ms`")

@bot.command()
async def find(ctx, fid: str):
    await ctx.send(f"Looking up ID `{fid}`...")
    
    player_data = ks_bot.api.get_player_info(fid)
    if player_data:
        embed = discord.Embed(title="Player Found:", color=0x66ccff)
        embed.set_thumbnail(url=player_data['avatar_image'])
        embed.add_field(name="Nickname", value=player_data['nickname'], inline=True)
        embed.add_field(name="Level", value=player_data['rendered_level'], inline=True)
        embed.add_field(name="Server", value=player_data['kid'], inline=True)
        if ks_bot.db.player_exists(fid):
                embed.description = "Btw, this player is already in the list for redeeming codes."
        else: embed.description = f"Btw, this player is NOT in the list for redeeming codes yet. You can add them with `!add {fid}`"
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"Could not find a player with ID '{fid}'. Please, try again.")


@bot.command()
async def add(ctx, fid: str):
    if ks_bot.db.player_exists(fid):
        await ctx.send(f"Player with ID {fid} is already in the list.")
        return

    await ctx.send(f"Searching for player ID {fid}...")
    player_data = ks_bot.api.get_player_info(fid)

    if not player_data:
        await ctx.send(f"Could not find a player with ID {fid}.")
        return

    embed = discord.Embed(
        title="Confirm Add Player",
        description=f"Would you like to add this player in the list for redeeming codes?",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=player_data['avatar_image'])
    embed.add_field(name="Nickname", value=player_data.get('nickname', 'Unknown'), inline=True)
    embed.add_field(name="Level", value=player_data.get('rendered_level', 'N/A'), inline=True)
    embed.add_field(name="Server", value=player_data.get('kid', 'N/A'), inline=True)
    
    view = ConfirmView()
    message = await ctx.send(embed=embed, view=view)

    await view.wait()

    if view.value is True:
        ks_bot.db._save_player_to_db(player_data)
        await message.edit(content=f"Player {player_data['nickname']} has been added.", embed=None, view=None)
    else:
        await message.edit(content="Action cancelled.", embed=None, view=None)

@bot.command()
async def delete(ctx, fid: str):
    player_record = ks_bot.db.get_player(fid)
    
    if not player_record:
        await ctx.send(f"Player ID {fid} is not in the list.")
        return

    name = player_record['nickname']

    embed = discord.Embed(
        title="Confirm Delete Player",
        description=f"Are you sure you want to delete {name} ({fid}) from the list for redeeming codes?",
        color=discord.Color.red()
    )
    
    view = ConfirmView()
    message = await ctx.send(embed=embed, view=view)

    await view.wait()

    if view.value is True:
        success = ks_bot.db._delete_player(fid)
        if success:
            await message.edit(content=f"Player {name} ({fid}) has been deleted.", embed=None, view=None)
        else:
            await message.edit(content="Failed to delete player due to a database error.", embed=None, view=None)
    else:
        await message.edit(content="Action cancelled.", embed=None, view=None)

@bot.command()
@commands.has_permissions(administrator=True)
async def list(ctx):
    players = ks_bot.db.show_all_players()
    if not players:
        await ctx.send("The player list is empty.")
        return

    description = ""
    for p in players:
        description += f"• **{p['nickname']}** (ID: `{p['fid']}`)\n"
    
    embed = discord.Embed(
        title="Registered Players", 
        description=description, 
        color=0x66ccff
    )
    await ctx.send(embed=embed)


@bot.command()
async def stats(ctx):
    count = ks_bot.db.get_player_count()
    all_codes = ks_bot.db.get_redeemed_codes()
    session_info = ks_bot.db.get_latest_redemption_info()
    
    embed = discord.Embed(title="System Statistics", color=0x66ccff)
    embed.add_field(name="Total Players Registered:", value=str(count), inline=True)
    embed.add_field(name="Total Codes Ever Redeemed:", value=str(len(all_codes)), inline=True)
    
    if session_info:
        codes_str = ", ".join(session_info['codes'])
        embed.add_field(
            name="Latest Activity (Last 24h):", 
            value=f"**Last Sync:** {session_info['timestamp']} UTC\n**Codes:** {codes_str}", 
            inline=False
        )
    else:
        embed.add_field(name="Latest Activity:", value="No codes redeemed in the last 24 hours.", inline=False)

    embed.add_field(name="All-Time Redeemed Codes:", value=", ".join(all_codes) if all_codes else "None", inline=False)
    embed.set_footer(text="Status: Operational")
    await ctx.send(embed=embed)


@bot.command()
@commands.is_owner()
async def redeemAll(ctx):
    await ctx.send("Starting a manual redemption cycle for all players. This may take a while...")
    await asyncio.to_thread(ks_bot.run_redemption_cycle)
    await ctx.send("Redemption cycle finished! Check your mail in the game for rewards.")

@bot.command()
@commands.is_owner()
async def logs(ctx, lines: int = 10):
    try:
        with open(constants.LOG_FILE, "r", encoding="utf-8") as f:
            log_lines = f.readlines()
            last_lines = log_lines[-lines:]
            
            message = "".join(last_lines)
            if len(message) > 1900: # Discord limit is 2000
                message = "... (truncated) ...\n" + message[-1900:]
            
            await ctx.send(f"```text\n{message}\n```")
    except Exception as e:
        await ctx.send(f"Error reading logs: {e}")

@bot.command()
async def history(ctx, fid: str):
    player = ks_bot.db.get_player(fid)
    if not player:
        await ctx.send(f"Player ID {fid} not found in the database.")
        return

    codes = ks_bot.db.check_codes_redeemed(fid)
    embed = discord.Embed(
        title=f"History: {player['nickname']}", 
        description=f"ID: `{fid}`", 
        color=0x66ccff
    )
    if codes:
        embed.add_field(name="Redeemed Codes", value=", ".join(codes), inline=False)
    else:
        embed.add_field(name="Redeemed Codes", value="No codes logged yet.", inline=False)
        
    await ctx.send(embed=embed)

@bot.command()
async def next(ctx):
    if daily_redemption_task.is_running():
        next_it = daily_redemption_task.next_iteration
        if next_it:
            now = datetime.now(timezone.utc)
            remaining = next_it - now
            await ctx.send(f"Daily task is running. Next cycle in: `{str(remaining).split('.')[0]}`")
        else:
            await ctx.send("Daily task is running (scheduling next iteration...).")
    else:
        await ctx.send("Warning: Daily task is NOT running.")


if __name__ == "__main__":
    bot.run(constants.DISCORD_TOKEN)