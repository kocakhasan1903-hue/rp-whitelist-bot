import os
import json
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ------------------ ENV ------------------
load_dotenv()
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()

_guild_env = (os.getenv("GUILD_ID") or "").strip()
GUILD_ID = int(_guild_env) if _guild_env.isdigit() else None  # optional, aber empfohlen

# ------------------ FILES ------------------
CONFIG_FILE = "config.json"
FAMILIES_FILE = "families.json"

def fatal(msg: str):
    raise SystemExit(f"❌ {msg}")

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ------------------ VALIDATION ------------------
if not TOKEN:
    fatal("DISCORD_TOKEN fehlt. Bitte im Hoster als Environment Variable setzen.")

CONFIG = load_json(CONFIG_FILE, {})

required = ["verify_channel_id", "auto_role_name", "embed_title", "embed_text"]
missing = [k for k in required if not str(CONFIG.get(k, "")).strip()]
if missing:
    fatal(f"config.json fehlt: {', '.join(missing)}")

verify_channel_id_str = str(CONFIG["verify_channel_id"]).strip()
if not verify_channel_id_str.isdigit():
    fatal("config.json: verify_channel_id muss eine Zahl (Channel-ID) sein.")
VERIFY_CHANNEL_ID = int(verify_channel_id_str)

AUTO_ROLE_NAME = str(CONFIG["auto_role_name"]).strip()
EMBED_TITLE = str(CONFIG["embed_title"]).strip()
EMBED_TEXT = str(CONFIG["embed_text"]).strip()

log_channel_id_str = str(CONFIG.get("log_channel_id", "")).strip()
LOG_CHANNEL_ID = int(log_channel_id_str) if log_channel_id_str.isdigit() else None

STAFF_ROLE_IDS = set()
for rid in CONFIG.get("staff_role_ids", []):
    rid_s = str(rid).strip()
    if rid_s.isdigit():
        STAFF_ROLE_IDS.add(int(rid_s))

MODAL_TITLE = "Rollenvergabe - LSD Sin Nombre"

# ------------------ STORAGE ------------------
def load_families():
    """
    families.json Format:
    {
      "Familienname": {"password": "...", "role_id": "123..."},
      ...
    }
    """
    return load_json(FAMILIES_FILE, {})

def save_families(data):
    save_json(FAMILIES_FILE, data)

# ------------------ BOT SETUP ------------------
intents = discord.Intents.default()
intents.members = True  # Developer Portal: Server Members Intent aktivieren!
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ HELPERS ------------------
async def log(guild: discord.Guild, text: str):
    if not LOG_CHANNEL_ID:
        return
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(text)
        except:
            pass

def can_manage(interaction: discord.Interaction) -> bool:
    """Wer darf /family verwalten? Admin ODER eine der staff_role_ids."""
    if interaction.user.guild_permissions.administrator:
        return True
    if STAFF_ROLE_IDS:
        member = interaction.user
        # interaction.user ist in Guild-Interaktionen ein Member-Objekt
        for r in getattr(member, "roles", []):
            if r.id in STAFF_ROLE_IDS:
                return True
    return False

def build_family_options(families: dict) -> list[discord.SelectOption]:
    # Discord erlaubt max 25 Optionen im Select
    names = sorted(list(families.keys()))[:25]
    return [discord.SelectOption(label=n, value=n) for n in names]

# ------------------ UI FLOW ------------------
class FamilySelect(discord.ui.Select):
    def __init__(self, families: dict):
        super().__init__(
            placeholder="Wähle deine Familie",
            min_values=1,
            max_values=1,
            options=build_family_options(families),
            custom_id="family_select_ui"
        )

    async def callback(self, interaction: discord.Interaction):
        families = load_families()
        fam = self.values[0]
        if fam not in families:
            await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)
            return

        # Nach Auswahl: Modal öffnen
        await interaction.response.send_modal(VerifyModal(family_name=fam))

class FamilySelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        families = load_families()
        self.add_item(FamilySelect(families))

class VerifyModal(discord.ui.Modal):
    def __init__(self, family_name: str):
        super().__init__(title=MODAL_TITLE, timeout=300)
        self.family_name = family_name

        self.first = discord.ui.TextInput(label="IC Vorname", required=True, max_length=32)
        self.last = discord.ui.TextInput(label="IC Nachname", required=True, max_length=32)
        self.password = discord.ui.TextInput(label="Familienpasswort", required=True, max_length=64)

        self.add_item(self.first)
        self.add_item(self.last)
        self.add_item(self.password)

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        entry = families.get(self.family_name)

        if not entry:
            await interaction.response.send_message("❌ Familie existiert nicht (mehr).", ephemeral=True)
            return

        pw_ok = (self.password.value.strip() == str(entry.get("password", "")))
        if not pw_ok:
            await log(interaction.guild, f"🚫 Passwort FAIL: {interaction.user} → {self.family_name}")
            await interaction.response.send_message("❌ Passwort ist falsch.", ephemeral=True)
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ Member nicht gefunden.", ephemeral=True)
            return

        role_id = str(entry.get("role_id", "")).strip()
        if not role_id.isdigit():
            await interaction.response.send_message("❌ Rolle ungültig (role_id).", ephemeral=True)
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht (mehr).", ephemeral=True)
            return

        # Nickname setzen (optional)
        nick = f"{self.first.value.strip()} {self.last.value.strip()}"[:32]
        try:
            await member.edit(nick=nick)
        except:
            pass

        # Einreise entfernen
        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        try:
            if einreise:
                await member.remove_roles(einreise)
        except:
            pass

        # Familienrolle geben
        try:
            await member.add_roles(role)
        except:
            await interaction.response.send_message(
                "❌ Konnte Rolle nicht geben. Prüfe Rollen-Hierarchie & Manage Roles.",
                ephemeral=True
            )
            return

        await log(interaction.guild, f"✅ Rollenvergabe OK: {interaction.user} → {self.family_name} ({role.name})")
        await interaction.response.send_message(
            f"✅ Erfolgreich! Willkommen **{nick}**.\nDu hast die Rolle **{role.name}** erhalten.",
            ephemeral=True
        )

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.success, custom_id="start_roles_ui")
    async def start(self, interaction: discord.Interaction, _):
        families = load_families()
        if not families:
            await interaction.response.send_message(
                "⚠️ Es sind noch keine Familien angelegt. Ein Teammitglied muss zuerst `/family add` nutzen.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Bitte wähle deine **Familie**:",
            view=FamilySelectView(),
            ephemeral=True
        )

# ------------------ ADMIN SLASH COMMANDS ------------------
family_group = app_commands.Group(name="family", description="Familienverwaltung (Rollenvergabe)")

@family_group.command(name="add", description="Familie hinzufügen/aktualisieren")
@app_commands.describe(familie="Familienname", passwort="Familienpasswort", rolle="Rolle die vergeben wird")
async def family_add(interaction: discord.Interaction, familie: str, passwort: str, rolle: discord.Role):
    if not can_manage(interaction):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    familie = familie.strip()
    passwort = passwort.strip()

    fams = load_families()
    fams[familie] = {"password": passwort, "role_id": str(rolle.id)}
    save_families(fams)

    await log(interaction.guild, f"🛠️ FAMILY ADD by {interaction.user}: {familie} → {rolle.name}")
    await interaction.response.send_message(f"✅ Familie **{familie}** gespeichert → {rolle.mention}", ephemeral=True)

@family_group.command(name="remove", description="Familie entfernen")
@app_commands.describe(familie="Familienname")
async def family_remove(interaction: discord.Interaction, familie: str):
    if not can_manage(interaction):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    familie = familie.strip()

    if familie not in fams:
        await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)
        return

    del fams[familie]
    save_families(fams)

    await log(interaction.guild, f"🛠️ FAMILY REMOVE by {interaction.user}: {familie}")
    await interaction.response.send_message(f"✅ Familie **{familie}** entfernt.", ephemeral=True)

@family_group.command(name="list", description="Familien anzeigen")
async def family_list(interaction: discord.Interaction):
    if not can_manage(interaction):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    if not fams:
        await interaction.response.send_message("ℹ️ Keine Familien hinterlegt.", ephemeral=True)
        return

    lines = [f"• **{k}** → <@&{v.get('role_id','?')}>" for k, v in fams.items()]
    await interaction.response.send_message("📜 Familien:\n" + "\n".join(lines), ephemeral=True)

bot.tree.add_command(family_group)

# ------------------ EVENTS ------------------
@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")
    bot.add_view(StartView())  # persistent button

    # UI-Nachricht im Verify-Channel sicherstellen
    for guild in bot.guilds:
        ch = guild.get_channel(VERIFY_CHANNEL_ID)
        if not ch:
            continue

        # Postet nur, wenn noch keine Bot-UI existiert
        found = False
        try:
            async for msg in ch.history(limit=30):
                if msg.author.id == bot.user.id and msg.components:
                    found = True
                    break
        except:
            pass

        if not found:
            embed = discord.Embed(title=EMBED_TITLE, description=EMBED_TEXT)
            try:
                await ch.send(embed=embed, view=StartView())
            except:
                pass

@bot.event
async def on_member_join(member: discord.Member):
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass
    await log(member.guild, f"👤 JOIN: {member} → {AUTO_ROLE_NAME}")

@bot.event
async def setup_hook():
    # Commands sync: mit GUILD_ID sofort, sonst global (kann dauern)
    if GUILD_ID:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Slash Commands synced to guild {GUILD_ID}")
    else:
        await bot.tree.sync()
        print("✅ Slash Commands synced globally (kann dauern)")

# ------------------ START ------------------
bot.run(TOKEN)
