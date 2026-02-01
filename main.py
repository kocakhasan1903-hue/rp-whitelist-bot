import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ================= ENV =================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ================= FILES =================
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
STAFF_ROLE_IDS = set(int(x) for x in CONFIG["staff_role_ids"])

# ================= BOT =================
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= HELPERS =================
def load_families():
    if not os.path.exists(FAMILIES_FILE):
        return {}
    with open(FAMILIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_families(data):
    with open(FAMILIES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_staff(member: discord.Member):
    return member.guild_permissions.administrator or any(
        r.id in STAFF_ROLE_IDS for r in member.roles
    )

async def log(guild, msg):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(msg)

# ================= UI =================
class VerifyModal(discord.ui.Modal, title="🧬 Identitätsprüfung"):
    ic_first = discord.ui.TextInput(label="IC Vorname")
    ic_last = discord.ui.TextInput(label="IC Nachname")
    password = discord.ui.TextInput(label="Familienpasswort")

    def __init__(self, family):
        super().__init__()
        self.family = family

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
            await member.edit(nick=f"{self.ic_first.value} {self.ic_last.value}")
        except:
            pass

        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            await member.remove_roles(einreise)

        await member.add_roles(role)
        await log(interaction.guild, f"✅ {member} → {role.name}")

        await interaction.response.send_message(
            f"🔥 Willkommen **{self.ic_first.value} {self.ic_last.value}**\n"
            f"🏷️ Rolle: **{role.name}**",
            ephemeral=True
        )

class FamilySelect(discord.ui.Select):
    def __init__(self):
        families = load_families()
        options = [
            discord.SelectOption(label=name, emoji="🏴")
            for name in families.keys()
        ]
        super().__init__(
            placeholder="🧠 Wähle deine Familie",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            VerifyModal(self.values[0])
        )

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(
        label="🔥 Rollenvergabe starten",
        style=discord.ButtonStyle.danger,
        emoji="🧬"
    )
    async def start(self, interaction: discord.Interaction, _):
        if not load_families():
            await interaction.response.send_message(
                "⚠️ Es sind noch keine Familien eingerichtet.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "👇 **Wähle deine Familie**",
            ephemeral=True,
            view=FamilyView()
        )

# ================= STAFF COMMANDS =================
@bot.tree.command(name="familie-add", description="Familie anlegen (Staff)")
async def familie_add(
    interaction: discord.Interaction,
    name: str,
    passwort: str,
    rolle: discord.Role
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    families = load_families()
    families[name] = {"password": passwort, "role_id": str(rolle.id)}
    save_families(families)

    await interaction.response.send_message(
        f"✅ Familie **{name}** angelegt → {rolle.mention}",
        ephemeral=True
    )

@bot.tree.command(name="familien-liste", description="Alle Familien anzeigen")
async def familien_liste(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    families = load_families()
    if not families:
        await interaction.response.send_message("Keine Familien vorhanden.", ephemeral=True)
        return

    text = "\n".join(f"🏴 **{k}**" for k in families.keys())
    await interaction.response.send_message(text, ephemeral=True)

@bot.tree.command(name="setup-rollenvergabe", description="UI posten (Staff)")
async def setup_ui(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(VERIFY_CHANNEL_ID)

    embed = discord.Embed(
        title=f"🔥 {EMBED_TITLE}",
        description=f"🧬 {EMBED_TEXT}",
        color=discord.Color.red()
    )
    embed.set_footer(text="Sin Nombre Kartell • Identitätsprüfung")

    await channel.send(embed=embed, view=StartView())
    await interaction.response.send_message("✅ Rollenvergabe gepostet.", ephemeral=True)

# ================= EVENTS =================
@bot.event
async def setup_hook():
    await bot.tree.sync()  # 🌍 GLOBAL
    print("🌍 Slash Commands GLOBAL synced")
    print("🌳 Commands:", [c.name for c in bot.tree.get_commands()])

@bot.event
async def on_ready():
    print(f"🔥 Online als {bot.user}")

@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        await member.add_roles(role)

# ================= START =================
bot.run(TOKEN)
