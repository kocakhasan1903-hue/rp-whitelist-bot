import os
import json
import time
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ------------------ LOAD ENV ------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

# ------------------ CONFIG ------------------
with open("config.json", "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

FAMILIES_FILE = "families.json"

def load_families():
    try:
        with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_families(data):
    with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ------------------ BOT SETUP ------------------
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
pending = {}  # user_id -> data

# ------------------ LOG ------------------
async def log(guild, text):
    if not CONFIG.get("log_channel_id"):
        return
    ch = guild.get_channel(int(CONFIG["log_channel_id"]))
    if ch:
        await ch.send(text)

# ------------------ UI MODAL ------------------
class VerifyModal(discord.ui.Modal, title="Whitelist Registrierung"):
    first = discord.ui.TextInput(label="IC Vorname", required=True)
    last = discord.ui.TextInput(label="IC Nachname", required=True)
    password = discord.ui.TextInput(label="Familienpasswort", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        if not families:
            await interaction.response.send_message(
                "⚠️ Es sind noch keine Familien angelegt.", ephemeral=True
            )
            return

        pending[interaction.user.id] = {
            "first": self.first.value.strip(),
            "last": self.last.value.strip(),
            "pw": self.password.value.strip(),
            "time": time.time()
        }

        options = [
            discord.SelectOption(label=name, value=name)
            for name in families.keys()
        ][:25]

        await interaction.response.send_message(
            "✅ Daten gespeichert. Wähle jetzt deine Familie:",
            ephemeral=True,
            view=FamilySelectView(options)
        )

# ------------------ FAMILY SELECT ------------------
class FamilySelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Familie auswählen",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        data = pending.get(interaction.user.id)
        if not data:
            await interaction.response.send_message(
                "❌ Session abgelaufen.", ephemeral=True
            )
            return

        families = load_families()
        fam = self.values[0]
        entry = families.get(fam)

        if not entry or data["pw"] != entry["password"]:
            await interaction.response.send_message(
                "❌ Falsches Passwort.", ephemeral=True
            )
            await log(interaction.guild, f"🚫 FAIL {interaction.user} ({fam})")
            return

        member = interaction.guild.get_member(interaction.user.id)
        role = interaction.guild.get_role(int(entry["role_id"]))

        if not member or not role:
            await interaction.response.send_message(
                "❌ Rollenfehler.", ephemeral=True
            )
            return

        # Nickname
        try:
            await member.edit(nick=f"{data['first']} {data['last']}"[:32])
        except:
            pass

        # Einreise entfernen
        einreise = discord.utils.get(
            interaction.guild.roles,
            name=CONFIG["auto_role_name"]
        )
        if einreise:
            await member.remove_roles(einreise)

        await member.add_roles(role)

        pending.pop(interaction.user.id, None)

        await log(interaction.guild, f"✅ VERIFIED {interaction.user} → {fam}")
        await interaction.response.send_message(
            f"✅ Willkommen **{data['first']} {data['last']}**!\n"
            f"Du bist jetzt **{role.name}**.",
            ephemeral=True
        )

class FamilySelectView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=300)
        self.add_item(FamilySelect(options))

# ------------------ VERIFY BUTTON ------------------
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Registrieren",
        style=discord.ButtonStyle.success,
        custom_id="verify_start"
    )
    async def start(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(VerifyModal())

# ------------------ EVENTS ------------------
@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    bot.add_view(VerifyView())

    for guild in bot.guilds:
        ch = guild.get_channel(int(CONFIG["verify_channel_id"]))
        if not ch:
            continue

        async for msg in ch.history(limit=20):
            if msg.author == bot.user and msg.components:
                return

        embed = discord.Embed(
            title=CONFIG["embed_title"],
            description=CONFIG["embed_text"]
        )
        await ch.send(embed=embed, view=VerifyView())

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=CONFIG["auto_role_name"])
    if role:
        await member.add_roles(role)
    await log(member.guild, f"👤 JOIN {member}")

# ------------------ ADMIN COMMANDS ------------------
family = app_commands.Group(name="family", description="Familienverwaltung")

@family.command(name="add")
async def add_family(
    interaction: discord.Interaction,
    familie: str,
    passwort: str,
    rolle: discord.Role
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Keine Rechte.", ephemeral=True)
        return

    fams = load_families()
    fams[familie] = {
        "password": passwort,
        "role_id": str(rolle.id)
    }
    save_families(fams)

    await interaction.response.send_message(
        f"✅ Familie **{familie}** gespeichert.",
        ephemeral=True
    )

@family.command(name="list")
async def list_families(interaction: discord.Interaction):
    fams = load_families()
    if not fams:
        await interaction.response.send_message("Keine Familien vorhanden.", ephemeral=True)
        return

    text = "\n".join([f"• {k}" for k in fams.keys()])
    await interaction.response.send_message(text, ephemeral=True)

bot.tree.add_command(family)

@bot.event
async def setup_hook():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))

# ------------------ START ------------------
bot.run(TOKEN)
