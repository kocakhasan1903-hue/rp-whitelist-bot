import os
import json
import base64
import time
import requests
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ===================== ENV =====================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")          # owner/repo
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_FAMILIES_PATH = os.getenv("GITHUB_FAMILIES_PATH", "families.json")

if not DISCORD_TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN fehlt (Railway Variables)")
if not GITHUB_TOKEN:
    raise SystemExit("❌ GITHUB_TOKEN fehlt (Railway Variables)")
if not GITHUB_REPO or "/" not in GITHUB_REPO:
    raise SystemExit("❌ GITHUB_REPO fehlt/ungültig (z.B. owner/repo)")

CONFIG_FILE = "config.json"

# ===================== CONFIG =====================
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

VERIFY_CHANNEL_ID = int(CONFIG["verify_channel_id"])
LOG_CHANNEL_ID = int(CONFIG["log_channel_id"])
AUTO_ROLE_NAME = CONFIG["auto_role_name"]
EMBED_TITLE = CONFIG["embed_title"]
EMBED_TEXT = CONFIG["embed_text"]
STAFF_ROLE_IDS = set(int(x) for x in CONFIG["staff_role_ids"])


# ===================== GitHub Storage (families.json) =====================
API_BASE = "https://api.github.com"
OWNER, REPO = GITHUB_REPO.split("/", 1)

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "rp-rollenvergabe-bot"
    }

def gh_get_families():
    """Return (families_dict, sha or None). Creates empty file if missing."""
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/contents/{GITHUB_FAMILIES_PATH}"
    params = {"ref": GITHUB_BRANCH}

    r = requests.get(url, headers=gh_headers(), params=params, timeout=20)

    if r.status_code == 404:
        # Create empty file
        empty = {}
        sha = gh_put_families(empty, sha=None, message="init families.json")
        return empty, sha

    r.raise_for_status()
    data = r.json()
    content_b64 = data.get("content", "")
    sha = data.get("sha")
    if not content_b64:
        return {}, sha

    decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    try:
        fams = json.loads(decoded) if decoded.strip() else {}
        if not isinstance(fams, dict):
            fams = {}
        return fams, sha
    except json.JSONDecodeError:
        return {}, sha

def gh_put_families(families: dict, sha: str | None, message: str):
    """Write families dict to GitHub. Returns new sha."""
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/contents/{GITHUB_FAMILIES_PATH}"

    body = json.dumps(families, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")

    payload = {
        "message": message,
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=gh_headers(), json=payload, timeout=20)

    # If SHA mismatch due to concurrency, retry once
    if r.status_code == 409:
        time.sleep(0.7)
        fams_now, sha_now = gh_get_families()
        # merge strategy: overwrite with our families (staff action wins)
        payload["sha"] = sha_now
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=20)

    r.raise_for_status()
    return r.json()["content"]["sha"]

# small cache to reduce calls (still correct enough for RP)
_FAM_CACHE = {"ts": 0, "data": {}, "sha": None}
CACHE_SECONDS = 5

def load_families():
    now = time.time()
    if now - _FAM_CACHE["ts"] < CACHE_SECONDS:
        return _FAM_CACHE["data"]
    fams, sha = gh_get_families()
    _FAM_CACHE.update({"ts": now, "data": fams, "sha": sha})
    return fams

def save_families(families: dict, message: str):
    # get latest sha (avoid overwriting)
    fams, sha = gh_get_families()
    # overwrite with provided families (staff changes are deliberate)
    new_sha = gh_put_families(families, sha=sha, message=message)
    _FAM_CACHE.update({"ts": time.time(), "data": families, "sha": new_sha})


# ===================== BOT =====================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

def is_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id in STAFF_ROLE_IDS for r in member.roles)

async def log(guild: discord.Guild, msg: str):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(msg)
        except:
            pass


# ===================== UI =====================
def build_embed():
    embed = discord.Embed(
        title=f"🔥 {EMBED_TITLE}",
        description=f"🧬 {EMBED_TEXT}\n\n"
                    f"1) Button klicken\n"
                    f"2) Familie wählen\n"
                    f"3) IC Daten + Passwort\n"
                    f"4) Rolle erhalten ✅",
        color=discord.Color.red()
    )
    embed.set_footer(text="Sin Nombre • Rollenvergabe System")
    return embed

def nickname_from_inputs(first: str, last: str, family: str) -> str:
    nick = f"{first.strip()} {last.strip()} | {family.strip()}"
    return nick[:32]

class VerifyModal(discord.ui.Modal, title="🧬 Rollenvergabe"):
    ic_first = discord.ui.TextInput(label="IC Vorname", max_length=32)
    ic_last = discord.ui.TextInput(label="IC Nachname", max_length=32)
    password = discord.ui.TextInput(label="Familienpasswort", max_length=64)

    def __init__(self, family_name: str):
        super().__init__()
        self.family_name = family_name

    async def on_submit(self, interaction: discord.Interaction):
        families = load_families()
        data = families.get(self.family_name)

        if not data:
            await interaction.response.send_message("❌ Familie existiert nicht (Staff muss sie anlegen).", ephemeral=True)
            return

        if self.password.value.strip() != str(data.get("password", "")):
            await log(interaction.guild, f"🚫 Passwort falsch: {interaction.user} → {self.family_name}")
            await interaction.response.send_message("❌ Passwort falsch.", ephemeral=True)
            return

        role_id = str(data.get("role_id", "")).strip()
        if not role_id.isdigit():
            await interaction.response.send_message("❌ Rolle-ID ungültig (Staff muss Familie neu setzen).", ephemeral=True)
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message("❌ Rolle existiert nicht (mehr). Staff muss Familie neu setzen.", ephemeral=True)
            return

        member = interaction.user

        # Nickname setzen
        try:
            await member.edit(nick=nickname_from_inputs(self.ic_first.value, self.ic_last.value, self.family_name))
        except:
            pass

        # Einreise entfernen
        einreise = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE_NAME)
        if einreise:
            try:
                await member.remove_roles(einreise)
            except:
                pass

        # alte Familienrollen entfernen
        for fam in families.values():
            old_role = interaction.guild.get_role(int(fam.get("role_id", 0)))
            if old_role and old_role in member.roles:
                try:
                    await member.remove_roles(old_role)
                except:
                    pass

        # neue Rolle geben
        try:
            await member.add_roles(role)
        except:
            await interaction.response.send_message(
                "❌ Rolle konnte nicht vergeben werden. Prüfe Rollen-Hierarchie & 'Rollen verwalten'.",
                ephemeral=True
            )
            return

        await log(interaction.guild, f"✅ Rollenvergabe: {interaction.user} → {role.name} ({self.family_name})")
        await interaction.response.send_message(
            f"✅ Erfolgreich!\n🏴 Familie: **{self.family_name}**\n🏷️ Rolle: **{role.name}**",
            ephemeral=True
        )

class FamilySelect(discord.ui.Select):
    def __init__(self):
        fams = load_families()
        if not fams:
            options = [discord.SelectOption(label="Keine Familien", value="none", description="Staff muss Familien anlegen")]
        else:
            options = [discord.SelectOption(label=name, value=name, emoji="🏴") for name in sorted(fams.keys())[:25]]

        super().__init__(
            placeholder="🏴 Wähle deine Familie",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("⚠️ Noch keine Familien angelegt.", ephemeral=True)
            return
        await interaction.response.send_modal(VerifyModal(self.values[0]))

class FamilyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ✅ dauerhaft (kein Interaktion-fehlgeschlagen)
        self.add_item(FamilySelect())

class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ✅ dauerhaft

    @discord.ui.button(label="Rollenvergabe starten", style=discord.ButtonStyle.danger, emoji="🧬", custom_id="start_roles_button")
    async def start(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("👇 Familie auswählen:", ephemeral=True, view=FamilyView())

async def ensure_ui_message(channel: discord.TextChannel) -> discord.Message:
    # findet vorhandene Bot-UI Nachricht und updated sie, sonst postet neu
    async for msg in channel.history(limit=50):
        if msg.author.id == bot.user.id and msg.embeds:
            if msg.embeds[0].title and EMBED_TITLE.lower() in msg.embeds[0].title.lower():
                await msg.edit(embed=build_embed(), view=StartView())
                return msg
    return await channel.send(embed=build_embed(), view=StartView())


# ===================== STAFF COMMANDS =====================
@bot.tree.command(name="familie_add", description="Familie anlegen (Staff)")
async def familie_add(interaction: discord.Interaction, name: str, passwort: str, rolle: discord.Role):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    name = name.strip()
    fams[name] = {"password": passwort.strip(), "role_id": str(rolle.id)}
    save_families(fams, message=f"familie_add: {name}")

    # UI automatisch refresh
    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if ch:
        await ensure_ui_message(ch)

    await log(interaction.guild, f"🛠️ familie_add: {interaction.user} → {name} = {rolle.name}")
    await interaction.response.send_message(f"✅ Familie **{name}** gespeichert → {rolle.mention}", ephemeral=True)

@bot.tree.command(name="familie_remove", description="Familie löschen (Staff)")
async def familie_remove(interaction: discord.Interaction, name: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    name = name.strip()
    if name not in fams:
        await interaction.response.send_message("❌ Familie nicht gefunden.", ephemeral=True)
        return

    del fams[name]
    save_families(fams, message=f"familie_remove: {name}")

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if ch:
        await ensure_ui_message(ch)

    await log(interaction.guild, f"🗑️ familie_remove: {interaction.user} → {name}")
    await interaction.response.send_message(f"✅ Familie **{name}** wurde entfernt.", ephemeral=True)

@bot.tree.command(name="familien_liste", description="Familien anzeigen (Staff)")
async def familien_liste(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    if not fams:
        await interaction.response.send_message("ℹ️ Keine Familien vorhanden.", ephemeral=True)
        return

    txt = "\n".join([f"🏴 **{k}**" for k in sorted(fams.keys())])
    await interaction.response.send_message(txt, ephemeral=True)

@bot.tree.command(name="familie_change", description="Familie eines Users ändern + Nickname anpassen (Staff)")
async def familie_change(interaction: discord.Interaction, user: discord.Member, familie: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    fams = load_families()
    familie = familie.strip()
    if familie not in fams:
        await interaction.response.send_message("❌ Familie existiert nicht.", ephemeral=True)
        return

    role = interaction.guild.get_role(int(fams[familie]["role_id"]))
    if not role:
        await interaction.response.send_message("❌ Zielrolle existiert nicht.", ephemeral=True)
        return

    # entferne alle anderen Familienrollen
    for data in fams.values():
        old_role = interaction.guild.get_role(int(data["role_id"]))
        if old_role and old_role in user.roles:
            try:
                await user.remove_roles(old_role)
            except:
                pass

    # gebe neue Rolle
    try:
        await user.add_roles(role)
    except:
        await interaction.response.send_message("❌ Rolle konnte nicht vergeben werden (Hierarchie prüfen).", ephemeral=True)
        return

    # Nickname anpassen: "vorheriger name | neue familie"
    base = (user.nick or user.name).split("|")[0].strip()
    try:
        await user.edit(nick=f"{base} | {familie}"[:32])
    except:
        pass

    await log(interaction.guild, f"🔄 familie_change: {interaction.user} → {user} => {familie}")
    await interaction.response.send_message(f"✅ {user.mention} ist jetzt **{familie}**.", ephemeral=True)

@bot.tree.command(name="ui_update", description="UI neu posten/aktualisieren (Staff)")
async def ui_update(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    ch = interaction.guild.get_channel(VERIFY_CHANNEL_ID)
    if not ch:
        await interaction.response.send_message("❌ Verify-Channel ID falsch oder Bot sieht den Channel nicht.", ephemeral=True)
        return

    msg = await ensure_ui_message(ch)
    await interaction.response.send_message(f"✅ UI aktualisiert: {msg.jump_url}", ephemeral=True)


# ===================== EVENTS =====================
@bot.event
async def setup_hook():
    # Commands global (überall sichtbar, kann bei Discord manchmal etwas dauern)
    await bot.tree.sync()
    print("🌍 Slash Commands GLOBAL synced")
    print("🌳 Commands:", [c.name for c in bot.tree.get_commands()])

@bot.event
async def on_ready():
    print(f"✅ Online als {bot.user}")

    # UI automatisch updaten (damit UI nach Neustart immer funktioniert)
    for g in bot.guilds:
        ch = g.get_channel(VERIFY_CHANNEL_ID)
        if ch:
            try:
                await ensure_ui_message(ch)
                await log(g, "📌 Rollenvergabe UI wurde automatisch aktualisiert.")
            except Exception as e:
                print("UI update error:", e)

@bot.event
async def on_member_join(member: discord.Member):
    # Einreise Rolle automatisch geben
    role = discord.utils.get(member.guild.roles, name=AUTO_ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

bot.run(DISCORD_TOKEN)
