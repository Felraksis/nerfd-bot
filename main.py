import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()  # loads variables from .env into environment

# ==================== CONFIG ====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ROSTER_CHANNEL_ID = int(os.getenv("ROSTER_CHANNEL_ID"))
REQUIRED_ROLE_ID = int(os.getenv("REQUIRED_ROLE_ID"))

TEAMS = ["NERFD", "N3RFD"]

DATA_FILE = "team_data.json"
ROSTER_MSG_FILE = "roster_messages.json"

# ==================== DATA HANDLING ====================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {team: [] for team in TEAMS}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return {team: [] for team in TEAMS}

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print("⚠️ team_data.json was corrupt/empty, resetting.")
        return {team: [] for team in TEAMS}

    # Migration safety: discard invalid entries, ensure required keys exist
    for team in TEAMS:
        entries = data.get(team, [])
        cleaned = []
        for e in entries:
            if isinstance(e, dict) and "username" in e and "discord_id" in e:
                e.setdefault("team", team)
                e.setdefault("discord_name", "Unknown#0000")
                cleaned.append(e)
        data[team] = cleaned

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_roster_messages():
    if not os.path.exists(ROSTER_MSG_FILE):
        return {}

    with open(ROSTER_MSG_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return {}

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("⚠️ roster_messages.json was corrupt/empty, resetting.")
        return {}


def save_roster_messages(msg_map):
    with open(ROSTER_MSG_FILE, "w", encoding="utf-8") as f:
        json.dump(msg_map, f, indent=2)


# ==================== BOT SETUP ====================

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


def has_required_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member):
            role = interaction.guild.get_role(REQUIRED_ROLE_ID)
            if role and role in interaction.user.roles:
                return True
        await interaction.response.send_message(
            "🚫 You don't have permission to use this command.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# ==================== ROSTER EMBED BUILDING ====================

def build_team_embed(team: str, entries: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"📋 Team {team} Roster",
        color=discord.Color.blue() if team == "NERFD" else discord.Color.purple()
    )

    if not entries:
        embed.description = "*No members registered yet.*"
        return embed

    lines = []

    for entry in entries:
        mention = f"<@{entry['discord_id']}>"
        link = f"https://warthunder.com/en/community/userinfo/?nick={quote(entry['username'])}"
        lines.append(f"{mention} — [{entry['username']}]({link})")


    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Total members: {len(entries)}")
    return embed


async def update_roster_embeds(guild: discord.Guild):
    data = load_data()
    msg_map = load_roster_messages()

    channel = guild.get_channel(ROSTER_CHANNEL_ID)
    if channel is None:
        try:
            channel = await guild.fetch_channel(ROSTER_CHANNEL_ID)
        except discord.NotFound:
            print("⚠️ Roster channel not found.")
            return

    for team in TEAMS:
        embed = build_team_embed(team, data[team])
        msg_id = msg_map.get(team)

        message = None
        if msg_id:
            try:
                message = await channel.fetch_message(msg_id)
            except discord.NotFound:
                message = None

        if message:
            await message.edit(embed=embed)
        else:
            new_msg = await channel.send(embed=embed)
            msg_map[team] = new_msg.id

    save_roster_messages(msg_map)


# ==================== MODAL ====================

class UsernameModal(discord.ui.Modal, title="War Thunder Registration"):
    def __init__(self, team: str, original_message: discord.Message):
        super().__init__()
        self.team = team
        self.original_message = original_message

    username = discord.ui.TextInput(
        label="War Thunder Username",
        placeholder="Enter your exact WT nickname",
        required=True,
        max_length=64
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        submitted_username = self.username.value.strip()
        user_id = interaction.user.id

        # --- Check 1: Is this WT username already registered? ---
        for t in TEAMS:
            for entry in data[t]:
                if entry["username"].lower() == submitted_username.lower():
                    if entry["discord_id"] != user_id:
                        # Registered by someone else entirely
                        embed = discord.Embed(
                            title="⚠️ Duplicate Username",
                            description=(
                                f"The War Thunder name **{submitted_username}** is already registered "
                                f"by <@{entry['discord_id']}> (`{entry['discord_name']}`) on team **{t}**.\n\n"
                                f"If you believe this is a mistake, please contact an admin."
                            ),
                            color=discord.Color.red()
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return
                    else:
                        # Same user trying to register the exact same name again — reject, no changes
                        embed = discord.Embed(
                            title="⚠️ Already Registered",
                            description=(
                                f"You're already registered as **{submitted_username}** on team **{t}**.\n"
                                f"This entry was **not** duplicated."
                            ),
                            color=discord.Color.orange()
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

        # --- Check 2: Does this Discord ID already have OTHER entries (different username)? ---
        existing_entries = []
        for t in TEAMS:
            for entry in data[t]:
                if entry["discord_id"] == user_id:
                    existing_entries.append(entry)

        if existing_entries:
            embed = discord.Embed(
                title="🔁 Existing Registration Found",
                description=(
                    f"You already have {len(existing_entries)} account(s) registered:\n\n" +
                    "\n".join(f"• **{e['username']}** ({e.get('team', '?')})" for e in existing_entries) +
                    "\n\nWhat would you like to do with your new submission "
                    f"(**{submitted_username}** on team **{self.team}**)?"
                ),
                color=discord.Color.blurple()
            )
            view = OverrideView(self.team, submitted_username, existing_entries, self.original_message)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        # --- No conflicts: register fresh ---
        data[self.team].append({
            "discord_id": user_id,
            "discord_name": str(interaction.user),
            "username": submitted_username,
            "team": self.team
        })
        save_data(data)
        await update_roster_embeds(interaction.guild)

        embed = discord.Embed(
            title="✅ Registered!",
            description=(
                f"Registered as **{submitted_username}** on team **{self.team}**!\n"
                f"🔗 https://warthunder.com/en/community/userinfo/?nick={submitted_username}"
            ),
            color=discord.Color.green()
        )
        try:
            await self.original_message.edit(embed=embed, view=None)
            await interaction.response.defer()
        except discord.HTTPException:
            await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== DUPLICATE HANDLING VIEWS ====================

class OverrideSelect(discord.ui.Select):
    """Shown when the same Discord ID already has one or more entries."""
    def __init__(self, team: str, username: str, existing_entries: list, original_message: discord.Message):
        self.team = team
        self.username = username
        self.original_message = original_message
        self.existing_entries = existing_entries

        options = []
        for idx, entry in enumerate(existing_entries):
            options.append(
                discord.SelectOption(
                    label=f"Override: {entry['username']} ({entry.get('team', '?')})",
                    description="Replace this existing entry with your new submission",
                    value=str(idx)
                )
            )
        options.append(
            discord.SelectOption(
                label="➕ Add as a new/second account",
                description="Keep existing entries and add this as an additional one",
                value="new"
            )
        )

        super().__init__(placeholder="Choose what to do...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        user_id = interaction.user.id

        # Double-check the new username still isn't taken by someone else (race condition safety)
        for t in TEAMS:
            for entry in data[t]:
                if entry["username"].lower() == self.username.lower() and entry["discord_id"] != user_id:
                    embed = discord.Embed(
                        title="⚠️ Duplicate Username",
                        description=(
                            f"The War Thunder name **{self.username}** is already registered "
                            f"by <@{entry['discord_id']}> (`{entry['discord_name']}`) on team **{t}**.\n\n"
                            f"If you believe this is a mistake, please contact an admin."
                        ),
                        color=discord.Color.red()
                    )
                    await interaction.response.edit_message(embed=embed, view=None)
                    return

        if self.values[0] == "new":
            data[self.team].append({
                "discord_id": user_id,
                "discord_name": str(interaction.user),
                "username": self.username,
                "team": self.team
            })
            result_desc = f"Added **{self.username}** as a new account on team **{self.team}**!"
        else:
            idx = int(self.values[0])
            target_entry = self.existing_entries[idx]
            target_team = target_entry.get("team")

            # Remove the old entry from its team list
            if target_team in TEAMS:
                data[target_team] = [
                    e for e in data[target_team]
                    if not (e["discord_id"] == user_id and e["username"] == target_entry["username"])
                ]

            # Add the new one to the selected team
            data[self.team].append({
                "discord_id": user_id,
                "discord_name": str(interaction.user),
                "username": self.username,
                "team": self.team
            })
            result_desc = (
                f"Replaced **{target_entry['username']}** with **{self.username}** "
                f"on team **{self.team}**!"
            )

        save_data(data)
        await update_roster_embeds(interaction.guild)

        embed = discord.Embed(
            title="✅ Registration Updated",
            description=(
                f"{result_desc}\n"
                f"🔗 https://warthunder.com/en/community/userinfo/?nick={self.username}"
            ),
            color=discord.Color.green()
        )

        # Update the ephemeral confirmation message
        await interaction.response.edit_message(embed=embed, view=None)

        # Also update the original team-selection message
        try:
            final_embed = discord.Embed(
                title="✅ Registered!",
                description=(
                    f"Registered as **{self.username}** on team **{self.team}**!\n"
                    f"🔗 https://warthunder.com/en/community/userinfo/?nick={self.username}"
                ),
                color=discord.Color.green()
            )
            await self.original_message.edit(embed=final_embed, view=None)
        except discord.HTTPException:
            pass


class OverrideView(discord.ui.View):
    def __init__(self, team: str, username: str, existing_entries: list, original_message: discord.Message):
        super().__init__(timeout=120)
        self.add_item(OverrideSelect(team, username, existing_entries, original_message))


# ==================== TEAM SELECT VIEW ====================

class TeamSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="NERFD", description="Join team NERFD"),
            discord.SelectOption(label="N3RFD", description="Join team N3RFD"),
        ]
        super().__init__(placeholder="Select your team...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        team = self.values[0]
        original_message = interaction.message
        await interaction.response.send_modal(UsernameModal(team, original_message))


class TeamSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TeamSelect())


# ==================== REGISTRATION BUTTON VIEW ====================

class RegisterButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="register_button")
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Team Registration",
            description="Please select your team below:",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=TeamSelectView(), ephemeral=True)


# ==================== SLASH COMMAND ====================

@bot.tree.command(name="register", description="Post the team registration message")
@has_required_role()
async def register(interaction: discord.Interaction):
    THUMBNAIL_URL = "https://cdn.discordapp.com/avatars/1514660834398175355/604b0c8d44629b88f95186555f8b2635.webp?size=1024"

    embed = discord.Embed(
        title="Squad Registration",
        description="Please press the button below, to sync your Warthunder and Discord Account!",
        color=discord.Color.from_str("#E91E3A")
    )
    embed.set_thumbnail(url=THUMBNAIL_URL)
    embed.set_footer(text="NERFD™ HQ Announcements", icon_url=THUMBNAIL_URL)

    view = RegisterButtonView()
    await interaction.response.send_message(embed=embed, view=view)



@register.error
async def register_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        pass  # Already handled in the check itself
    else:
        print(f"Unexpected error in /register: {error}")


# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    bot.add_view(RegisterButtonView())
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")




# ==================== RUN ====================

bot.run(BOT_TOKEN)
