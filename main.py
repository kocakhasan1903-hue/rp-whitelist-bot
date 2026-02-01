import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ================= ENV =================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

CONFIG_FILE = "config.json"
FAMILIES_FILE = "families.json"

# ================= LOAD CONFIG =================
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

VERIFY_CHANNEL_ID = int(CONFIG["verify_channel_id"])
LOG_CHANNEL_ID = int(CONFIG["log_channel_id"])
AUTO_ROLE_NAME = CONFIG["auto_role_name"]
EMBED_TITLE = CONFIG["embed_title"]
EMBED_TEXT = CONFIG["embed_text"]
STAFF_ROLE_IDS = set(int(r) for r in CONFIG["staff_role_ids"])

MODAL_TITLE = "Rollenvergabe - LSD Sin Nombre"

# ================= FILE HELPERS =================
def load_families():
    if not os.path.exists(FAMILIES_FILE):
        return {}
    with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_families(data):
    with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ================= BOT =================
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= PERMISSIONS =================
def is_staff(member: discord.Member):
    if member.guild_permissions.administrator:
        return True
    return any(role.id in STAFF_ROLE_IDS for role in member.roles)

async def log(guild, text):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(text)

# ================= UI =================
class VerifyModal(discord.ui.Modal):
    def __init__(self, family):
        super().__init__(title=MODAL_TITLE)
        self.family = family

        self.first = discord.ui.TextInput(label="IC Vorname")
        self.last = discord.ui.TextInput(label="IC Nachname")
        self.password = discord.ui.TextInput(label="Familienpasswort")

        self.add_item(self.first)
        self.add_item(self.last)
        self.add_item(self.password)

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        data = families.get(self.family)

        if not data or self.password.value != data["password"]:
            await interaction.response.send_message("❌ Passwort falsch.", ephemeral=True)
            return

        role = interaction.guild.get_role(int(data["role_id"]))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht.", ephemeral=True)
            return

        member = interaction.user

        try:
            await member.edit(nick=f"{self.first.value} {self.last.value}")
        except:
            pass

        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            await member.remove_roles(einreise)

        await member.add_roles(role)
        await log(interaction.guild, f"✅ {member} → {role.name}")

        await interaction.response.send_message(
            f"✅ Willkommen **{self.first.value} {self.last.value}**\nRolle: **{role.name}**",
            ephemeral=True
        )

class FamilySelect(discord.ui.Select):
    def __init__(self):
        families = load_families()
        options = [
            discord.SelectOption(label=name, value=name)
            for name in families.keys()
        ]
        super().__init__(
            placeholder="Wähle deine Familie",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VerifyModal(self.values[0]))

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, _):
        if not load_families():
            await interaction.response.send_message(
                "⚠️ Noch keine Familien angelegt.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Bitte wähle deine Familie:",
            ephemeral=True,
            view=FamilyView()
        )

# ================= SLASH COMMANDS =================
family = app_commands.Group(name="family", description="Familienverwaltung")

@family.command(name="add", description="Familie hinzufügen")
async def family_add(
    interaction: discord.Interaction,
    familie: str,
    passwort: str,
    rolle: discord.Role
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    families = load_families()
    families[familie] = {
        "password": passwort,
        "role_id": str(rolle.id)
    }
    save_families(families)

    await interaction.response.send_message(
        f"✅ Familie **{familie}** gespeichert → {rolle.mention}",
        ephemeral=True
    )

@family.command(name="list", description="Familien anzeigen")
async def family_list(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    families = load_families()
    if not families:
        await interaction.response.send_message("Keine Familien vorhanden.", ephemeral=True)
        return

    text = "\n".join(f"• {name}" for name in families.keys())
    await interaction.response.send_message(text, ephemeral=True)

bot.tree.add_command(family)

# ================= EVENTS =================
@bot.event
async def setup_hook():
    guild = discord.Object(id=GUILD_ID)

    bot.tree.clear_commands(guild=guild)
    await bot.tree.sync(guild=guild)
    print("🧹 Commands cleared")

    await bot.tree.sync(guild=guild)
    print(f"✅ Slash Commands synced to guild {GUILD_ID}")
    print("🌳 Commands:", [c.name for c in bot.tree.get_commands()])

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    bot.add_view(StartView())

    guild = bot.get_guild(GUILD_ID)
    channel = guild.get_channel(VERIFY_CHANNEL_ID)

    async for msg in channel.history(limit=20):
        if msg.author == bot.user:
            return

    embed = discord.Embed(title=EMBED_TITLE, description=EMBED_TEXT)
    await channel.send(embed=embed, view=StartView())

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        await member.add_roles(role)

# ================= START =================
bot.run(TOKEN)

