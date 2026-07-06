import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from urllib.parse import quote
import re
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

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

APPLICATIONS_FILE = "applications.json"

APPLICATION_CATEGORY_ID = 1453607606089285653
TICKET_BOT_ID = 718493970652594217
OFFICER_ROLE_ID = 1395796314150666380
OFFICER_REVIEW_ROLE_ID = 1395796314150666380
LOG_CHANNEL_ID = 1523740893755211786
SQB_REGION_CHANNEL_ID = 1509920425952678051

PRIVATE_ROLE_ID = 1361383932167196815
NERFD_SQUAD_ROLE_ID = 1460059995570962533
N3RFD_SQUAD_ROLE_ID = 1460059961169023039
VERIFIED_WT_ROLE_ID = 1523663455830147122
SQB_RESERVE_ROLE_ID = 1400809049880006749

THUMBNAIL_URL = "https://cdn.discordapp.com/avatars/1514660834398175355/604b0c8d44629b88f95186555f8b2635.webp?size=1024"

APP_COLOR_PENDING = discord.Color.from_str("#2985CC")
APP_COLOR_ACCEPTED = discord.Color.from_str("#77B255")
APP_COLOR_REJECTED = discord.Color.from_str("#E91E3A")


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

def load_applications():
    if not os.path.exists(APPLICATIONS_FILE):
        return {}
    with open(APPLICATIONS_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}

def save_applications(data):
    with open(APPLICATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)



# ==================== BOT SETUP ====================

intents = discord.Intents.default()
intents.message_content = True   # ADD THIS LINE

bot = commands.Bot(command_prefix="!", intents=intents)



def has_officer_permission(member: discord.Member) -> bool:
    return any(role.id == OFFICER_REVIEW_ROLE_ID for role in member.roles)


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
        lines.append(f"{mention} — `{entry['username']}` [[+]]({link})")

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

# ==================== REMOVE/EDIT ENTRY SYSTEM ====================

class ConfirmDeleteModal(discord.ui.Modal, title="Confirm Deletion"):
    def __init__(self, team: str, entry: dict, parent_view: "EntryActionView"):
        super().__init__()
        self.team = team
        self.entry = entry
        self.parent_view = parent_view

    confirm_text = discord.ui.TextInput(
        label='Type "Confirm" to delete this entry',
        placeholder="Confirm",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_text.value.strip().lower() != "confirm":
            await interaction.response.send_message(
                "❌ Confirmation text did not match. Deletion cancelled.", ephemeral=True
            )
            return

        data = load_data()
        data[self.team] = [
            e for e in data[self.team]
            if not (e["discord_id"] == self.entry["discord_id"] and e["username"] == self.entry["username"])
        ]
        save_data(data)
        await update_roster_embeds(interaction.guild)

        embed = discord.Embed(
            title="🗑️ Entry Deleted",
            description=(
                f"Removed **{self.entry['username']}** (<@{self.entry['discord_id']}>) "
                f"from team **{self.team}**."
            ),
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class EditUsernameModal(discord.ui.Modal, title="Edit Username"):
    def __init__(self, team: str, entry: dict):
        super().__init__()
        self.team = team
        self.entry = entry

    new_username = discord.ui.TextInput(
        label="New War Thunder Username",
        required=True,
        max_length=64
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.new_username.value.strip()
        data = load_data()

        # Check for conflicts with other entries (any team)
        for t in TEAMS:
            for e in data[t]:
                if e["username"].lower() == new_name.lower() and not (
                    e["discord_id"] == self.entry["discord_id"] and e["username"] == self.entry["username"]
                ):
                    embed = discord.Embed(
                        title="⚠️ Duplicate Username",
                        description=(
                            f"**{new_name}** is already registered by <@{e['discord_id']}> "
                            f"(`{e['discord_name']}`) on team **{t}**. Edit cancelled."
                        ),
                        color=discord.Color.red()
                    )
                    await interaction.response.edit_message(embed=embed, view=None)
                    return

        # Apply the edit
        for e in data[self.team]:
            if e["discord_id"] == self.entry["discord_id"] and e["username"] == self.entry["username"]:
                e["username"] = new_name
                break

        save_data(data)
        await update_roster_embeds(interaction.guild)

        embed = discord.Embed(
            title="✏️ Entry Updated",
            description=(
                f"<@{self.entry['discord_id']}> is now registered as **{new_name}** "
                f"on team **{self.team}**.\n"
                f"🔗 https://warthunder.com/en/community/userinfo/?nick={quote(new_name)}"
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class EntryActionView(discord.ui.View):
    """Shows Delete/Edit buttons for a single selected entry."""
    def __init__(self, team: str, entry: dict):
        super().__init__(timeout=120)
        self.team = team
        self.entry = entry

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ConfirmDeleteModal(self.team, self.entry, self))

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditUsernameModal(self.team, self.entry))


class EntrySelect(discord.ui.Select):
    """Lists entries for the chosen team; selecting one shows action buttons."""
    def __init__(self, team: str, entries: list):
        self.team = team
        self.entries = entries

        options = []
        for idx, entry in enumerate(entries):
            options.append(
                discord.SelectOption(
                    label=entry["username"][:100],
                    description=f"Discord: {entry.get('discord_name', 'Unknown')}"[:100],
                    value=str(idx)
                )
            )

        super().__init__(placeholder="Select an entry...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        entry = self.entries[idx]

        embed = discord.Embed(
            title="📄 Entry Details",
            description=(
                f"**Username:** {entry['username']}\n"
                f"**Discord:** <@{entry['discord_id']}> (`{entry.get('discord_name', 'Unknown')}`)\n"
                f"**Team:** {self.team}\n"
                f"🔗 https://warthunder.com/en/community/userinfo/?nick={quote(entry['username'])}"
            ),
            color=discord.Color.blurple()
        )
        view = EntryActionView(self.team, entry)
        await interaction.response.edit_message(embed=embed, view=view)


class EntrySelectView(discord.ui.View):
    def __init__(self, team: str, entries: list):
        super().__init__(timeout=120)
        self.add_item(EntrySelect(team, entries))


class TeamPickSelect(discord.ui.Select):
    """First step: pick which team's roster to browse."""
    def __init__(self, data: dict):
        self.data = data
        options = [
            discord.SelectOption(
                label=team,
                description=f"{len(data[team])} entries"
            ) for team in TEAMS
        ]
        super().__init__(placeholder="Select a squad...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        team = self.values[0]
        entries = self.data[team]

        if not entries:
            embed = discord.Embed(
                title=f"📋 {team} Entries",
                description="*No entries in this squad.*",
                color=discord.Color.greyple()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return

        lines = [f"• **{e['username']}** — <@{e['discord_id']}>" for e in entries]
        embed = discord.Embed(
            title=f"📋 {team} Entries",
            description="\n".join(lines) + "\n\nSelect an entry below to manage it:",
            color=discord.Color.blue() if team == "NERFD" else discord.Color.purple()
        )
        view = EntrySelectView(team, entries)
        await interaction.response.edit_message(embed=embed, view=view)


class TeamPickView(discord.ui.View):
    def __init__(self, data: dict):
        super().__init__(timeout=120)
        self.add_item(TeamPickSelect(data))

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

# =================== BUILD APPLICATION EMBED =================

def build_application_embed(squad, applicant_id, ign, meets_requirements, age_confirmed, status="pending", handled_by=None):
    if status == "accepted":
        color = APP_COLOR_ACCEPTED
        title = "Application Accepted"
    elif status == "rejected":
        color = APP_COLOR_REJECTED
        title = "Application Rejected"
    else:
        color = APP_COLOR_PENDING
        title = "Application Pending"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Applicant", value=f"<@{applicant_id}>", inline=False)
    embed.add_field(name="Applying For", value=squad, inline=True)
    embed.add_field(name="In-Game Username", value=ign, inline=True)
    embed.add_field(name="Meets Requirements?", value=meets_requirements, inline=True)
    embed.add_field(name="Over 16?", value=age_confirmed, inline=True)

    if handled_by:
        embed.add_field(name="Handled By", value=f"<@{handled_by}>", inline=False)

    embed.set_thumbnail(url=THUMBNAIL_URL)
    embed.set_footer(text="NERFD™ HQ Applications", icon_url=THUMBNAIL_URL)
    return embed

# =================== BUILD APPLICATION EMBED BUTTONS =================

class ApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, emoji="✅", custom_id="app_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        apps = load_applications()
        record = apps.get(str(interaction.message.id))
        if not record or record["resolved"]:
            await interaction.response.send_message("⚠️ This application has already been resolved.", ephemeral=True)
            return
        await interaction.response.send_modal(AcceptConfirmModal(interaction.message.id))

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="❌", custom_id="app_reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        apps = load_applications()
        record = apps.get(str(interaction.message.id))
        if not record or record["resolved"]:
            await interaction.response.send_message("⚠️ This application has already been resolved.", ephemeral=True)
            return
        await interaction.response.send_modal(RejectConfirmModal(interaction.message.id))

    @discord.ui.button(label="Edit Application", style=discord.ButtonStyle.blurple, custom_id="app_edit")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        apps = load_applications()
        record = apps.get(str(interaction.message.id))
        if not record:
            await interaction.response.send_message("⚠️ Could not find application data.", ephemeral=True)
            return
        if record["resolved"]:
            await interaction.response.send_message("⚠️ This application has already been resolved.", ephemeral=True)
            return
        await interaction.response.send_modal(EditApplicationModal(interaction.message.id, record["ign"]))


# =================== DETECTING TICKETS =================

@bot.event
async def on_message(message: discord.Message):
    logging.info(
        f"on_message fired | author={message.author} (id={message.author.id}) | "
        f"bot={message.author.bot} | guild={message.guild} | "
        f"channel={message.channel} (id={message.channel.id}) | "
        f"content={message.content!r} | embeds={len(message.embeds)}"
    )

    if message.author.id == TICKET_BOT_ID:
        logging.info(f"Message is from TICKET_BOT_ID ({TICKET_BOT_ID}) ✅")

        if not message.guild:
            logging.info("Message has no guild (DM?) — skipping")
        else:
            channel = message.channel
            category_id = getattr(channel, "category_id", None)
            logging.info(
                f"Channel category_id={category_id} | expected={APPLICATION_CATEGORY_ID} | "
                f"match={category_id == APPLICATION_CATEGORY_ID}"
            )

            if category_id == APPLICATION_CATEGORY_ID:
                logging.info(f"Category matches. Embed count = {len(message.embeds)}")
                if message.embeds and len(message.embeds) >= 2:
                    logging.info("Embed count sufficient — calling handle_new_application()")
                    await handle_new_application(message)
                else:
                    logging.info("Embed count insufficient — skipping handle_new_application()")
            else:
                logging.info("Category does not match — skipping")
    else:
        logging.debug(f"Ignoring message from non-ticket-bot author (id={message.author.id})")

    await bot.process_commands(message)
    logging.info(
        f"is_webhook={message.webhook_id is not None} | webhook_id={message.webhook_id} | "
        f"author_id={message.author.id} | TICKET_BOT_ID={TICKET_BOT_ID}"
    )




def parse_squad_from_channel_name(name: str) -> str | None:
    name_lower = name.lower()
    if name_lower.startswith("nerfd-application"):
        return "NERFD"
    elif name_lower.startswith("n3rfd-application"):
        return "N3RFD"
    return None


def parse_ticket_embeds(embeds: list[discord.Embed]):
    first_embed = embeds[0]
    second_embed = embeds[1]

    applicant_id = None
    if first_embed.description:
        match = re.search(r"<@!?(\d+)>", first_embed.description)
        if match:
            applicant_id = int(match.group(1))

    ign = None
    meets_requirements = None
    age_confirmed = None

    for field in second_embed.fields:
        name = (field.name or "").lower()
        value = (field.value or "").strip()

        if "in game username" in name:
            ign = value
        elif "meet our application requirements" in name:
            meets_requirements = value
        elif "over the age of" in name or "age" in name:
            age_confirmed = value

    return applicant_id, ign, meets_requirements, age_confirmed



async def handle_new_application(ticket_message: discord.Message):
    channel = ticket_message.channel
    logging.info(f"handle_new_application START | message_id={ticket_message.id} | channel={channel.name}")

    squad = parse_squad_from_channel_name(channel.name)
    logging.info(f"Parsed squad = {squad!r} from channel name {channel.name!r}")
    if squad is None:
        logging.warning(f"⚠️ Could not determine squad from channel name: {channel.name}")
        return

    for i, e in enumerate(ticket_message.embeds):
        logging.info(f"Embed[{i}] title={e.title!r} description={e.description!r}")
        for f in e.fields:
            logging.info(f"Embed[{i}] field: name={f.name!r} value={f.value!r} inline={f.inline}")

    parsed = parse_ticket_embeds(ticket_message.embeds)
    logging.info(f"parse_ticket_embeds() returned: {parsed!r}")
    if parsed is None:
        logging.warning(f"⚠️ parse_ticket_embeds returned None for channel {channel.name}")
        return
    applicant_id, ign, meets_requirements, age_confirmed = parsed
    logging.info(
        f"Parsed application data | applicant_id={applicant_id} | ign={ign!r} | "
        f"meets_requirements={meets_requirements!r} | age_confirmed={age_confirmed!r}"
    )

    if applicant_id is None or ign is None:
        logging.warning(f"⚠️ Failed to parse ticket data in {channel.name} (applicant_id or ign missing)")
        return

    try:
        embed = build_application_embed(
            squad=squad,
            applicant_id=applicant_id,
            ign=ign,
            meets_requirements=meets_requirements,
            age_confirmed=age_confirmed,
            status="pending"
        )

        officer_role_mention = f"<@&{OFFICER_ROLE_ID}>"
        view = ApplicationView()
        mgmt_message = await channel.send(
            content=f"",
            embed=embed,
            view=view
        )
        logging.info(f"Sent application review embed | mgmt_message_id={mgmt_message.id}")

        apps = load_applications()
        apps[str(mgmt_message.id)] = {
            "applicant_id": applicant_id,
            "squad": squad,
            "ign": ign,
            "meets_requirements": meets_requirements or "Unknown",
            "age_confirmed": age_confirmed or "Unknown",
            "channel_id": channel.id,
            "resolved": False
        }
        save_applications(apps)
        logging.info(f"Saved application data for mgmt_message_id={mgmt_message.id} | {apps[str(mgmt_message.id)]}")

    except Exception:
        logging.exception(f"❌ handle_new_application failed while sending/saving for channel {channel.name}")
        return

    logging.info(f"handle_new_application COMPLETE | message_id={ticket_message.id}")


# ==================== APPLICATION BUTTON LOGIC ====================

OFFICER_REVIEW_ROLE_ID = 1523733774314246246

def has_officer_permission(member: discord.Member) -> bool:
    return any(role.id == OFFICER_REVIEW_ROLE_ID for role in member.roles)


class AcceptConfirmModal(discord.ui.Modal, title="Confirm Acceptance"):
    def __init__(self, message_id: int):
        super().__init__()
        self.message_id = message_id

    confirm = discord.ui.TextInput(
        label='Accept this application? (Yes/No)',
        placeholder="Yes or No",
        required=True,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not has_officer_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to do this.",
                ephemeral=True
            )
            return

        answer = self.confirm.value.strip().lower()
        if answer != "yes":
            await interaction.response.send_message("Cancelled — no changes made.", ephemeral=True)
            return

        apps = load_applications()
        record = apps.get(str(self.message_id))
        if not record or record["resolved"]:
            await interaction.response.send_message("⚠️ Application no longer available.", ephemeral=True)
            return

        guild = interaction.guild
        applicant_id = record["applicant_id"]
        squad = record["squad"]

        member = guild.get_member(applicant_id)
        if member is None:
            try:
                member = await guild.fetch_member(applicant_id)
            except discord.NotFound:
                member = None

        # Determine roles to assign
        role_ids = [PRIVATE_ROLE_ID, VERIFIED_WT_ROLE_ID]
        if squad == "NERFD":
            role_ids += [NERFD_SQUAD_ROLE_ID, SQB_RESERVE_ROLE_ID]
        else:
            role_ids += [N3RFD_SQUAD_ROLE_ID]

        assigned = []
        already_had = []

        if member:
            for rid in role_ids:
                role = guild.get_role(rid)
                if role is None:
                    continue
                if role in member.roles:
                    already_had.append(role.name)
                else:
                    try:
                        await member.add_roles(role, reason=f"Application accepted by {interaction.user}")
                        assigned.append(role.name)
                    except discord.HTTPException:
                        pass

        # Update record + save to team data
        record["resolved"] = True
        record["handled_by"] = interaction.user.id
        record["result"] = "accepted"
        apps[str(self.message_id)] = record
        save_applications(apps)

        data = load_data()
        data[squad].append({
            "discord_id": applicant_id,
            "discord_name": str(member) if member else str(applicant_id),
            "username": record["ign"],
            "team": squad
        })
        save_data(data)
        await update_roster_embeds(guild)

        # Update embed
        new_embed = build_application_embed(
            squad=squad,
            applicant_id=applicant_id,
            ign=record["ign"],
            meets_requirements=record["meets_requirements"],
            age_confirmed=record["age_confirmed"],
            status="accepted",
            handled_by=interaction.user.id
        )
        await interaction.message.edit(embed=new_embed, view=None)

        # Ephemeral reminder to officer
        role_summary = ""
        if assigned:
            role_summary += f"**Assigned:** {', '.join(assigned)}\n"
        if already_had:
            role_summary += f"**Already had:** {', '.join(already_had)}\n"
        if not member:
            role_summary = "⚠️ Could not find member in server to assign roles.\n"

        await interaction.response.send_message(
            f"✅ Application accepted!\n\n{role_summary}\n"
            f"🔔 Please remember to also **accept {record['ign']} in-game** or via the WT Assistant App.\n"
            f"📪 Please close this ticket using `/ticket close (reason)`.",
            ephemeral=True
        )

        # DM applicant
        if member:
            try:
                dm_embed = discord.Embed(
                    title="🎉 Application Accepted!",
                    description=(
                        f"Congratulations! Your application to join **{squad}** has been **accepted**.\n"
                        f"You will be accepted in-game shortly. Happy hunting! 🎯"
                    ),
                    color=APP_COLOR_ACCEPTED
                )
                dm_embed.add_field(name="In-Game Username", value=record["ign"], inline=True)
                dm_embed.add_field(name="Meets Requirements?", value=record["meets_requirements"], inline=True)
                dm_embed.add_field(name="Over 16?", value=record["age_confirmed"], inline=True)
                if squad == "NERFD":
                    dm_embed.add_field(
                        name="Next Step",
                        value=f"Please visit <#{SQB_REGION_CHANNEL_ID}> to select your SQB region.",
                        inline=False
                    )
                dm_embed.set_thumbnail(url=THUMBNAIL_URL)
                dm_embed.set_footer(text="NERFD™ HQ Applications", icon_url=THUMBNAIL_URL)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass

        # Log
        await send_application_log(guild, record, interaction.user.id, "accepted")


class RejectConfirmModal(discord.ui.Modal, title="Confirm Rejection"):
    def __init__(self, message_id: int):
        super().__init__()
        self.message_id = message_id

    confirm = discord.ui.TextInput(
        label='Reject this application? (Yes/No)',
        placeholder="Yes or No",
        required=True,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not has_officer_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to do this.",
                ephemeral=True
            )
            return

        answer = self.confirm.value.strip().lower()
        if answer != "yes":
            await interaction.response.send_message("Cancelled — no changes made.", ephemeral=True)
            return

        apps = load_applications()
        record = apps.get(str(self.message_id))
        if not record or record["resolved"]:
            await interaction.response.send_message("⚠️ Application no longer available.", ephemeral=True)
            return

        guild = interaction.guild
        applicant_id = record["applicant_id"]
        squad = record["squad"]

        record["resolved"] = True
        record["handled_by"] = interaction.user.id
        record["result"] = "rejected"
        apps[str(self.message_id)] = record
        save_applications(apps)

        new_embed = build_application_embed(
            squad=squad,
            applicant_id=applicant_id,
            ign=record["ign"],
            meets_requirements=record["meets_requirements"],
            age_confirmed=record["age_confirmed"],
            status="rejected",
            handled_by=interaction.user.id
        )
        await interaction.message.edit(embed=new_embed, view=None)

        await interaction.response.send_message(
            f"❌ Application rejected.\n\n"
            f"⚠️ Please do **not** accept {record['ign']} in-game or via the WT Assistant App.\n"
            f"📪 Please close this ticket using `/ticket close (reason)`.",
            ephemeral=True
        )

        member = guild.get_member(applicant_id)
        if member is None:
            try:
                member = await guild.fetch_member(applicant_id)
            except discord.NotFound:
                member = None

        if member:
            try:
                dm_embed = discord.Embed(
                    title="Application Update",
                    description=(
                        f"We're sorry to inform you that your application to join **{squad}** "
                        f"has been **rejected**."
                    ),
                    color=APP_COLOR_REJECTED
                )
                dm_embed.add_field(name="In-Game Username", value=record["ign"], inline=True)
                dm_embed.add_field(name="Meets Requirements?", value=record["meets_requirements"], inline=True)
                dm_embed.add_field(name="Over 16?", value=record["age_confirmed"], inline=True)
                dm_embed.set_thumbnail(url=THUMBNAIL_URL)
                dm_embed.set_footer(text="NERFD™ HQ Applications", icon_url=THUMBNAIL_URL)
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass

        await send_application_log(guild, record, interaction.user.id, "rejected")


class EditApplicationModal(discord.ui.Modal, title="Edit Application"):
    def __init__(self, message_id: int, current_ign: str):
        super().__init__()
        self.message_id = message_id
        self.ign_input.default = current_ign

    ign_input = discord.ui.TextInput(
        label="In-Game Username",
        required=True,
        max_length=64
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not has_officer_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to do this.",
                ephemeral=True
            )
            return

        apps = load_applications()
        record = apps.get(str(self.message_id))
        if not record or record["resolved"]:
            await interaction.response.send_message("⚠️ Application no longer available.", ephemeral=True)
            return

        record["ign"] = self.ign_input.value.strip()
        apps[str(self.message_id)] = record
        save_applications(apps)

        new_embed = build_application_embed(
            squad=record["squad"],
            applicant_id=record["applicant_id"],
            ign=record["ign"],
            meets_requirements=record["meets_requirements"],
            age_confirmed=record["age_confirmed"],
            status="pending"
        )
        await interaction.message.edit(embed=new_embed, view=ApplicationView())
        await interaction.response.send_message("✅ Application updated.", ephemeral=True)


async def send_application_log(guild: discord.Guild, record: dict, handled_by_id: int, result: str):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await guild.fetch_channel(LOG_CHANNEL_ID)
        except discord.NotFound:
            return

    color = APP_COLOR_ACCEPTED if result == "accepted" else APP_COLOR_REJECTED
    title = "📄 Application Accepted" if result == "accepted" else "📄 Application Rejected"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Applicant", value=f"<@{record['applicant_id']}>", inline=False)
    embed.add_field(name="Squad", value=record["squad"], inline=True)
    embed.add_field(name="In-Game Username", value=record["ign"], inline=True)
    embed.add_field(name="Meets Requirements?", value=record["meets_requirements"], inline=True)
    embed.add_field(name="Over 16?", value=record["age_confirmed"], inline=True)
    embed.add_field(name="Handled By", value=f"<@{handled_by_id}>", inline=False)
    embed.set_thumbnail(url=THUMBNAIL_URL)
    embed.set_footer(text="NERFD™ HQ Applications", icon_url=THUMBNAIL_URL)

    await channel.send(embed=embed)



# ==================== SLASH COMMANDS ====================

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

@bot.tree.command(name="check", description="Check your currently registered War Thunder account(s)")
async def check(interaction: discord.Interaction):
    data = load_data()
    user_id = interaction.user.id

    entries = []
    for t in TEAMS:
        for entry in data[t]:
            if entry["discord_id"] == user_id:
                entries.append(entry)

    if not entries:
        embed = discord.Embed(
            title="🔍 Registration Check",
            description=(
                "You don't have any War Thunder account linked yet.\n\n"
                "Use the registration button in the announcement channel to get set up!"
            ),
            color=discord.Color.red()
        )
    else:
        lines = []
        for entry in entries:
            link = f"https://warthunder.com/en/community/userinfo/?nick={quote(entry['username'])}"
            lines.append(f"• **{entry['username']}** — Team **{entry.get('team', '?')}**\n  🔗 {link}")

        embed = discord.Embed(
            title="🔍 Registration Check",
            description=(
                f"You currently have **{len(entries)}** account(s) registered:\n\n" +
                "\n".join(lines)
            ),
            color=discord.Color.green()
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== /remove COMMAND ====================

@bot.tree.command(name="remove", description="View, edit, or delete registered entries")
@has_required_role()
async def remove(interaction: discord.Interaction):
    data = load_data()

    all_lines = []
    for team in TEAMS:
        if data[team]:
            all_lines.append(f"**{team}:**")
            for e in data[team]:
                all_lines.append(f"• {e['username']} — <@{e['discord_id']}>")
        else:
            all_lines.append(f"**{team}:** *No entries*")

    embed = discord.Embed(
        title="🗂️ All Registered Entries",
        description="\n".join(all_lines) if all_lines else "*No entries at all.*",
        color=discord.Color.dark_gold()
    )
    embed.add_field(name="\u200b", value="Select a squad below to manage its entries:", inline=False)

    view = TeamPickView(data)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@remove.error
async def remove_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        pass
    else:
        print(f"Unexpected error in /remove: {error}")

# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():

    bot.add_view(RegisterButtonView())
    bot.add_view(ApplicationView())
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info(f"Connected to {len(bot.guilds)} guild(s)")




# ==================== RUN ====================

bot.run(BOT_TOKEN)
