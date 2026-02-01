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
AUTO_ROLE_NAME = CONFIG["auto_role_name"]
STAFF_ROLE_IDS = set(int(x) for x in CONFIG["staff_role_ids"])

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
    return any(r.id in STAFF_ROLE_IDS for r in member.roles)

# ================= SLASH COMMANDS =================

@bot.tree.command(name="family", description="Familienverwaltung (Staff)")
@app_commands.describe(
    action="add | list",
    familie="Familienname",
    passwort="Familienpasswort",
    rolle="Rolle"
)
async def family(
    interaction: discord.Interaction,
    action: str,
    familie: str = None,
    passwort: str = None,
    rolle: discord.Role = None
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    families = load_families()

    if action == "add":
        if not familie or not passwort or not rolle:
            await interaction.response.send_message(
                "❌ Nutzung: /family add familie passwort rolle",
                ephemeral=True
            )
            return

        families[familie] = {
            "password": passwort,
            "role_id": str(rolle.id)
        }
        save_families(families)

        await interaction.response.send_message(
            f"✅ Familie **{familie}** gespeichert → {rolle.mention}",
            ephemeral=True
        )

    elif action == "list":
        if not families:
            await interaction.response.send_message("Keine Familien vorhanden.", ephemeral=True)
            return

        text = "\n".join(f"• {k}" for k in families.keys())
        await interaction.response.send_message(text, ephemeral=True)

    else:
        await interaction.response.send_message(
            "❌ Ungültige Aktion. Nutze: add | list",
            ephemeral=True
        )

# ================= VERIFY COMMAND =================

@bot.tree.command(name="verify", description="Rollenvergabe starten")
@app_commands.describe(
    vorname="IC Vorname",
    nachname="IC Nachname",
    familie="Familienname",
    passwort="Familienpasswort"
)
async def verify(
    interaction: discord.Interaction,
    vorname: str,
    nachname: str,
    familie: str,
    passwort: str
):
    if interaction.channel_id != VERIFY_CHANNEL_ID:
        await interaction.response.send_message(
            "❌ Bitte nutze diesen Befehl im Verifizierungs-Channel.",
            ephemeral=True
        )
        return

    families = load_families()
    data = families.get(familie)

    if not data or passwort != data["password"]:
        await interaction.response.send_message("❌ Passwort oder Familie falsch.", ephemeral=True)
        return

    role = interaction.guild.get_role(int(data["role_id"]))
    if not role:
        await interaction.response.send_message("❌ Rolle existiert nicht.", ephemeral=True)
        return

    member = interaction.user

    try:
        await member.edit(nick=f"{vorname} {nachname}")
    except:
        pass

    einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
    if einreise:
        await member.remove_roles(einreise)

    await member.add_roles(role)

    await interaction.response.send_message(
        f"✅ Willkommen **{vorname} {nachname}**\nRolle: **{role.name}**",
        ephemeral=True
    )

# ================= EVENTS =================

@bot.event
async def setup_hook():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"✅ Slash Commands synced to guild {GUILD_ID}")
    print("🌳 Commands:", [c.name for c in bot.tree.get_commands()])

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        await member.add_roles(role)

# ================= START =================
bot.run(TOKEN)
