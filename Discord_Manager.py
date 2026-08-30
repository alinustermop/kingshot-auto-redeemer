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

async def is_admin_or_owner(interaction: discord.Interaction) -> bool:
    # 1. If they are the bot owner, always allow bypass
    if await interaction.client.is_owner(interaction.user):
        return True
    
    # 2. Otherwise, check if they have server administrator permissions
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
        
    return False

# --- INTERACTIVE MODALS & VIEWS ---

class FeedbackModal(discord.ui.Modal, title="Anonymous Feedback & Suggestions"):
    feedback_input = discord.ui.TextInput(
        label="Your Message, Suggestion, or Complaint",
        style=discord.TextStyle.paragraph,
        placeholder="Type your anonymous message here...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Thank you! Your anonymous message has been sent to the developer.", ephemeral=True)
        
        try:
            owner_id = getattr(constants, "DEVELOPER_DISCORD_ID", None)
            if owner_id:
                owner = await bot.fetch_user(owner_id)
                if owner:
                    embed = discord.Embed(
                        title="📥 New Anonymous Feedback",
                        description=self.feedback_input.value,
                        color=0xffa500
                    )
                    embed.set_footer(text=f"Sent from server: {interaction.guild.name if interaction.guild else 'Direct Message'}")
                    await owner.send(embed=embed)
        except Exception as e:
            logging.getLogger("BOT").error(f"Failed to send anonymous feedback DM: {e}")

class KingdomStarsModal(discord.ui.Modal, title="Gift Kingdom Stars Schedule"):
    date_input = discord.ui.TextInput(
        label="Date (UTC)",
        style=discord.TextStyle.short,
        placeholder="e.g., March 15 or 2026-03-15",
        required=True,
        max_length=50
    )
    time_input = discord.ui.TextInput(
        label="Time (UTC)",
        style=discord.TextStyle.short,
        placeholder="e.g., 14:00 UTC",
        required=True,
        max_length=50
    )
    gifter_input = discord.ui.TextInput(
        label="Your In-Game Name / Alias (Optional)",
        style=discord.TextStyle.short,
        placeholder="e.g., JohnDoe (leave blank if anonymous)",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        date_val = self.date_input.value
        time_val = self.time_input.value
        gifter_val = self.gifter_input.value.strip() if self.gifter_input.value else "Anonymous"

        await interaction.response.send_message("⭐ Thank you! Your Kingdom Stars schedule has been sent to the developer.", ephemeral=True)

        try:
            owner_id = getattr(constants, "DEVELOPER_DISCORD_ID", None)
            if owner_id:
                owner = await bot.fetch_user(owner_id)
                if owner:
                    embed = discord.Embed(
                        title="⭐ New Kingdom Stars Gift!",
                        description="Someone wants to gift you stars. Please login and send verification code in WC.",
                        color=0xffd700
                    )
                    embed.add_field(name="Date", value=date_val, inline=True)
                    embed.add_field(name="Time", value=time_val, inline=True)
                    embed.add_field(name="Gifter / Alias", value=gifter_val, inline=False)
                    embed.set_footer(text=f"Server: {interaction.guild.name if interaction.guild else 'Direct Message'}")
                    await owner.send(embed=embed)
        except Exception as e:
            logging.getLogger("BOT").error(f"Failed to send Kingdom Stars DM: {e}")

class SupportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💡 Send Anonymous Feedback", style=discord.ButtonStyle.primary)
    async def feedback_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal())

    @discord.ui.button(label="⭐ Gift Kingdom Stars", style=discord.ButtonStyle.success)
    async def stars_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(KingdomStarsModal())

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
        
        # Sorting logic: Starred first (0), Unstarred second (1), then by account type order
        def sort_key(p):
            is_starred = 0 if (p['is_starred'] if 'is_starred' in p.keys() else 0) else 1
            
            t = (p['account_type'].lower() if ('account_type' in p.keys() and p['account_type']) else "").strip()
            if t == "main": type_order = 1
            elif t == "alt": type_order = 2
            elif t == "farm": type_order = 3
            else: type_order = 4
            
            return (is_starred, type_order)

        self.players = sorted(players, key=sort_key)
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(self.players) - 1) // per_page + 1

    def create_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_players = self.players[start:end]

        description_lines = []
        for p in page_players:
            is_starred = p['is_starred'] if 'is_starred' in p.keys() else 0
            star_suffix = " ⭐" if is_starred else ""
            
            # Select icon based on account type
            t = (p['account_type'].lower() if ('account_type' in p.keys() and p['account_type']) else "").strip()
            if t == "main":
                type_icon = "👑"
            elif t == "alt":
                type_icon = "🛡️"
            elif t == "farm":
                type_icon = "🌾"
            else:
                type_icon = "📁"

            description_lines.append(f"• {type_icon} **{p['nickname']}**{star_suffix} — ID: `{p['fid']}` | Server: *{p['kid']}*")

        embed = discord.Embed(
            title=f"Registered Players ({len(self.players)} total)", 
            description="\n".join(description_lines), 
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

class HelpPagination(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.current_page = 0

    def create_embed(self):
        embed = discord.Embed(color=0x66ccff)
        if self.current_page == 0:
            embed.title = "🤖 Kingshot Bot Commands (Page 1/2: User Commands)"
            commands_text = (
                "**/find [id]**: Check if a player ID is registered in database\n"
                "**/find_by_name [name]**: Search players by nickname\n"
                "**/add [id] [server_id] [nickname] (type)**: Add a new player\n"
                "**/link [id]**: Link a player ID to your Discord account\n"
                "**/unlink [id]**: Unlink a player ID from your account\n"
                "**/my_accounts**: View all your linked Kingshot accounts\n"
                "**/redeem_for_me**: Redeem active codes for your linked accounts\n"
                "**/redeem_for [id]**: Redeem active codes for a specific player ID\n"
                "**/update_player [id] (nickname) (server_id) (type)**: Update player details\n"
                "**/delete [id]**: Remove a player from the database\n"
                "**/active_codes**: View all active gift codes\n"
                "**/history [id]**: See redeemed codes for a player\n"
                "**/support**: How to support the developer & send feedback\n"
                "**/feedback**: Send an anonymous suggestion or complaint\n"
                "**/gift_kingdom_stars**: Schedule a time for gifting Kingdom Stars\n"
            )
        else:
            embed.title = "🛠️ Kingshot Bot Commands (Page 2/2: Admins)"
            commands_text = (
                "**/stats**: Show bot statistics\n"
                "**/servers_stats**: Show player distribution across servers\n"
                "**/next**: See when the next auto-redemption cycle starts\n"
                "**/set_channel**: Set this channel for redemption reports *(Admins)*\n"
                "**/unset_channel**: Stop reports for this server *(Admins)*\n"
                "**/list_players**: Show all registered players *(Owner)*\n"
                "**/list_channels**: List all registered discord channels *(Owner)*\n"
                "**/list_server_players [kid]**: List all players in a specific server *(Owner)*\n"
            )
        embed.add_field(name="Available Commands", value=commands_text, inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1} of 2")
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
        if self.current_page < 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("You are on the last page.", ephemeral=True)

## TO TEST
class BroadcastModal(discord.ui.Modal, title="Broadcast Bot Update"):
    update_title = discord.ui.TextInput(
        label="Update Title",
        style=discord.TextStyle.short,
        placeholder="e.g., 🚀 Bot Update v1.2 Released!",
        required=True,
        max_length=256
    )
    
    update_message = discord.ui.TextInput(
        label="Update Message (Max ~2500 chars)",
        style=discord.TextStyle.paragraph,
        placeholder="Write your update notes here... What's new?",
        required=True,
        max_length=2500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        title = self.update_title.value
        message = self.update_message.value

        embed = discord.Embed(
            title=title,
            description=message,
            color=0x66ccff
        )
        embed.set_footer(text="📢 Kingshot Bot Official Update Announcement")

        # Fetch all registered channels across all servers
        channel_ids = ks_bot.db.get_all_target_channels()
        if not channel_ids:
            await interaction.followup.send("❌ No registered report channels found across any servers.", ephemeral=True)
            return

        success_count = 0
        fail_count = 0

        for cid in channel_ids:
            channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
            if channel:
                try:
                    await channel.send(embed=embed)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    logging.getLogger("BOT").error(f"Failed to broadcast update to channel {cid}: {e}")

        await interaction.followup.send(
            f"✅ Update broadcast sent successfully!\n"
            f"• Delivered to: **{success_count}** channel(s)\n"
            f"• Failed/No Access: **{fail_count}** channel(s)",
            ephemeral=True
        )

# --- BACKGROUND TASKS ---

@tasks.loop(hours=24)
async def daily_redemption_task():
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle)
    await broadcast_stats(stats) 

@daily_redemption_task.before_loop
async def before_daily_redemption():
    await bot.wait_until_ready()

@tasks.loop(hours=2)
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
    embed.set_footer(text="These will be automatically redeemed in the next redemption cycle.")

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
    is_starred = stats.get('starred_only', False)
    title_str = "⭐ Starred Redemption Cycle Finished!" if is_starred else "✅ Redemption Cycle Finished!"

    embed = discord.Embed(
        title=title_str, 
        description="Check your in-game mail for rewards.", 
        color=0x00ff00
    )
    embed.add_field(name="Total Players", value=str(stats['total_players']), inline=True)
    embed.add_field(name="Skipped (Full)", value=str(stats['skipped_full']), inline=True)
    embed.add_field(name="Already Claimed", value=str(stats.get('already_claimed', 0)), inline=True)
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
    view = HelpPagination()
    await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)

@bot.tree.command(name="feedback", description="Send an anonymous suggestion, review, or complaint to the developer")
async def feedback_command(interaction: discord.Interaction):
    await interaction.response.send_modal(FeedbackModal())

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: `{latency}ms`", ephemeral=True)

@bot.tree.command(name="support", description="How you can support the bot developer and send feedback")
async def support_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="☕ Support the Developer",
        description=(
            "Hey! Thanks for using the **Kingshot Auto-Redeemer** bot!\n\n"
            "This bot is developed and maintained in my free time to keep your accounts fueled with rewards daily.\n"
            "Also I am working on an extra bot to help our server community *wink*.\n\n"
            "If this tool saves you time and you'd like to support the hosting costs and future updates, you can check out:\n"
            f"• **Developer Discord**: Contact `{constants.DEVELOPER_NAME}`\n"
            "• **Feedback & Suggestions**: Drop ideas using the anonymous form below.\n"
            f"• **Direct help**: Send a little smth [here]({constants.JAR_LINK}) or `{constants.CARD_NUMBER}`!\n"
            "• **Gift Kingdom Stars**: Request me to be on the game at a certain time to give you Verification Code.\n\n"
            "Thank you so much for your help and patience! ❤️"
        ),
        color=0xffa500
    )
    view = SupportView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="gift_kingdom_stars", description="Schedule a time for gifting Kingdom Stars")
async def gift_kingdom_stars(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⭐ Gift Kingdom Stars",
        description=(
            "If you want, you can support me by sending [kingdom stars](https://store.centurygames.com/kingshot) anonymously.\n\n"
            "Set UTC time and date when I need to be online to send a Verification Code in the World Chat.\n"
            f"My in-game ID: `{constants.IN_GAME_ID}`\n\n"
            "Click the button below to submit your schedule!"
        ),
        color=0xffd700
    )
    
    class StarsView(discord.ui.View):
        @discord.ui.button(label="⭐ Submit Schedule", style=discord.ButtonStyle.success)
        async def open_modal(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
            await btn_interaction.response.send_modal(KingdomStarsModal())

    await interaction.response.send_message(embed=embed, view=StarsView(), ephemeral=True)

@bot.tree.command(name="broadcast_update", description="Broadcast an update message to all registered server channels (Owner Only)")
@app_commands.check(is_bot_owner)
async def broadcast_update(interaction: discord.Interaction):
    await interaction.response.send_modal(BroadcastModal())

@bot.tree.command(name="force_link", description="Forcefully link a player ID to a specific Discord user ID (Owner Only)")
@app_commands.rename(fid="player_id", user_id="discord_user_id")
@app_commands.describe(
    fid="The Kingshot Player ID (FID)",
    user_id="The Discord User ID to link the account to"
)
@app_commands.check(is_bot_owner)
async def force_link(interaction: discord.Interaction, fid: str, user_id: str):
    await interaction.response.defer(ephemeral=True)

    # 1. Validate player exists
    player = ks_bot.db.get_player(fid)
    if not player:
        await interaction.followup.send(f"❌ Player ID `{fid}` not found in the database.", ephemeral=True)
        return

    # 2. Validate discord user ID format (must be numeric)
    if not user_id.isdigit():
        await interaction.followup.send("❌ Discord User ID must be a valid number.", ephemeral=True)
        return

    # 3. Perform the link
    success = ks_bot.db.link_player_to_discord(fid, user_id)
    if success:
        await interaction.followup.send(
            f"🔗 Successfully force-linked **{player['nickname']}** (`{fid}`) to Discord User ID `<@{user_id}>` (`{user_id}`).",
            ephemeral=True
        )
    else:
        await interaction.followup.send("❌ Failed to link account due to a database error.", ephemeral=True)

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

@bot.tree.command(name="link", description="Link a Kingshot player ID to your Discord account")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID you want to link to your Discord account")
async def link_account(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)

    player = ks_bot.db.get_player(fid)
    if not player:
        await interaction.followup.send(
            f"❌ Player ID `{fid}` was not found in the database. Use `/add` to register them first.",
            ephemeral=True
        )
        return

    success = ks_bot.db.link_player_to_discord(fid, interaction.user.id)
    if success:
        await interaction.followup.send(
            f"🔗 Successfully linked **{player['nickname']}** (`{fid}`) to your Discord account!",
            ephemeral=True
        )
    else:
        await interaction.followup.send("❌ Failed to link account due to a database error.", ephemeral=True)

@bot.tree.command(name="unlink", description="Unlink a Kingshot player ID from your Discord account")
@app_commands.rename(fid="id")
@app_commands.describe(fid="The Player ID you want to unlink")
async def unlink_account(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)

    success = ks_bot.db.unlink_player_from_discord(fid, interaction.user.id)
    if success:
        await interaction.followup.send(f"🔓 Successfully unlinked player ID `{fid}` from your Discord account.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Could not unlink. Either ID `{fid}` wasn't linked to your account or doesn't exist.", ephemeral=True)

@bot.tree.command(name="my_accounts", description="View all Kingshot accounts linked to your Discord profile")
async def my_accounts(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    accounts = ks_bot.db.get_players_by_discord_id(interaction.user.id)
    if not accounts:
        await interaction.followup.send(
            "ℹ️ You have no linked accounts yet. Use `/link [id]` to connect your accounts!",
            ephemeral=True
        )
        return

    mains, alts, farms, unassigned = [], [], [], []
    for p in accounts:
        star_icon = "⭐ " if (p['is_starred'] if 'is_starred' in p.keys() else 0) else ""
        t = (p['account_type'].lower() if ('account_type' in p.keys() and p['account_type']) else "").strip()
        
        line = f"• {star_icon}**{p['nickname']}** — ID: `{p['fid']}` | Server: *{p['kid']}*"
        
        if t == "main":
            mains.append(line)
        elif t == "alt":
            alts.append(line)
        elif t == "farm":
            farms.append(line)
        else:
            unassigned.append(line)

    description_parts = []
    if mains:
        description_parts.append("👑 **Mains:**")
        description_parts.extend(mains)
    if alts:
        description_parts.append("\n🛡️ **Alts:**")
        description_parts.extend(alts)
    if farms:
        description_parts.append("\n🌾 **Farms:**")
        description_parts.extend(farms)
    if unassigned:
        description_parts.append("\n📁 **Other Accounts:**")
        description_parts.extend(unassigned)

    embed = discord.Embed(
        title=f"👤 Your Linked Accounts ({len(accounts)} total)",
        description="\n".join(description_parts),
        color=0x66ccff
    )
    embed.set_footer(text="Use /redeem_for_me to redeem codes for all of them at once!")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="redeem_for_me", description="Redeem active codes for all your linked Kingshot accounts")
async def redeem_for_me(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    accounts = ks_bot.db.get_players_by_discord_id(interaction.user.id)
    if not accounts:
        await interaction.followup.send(
            "❌ You have no linked accounts. Use `/link [id]` to link your accounts first!",
            ephemeral=True
        )
        return

    await interaction.followup.send(
        f"🚀 Starting redemption for **{len(accounts)}** linked account(s)... This may take a minute.",
        ephemeral=True
    )

    summary_lines = []
    for p in accounts:
        res = await asyncio.to_thread(ks_bot.redeem_for_player, str(p['fid']))
        if res["status"] == "success":
            summary_lines.append(f"• **{res['nickname']}** (`{p['fid']}`): Redeemed **{res['redeemed_new']}** new code(s)")
        else:
            summary_lines.append(f"• **{res['nickname']}** (`{p['fid']}`): ⚠️ {res['msg']}")

    embed = discord.Embed(
        title="🎁 Personal Redemption Complete",
        description="\n".join(summary_lines),
        color=0x00ff00
    )
    embed.set_footer(text="Check your in-game mail for rewards!")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="star", description="Mark a player account as Starred ⭐ (Owner Only)")
@app_commands.rename(fid="id")
@app_commands.check(is_bot_owner)
async def star_player(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    player = ks_bot.db.get_player(fid)
    if not player:
        await interaction.followup.send(f"❌ Player ID `{fid}` not found.", ephemeral=True)
        return

    success = ks_bot.db.toggle_star_player(fid, True)
    if success:
        await interaction.followup.send(f"⭐ **{player['nickname']}** (`{fid}`) is now a Starred Account.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Failed to update star status.", ephemeral=True)

@bot.tree.command(name="unstar", description="Remove Starred status from a player account (Owner Only)")
@app_commands.rename(fid="id")
@app_commands.check(is_bot_owner)
async def unstar_player(interaction: discord.Interaction, fid: str):
    await interaction.response.defer(ephemeral=True)
    player = ks_bot.db.get_player(fid)
    if not player:
        await interaction.followup.send(f"❌ Player ID `{fid}` not found.", ephemeral=True)
        return

    success = ks_bot.db.toggle_star_player(fid, False)
    if success:
        await interaction.followup.send(f"⚪ Removed Starred status from **{player['nickname']}** (`{fid}`).", ephemeral=True)
    else:
        await interaction.followup.send("❌ Failed to update star status.", ephemeral=True)

@bot.tree.command(name="redeem_starred", description="Trigger manual redemption for Starred accounts ONLY (Owner Only)")
@app_commands.check(is_bot_owner)
async def redeem_starred(interaction: discord.Interaction):
    starred_count = ks_bot.db.get_starred_count()
    if starred_count == 0:
        await interaction.response.send_message("❌ No starred accounts found. Use `/star [id]` to star accounts first.", ephemeral=True)
        return

    await interaction.response.send_message(f"⭐ Starting redemption cycle for **{starred_count}** Starred Account(s)...", ephemeral=True)
    
    # Run cycle for starred accounts only
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle, starred_only=True)
    if not stats:
        await interaction.followup.send("❌ Redemption cycle finished with no data returned.", ephemeral=True)
        return

    # Build private response embed
    embed = discord.Embed(
        title="⭐ Starred Accounts Redemption Summary", 
        description="Check in-game mail for rewards.", 
        color=0xffd700
    )
    embed.add_field(name="Total Starred", value=str(stats['total_players']), inline=True)
    embed.add_field(name="Skipped (DB Synced)", value=str(stats['skipped_full']), inline=True)
    embed.add_field(name="Already Claimed", value=str(stats.get('already_claimed', 0)), inline=True)
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

    await interaction.followup.send(embed=embed, ephemeral=True)

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

@bot.tree.command(name="update_player", description="Update a registered player's nickname, server ID, or account type")
@app_commands.rename(fid="id", nickname="new_nickname", kid="new_server_id", account_type="type")
@app_commands.describe(
    fid="The Player ID to update",
    nickname="New in-game nickname (Optional)",
    kid="New Kingdom / Server ID (Optional)",
    account_type="Account type (Main, Farm, Alt, or None to clear)"
)
@app_commands.choices(account_type=[
    app_commands.Choice(name="Main", value="main"),
    app_commands.Choice(name="Farm", value="farm"),
    app_commands.Choice(name="Alt", value="alt"),
    app_commands.Choice(name="None (Clear)", value="none"),
])
async def update_player(
    interaction: discord.Interaction, 
    fid: str, 
    nickname: str = None, 
    kid: int = None,
    account_type: app_commands.Choice[str] = None
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
    if nickname is None and kid is None and account_type is None:
        await interaction.followup.send(
            "⚠️ Please provide at least a new nickname, server ID, or account type to update.", 
            ephemeral=True
        )
        return

    # 3. Determine new values (fallback to current values if omitted)
    updated_nickname = nickname if nickname is not None else existing_player['nickname']
    updated_kid = kid if kid is not None else existing_player['kid']
    
    if account_type is not None:
        updated_type = None if account_type.value == "none" else account_type.value
    else:
        updated_type = existing_player['account_type']

    # 4. Save updates to SQLite
    ks_bot.db._update_player_info(fid, updated_nickname, updated_kid, updated_type)

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
    old_type_str = existing_player['account_type'].upper() if existing_player['account_type'] else "None"
    new_type_str = updated_type.upper() if updated_type else "None"
    embed.add_field(
        name="Account Type",
        value=f"{old_type_str} ➔ **{new_type_str}**",
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
        star_str = " ⭐ (Starred)" if player_data['is_starred'] else ""
        acc_type = f" `[{player_data['account_type'].upper()}]`" if player_data.get('account_type') else ""
        embed = discord.Embed(title="Player Found in Database:", color=0x66ccff)
        embed.add_field(name="Nickname", value=f"{player_data['nickname']}{star_str}{acc_type}", inline=True)
        embed.add_field(name="Player ID", value=str(player_data['fid']), inline=True)
        embed.add_field(name="Server (Kingdom)", value=str(player_data['kid']), inline=True)
        embed.description = "This player is in the auto-redeem list."
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"Player ID `{fid}` is NOT in the list yet. Use `/add` to add them.", ephemeral=True)

@bot.tree.command(name="add", description="Add a player to the auto-redeem list")
@app_commands.rename(fid="id", kid="server_id", nickname="nickname", account_type="type")
@app_commands.describe(
    fid="The Player ID to add",
    kid="The Kingdom / Server ID (e.g., 718)",
    nickname="Player's in-game nickname",
    account_type="Optional account type (Main, Farm, Alt)"
)
@app_commands.choices(account_type=[
    app_commands.Choice(name="Main", value="main"),
    app_commands.Choice(name="Farm", value="farm"),
    app_commands.Choice(name="Alt", value="alt"),
])
async def add(
    interaction: discord.Interaction, 
    fid: str, 
    kid: int, 
    nickname: str,
    account_type: app_commands.Choice[str] = None
):
    await interaction.response.defer(ephemeral=True)

    if ks_bot.db.player_exists(fid):
        await interaction.followup.send(f"Player with ID `{fid}` is already in the list.", ephemeral=True)
        return

    type_val = account_type.value if account_type else None
    player_data = {
        "fid": fid, 
        "nickname": nickname, 
        "kid": kid, 
        "discord_user_id": str(interaction.user.id),
        "account_type": type_val
    }

    embed = discord.Embed(title="Confirm Add Player", color=discord.Color.blue())
    embed.add_field(name="Nickname", value=nickname, inline=True)
    embed.add_field(name="Player ID", value=fid, inline=True)
    embed.add_field(name="Server (Kingdom)", value=str(kid), inline=True)
    if type_val:
        embed.add_field(name="Type", value=type_val.upper(), inline=True)
    
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
    starred_count = ks_bot.db.get_starred_count()
    kingdom_count = ks_bot.db.get_kingdom_count()
    all_codes = ks_bot.db.get_redeemed_codes()
    session_info = ks_bot.db.get_latest_redemption_info()
    
    embed = discord.Embed(title="System Statistics", color=0x66ccff)
    embed.add_field(name="Registered Players", value=str(players_count), inline=True)
    embed.add_field(name="Starred Accounts ⭐", value=str(starred_count), inline=True)
    embed.add_field(name="Kingdoms", value=str(kingdom_count), inline=True)
    embed.add_field(name="Total Codes Redeemed", value=str(len(all_codes)), inline=True)
    
    if session_info:
        codes_str = ", ".join(session_info['codes'])
        embed.add_field(name="Latest Activity (Last 24h)", value=f"**Time:** {session_info['timestamp']} UTC\n**Codes:** {codes_str}", inline=False)
    
    embed.add_field(name="All-Time Codes", value=", ".join(all_codes) if all_codes else "None", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="list_starred", description="Show all Starred Accounts grouped by type (Owner Only)")
@app_commands.check(is_bot_owner)
async def list_starred_players(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    players = ks_bot.db.get_starred_players()
    if not players:
        await interaction.followup.send("⭐ No starred accounts found in the database.", ephemeral=True)
        return

    mains, alts, farms, unassigned = [], [], [], []
    for p in players:
        t = (p['account_type'].lower() if ('account_type' in p.keys() and p['account_type']) else "").strip()
        line = f"• **{p['nickname']}** — ID: `{p['fid']}` | Server: *{p['kid']}*"
        
        if t == "main":
            mains.append(line)
        elif t == "alt":
            alts.append(line)
        elif t == "farm":
            farms.append(line)
        else:
            unassigned.append(line)

    description_parts = []
    if mains:
        description_parts.append("👑 **Mains:**")
        description_parts.extend(mains)
    if alts:
        description_parts.append("\n🛡️ **Alts:**")
        description_parts.extend(alts)
    if farms:
        description_parts.append("\n🌾 **Farms:**")
        description_parts.extend(farms)
    if unassigned:
        description_parts.append("\n📁 **Other Accounts:**")
        description_parts.extend(unassigned)

    embed = discord.Embed(
        title=f"⭐ Starred Accounts ({len(players)} total)", 
        description="\n".join(description_parts), 
        color=0xffd700
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="redeem_all", description="Force manual redemption for ALL players (Owner Only)")
@app_commands.check(is_bot_owner)
async def redeem_all(interaction: discord.Interaction):
    await interaction.response.send_message("🚀 Starting manual cycle for ALL players. Summary will be posted to all registered channels.", ephemeral=True)
    stats = await asyncio.to_thread(ks_bot.run_redemption_cycle, starred_only=False)
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
    star_str = " ⭐" if player['is_starred'] else ""
    acc_type = f" `[{player['account_type'].upper()}]`" if player.get('account_type') else ""
    embed = discord.Embed(title=f"History: {player['nickname']}{star_str}{acc_type}", description=f"ID: `{fid}`", color=0x66ccff)
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
@app_commands.check(is_admin_or_owner)
async def set_channel(interaction: discord.Interaction):
    ks_bot.db._set_guild_channel(interaction.guild_id, interaction.channel_id)
    await interaction.response.send_message(
        f"✅ This channel has been registered for redemption reports.", 
        ephemeral=True
    )

@bot.tree.command(name="unset_channel", description="Stop sending redemption reports to this server")
@app_commands.check(is_admin_or_owner)
async def unset_channel(interaction: discord.Interaction):
    success = ks_bot.db._delete_guild_channel(interaction.guild_id)
    if success:
        await interaction.response.send_message(f"✅ This server has been unregistered from redemption reports.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ This server was not registered in the list.", ephemeral=True)

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

@bot.tree.command(name="remove_channel", description="Unregister a redemption report channel by its Discord Channel ID (Owner Only)")
@app_commands.describe(channel_id="The Discord Channel ID to remove")
@app_commands.check(is_bot_owner)
async def remove_channel(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer(ephemeral=True)
    
    try:
        cid = int(channel_id)
    except ValueError:
        await interaction.followup.send("❌ Channel ID must be a valid number.", ephemeral=True)
        return

    # Delete matching target channel from guild_settings
    ks_bot.db.cursor.execute("DELETE FROM guild_settings WHERE target_channel_id = ?", (cid,))
    ks_bot.db.conn.commit()

    if ks_bot.db.cursor.rowcount > 0:
        await interaction.followup.send(f"✅ Successfully unregistered channel ID `{cid}` from report updates.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Channel ID `{cid}` was not found in the registered channels list.", ephemeral=True)

@bot.tree.command(name="find_by_name", description="Search for players in the database by nickname")
@app_commands.describe(name="The nickname or partial name to search for")
async def find_by_name(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    
    ks_bot.db.cursor.execute(
        "SELECT fid, nickname, kid, is_starred, account_type, discord_user_id FROM players WHERE nickname LIKE ?", 
        (f"%{name}%",)
    )
    players = ks_bot.db.cursor.fetchall()
    
    if not players:
        await interaction.followup.send(f"❌ No players found matching nickname part `{name}`.", ephemeral=True)
        return

    view = PlayerPagination(players, per_page=15)
    embed = view.create_embed()
    embed.title = f"Search Results for '{name}' ({len(players)} found)"
    
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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