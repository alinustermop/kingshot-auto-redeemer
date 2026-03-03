import discord
from discord.ext import commands
import asyncio
import constants
import logging
from main import KingshotBot

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

logger = logging.getLogger()
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)-4s | %(message)s')

handler.setFormatter(formatter)
handler.addFilter(DiscordNameFilter()) 
logger.addHandler(handler)
logger.setLevel(logging.INFO)




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

# --- BOT COMMANDS ---

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Bot is ready.")

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



bot.run(constants.DISCORD_TOKEN)