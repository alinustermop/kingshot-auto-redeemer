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
    if await interaction.client.is_owner(interaction.user):
        return True
    return False

# --- INTERACTIVE VIEW ---

class ConfirmView(discord.ui.View):
    def __init__(self, timeout=30):
        super().__init__(timeout=timeout)
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        try:
            await interaction.response.edit_message(view=None) 
        except discord.errors.NotFound:
            pass 

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        try:
            await interaction.response.edit_message(view=None)
        except discord.errors.NotFound:
            pass

class PlayerPagination(discord.ui.View):
    def __init__(self, players, per_page=15):
        super().__init__(timeout=60)
        self.players = players
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(players) - 1) // per_page + 1

    def create_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_players = self.players[start:end]

        description = "\n".join([f"• **{p['nickname']}** (ID: `{p['fid']}`) Server: *{p['kid']}*" for p in page_players])
        embed = discord.Embed(
            title=f"Registered Players ({len(self.players)} total)", 
            description=description, 
            color=0x66ccff
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages}")
        return embed

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.gray)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("You are on the first page.", ephemeral=True)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.gray)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("You are on the last page.", ephemeral=True)

# --- BACKGROUND TASKS ---

@tasks.loop(hours=24)
async def daily_redemption_task():
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle)
    await broadcast_stats(stats) 

@daily_redemption_task.before_loop
async def before_daily_redemption():
    await bot.wait_until_ready()

@tasks.loop(hours=8)
async def code_discovery_task():
    new_codes = await asyncio.to_thread(ks_bot.check_for_new_codes)
    if new_codes:
        await broadcast_new_codes(new_codes)

@code_discovery_task.before_loop
async def before_code_discovery():
    await bot.wait_until_ready()

# --- HELPER FUNCTIONS ---

async def broadcast_new_codes(new_codes):
    channel_ids = ks_bot.db.get_all_target_channels()
    if not channel_ids:
        return

    embed = discord.Embed(
        title="🎁 New Gift Code Discovered!",
        description=f"Found **{len(new_codes)}** new code(s):\n" + "\n".join([f"• `{c}`" for c in new_codes]),
        color=0xffd700
    )
    embed.set_footer(text="These will be automatically redeemed in the next 24h cycle.")

    for cid in channel_ids:
        channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logging.getLogger("BOT").error(f"Error broadcasting new code alert to {cid}: {e}")

async def broadcast_stats(stats):
    if not stats:
        return

    channel_ids = ks_bot.db.get_all_target_channels()
    if not channel_ids:
        return

    # 1. Announce New Gift Codes if found
    new_codes = stats.get('new_codes', [])
    if new_codes:
        await broadcast_new_codes(new_codes)

    # 2. Announce Summary Report
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
    embed = discord.Embed(color=0x66ccff)
    commands_text = (
            "**/find [id]**: Check if a player ID is registered in database\n"
            "**/add [id] [server_id] [nickname]**: Add a new player to the database\n"
            "**/delete [id]**: Remove a player from the database\n"
            "**/update_player [id] (new_nickname) (new_server_id)**: Update player details\n"
            "**/active_codes**: View all active gift codes\n"
            "**/history [id]**: See redeemed codes for a player\n"
            "**/stats**: Show bot statistics\n"
            "**/next**: See when the next auto-redemption cycle starts\n"
            "**/servers_stats**: Show player distribution across servers\n"
            "**/redeem_for [id]**: Redeem all active codes for a specific player ID\n"
            "**/set_channel**: Set this channel for redemption reports *(Admins)*\n"
            "**/unset_channel**: Stop reports for this server *(Admins)*\n"
        )
    embed.add_field(name="Available Commands", value=commands_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: `{latency}ms`", ephemeral=True)

@bot.command()
async def sync(ctx, spec: str = None):
    """
    Usage:
      !sync          -> Instant sync to the current server (Guild)
      !sync target   -> Instant sync to TEST_GUILD_ID defined in constants.py
      !sync global   -> Sync globally across all servers (Takes up to 1h to propagate)
    """
    if not await bot.is_owner(ctx.author):
        await ctx.send("❌ You do not have permission to sync commands.")
        return

    # Send temporary status message and keep reference to it
    status_msg = await ctx.send("⏳ Processing command sync...")

    try:
        if spec == "global":
            # Global sync (standard)
            synced = await bot.tree.sync()
            await status_msg.edit(content=f"🌐 **Global Sync Complete!** Synced {len(synced)} slash commands. *(Note: Global updates can take up to 1 hour to display in Discord)*")

        elif spec == "target" and hasattr(constants, "TEST_GUILD_ID") and constants.TEST_GUILD_ID:
            # Sync directly to the target server ID specified in constants.py
            guild = discord.Object(id=constants.TEST_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            await status_msg.edit(content=f"⚡ **Instant Target Sync Complete!** Synced {len(synced)} slash commands to Guild ID `{constants.TEST_GUILD_ID}`.")

        elif ctx.guild:
            # Default behavior: Instant sync to the current server where the command was run
            guild = ctx.guild
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            await status_msg.edit(content=f"⚡ **Instant Local Sync Complete!** Synced {len(synced)} slash commands to **{guild.name}**.")

        else:
            await status_msg.edit(content="❌ Cannot sync locally outside of a server. Use `!sync global` or `!sync target` in DMs.")

    except Exception as e:
        await status_msg.edit(content=f"❌ Sync failed: {e}")
        logging.getLogger("BOT").error(f"Sync error: {e}")

@bot.command()
async def clear_guild_sync(ctx):
    """Clears guild-specific commands so only global commands appear."""
    if not await bot.is_owner(ctx.author):
        return

    status_msg = await ctx.send("🧹 Clearing local guild commands...")
    try:
        # Clear commands registered specifically to this server
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        await status_msg.edit(content="✅ **Guild commands cleared!** Restart your Discord client (`Ctrl + R`) to update the menu.")
    except Exception as e:
        await status_msg.edit(content=f"❌ Failed to clear guild commands: {e}")

@bot.tree.command(name="active_codes", description="Show all active gift codes currently available")
async def active_codes(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    codes = await asyncio.to_thread(ks_bot.api.get_active_codes)
    
    if not codes:
        await interaction.followup.send("No active gift codes found at the moment.", ephemeral=True)
        return

    code_list_str = "\n".join([f"• `{c}`" for c in codes])
    embed = discord.Embed(
        title="🎁 Active Gift Codes",
        description=f"Currently active codes ({len(codes)} total):\n\n{code_list_str}",
        color=0x66ccff
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="update_player", description="Update a registered player's nickname or server (Kingdom) ID")
@app_commands.rename(fid="id", nickname="new_nickname", kid="new_server_id")
@app_commands.describe(
    fid="The Player ID to update",
    nickname="New in-game nickname (Optional)",
    kid="New Kingdom / Server ID (Optional)"
)
async def update_player(
    interaction: discord.Interaction, 
    fid: str, 
    nickname: str = None, 
    kid: int = None
):
    await interaction.response.defer(ephemeral=True)

    # 1. Verify player exists in local database
    existing_player = ks_bot.db.get_player(fid)
    if not existing_player:
        await interaction.followup.send(
            f"❌ Player ID `{fid}` was not found in the database. Use `/add` to register them first.", 
            ephemeral=True
        )
        return

    # 2. Check if at least one field was provided
    if nickname is None and kid is None:
        await interaction.followup.send(
            "⚠️ Please provide at least a new nickname or a new server ID to update.", 
            ephemeral=True
        )
        return

    # 3. Determine new values (fallback to current values if omitted)
    updated_nickname = nickname if nickname is not None else existing_player['nickname']
    updated_kid = kid if kid is not None else existing_player['kid']

    # 4. Save updates to SQLite
    ks_bot.db._update_player_info(fid, updated_nickname, updated_kid)

    # 5. Send confirmation embed
    embed = discord.Embed(
        title="✅ Player Info Updated", 
        color=discord.Color.green()
    )
    embed.add_field(name="Player ID", value=f"`{fid}`", inline=True)
    embed.add_field(
        name="Nickname", 
        value=f"{existing_player['nickname']} ➔ **{updated_nickname}**", 
        inline=False
    )
    embed.add_field(
        name="Server (Kingdom)", 
        value=f"{existing_player['kid']} ➔ **{updated_kid}**", 
        inline=False
    )

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="schedule_start", description="Start the 24-hour automatic redemption loop (Owner only)")
@app_commands.check(is_bot_owner)
async def schedule_start(interaction: discord.Interaction):
    started = []
    if not daily_redemption_task.is_running():
        daily_redemption_task.start()
        started.append("24h Redemption Loop")
    if not code_discovery_task.is_running():
        code_discovery_task.start()
        started.append("8h Code Tracking Loop")
        
    if started:
        await interaction.response.send_message(f"✅ Started: **{', '.join(started)}**.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ Both schedules are already running.", ephemeral=True)

@bot.tree.command(name="schedule_stop", description="Stop the 24-hour automatic redemption loop (Owner only)")
@app_commands.check(is_bot_owner)
async def schedule_stop(interaction: discord.Interaction):
    stopped = []
    if daily_redemption_task.is_running():
        daily_redemption_task.cancel()
        stopped.append("24h Redemption Loop")
    if code_discovery_task.is_running():
        code_discovery_task.cancel()
        stopped.append("8h Code Tracking Loop")
        
    if stopped:
        await interaction.response.send_message(f"🛑 Stopped: **{', '.join(stopped)}**.", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ No schedules are currently running.", ephemeral=True)

@bot.tree.command(name="find", description="Search for a player in the database by ID")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID to look up")
async def find(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    
    player_data = ks_bot.db.get_player(fid)
    if player_data:
        embed = discord.Embed(title="Player Found in Database:", color=0x66ccff)
        embed.add_field(name="Nickname", value=player_data['nickname'], inline=True)
        embed.add_field(name="Player ID", value=str(player_data['fid']), inline=True)
        embed.add_field(name="Server (Kingdom)", value=str(player_data['kid']), inline=True)
        embed.description = "This player is in the auto-redeem list."
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"Player ID `{fid}` is NOT in the list yet. Use `/add` to add them.", ephemeral=True)

@bot.tree.command(name="add", description="Add a player to the auto-redeem list")
@app_commands.rename(fid="id", kid="server_id", nickname="nickname")
@app_commands.describe(
    fid="The Player ID to add",
    kid="The Kingdom / Server ID (e.g., 718)",
    nickname="Player's in-game nickname"
)
async def add(interaction: discord.Interaction, fid: str, kid: int, nickname: str):
    await interaction.response.defer(ephemeral=True)

    if ks_bot.db.player_exists(fid):
        await interaction.followup.send(f"Player with ID `{fid}` is already in the list.", ephemeral=True)
        return

    player_data = {"fid": fid, "nickname": nickname, "kid": kid}

    embed = discord.Embed(title="Confirm Add Player", color=discord.Color.blue())
    embed.add_field(name="Nickname", value=nickname, inline=True)
    embed.add_field(name="Player ID", value=fid, inline=True)
    embed.add_field(name="Server (Kingdom)", value=str(kid), inline=True)
    
    view = ConfirmView()
    message = await interaction.followup.send(embed=embed, view=view, wait=True, ephemeral=True)
    await view.wait()

    if view.value is True:
        ks_bot.db._save_player_to_db(player_data)
        await message.edit(content=f"Player **{nickname}** (ID: `{fid}`, Server: `{kid}`) has been added.", embed=None, view=None)
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
    embed = discord.Embed(title="Confirm Delete", description=f"Delete **{player_record['nickname']}** ({fid})?", color=discord.Color.red())
    message = await interaction.followup.send(embed=embed, view=view, wait=True, ephemeral=True)
    await view.wait()

    if view.value is True:
        ks_bot.db._delete_player(fid)
        await message.edit(content=f"Deleted **{player_record['nickname']}** ({fid}).", embed=None, view=None)
    else:
        await message.edit(content="Action cancelled.", embed=None, view=None)

@bot.tree.command(name="list_players", description="Show all registered players with pagination")
@app_commands.check(is_bot_owner)
async def list_registered_players(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    players = ks_bot.db.show_all_players()
    if not players:
        await interaction.followup.send("The list is empty.", ephemeral=True)
        return
    view = PlayerPagination(players, per_page=20)
    await interaction.followup.send(embed=view.create_embed(), view=view, ephemeral=True)

@bot.tree.command(name="stats", description="View bot statistics")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    players_count = ks_bot.db.get_player_count()
    kingdom_count = ks_bot.db.get_kingdom_count()
    all_codes = ks_bot.db.get_redeemed_codes()
    session_info = ks_bot.db.get_latest_redemption_info()
    
    embed = discord.Embed(title="System Statistics", color=0x66ccff)
    embed.add_field(name="Registered Players", value=str(players_count), inline=True)
    embed.add_field(name="Kingdoms", value=str(kingdom_count), inline=True)
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

@bot.tree.command(name="servers_stats", description="Show player distribution across servers")
async def servers_stats(interaction: discord.Interaction):
    stats = ks_bot.db.get_servers_stats()
    total = ks_bot.db.get_player_count()
    
    if not stats:
        await interaction.response.send_message("No player data available.", ephemeral=True)
        return

    description = ""
    for row in stats:
        server_id = row['kid'] if row['kid'] is not None else "Unknown"
        description += f"**Server {server_id}**: {row['player_count']} player(s)\n"
    
    description += f"\n**Total players**: {total} players"
    
    embed = discord.Embed(title="📊 Server Distribution", description=description, color=0x66ccff)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="list_server_players", description="List all players in a specific server (Owner only)")
@app_commands.describe(kid="The Kingdom/Server ID to filter by")
@app_commands.check(is_bot_owner)
async def list_server_players(interaction: discord.Interaction, kid: int):
    players = ks_bot.db.get_players_by_server(kid)
    
    if not players:
        await interaction.response.send_message(f"No players found for Server `{kid}`.", ephemeral=True)
        return

    view = PlayerPagination(players)
    embed = view.create_embed()
    embed.title = f"Players in Server {kid}"
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You do not have the required Admin permissions."
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ Authorized users only (Bot Owner check failed)."
    else:
        message = f"❌ Unexpected error: {error}"
        logging.getLogger("BOT").error(f"Command Error: {error}")

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

if __name__ == "__main__":
    bot.run(constants.DISCORD_TOKEN)