import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import json
from flask import Flask
from threading import Thread
from datetime import datetime, timezone, timedelta
import pytz
import time
import sqlite3
import uuid
import re
import io
import sys
import signal
import aiohttp

# ========== DATABASE SETUP ==========

# Initialize announcements database
def init_announcements_db():
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS announcements
                 (id TEXT PRIMARY KEY,
                  title TEXT,
                  description TEXT,
                  role_id TEXT,
                  channel_id TEXT,
                  announce_time TEXT,
                  created_by TEXT,
                  created_by_name TEXT,
                  created_at TEXT,
                  status TEXT)''')
    conn.commit()
    conn.close()

# Initialize LFM database for GLOBAL cooldown
def init_lfm_db():
    conn = sqlite3.connect('lfm.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS lfm_global_cooldown
                 (id INTEGER PRIMARY KEY CHECK (id = 1),
                  last_used TIMESTAMP,
                  last_user_id TEXT,
                  last_user_name TEXT)''')
    c.execute("INSERT OR IGNORE INTO lfm_global_cooldown (id, last_used, last_user_id, last_user_name) VALUES (1, ?, ?, ?)",
              (datetime.now().isoformat(), "0", "None"))
    conn.commit()
    conn.close()

# Initialize Top 10 Players database
def init_top10_db():
    conn = sqlite3.connect('top10.db')
    c = conn.cursor()
    
    # Create table for each position
    positions = ['GK', 'LB', 'RB', 'CB', 'CM', 'CDM', 'CAM', 'LM', 'RM', 'LW', 'RW', 'ST']
    
    for position in positions:
        c.execute(f'''CREATE TABLE IF NOT EXISTS top10_{position}
                     (rank INTEGER PRIMARY KEY,
                      player_name TEXT,
                      card_name TEXT,
                      rating INTEGER,
                      special TEXT,
                      updated_by TEXT,
                      updated_at TIMESTAMP)''')
        
        # Check if table is empty, insert default placeholders
        c.execute(f"SELECT COUNT(*) FROM top10_{position}")
        count = c.fetchone()[0]
        
        if count == 0:
            for i in range(1, 11):
                c.execute(f"INSERT INTO top10_{position} (rank, player_name, card_name, rating, special, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (i, f"Player {i}", f"Card {i}", 90 - i, "Base", "system", datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

# Call these when bot starts
print("📁 Initializing databases...")
init_announcements_db()
init_lfm_db()
init_top10_db()
print("✅ Databases initialized")

# Top 10 Functions
def get_top10(position):
    """Get top 10 players for a position"""
    conn = sqlite3.connect('top10.db')
    c = conn.cursor()
    c.execute(f"SELECT rank, player_name, card_name, rating, special, updated_by, updated_at FROM top10_{position} ORDER BY rank")
    results = c.fetchall()
    conn.close()
    return results

def update_top10_entry(position, rank, player_name, card_name, rating, special, updated_by):
    """Update a top 10 entry"""
    conn = sqlite3.connect('top10.db')
    c = conn.cursor()
    c.execute(f"UPDATE top10_{position} SET player_name = ?, card_name = ?, rating = ?, special = ?, updated_by = ?, updated_at = ? WHERE rank = ?",
              (player_name, card_name, rating, special, updated_by, datetime.now().isoformat(), rank))
    conn.commit()
    conn.close()
    return True

def swap_top10_entries(position, rank1, rank2):
    """Swap two entries in top 10"""
    conn = sqlite3.connect('top10.db')
    c = conn.cursor()
    
    # Get both entries
    c.execute(f"SELECT player_name, card_name, rating, special, updated_by, updated_at FROM top10_{position} WHERE rank = ?", (rank1,))
    entry1 = c.fetchone()
    c.execute(f"SELECT player_name, card_name, rating, special, updated_by, updated_at FROM top10_{position} WHERE rank = ?", (rank2,))
    entry2 = c.fetchone()
    
    if entry1 and entry2:
        # Update them swapped
        c.execute(f"UPDATE top10_{position} SET player_name = ?, card_name = ?, rating = ?, special = ?, updated_by = ?, updated_at = ? WHERE rank = ?",
                  (entry2[0], entry2[1], entry2[2], entry2[3], "system", datetime.now().isoformat(), rank1))
        c.execute(f"UPDATE top10_{position} SET player_name = ?, card_name = ?, rating = ?, special = ?, updated_by = ?, updated_at = ? WHERE rank = ?",
                  (entry1[0], entry1[1], entry1[2], entry1[3], "system", datetime.now().isoformat(), rank2))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False

# LFM Global Cooldown functions
def check_lfm_global_cooldown():
    """Check if LFM is on global cooldown"""
    conn = sqlite3.connect('lfm.db')
    c = conn.cursor()
    c.execute("SELECT last_used, last_user_id, last_user_name FROM lfm_global_cooldown WHERE id = 1")
    result = c.fetchone()
    conn.close()
    
    if result:
        last_used = datetime.fromisoformat(result[0])
        last_user_id = result[1]
        last_user_name = result[2]
        time_passed = datetime.now() - last_used
        if time_passed.total_seconds() < 300:
            remaining = 300 - time_passed.total_seconds()
            return True, remaining, last_user_id, last_user_name
    return False, 0, None, None

def update_lfm_global_cooldown(user_id, user_name):
    """Update global cooldown with who used it"""
    conn = sqlite3.connect('lfm.db')
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE lfm_global_cooldown SET last_used = ?, last_user_id = ?, last_user_name = ? WHERE id = 1",
              (now, user_id, user_name))
    conn.commit()
    conn.close()

# Function to parse timestamp from various formats
def parse_timestamp(timestamp_str):
    """Parse timestamp from various formats (Unix timestamp or Discord timestamp)"""
    timestamp_str = timestamp_str.strip()
    
    # Check if it's a Discord timestamp format like <t:1734567890>
    discord_match = re.match(r'<t:(\d+)>', timestamp_str)
    if discord_match:
        return int(discord_match.group(1))
    
    # Check if it's a pure Unix timestamp
    try:
        ts = int(timestamp_str)
        # Check if it's a valid timestamp (10 digits for seconds, 13 for milliseconds)
        if len(str(ts)) == 13:
            ts = ts // 1000  # Convert milliseconds to seconds
        return ts
    except ValueError:
        pass
    
    return None

# Function to add announcement
def add_announcement_to_db(title, description, role_id, channel_id, announce_time, created_by, created_by_name):
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    announcement_id = str(uuid.uuid4())[:8]
    c.execute("INSERT INTO announcements (id, title, description, role_id, channel_id, announce_time, created_by, created_by_name, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (announcement_id, title, description, role_id, channel_id, announce_time.isoformat(), created_by, created_by_name, datetime.now().isoformat(), "pending"))
    conn.commit()
    conn.close()
    return announcement_id

# Function to get pending announcements
def get_pending_announcements():
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT * FROM announcements WHERE status = 'pending' AND announce_time <= ?", (now,))
    announcements = c.fetchall()
    conn.close()
    return announcements

# Function to update announcement status
def update_announcement_status(announcement_id, status):
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    c.execute("UPDATE announcements SET status = ? WHERE id = ?", (status, announcement_id))
    conn.commit()
    conn.close()

# Function to get user's announcements
def get_user_announcements(created_by):
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    c.execute("SELECT * FROM announcements WHERE created_by = ? ORDER BY announce_time", (created_by,))
    announcements = c.fetchall()
    conn.close()
    return announcements

# Function to delete announcement
def delete_announcement(announcement_id, created_by):
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    c.execute("DELETE FROM announcements WHERE id = ? AND created_by = ?", (announcement_id, created_by))
    rows_affected = c.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

# Function to cancel announcement
def cancel_announcement(announcement_id, created_by):
    conn = sqlite3.connect('announcements.db')
    c = conn.cursor()
    c.execute("UPDATE announcements SET status = 'cancelled' WHERE id = ? AND created_by = ?", (announcement_id, created_by))
    rows_affected = c.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

# Keep-alive server for 24/7 hosting
app = Flask('')

@app.route('/')
def home():
    try:
        latency = round(bot.latency * 1000) if hasattr(bot, 'latency') and bot.latency else 0
        servers = len(bot.guilds) if hasattr(bot, 'guilds') else 0
        return f"⚡ Ω Lite is running! Servers: {servers} | Latency: {latency}ms"
    except:
        return "⚡ Ω Lite is starting up... Please wait a moment."

def run():
    # Use Render's provided PORT environment variable, fallback to 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True # Ensures thread closes cleanly when bot stops
    t.start()

# ========== SELF-PING FUNCTION TO KEEP BOT ALIVE ==========
async def self_ping():
    """Ping the external URL every 14 minutes to trick Render's idle detector"""
    await bot.wait_until_ready()
    
    # NOTE: Set this environment variable in Render, or replace the fallback string with your actual URL
    RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://your-bot-name.onrender.com")
    
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_EXTERNAL_URL) as response:
                    if response.status == 200:
                        print(f"🔄 External ping sent at {datetime.now().strftime('%H:%M:%S')} - Bot kept alive")
                    else:
                        print(f"⚠️ External ping returned status: {response.status}")
        except Exception as e:
            print(f"⚠️ External ping failed: {e}. Ensure RENDER_EXTERNAL_URL is correct.")
        
        await asyncio.sleep(840)  # Ping every 14 minutes (840 seconds). Render sleeps at 15m.

# Load formations data
def load_formations():
    try:
        with open('formations.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "formations": {
                "manager_mode": ["4-2-4", "4-3-3 Holding", "4-2-3-1 Wide", "4-3-3 Attack", "4-1-2-1-2 Narrow", "4-2-1-3"],
                "vs_attack": ["4-2-4", "3-5-2", "3-4-1-2", "3-4-2-1", "5-2-2-1", "4-3-3 Attack", "4-2-1-3", "5-3-2", "4-3-3 Holding"],
                "head_to_head": ["4-2-1-3", "4-2-3-1", "3-5-2", "4-2-2-2", "4-3-3 Holding", "4-3-3 Attack", "4-2-4", "4-1-2-1-2 Wide", "4-1-2-1-2 Narrow"]
            }
        }

# Load redeem codes
def load_redeem_codes():
    try:
        with open('redeem_codes.json', 'r') as f:
            data = json.load(f)
            if "redeem_codes" not in data:
                data["redeem_codes"] = []
            if "redeem_history" not in data:
                data["redeem_history"] = {}
            return data
    except FileNotFoundError:
        default_codes = {
            "redeem_codes": [],
            "redeem_history": {},
            "last_updated": ""
        }
        save_redeem_codes(default_codes)
        return default_codes

# Save redeem codes
def save_redeem_codes(data):
    try:
        with open('redeem_codes.json', 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving redeem codes: {e}")
        return False

# Check if user has permission to manage redeem codes
def can_manage_redeem_codes(user_id):
    authorized_users = [
        1214456066687893506,
        553418145063239684,
        1221841129151139841
    ]
    return user_id in authorized_users

# Check if user has permission to edit top 10
def can_edit_top10(user_id):
    authorized_users = [
        1214456066687893506,
        553418145063239684
    ]
    return user_id in authorized_users

# Common timezone abbreviations mapping
TIMEZONE_MAPPING = {
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    "HAST": "Pacific/Honolulu",
    "GMT": "Europe/London",
    "BST": "Europe/London",
    "UTC": "UTC",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "EET": "Europe/Helsinki",
    "EEST": "Europe/Helsinki",
    "WET": "Europe/Lisbon",
    "WEST": "Europe/Lisbon",
    "IST": "Asia/Kolkata",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "CST_CHINA": "Asia/Shanghai",
    "HKT": "Asia/Hong_Kong",
    "SGT": "Asia/Singapore",
    "PHT": "Asia/Manila",
    "WIB": "Asia/Jakarta",
    "WITA": "Asia/Makassar",
    "WIT": "Asia/Jayapura",
    "PKT": "Asia/Karachi",
    "BDT": "Asia/Dhaka",
    "MMT": "Asia/Yangon",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "ACST": "Australia/Adelaide",
    "ACDT": "Australia/Adelaide",
    "AWST": "Australia/Perth",
    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
    "SAST": "Africa/Johannesburg",
    "EAT": "Africa/Nairobi",
    "MSK": "Europe/Moscow",
    "GST": "Asia/Dubai",
}

def get_timezone_from_abbreviation(abbr):
    abbr_upper = abbr.upper()
    if abbr_upper in TIMEZONE_MAPPING:
        return pytz.timezone(TIMEZONE_MAPPING[abbr_upper])
    try:
        if "/" in abbr:
            return pytz.timezone(abbr)
        for tz_name in pytz.all_timezones:
            if abbr_upper in tz_name.upper():
                return pytz.timezone(tz_name)
    except:
        pass
    return None

class FCOHomiesBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!',
            intents=discord.Intents.all(),
            help_command=None
        )
        self.formations_data = load_formations()
        self.redeem_data = load_redeem_codes()
        self.lfm_role_id = 1391787410182111456

    async def setup_hook(self):
        # Wait to avoid rate limits on startup
        print("🔄 Waiting 5 seconds before syncing commands to avoid rate limits...")
        await asyncio.sleep(5)
        print("🔄 Syncing slash commands...")
        try:
            synced = await self.tree.sync()
            print(f"✅ Slash commands synced globally! {len(synced)} commands loaded.")
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print("⚠️ Rate limited while syncing commands. Will retry later.")
                # Retry after 10 seconds
                await asyncio.sleep(10)
                try:
                    synced = await self.tree.sync()
                    print(f"✅ Slash commands synced on retry! {len(synced)} commands loaded.")
                except Exception as retry_error:
                    print(f"❌ Still rate limited: {retry_error}")
            else:
                print(f"❌ Error syncing commands: {e}")
        except Exception as e:
            print(f"❌ Error syncing commands: {e}")

bot = FCOHomiesBot()

@bot.event
async def on_ready():
    print(f'⚡ Ω LITE is now operational!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    print(f'🔧 User: {bot.user}')
    print(f'🆔 ID: {bot.user.id}')
    print(f'🔄 Slash commands: Active')
    print(f'📢 Announcement system: Active')
    print(f'🎮 LFM system: Active (5-min GLOBAL cooldown)')
    print(f'🏆 Top 10 Players system: Active')
    print(f'💾 Backup/Restore system: Active')
    print(f'🔄 Self-ping system: Active (every 14 minutes)')
    
    bot.loop.create_task(check_announcements())
    bot.loop.create_task(self_ping())  # Start self-pinging to keep bot alive
    
    # Wait a bit before fetching commands to avoid rate limits
    await asyncio.sleep(3)
    try:
        commands = await bot.tree.fetch_commands()
        print(f"📝 Global commands registered: {len(commands)}")
        for cmd in commands:
            print(f"  - /{cmd.name}")
    except discord.errors.HTTPException as e:
        if e.status == 429:
            print("⚠️ Rate limited while fetching commands. Will try later.")
        else:
            print(f"⚠️ Could not fetch commands: {e}")
    except Exception as e:
        print(f"⚠️ Could not fetch commands: {e}")
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.playing, 
        name="Ω Lite | /help"
    ))

# ========== BACKUP AND RESTORE COMMANDS ==========

@bot.tree.command(name="backup", description="Download all database files for backup")
async def backup_command(interaction: discord.Interaction):
    """Download all database files for backup"""
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Authorized users only!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    files_to_backup = ['top10.db', 'announcements.db', 'lfm.db', 'redeem_codes.json', 'formations.json']
    backup_files = []
    
    for file in files_to_backup:
        if os.path.exists(file):
            backup_files.append(discord.File(file))
    
    if backup_files:
        embed = discord.Embed(
            title="📦 Backup Complete",
            description=f"**Time:** <t:{int(datetime.now().timestamp())}:F>\n**Files:** {len(backup_files)}",
            color=0x10B981
        )
        embed.add_field(name="Files included", value="\n".join([f"• {f}" for f in files_to_backup if os.path.exists(f)]), inline=False)
        embed.add_field(name="💡 Restore", value="Use `/restore` with these files to restore your data", inline=False)
        embed.set_footer(text="Ω Lite | Save these files safely!")
        
        await interaction.followup.send(embed=embed, files=backup_files)
    else:
        await interaction.followup.send("❌ No backup files found!", ephemeral=True)

@bot.tree.command(name="restore", description="Restore database files from backup")
async def restore_command(interaction: discord.Interaction, file1: discord.Attachment = None, file2: discord.Attachment = None, file3: discord.Attachment = None, file4: discord.Attachment = None, file5: discord.Attachment = None):
    """Restore database files from uploaded backup files"""
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Authorized users only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    files = [f for f in [file1, file2, file3, file4, file5] if f is not None]
    
    if not files:
        await interaction.followup.send(
            "❌ Please attach files to restore!\n\n"
            "**Usage:** `/restore file1:top10.db file2:announcements.db`\n"
            "You can restore up to 5 files at once.",
            ephemeral=True
        )
        return
    
    restored_files = []
    failed_files = []
    
    for attachment in files:
        # Check if it's a valid backup file
        valid_extensions = ['.db', '.json']
        if not any(attachment.filename.endswith(ext) for ext in valid_extensions):
            failed_files.append(f"{attachment.filename} (invalid file type)")
            continue
        
        try:
            # Download the file
            file_data = await attachment.read()
            
            # Save to current directory
            with open(attachment.filename, 'wb') as f:
                f.write(file_data)
            
            restored_files.append(attachment.filename)
            
        except Exception as e:
            failed_files.append(f"{attachment.filename} ({str(e)})")
    
    # Create result embed
    embed = discord.Embed(
        title="🔄 Restore Results",
        color=0x10B981 if restored_files else 0xDC2626,
        timestamp=datetime.now()
    )
    
    if restored_files:
        embed.add_field(name="✅ Restored", value="\n".join([f"• {f}" for f in restored_files]), inline=False)
    
    if failed_files:
        embed.add_field(name="❌ Failed", value="\n".join(failed_files), inline=False)
    
    if restored_files:
        embed.add_field(name="⚠️ Important", value="Restart the bot for changes to take full effect!", inline=False)
    
    embed.set_footer(text="Ω Lite | Restore Complete")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ========== ANNOUNCEMENT BACKGROUND TASK ==========

async def check_announcements():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            pending = get_pending_announcements()
            
            for announcement in pending:
                announcement_id = announcement[0]
                title = announcement[1]
                description = announcement[2]
                role_id = announcement[3]
                channel_id = announcement[4]
                announce_time_str = announcement[5]
                created_by = announcement[6]
                created_by_name = announcement[7]
                
                try:
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        role = channel.guild.get_role(int(role_id))
                        
                        if role:
                            embed = discord.Embed(
                                title=f"📢 {title}",
                                description=description,
                                color=0x8B5CF6,
                                timestamp=datetime.now()
                            )
                            embed.add_field(name="Scheduled by", value=created_by_name, inline=True)
                            embed.add_field(name="Announcement ID", value=f"`{announcement_id}`", inline=True)
                            embed.set_footer(text="Ω Lite Announcement System")
                            
                            await channel.send(content=f"{role.mention}", embed=embed)
                            update_announcement_status(announcement_id, "sent")
                            print(f"✅ Sent announcement {announcement_id} in {channel.guild.name}")
                        else:
                            update_announcement_status(announcement_id, "failed")
                    else:
                        update_announcement_status(announcement_id, "failed")
                    
                except Exception as e:
                    print(f"❌ Failed to send announcement {announcement_id}: {e}")
                    update_announcement_status(announcement_id, "failed")
            
            await asyncio.sleep(30)
            
        except Exception as e:
            print(f"❌ Error in announcement checker: {e}")
            await asyncio.sleep(60)

# ========== ANNOUNCEMENT COMMANDS WITH TIMESTAMP ==========

@bot.tree.command(name="announce", description="Schedule an announcement with role ping using timestamp")
@app_commands.describe(
    title="Title of the announcement",
    description="What the announcement is about",
    role="Role to ping (mention the role)",
    timestamp="Unix timestamp or Discord timestamp (e.g., 1734567890 or <t:1734567890>)"
)
async def schedule_announcement(
    interaction: discord.Interaction, 
    title: str, 
    description: str, 
    role: discord.Role, 
    timestamp: str
):
    """Schedule an announcement using a timestamp"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Parse the timestamp
        ts = parse_timestamp(timestamp)
        
        if ts is None:
            await interaction.followup.send(
                "❌ Invalid timestamp! Please provide a valid Unix timestamp or Discord timestamp.\n"
                "**Examples:**\n"
                "• `1734567890` (Unix timestamp in seconds)\n"
                "• `<t:1734567890>` (Discord timestamp format)",
                ephemeral=True
            )
            return
        
        # Convert timestamp to datetime
        announce_time = datetime.fromtimestamp(ts, tz=pytz.UTC)
        now = datetime.now(pytz.UTC)
        
        # Check if time is in the future
        if announce_time <= now:
            await interaction.followup.send("❌ Announcement time must be in the future!", ephemeral=True)
            return
        
        # Add to database
        announcement_id = add_announcement_to_db(
            title, description, str(role.id), str(interaction.channel_id),
            announce_time, str(interaction.user.id), interaction.user.name
        )
        
        # Create embed
        embed = discord.Embed(
            title="✅ Announcement Scheduled!",
            description=f"I'll announce this in {interaction.channel.mention}",
            color=0x10B981
        )
        
        # Format time display
        time_diff = announce_time - now
        days = time_diff.days
        hours = time_diff.seconds // 3600
        minutes = (time_diff.seconds % 3600) // 60
        seconds = time_diff.seconds % 60
        
        if days > 0:
            time_display = f"in {days} day{'s' if days > 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
        elif hours > 0:
            time_display = f"in {hours} hour{'s' if hours > 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
        elif minutes > 0:
            time_display = f"in {minutes} minute{'s' if minutes > 1 else ''}"
        else:
            time_display = f"in {seconds} second{'s' if seconds != 1 else ''}"
        
        embed.add_field(
            name="📢 **Announcement**",
            value=f"**{title}**\n{description}",
            inline=False
        )
        embed.add_field(name="👥 Role", value=role.mention, inline=True)
        embed.add_field(name="⏰ Time", value=f"<t:{ts}:F>\n({time_display})", inline=True)
        embed.add_field(name="🆔 ID", value=f"`{announcement_id}`", inline=True)
        embed.add_field(
            name="💡 **Commands**",
            value=f"`/announce_list` - View your announcements\n`/announce_cancel {announcement_id}` - Cancel this",
            inline=False
        )
        
        embed.set_footer(text="Ω Lite | Announcement System | Use Unix timestamps")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="announce_list", description="View all your scheduled announcements")
async def list_announcements(interaction: discord.Interaction):
    announcements = get_user_announcements(str(interaction.user.id))
    
    if not announcements:
        await interaction.response.send_message("📭 You have no scheduled announcements!", ephemeral=True)
        return
    
    pending = [a for a in announcements if a[9] == "pending"]
    sent = [a for a in announcements if a[9] == "sent"]
    cancelled = [a for a in announcements if a[9] == "cancelled"]
    
    embed = discord.Embed(
        title="📋 Your Announcements",
        description=f"Total: {len(announcements)} | ✅ Pending: {len(pending)} | 📤 Sent: {len(sent)} | ❌ Cancelled: {len(cancelled)}",
        color=0x8B5CF6
    )
    
    if pending:
        text = ""
        for ann in pending[:5]:
            announce_time = datetime.fromisoformat(ann[5])
            ts = int(announce_time.timestamp())
            text += f"**`{ann[0]}`** | {ann[1]} | <t:{ts}:R>\n"
        embed.add_field(name=f"✅ Pending ({len(pending)})", value=text, inline=False)
    
    if sent:
        text = ""
        for ann in sent[:3]:
            announce_time = datetime.fromisoformat(ann[5])
            ts = int(announce_time.timestamp())
            text += f"**`{ann[0]}`** | {ann[1]} | <t:{ts}:R>\n"
        embed.add_field(name=f"📤 Sent ({len(sent)})", value=text or "None", inline=False)
    
    embed.set_footer(text="Ω Lite | Use /announce_cancel <id> to cancel")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="announce_cancel", description="Cancel a scheduled announcement")
@app_commands.describe(announcement_id="The ID of the announcement to cancel")
async def cancel_announcement_command(interaction: discord.Interaction, announcement_id: str):
    success = cancel_announcement(announcement_id, str(interaction.user.id))
    
    if success:
        await interaction.response.send_message(f"✅ Announcement `{announcement_id}` cancelled!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Announcement `{announcement_id}` not found or doesn't belong to you!", ephemeral=True)

# ========== TOP 10 COMMANDS ==========

@bot.tree.command(name="top10", description="View the top 10 players for any position")
@app_commands.describe(
    position="Select the position to view"
)
@app_commands.choices(position=[
    app_commands.Choice(name="GK - Goalkeeper", value="GK"),
    app_commands.Choice(name="LB - Left Back", value="LB"),
    app_commands.Choice(name="RB - Right Back", value="RB"),
    app_commands.Choice(name="CB - Center Back", value="CB"),
    app_commands.Choice(name="CM - Center Midfielder", value="CM"),
    app_commands.Choice(name="CDM - Defensive Midfielder", value="CDM"),
    app_commands.Choice(name="CAM - Attacking Midfielder", value="CAM"),
    app_commands.Choice(name="LM - Left Midfielder", value="LM"),
    app_commands.Choice(name="RM - Right Midfielder", value="RM"),
    app_commands.Choice(name="LW - Left Winger", value="LW"),
    app_commands.Choice(name="RW - Right Winger", value="RW"),
    app_commands.Choice(name="ST - Striker", value="ST")
])
async def top10_view(interaction: discord.Interaction, position: str):
    """View the top 10 players for a specific position"""
    await interaction.response.defer()
    
    try:
        top10_data = get_top10(position)
        
        # Position full names for display
        position_names = {
            "GK": "Goalkeeper", "LB": "Left Back", "RB": "Right Back", "CB": "Center Back",
            "CM": "Center Midfielder", "CDM": "Defensive Midfielder", "CAM": "Attacking Midfielder",
            "LM": "Left Midfielder", "RM": "Right Midfielder", "LW": "Left Winger",
            "RW": "Right Winger", "ST": "Striker"
        }
        
        embed = discord.Embed(
            title=f"🏆 Top 10 {position_names.get(position, position)}",
            description=f"The best players for **{position}** position in FC Mobile",
            color=0xF5A623
        )
        
        # Build the list
        list_text = ""
        for rank, player_name, card_name, rating, special, updated_by, updated_at in top10_data:
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
            list_text += f"{medal} **{player_name}** - {card_name}\n"
            list_text += f"   ⭐ **{rating}** OVR | {special}\n\n"
        
        embed.add_field(name="Rankings", value=list_text, inline=False)
        
        # Add update info
        last_updated = datetime.fromisoformat(top10_data[0][6]) if top10_data else datetime.now()
        embed.set_footer(text=f"Last updated: {last_updated.strftime('%Y-%m-%d %H:%M UTC')} | Ω Lite")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="top10_edit", description="Edit the top 10 list for a position (Authorized only)")
@app_commands.describe(
    position="Select the position to edit",
    rank="Rank number (1-10)",
    player_name="Player name",
    card_name="Card name (e.g., TOTY, UCL, etc.)",
    rating="Player rating",
    special="Special card type (e.g., TOTY, Icon, etc.)"
)
@app_commands.choices(position=[
    app_commands.Choice(name="GK - Goalkeeper", value="GK"),
    app_commands.Choice(name="LB - Left Back", value="LB"),
    app_commands.Choice(name="RB - Right Back", value="RB"),
    app_commands.Choice(name="CB - Center Back", value="CB"),
    app_commands.Choice(name="CM - Center Midfielder", value="CM"),
    app_commands.Choice(name="CDM - Defensive Midfielder", value="CDM"),
    app_commands.Choice(name="CAM - Attacking Midfielder", value="CAM"),
    app_commands.Choice(name="LM - Left Midfielder", value="LM"),
    app_commands.Choice(name="RM - Right Midfielder", value="RM"),
    app_commands.Choice(name="LW - Left Winger", value="LW"),
    app_commands.Choice(name="RW - Right Winger", value="RW"),
    app_commands.Choice(name="ST - Striker", value="ST")
])
async def top10_edit(
    interaction: discord.Interaction, 
    position: str, 
    rank: int, 
    player_name: str, 
    card_name: str, 
    rating: int, 
    special: str
):
    """Edit a specific rank in the top 10 list (Authorized only)"""
    
    # Check authorization
    if not can_edit_top10(interaction.user.id):
        await interaction.response.send_message("❌ This command is for authorized users only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if rank < 1 or rank > 10:
            await interaction.followup.send("❌ Rank must be between 1 and 10!", ephemeral=True)
            return
        
        # Update the entry
        update_top10_entry(position, rank, player_name, card_name, rating, special, interaction.user.name)
        
        embed = discord.Embed(
            title="✅ Top 10 Updated!",
            description=f"Successfully updated **{position}** position at rank **{rank}**",
            color=0x10B981
        )
        embed.add_field(name="Player", value=player_name, inline=True)
        embed.add_field(name="Card", value=card_name, inline=True)
        embed.add_field(name="Rating", value=f"{rating} OVR", inline=True)
        embed.add_field(name="Special", value=special, inline=True)
        embed.set_footer(text=f"Updated by {interaction.user.name}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="top10_swap", description="Swap two ranks in the top 10 list (Authorized only)")
@app_commands.describe(
    position="Select the position",
    rank1="First rank to swap",
    rank2="Second rank to swap"
)
@app_commands.choices(position=[
    app_commands.Choice(name="GK - Goalkeeper", value="GK"),
    app_commands.Choice(name="LB - Left Back", value="LB"),
    app_commands.Choice(name="RB - Right Back", value="RB"),
    app_commands.Choice(name="CB - Center Back", value="CB"),
    app_commands.Choice(name="CM - Center Midfielder", value="CM"),
    app_commands.Choice(name="CDM - Defensive Midfielder", value="CDM"),
    app_commands.Choice(name="CAM - Attacking Midfielder", value="CAM"),
    app_commands.Choice(name="LM - Left Midfielder", value="LM"),
    app_commands.Choice(name="RM - Right Midfielder", value="RM"),
    app_commands.Choice(name="LW - Left Winger", value="LW"),
    app_commands.Choice(name="RW - Right Winger", value="RW"),
    app_commands.Choice(name="ST - Striker", value="ST")
])
async def top10_swap(interaction: discord.Interaction, position: str, rank1: int, rank2: int):
    """Swap two ranks in the top 10 list (Authorized only)"""
    
    if not can_edit_top10(interaction.user.id):
        await interaction.response.send_message("❌ This command is for authorized users only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if rank1 < 1 or rank1 > 10 or rank2 < 1 or rank2 > 10:
            await interaction.followup.send("❌ Ranks must be between 1 and 10!", ephemeral=True)
            return
        
        if rank1 == rank2:
            await interaction.followup.send("❌ Cannot swap the same rank!", ephemeral=True)
            return
        
        success = swap_top10_entries(position, rank1, rank2)
        
        if success:
            embed = discord.Embed(
                title="✅ Top 10 Swapped!",
                description=f"Successfully swapped rank **{rank1}** and rank **{rank2}** in **{position}** position",
                color=0x10B981
            )
            embed.set_footer(text=f"Updated by {interaction.user.name}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to swap entries!", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ========== LFM COMMAND ==========

@bot.tree.command(name="lfm", description="Looking for match - Pings the LFM role (5-min GLOBAL cooldown)")
async def lfm_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    try:
        on_cooldown, remaining, last_user_id, last_user_name = check_lfm_global_cooldown()
        
        if on_cooldown:
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
            
            last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
                
            embed = discord.Embed(
                title="⏳ Global Cooldown Active",
                description=f"LFM is on global cooldown for another **{time_text}**",
                color=0xF59E0B
            )
            embed.add_field(name="Last used by", value=f"{last_user_mention}", inline=False)
            embed.add_field(name="Next use", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=False)
            embed.set_footer(text="Ω Lite | LFM System")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        lfm_role = interaction.guild.get_role(bot.lfm_role_id)
        
        if not lfm_role:
            await interaction.followup.send("❌ LFM role not found! Please contact an admin.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎮 Looking for Match",
            description=f"{interaction.user.mention} is looking for a match!",
            color=0x10B981,
            timestamp=datetime.now()
        )
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(
            name="💡 How to join",
            value="Ping the player who used this command!",
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Ω Lite | LFM System (5-min global cooldown)")
        
        await interaction.channel.send(content=f"{lfm_role.mention}", embed=embed)
        update_lfm_global_cooldown(str(interaction.user.id), interaction.user.name)
        
        confirm_embed = discord.Embed(
            title="✅ LFM Posted!",
            description="Your looking for match message has been posted!",
            color=0x10B981
        )
        confirm_embed.add_field(
            name="🌍 Global Cooldown", 
            value="LFM is now on cooldown for **5 minutes** for EVERYONE", 
            inline=False
        )
        confirm_embed.add_field(
            name="Next use",
            value=f"<t:{int((datetime.now() + timedelta(minutes=5)).timestamp())}:R>",
            inline=False
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="lfm_status", description="Check LFM global cooldown status")
async def lfm_status_check(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    on_cooldown, remaining, last_user_id, last_user_name = check_lfm_global_cooldown()
    
    if on_cooldown:
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
        
        last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
            
        embed = discord.Embed(
            title="⏳ LFM Global Cooldown",
            description=f"LFM is currently on **global cooldown**",
            color=0xF59E0B
        )
        embed.add_field(name="Time remaining", value=time_text, inline=True)
        embed.add_field(name="Ready at", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=True)
        embed.add_field(name="Last used by", value=last_user_mention, inline=False)
    else:
        embed = discord.Embed(
            title="✅ LFM Ready",
            description="LFM is **available** right now! Use `/lfm` to ping the role.",
            color=0x10B981
        )
    
    embed.set_footer(text="Ω Lite | LFM System")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ========== OVR COMMAND ==========

@bot.tree.command(name="ovr", description="Calculate team OVR quickly")
@app_commands.describe(
    count="Number of players (min 11)",
    base_ovr_values="Base OVR values separated by +",
    rankup_values="Rankup values separated by +",
    total_max_badges="Total max badges (optional)"
)
async def ovr_calc(interaction: discord.Interaction, count: int, base_ovr_values: str, rankup_values: str, total_max_badges: int = 0):
    await interaction.response.defer()
    
    try:
        base_list = [int(x.strip()) for x in base_ovr_values.split('+')]
        rank_list = [int(x.strip()) for x in rankup_values.split('+')]
        
        if count < 11:
            await interaction.followup.send("❌ Minimum 11 players required!", ephemeral=True)
            return
        
        if len(base_list) != count or len(rank_list) != count:
            await interaction.followup.send(f"❌ Expected {count} values each!", ephemeral=True)
            return
        
        base_total = sum(base_list)
        rank_total = sum(rank_list)
        
        current_base = 1 + (base_total - 1) // count
        current_ranks = 1 + (rank_total - 1) // count
        total_ovr = current_base + current_ranks + total_max_badges
        
        base_req = (current_base * count) + 1 - base_total
        rank_req = (current_ranks * count) + 1 - rank_total
        
        embed = discord.Embed(title="⚡ Ω Lite OVR Analysis", color=0x1E40AF)
        embed.add_field(name="👥 Players", value=count, inline=True)
        embed.add_field(name="⭐ Base OVR", value=current_base, inline=True)
        embed.add_field(name="⬆️ Rankups", value=current_ranks, inline=True)
        
        if total_max_badges > 0:
            embed.add_field(name="🏅 Max Badges", value=f"+{total_max_badges}", inline=True)
            embed.add_field(name="🎯 Total OVR", value=f"**{total_ovr}**", inline=True)
        else:
            embed.add_field(name="🎯 Total OVR", value=total_ovr, inline=True)
        
        if base_req > 0 or rank_req > 0:
            req_text = []
            if base_req > 0:
                req_text.append(f"• Base OVR: +{base_req} total")
            if rank_req > 0:
                req_text.append(f"• Rankups: +{rank_req} total")
            embed.add_field(name="📈 Next Level", value="\n".join(req_text), inline=False)
        
        embed.set_footer(text="Ω Lite | Use + between values")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# Investment Calculator
@bot.tree.command(name="invest", description="Calculate investment profit/loss with 10% tax")
@app_commands.describe(
    buy_price="Buying price per item",
    buy_quantity="Quantity to buy", 
    sell_price="Selling price per item",
    sell_quantity="Quantity to sell"
)
async def invest_calc(interaction: discord.Interaction, buy_price: float, buy_quantity: int, sell_price: float, sell_quantity: int):
    await interaction.response.defer()
    
    try:
        TAX_RATE = 0.10
        
        total_investment = buy_price * buy_quantity
        total_sales_before_tax = sell_price * sell_quantity
        total_tax = total_sales_before_tax * TAX_RATE
        total_sales_after_tax = total_sales_before_tax - total_tax
        net_profit_loss = total_sales_after_tax - total_investment
        
        if net_profit_loss > 0:
            result_text = f"💰 Profit: {net_profit_loss:,.2f} coins"
            embed_color = 0x10B981
        elif net_profit_loss < 0:
            result_text = f"📉 Loss: {abs(net_profit_loss):,.2f} coins"
            embed_color = 0xDC2626
        else:
            result_text = "⚖️ Break Even"
            embed_color = 0x1E40AF
        
        embed = discord.Embed(title="💹 Ω Lite Investment Report", color=embed_color)
        embed.add_field(name="Total Investment", value=f"{total_investment:,.2f} coins", inline=False)
        embed.add_field(name="Total Sales (Before Tax)", value=f"{total_sales_before_tax:,.2f} coins", inline=True)
        embed.add_field(name="Total Tax (10%)", value=f"{total_tax:,.2f} coins", inline=True)
        embed.add_field(name="Total Sales (After Tax)", value=f"{total_sales_after_tax:,.2f} coins", inline=False)
        embed.add_field(name="Result", value=result_text, inline=False)
        
        if net_profit_loss > 0:
            roi = (net_profit_loss / total_investment) * 100
            embed.add_field(name="📈 ROI", value=f"{roi:.2f}%", inline=True)
        
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# Timezone Converter
@bot.tree.command(name="timezone", description="Convert UTC time to any timezone")
@app_commands.describe(
    utc_time="UTC time or 'now'",
    timezone="Target timezone (e.g., EST, GMT, IST)"
)
async def timezone_convert(interaction: discord.Interaction, utc_time: str, timezone: str):
    await interaction.response.defer()
    
    try:
        if utc_time.lower() == 'now':
            utc_time_obj = datetime.now(pytz.UTC)
        else:
            try:
                utc_time_obj = datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    utc_time_obj = datetime.strptime(utc_time, '%Y-%m-%d %H:%M')
                except ValueError:
                    await interaction.followup.send("❌ Use: YYYY-MM-DD HH:MM:SS", ephemeral=True)
                    return
            utc_time_obj = pytz.UTC.localize(utc_time_obj)
        
        target_tz = get_timezone_from_abbreviation(timezone)
        
        if target_tz is None:
            await interaction.followup.send(f"❌ Unknown timezone: {timezone}", ephemeral=True)
            return
        
        converted_time = utc_time_obj.astimezone(target_tz)
        
        embed = discord.Embed(title="🕒 Ω Lite Time Conversion", color=0x8B5CF6)
        embed.add_field(name="🌐 UTC", value=utc_time_obj.strftime('%Y-%m-%d %H:%M:%S'), inline=False)
        embed.add_field(name="🎯 Converted", value=converted_time.strftime('%Y-%m-%d %H:%M:%S'), inline=False)
        embed.add_field(name="📍 Timezone", value=timezone.upper(), inline=True)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# Date to Timestamp
@bot.tree.command(name="datetotimestamp", description="Convert date and time to Unix timestamp")
@app_commands.describe(
    date="Date in YYYY-MM-DD",
    time="Time in HH:MM:SS",
    timezone="Timezone abbreviation"
)
async def date_to_timestamp(interaction: discord.Interaction, date: str, time: str = "00:00:00", timezone: str = "UTC"):
    await interaction.response.defer()
    
    try:
        datetime_str = f"{date} {time}"
        
        try:
            dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M')
            except ValueError:
                dt = datetime.strptime(date, '%Y-%m-%d')
        
        if timezone.upper() == "UTC":
            dt = dt.replace(tzinfo=pytz.UTC)
        else:
            tz = get_timezone_from_abbreviation(timezone)
            if tz is None:
                await interaction.followup.send(f"❌ Unknown timezone: {timezone}", ephemeral=True)
                return
            dt = tz.localize(dt)
            dt = dt.astimezone(pytz.UTC)
        
        timestamp = int(dt.timestamp())
        
        embed = discord.Embed(title="📅 Timestamp Converter", color=0x10B981)
        embed.add_field(name="Unix Timestamp", value=f"`{timestamp}`", inline=False)
        embed.add_field(name="Discord Timestamp", value=f"`<t:{timestamp}>` → <t:{timestamp}>", inline=False)
        embed.add_field(name="Full Format", value=f"`<t:{timestamp}:F>` → <t:{timestamp}:F>", inline=False)
        embed.add_field(name="Relative", value=f"`<t:{timestamp}:R>` → <t:{timestamp}:R>", inline=False)
        embed.set_footer(text="Ω Lite | Use these in any Discord message")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# Formations Command
@bot.tree.command(name="formations", description="Get best formations for different game modes")
@app_commands.choices(game_mode=[
    app_commands.Choice(name="Manager Mode", value="manager_mode"),
    app_commands.Choice(name="VS Attack", value="vs_attack"),
    app_commands.Choice(name="Head to Head", value="head_to_head")
])
async def formations_command(interaction: discord.Interaction, game_mode: str):
    try:
        formations_data = bot.formations_data
        game_mode_display = {
            "manager_mode": "Manager Mode",
            "vs_attack": "VS Attack", 
            "head_to_head": "Head to Head"
        }
        
        if game_mode not in formations_data["formations"]:
            await interaction.response.send_message("❌ Invalid game mode!", ephemeral=True)
            return
        
        formations_list = formations_data["formations"][game_mode]
        
        embed = discord.Embed(
            title=f"⚡ Ω Lite - {game_mode_display[game_mode]} Formations",
            color=0x8B5CF6
        )
        
        formations_text = "\n".join([f"• {formation}" for formation in formations_list])
        embed.add_field(name="Recommended Formations", value=formations_text, inline=False)
        embed.set_footer(text="Ω Lite")
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

# ========== REDEEM CODE COMMANDS ==========

@bot.tree.command(name="redeem", description="View active FC Mobile redeem codes")
async def redeem_codes(interaction: discord.Interaction):
    await interaction.response.defer()
    
    try:
        redeem_codes_list = [code for code in bot.redeem_data["redeem_codes"] if code.get("active", True)]
        
        if not redeem_codes_list:
            embed = discord.Embed(title="🎁 No Active Codes", color=0xF59E0B)
            embed.set_footer(text="Ω Lite")
            await interaction.followup.send(embed=embed)
            return
        
        description = f"**{len(redeem_codes_list)} active code(s)**\n\n[Redeem here](https://redeem.fcm.ea.com)\n\n"
        
        for i, code in enumerate(redeem_codes_list, 1):
            description += f"`{code['code']}`\n🎁 {code.get('reward', 'No reward')}\n\n"
        
        embed = discord.Embed(title="🎁 FC Mobile Codes", description=description, color=0x10B981)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="redeem_add", description="Add redeem code (Authorized only)")
@app_commands.describe(code="Code", reward="Reward", active="Active status")
async def redeem_add(interaction: discord.Interaction, code: str, reward: str, active: bool = True):
    if not can_manage_redeem_codes(interaction.user.id):
        await interaction.response.send_message("❌ Authorized only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        code_upper = code.upper()
        for existing in bot.redeem_data["redeem_codes"]:
            if existing["code"].upper() == code_upper:
                await interaction.followup.send(f"❌ Code exists!", ephemeral=True)
                return
        
        new_code = {
            "code": code_upper, "reward": reward, "active": active,
            "added_by": str(interaction.user.id), "added_by_name": interaction.user.name,
            "added_at": datetime.now().isoformat()
        }
        
        bot.redeem_data["redeem_codes"].append(new_code)
        bot.redeem_data["last_updated"] = datetime.now().isoformat()
        
        if save_redeem_codes(bot.redeem_data):
            await interaction.followup.send(f"✅ Added `{code_upper}`", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to save!", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="redeem_remove", description="Remove redeem code (Authorized only)")
@app_commands.describe(code="Code to remove")
async def redeem_remove(interaction: discord.Interaction, code: str):
    if not can_manage_redeem_codes(interaction.user.id):
        await interaction.response.send_message("❌ Authorized only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        removed = False
        for i, rc in enumerate(bot.redeem_data["redeem_codes"]):
            if rc["code"].upper() == code.upper():
                bot.redeem_data["redeem_codes"].pop(i)
                bot.redeem_data["last_updated"] = datetime.now().isoformat()
                removed = True
                break
        
        if removed and save_redeem_codes(bot.redeem_data):
            await interaction.followup.send(f"✅ Removed `{code.upper()}`", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Code not found!", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ========== UTILITY COMMANDS ==========

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="⚡ Ω Lite Status",
        description=f"**Latency:** {latency}ms\n**Servers:** {len(bot.guilds)}",
        color=0x10B981
    )
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sync", description="Sync commands (Owner only)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 1214456066687893506:
        await interaction.response.send_message("❌ Owner only!", ephemeral=True)
        return
    
    try:
        await interaction.response.send_message("🔄 Syncing...", ephemeral=True)
        synced = await bot.tree.sync()
        await interaction.edit_original_response(content=f"✅ Synced {len(synced)} commands!")
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Failed: {e}")

@bot.tree.command(name="timezones", description="Show available timezone abbreviations")
async def timezone_help(interaction: discord.Interaction):
    embed = discord.Embed(title="🌍 Timezone Abbreviations", color=0x8B5CF6)
    embed.add_field(name="Americas", value="EST, CST, MST, PST, EDT, CDT, MDT, PDT", inline=False)
    embed.add_field(name="Europe", value="GMT, BST, UTC, CET, CEST, EET, EEST", inline=False)
    embed.add_field(name="Asia", value="IST, JST, KST, HKT, SGT, PHT, PKT", inline=False)
    embed.add_field(name="Oceania", value="AEST, AEDT, ACST, AWST, NZST", inline=False)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

# ========== HELP COMMAND ==========

@bot.tree.command(name="help", description="Get help with commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚡ Ω Lite - Help",
        description="**FC Mobile Discord Bot**",
        color=0x8B5CF6
    )
    
    embed.add_field(
        name="🎮 **Game Tools**",
        value="`/ovr` - Calculate team OVR\n`/invest` - Investment calculator\n`/formations` - Best formations\n`/top10` - View top players",
        inline=False
    )
    
    embed.add_field(
        name="🌍 **Time Tools**",
        value="`/timezone` - Convert timezones\n`/datetotimestamp` - Get Discord timestamps\n`/timezones` - List abbreviations",
        inline=False
    )
    
    embed.add_field(
        name="🎁 **Rewards**",
        value="`/redeem` - View FC Mobile codes\n`/lfm` - Looking for match\n`/lfm_status` - Check cooldown",
        inline=False
    )
    
    embed.add_field(
        name="📢 **Announcements**",
        value="`/announce` - Schedule announcement (use timestamps)\n`/announce_list` - View yours\n`/announce_cancel` - Cancel",
        inline=False
    )
    
    embed.add_field(
        name="🏆 **Top 10 Management**",
        value="`/top10_edit` - Edit entry\n`/top10_swap` - Swap ranks",
        inline=False
    )
    
    embed.add_field(
        name="💾 **Backup & Restore**",
        value="`/backup` - Download all database files\n`/restore` - Upload files to restore data",
        inline=False
    )
    
    embed.add_field(
        name="🔧 **Utilities**",
        value="`/ping` - Check status\n`/help` - This menu",
        inline=False
    )
    
    embed.add_field(
        name="📝 **Getting Timestamps**",
        value="Use `/datetotimestamp` to get Unix timestamps for scheduling announcements!",
        inline=False
    )
    
    embed.set_footer(text="Ω Lite | Made for FC Mobile")
    await interaction.response.send_message(embed=embed)

# ========== START BOT ==========

if __name__ == "__main__":
    # Start Flask server for Render
    keep_alive()
    
    # Get bot token
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("❌ ERROR: BOT_TOKEN not set!")
        sys.exit(1)
    
    print("🚀 Starting bot...")
    print("🌐 Starting Ω Lite on Render...")
    print("🏆 Top 10 Players system: ACTIVE")
    print("📢 Announcement system: Using Unix timestamps")
    print("💾 Backup/Restore system: ACTIVE")
    print("🔄 Self-ping system: ACTIVE (every 14 minutes)")
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\n🛑 Received shutdown signal, closing bot...")
        asyncio.create_task(bot.close())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the bot with auto-reconnect
    try:
        bot.run(token, reconnect=True)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        sys.exit(1)
