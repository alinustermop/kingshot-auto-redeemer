import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import constants
from main import KingshotBot
from datetime import datetime, time, timezone

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

ks_bot = KingshotBot()

# --- CUSTOM CHECKS ---

async def is_bot_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)

# --- INTERACTIVE VIEW ---

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
    # Runs the redemption cycle automatically every 24 hours
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle)
    await broadcast_stats(stats) 

@daily_redemption_task.before_loop
async def before_daily_redemption():
    await bot.wait_until_ready()

# --- HELPER FUNCTIONS ---

async def broadcast_stats(stats):
    if not stats:
        return

    embed = discord.Embed(
        title="✅ Redemption Cycle Finished!", 
        description="Check your in-game mail for rewards.", 
        color=0x00ff00
    )
    embed.add_field(name="Total Players", value=str(stats['total_players']), inline=True)
    embed.add_field(name="Skipped (Full)", value=str(stats['skipped_full']), inline=True)
    embed.add_field(name="Dropped (Errors)", value=str(stats['skipped_error']), inline=True)
    
    if stats['distribution']:
        dist_text = "\n".join([
            f"• **{num}** player(s) redeemed **{count}** code(s)" 
            for count, num in sorted(stats['distribution'].items(), reverse=True)
        ])
        embed.add_field(name="Success Distribution", value=dist_text, inline=False)
    else:
        embed.add_field(name="Status", value="No new codes were redeemed for anyone.", inline=False)

    if stats['failed_players']:
        embed.add_field(name="Failed Players", value=", ".join(stats['failed_players']), inline=False)

    channel_ids = ks_bot.db.get_all_target_channels()
    for cid in channel_ids:
        channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                logging.getLogger("BOT").warning(f"Permission denied to send messages in channel {cid}")
            except Exception as e:
                logging.getLogger("BOT").error(f"Error broadcasting to channel {cid}: {e}")

# --- BOT EVENTS ---

@bot.event
async def on_ready():
    await bot.tree.sync() 
    print(f"Logged in as {bot.user}")
    print("Bot is ready. Scheduling is currently: OFF")

# --- SLASH COMMANDS ---

@bot.tree.command(name="help", description="Show all available commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Kingshot Bot Commands",
        description="Here is a list of everything I can do:",
        color=0x66ccff
    )
    commands_text = (
            "**/find [id]**: Search for a player and check if they are in the list\n"
            "**/add [id]**: Add a new player to the auto-redeem list\n"
            "**/delete [id]**: Remove a player from the list\n"
            "**/history [id]**: See which codes a player has already used\n"
            "**/stats**: Show bot statistics and last 24h activity\n"
            "**/next**: See when the next auto-redemption cycle starts\n"
            "**/ping**: Check connection latency\n"
            "**/redeem_for [id]**: Redeem all active codes for a specific player ID\n"
            "**/redeem_all**: Trigger a manual sync cycle (Owner only)\n"
            "**/set_channel**: Set this channel for redemption reports (Admins only)\n"
            "**/unset_channel**: Stop reports for this server (Admins only)\n"
            "**/list_players**: Show all registered players (Owner only)\n"
            "**/list_channels**: List all registered servers/channels (Owner only)\n"
            "**/schedule_start**: Start the 24h automatic loop (Owner only)\n"
            "**/schedule_stop**: Stop the 24h automatic loop (Owner only)\n"
            "**/logs**: View recent bot activity logs (Owner only)"
        )
    embed.add_field(name="Available Commands", value=commands_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: `{latency}ms`", ephemeral=True)

@bot.command()
async def sync(ctx):
    if await bot.is_owner(ctx.author):
        await ctx.send("Attempting to sync slash commands with Discord...")
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"Success! Synced {len(synced)} slash commands.")
        except Exception as e:
            await ctx.send(f"Sync failed: {e}")
    else:
        await ctx.send("You do not have permission to sync commands.")

@bot.tree.command(name="schedule_start", description="Start the 24-hour automatic redemption loop (Owner only)")
@app_commands.check(is_bot_owner)
async def schedule_start(interaction: discord.Interaction):
    if not daily_redemption_task.is_running():
        daily_redemption_task.start()
        await interaction.response.send_message("✅ 24-hour automatic redemption loop has been **STARTED**.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ The schedule is already running.", ephemeral=True)

@bot.tree.command(name="schedule_stop", description="Stop the 24-hour automatic redemption loop (Owner only)")
@app_commands.check(is_bot_owner)
async def schedule_stop(interaction: discord.Interaction):
    if daily_redemption_task.is_running():
        daily_redemption_task.cancel()
        await interaction.response.send_message("🛑 24-hour automatic redemption loop has been **STOPPED**.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ The schedule is not currently running.", ephemeral=True)

@bot.tree.command(name="find", description="Search for a player by ID")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID to look up")
async def find(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    
    player_data = ks_bot.api.get_player_info(fid)
    if player_data:
        existing_player = ks_bot.db.get_player(fid)
        if existing_player and existing_player['nickname'] != player_data['nickname']:
            ks_bot.db.update_player_nickname(fid, player_data['nickname'])

        embed = discord.Embed(title="Player Found:", color=0x66ccff)
        embed.set_thumbnail(url=player_data.get('avatar_image', ''))
        embed.add_field(name="Nickname", value=player_data.get('nickname', 'Unknown'), inline=True)
        embed.add_field(name="Level", value=player_data.get('rendered_level', 'N/A'), inline=True)
        embed.add_field(name="Server", value=player_data.get('kid', 'N/A'), inline=True)
        
        if existing_player:
            embed.description = "Btw, this player is already in the list for redeeming codes."
        else: 
            embed.description = f"Btw, this player is NOT in the list yet. Use `/add {fid}` to add them."
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"Could not find a player with ID '{fid}'.", ephemeral=True)

@bot.tree.command(name="add", description="Add a player to the auto-redeem list")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID to add")
async def add(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)

    if ks_bot.db.player_exists(fid):
        await interaction.followup.send(f"Player with ID {fid} is already in the list.", ephemeral=True)
        return

    player_data = ks_bot.api.get_player_info(fid)
    if not player_data:
        await interaction.followup.send(f"Could not find a player with ID {fid}.", ephemeral=True)
        return

    embed = discord.Embed(title="Confirm Add Player", color=discord.Color.blue())
    embed.add_field(name="Nickname", value=player_data.get('nickname', 'Unknown'), inline=True)
    embed.add_field(name="Level", value=player_data.get('rendered_level', 'N/A'), inline=True)
    
    view = ConfirmView()
    message = await interaction.followup.send(embed=embed, view=view, wait=True, ephemeral=True)
    await view.wait()

    if view.value is True:
        ks_bot.db._save_player_to_db(player_data)
        await message.edit(content=f"Player **{player_data['nickname']}** has been added.", embed=None, view=None)
    else:
        await message.edit(content="Action cancelled.", embed=None, view=None)

@bot.tree.command(name="delete", description="Remove a player from the auto-redeem list")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID to delete")
async def delete(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    player_record = ks_bot.db.get_player(fid)
    
    if not player_record:
        await interaction.followup.send(f"Player ID {fid} is not in the list.", ephemeral=True)
        return

    view = ConfirmView()
    embed = discord.Embed(title="Confirm Delete", description=f"Delete **{player_record['nickname']}**?", color=discord.Color.red())
    message = await interaction.followup.send(embed=embed, view=view, wait=True, ephemeral=True)
    await view.wait()

    if view.value is True:
        ks_bot.db._delete_player(fid)
        await message.edit(content=f"Deleted **{player_record['nickname']}** ({fid}).", embed=None, view=None)
    else:
        await message.edit(content="Action cancelled.", embed=None, view=None)

@bot.tree.command(name="list_players", description="Show all registered players")
@app_commands.check(is_bot_owner)
async def list_players(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    players = ks_bot.db.show_all_players()
    if not players:
        await interaction.followup.send("The list is empty.", ephemeral=True)
        return

    description = "\n".join([f"• **{p['nickname']}** (ID: `{p['fid']}`)" for p in players])
    embed = discord.Embed(title="Registered Players", description=description, color=0x66ccff)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="stats", description="View bot statistics")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    count = ks_bot.db.get_player_count()
    all_codes = ks_bot.db.get_redeemed_codes()
    session_info = ks_bot.db.get_latest_redemption_info()
    
    embed = discord.Embed(title="System Statistics", color=0x66ccff)
    embed.add_field(name="Registered Players", value=str(count), inline=True)
    embed.add_field(name="Total Codes Redeemed", value=str(len(all_codes)), inline=True)
    
    if session_info:
        codes_str = ", ".join(session_info['codes'])
        embed.add_field(name="Latest Activity (Last 24h)", value=f"**Time:** {session_info['timestamp']} UTC\n**Codes:** {codes_str}", inline=False)
    
    embed.add_field(name="All-Time Codes", value=", ".join(all_codes) if all_codes else "None", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="redeem_all", description="Force manual redemption (Owner Only)")
@app_commands.check(is_bot_owner)
async def redeem_all(interaction: discord.Interaction):
    await interaction.response.send_message("🚀 Starting manual cycle. Summary will be posted to all registered channels.", ephemeral=True)
    
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle)
    
    await broadcast_stats(stats)

@bot.tree.command(name="logs", description="Check recent bot logs (Owner Only)")
@app_commands.check(is_bot_owner)
async def logs(interaction: discord.Interaction, lines: int = 10):
    await interaction.response.defer(ephemeral=True)
    try:
        with open(constants.LOG_FILE, "r", encoding="utf-8") as f:
            message = "".join(f.readlines()[-lines:])
            await interaction.followup.send(f"```text\n{message[-1900:]}\n```", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(name="history", description="Check player history")
@app_commands.rename(fid="id")
async def history(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    player = ks_bot.db.get_player(fid)
    if not player:
        await interaction.followup.send(f"ID {fid} not found.", ephemeral=True)
        return

    codes = ks_bot.db.check_codes_redeemed(fid)
    embed = discord.Embed(title=f"History: {player['nickname']}", description=f"ID: `{fid}`", color=0x66ccff)
    embed.add_field(name="Redeemed Codes", value=", ".join(codes) if codes else "None", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="next", description="Time until next auto-sync")
async def next_cycle(interaction: discord.Interaction):
    if daily_redemption_task.is_running():
        next_it = daily_redemption_task.next_iteration
        remaining = next_it - datetime.now(timezone.utc) if next_it else "Calculating..."
        await interaction.response.send_message(f"Next cycle in: `{str(remaining).split('.')[0]}`", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Task not running.", ephemeral=True)

@bot.tree.command(name="redeem_for", description="Redeem all active codes for a specific player ID")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The player ID to redeem codes for")
async def redeem_for(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    
    response = await asyncio.to_thread(ks_bot.redeem_for_player, fid)

    if response["status"] == "error":
        await interaction.followup.send(f"Error: {response['msg']}", ephemeral=True)
        return

    nickname = response["nickname"]
    new_redeemed = response["redeemed_new"]
    total = response["total_active"]
    details = "\n".join(response["details"])

    report = (
        f"**Redemption Report for {nickname} ({fid})**\n"
        f"Processed {total} active codes.\n"
        f"Newly redeemed: {new_redeemed}\n\n"
        f"**Details:**\n"
        f"```\n{details}\n```"
    )

    await interaction.followup.send(report, ephemeral=True)

@bot.tree.command(name="set_channel", description="Set this channel for redemption reports")
@app_commands.checks.has_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction):
    ks_bot.db._set_guild_channel(interaction.guild_id, interaction.channel_id)
    await interaction.response.send_message(
        f"✅ This channel has been registered for redemption reports.", 
        ephemeral=True
    )

@bot.tree.command(name="unset_channel", description="Stop sending redemption reports to this server")
@app_commands.checks.has_permissions(administrator=True)
async def unset_channel(interaction: discord.Interaction):
    success = ks_bot.db._delete_guild_channel(interaction.guild_id)
    if success:
        await interaction.response.send_message("✅ This server has been unregistered from redemption reports.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ This server was not registered in the list.", ephemeral=True)

@bot.tree.command(name="list_channels", description="Show all registered Discord servers and channels (Owner Only)")
@app_commands.check(is_bot_owner)
async def list_channels(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    registrations = ks_bot.db.get_all_registrations()
    if not registrations:
        await interaction.followup.send("The registration list is empty.", ephemeral=True)
        return

    description = ""
    for reg in registrations:
        guild = bot.get_guild(reg['guild_id'])
        channel = bot.get_channel(reg['target_channel_id'])
        
        guild_name = guild.name if guild else f"Unknown Guild ({reg['guild_id']})"
        channel_name = channel.mention if channel else f"Unknown Channel ({reg['target_channel_id']})"
        
        description += f"• **{guild_name}**: {channel_name}\n"

    embed = discord.Embed(title="Registered Report Channels", description=description, color=0x66ccff)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Admin permissions required.", ephemeral=True)
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ Authorized users only.", ephemeral=True)
    else:
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Unexpected error.", ephemeral=True)

if __name__ == "__main__":
    bot.run(constants.DISCORD_TOKEN)