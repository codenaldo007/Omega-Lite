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
import gc
from contextlib import contextmanager

# ========== DATABASE SETUP ==========

@contextmanager
def db_connection(db_name, timeout=10):
    """Context manager for safe database connections"""
    conn = None
    try:
        conn = sqlite3.connect(db_name, timeout=timeout)
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# Initialize announcements database
def init_announcements_db():
    try:
        with db_connection('announcements.db') as conn:
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
    except Exception as e:
        print(f"❌ Error initializing announcements DB: {e}")

# Initialize LFM database for GLOBAL cooldowns
def init_lfm_db():
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            
            # LFM cooldown table (5 minutes = 300 seconds)
            c.execute('''CREATE TABLE IF NOT EXISTS lfm_global_cooldown
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          last_used TIMESTAMP,
                          last_user_id TEXT,
                          last_user_name TEXT)''')
            c.execute("INSERT OR IGNORE INTO lfm_global_cooldown (id, last_used, last_user_id, last_user_name) VALUES (1, ?, ?, ?)",
                      (datetime.now().isoformat(), "0", "None"))
            
            # SquadHelp cooldown table (15 minutes = 900 seconds)
            c.execute('''CREATE TABLE IF NOT EXISTS squadhelp_global_cooldown
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          last_used TIMESTAMP,
                          last_user_id TEXT,
                          last_user_name TEXT)''')
            c.execute("INSERT OR IGNORE INTO squadhelp_global_cooldown (id, last_used, last_user_id, last_user_name) VALUES (1, ?, ?, ?)",
                      (datetime.now().isoformat(), "0", "None"))
            
            # DRHelp cooldown table (5 minutes = 300 seconds)
            c.execute('''CREATE TABLE IF NOT EXISTS drhelp_global_cooldown
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          last_used TIMESTAMP,
                          last_user_id TEXT,
                          last_user_name TEXT)''')
            c.execute("INSERT OR IGNORE INTO drhelp_global_cooldown (id, last_used, last_user_id, last_user_name) VALUES (1, ?, ?, ?)",
                      (datetime.now().isoformat(), "0", "None"))
            
            conn.commit()
    except Exception as e:
        print(f"❌ Error initializing LFM DB: {e}")

# Call these when bot starts
print("📁 Initializing databases...")
init_announcements_db()
init_lfm_db()
print("✅ Databases initialized")

# ========== SNIPE STORAGE ==========
# Store up to 50 deleted messages per channel
deleted_messages = {}  # {channel_id: [msg1, msg2, msg3, ...]}
edited_messages = {}   # {channel_id: [msg1, msg2, msg3, ...]}

# Users that won't be sniped (add your user ID here)
SNIPE_IGNORE_USERS = [1214456066687893506]  # Your user ID - bot won't snipe you

# ========== COOLDOWN FUNCTIONS ==========

def check_lfm_global_cooldown():
    """Check if LFM is on global cooldown"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            c.execute("SELECT last_used, last_user_id, last_user_name FROM lfm_global_cooldown WHERE id = 1")
            result = c.fetchone()
            
            if result:
                last_used = datetime.fromisoformat(result[0])
                last_user_id = result[1]
                last_user_name = result[2]
                time_passed = datetime.now() - last_used
                if time_passed.total_seconds() < 300:
                    remaining = 300 - time_passed.total_seconds()
                    return True, remaining, last_user_id, last_user_name
        return False, 0, None, None
    except Exception as e:
        print(f"⚠️ Error checking LFM cooldown: {e}")
        return False, 0, None, None

def update_lfm_global_cooldown(user_id, user_name):
    """Update global cooldown with who used it"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("UPDATE lfm_global_cooldown SET last_used = ?, last_user_id = ?, last_user_name = ? WHERE id = 1",
                      (now, user_id, user_name))
            conn.commit()
    except Exception as e:
        print(f"⚠️ Error updating LFM cooldown: {e}")

def check_squadhelp_global_cooldown():
    """Check if SquadHelp is on global cooldown"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            c.execute("SELECT last_used, last_user_id, last_user_name FROM squadhelp_global_cooldown WHERE id = 1")
            result = c.fetchone()
            
            if result:
                last_used = datetime.fromisoformat(result[0])
                last_user_id = result[1]
                last_user_name = result[2]
                time_passed = datetime.now() - last_used
                if time_passed.total_seconds() < 900:
                    remaining = 900 - time_passed.total_seconds()
                    return True, remaining, last_user_id, last_user_name
        return False, 0, None, None
    except Exception as e:
        print(f"⚠️ Error checking SquadHelp cooldown: {e}")
        return False, 0, None, None

def update_squadhelp_global_cooldown(user_id, user_name):
    """Update SquadHelp global cooldown with who used it"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("UPDATE squadhelp_global_cooldown SET last_used = ?, last_user_id = ?, last_user_name = ? WHERE id = 1",
                      (now, user_id, user_name))
            conn.commit()
    except Exception as e:
        print(f"⚠️ Error updating SquadHelp cooldown: {e}")

def check_drhelp_global_cooldown():
    """Check if DRHelp is on global cooldown"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            c.execute("SELECT last_used, last_user_id, last_user_name FROM drhelp_global_cooldown WHERE id = 1")
            result = c.fetchone()
            
            if result:
                last_used = datetime.fromisoformat(result[0])
                last_user_id = result[1]
                last_user_name = result[2]
                time_passed = datetime.now() - last_used
                if time_passed.total_seconds() < 300:
                    remaining = 300 - time_passed.total_seconds()
                    return True, remaining, last_user_id, last_user_name
        return False, 0, None, None
    except Exception as e:
        print(f"⚠️ Error checking DRHelp cooldown: {e}")
        return False, 0, None, None

def update_drhelp_global_cooldown(user_id, user_name):
    """Update DRHelp global cooldown with who used it"""
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("UPDATE drhelp_global_cooldown SET last_used = ?, last_user_id = ?, last_user_name = ? WHERE id = 1",
                      (now, user_id, user_name))
            conn.commit()
    except Exception as e:
        print(f"⚠️ Error updating DRHelp cooldown: {e}")

# ========== TIMESTAMP PARSING ==========

def parse_timestamp(timestamp_str):
    """Parse timestamp from various formats (Unix timestamp or Discord timestamp)"""
    timestamp_str = timestamp_str.strip()
    
    discord_match = re.match(r'<t:(\d+)>', timestamp_str)
    if discord_match:
        return int(discord_match.group(1))
    
    try:
        ts = int(timestamp_str)
        if len(str(ts)) == 13:
            ts = ts // 1000
        return ts
    except ValueError:
        pass
    
    return None

# ========== ANNOUNCEMENT DATABASE FUNCTIONS ==========

def add_announcement_to_db(title, description, role_id, channel_id, announce_time, created_by, created_by_name):
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            announcement_id = str(uuid.uuid4())[:8]
            c.execute("INSERT INTO announcements (id, title, description, role_id, channel_id, announce_time, created_by, created_by_name, created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (announcement_id, title, description, role_id, channel_id, announce_time.isoformat(), created_by, created_by_name, datetime.now().isoformat(), "pending"))
            conn.commit()
            return announcement_id
    except Exception as e:
        print(f"❌ Error adding announcement: {e}")
        return None

def get_pending_announcements():
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("SELECT * FROM announcements WHERE status = 'pending' AND announce_time <= ?", (now,))
            announcements = c.fetchall()
            return announcements
    except Exception as e:
        print(f"❌ Error getting pending announcements: {e}")
        return []

def update_announcement_status(announcement_id, status):
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE announcements SET status = ? WHERE id = ?", (status, announcement_id))
            conn.commit()
    except Exception as e:
        print(f"❌ Error updating announcement status: {e}")

def get_user_announcements(created_by):
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM announcements WHERE created_by = ? ORDER BY announce_time", (created_by,))
            announcements = c.fetchall()
            return announcements
    except Exception as e:
        print(f"❌ Error getting user announcements: {e}")
        return []

def cancel_announcement(announcement_id, created_by):
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE announcements SET status = 'cancelled' WHERE id = ? AND created_by = ?", (announcement_id, created_by))
            rows_affected = c.rowcount
            conn.commit()
            return rows_affected > 0
    except Exception as e:
        print(f"❌ Error cancelling announcement: {e}")
        return False

# ========== DATA LOADING FUNCTIONS ==========

def load_formations():
    try:
        with open('formations.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "formations": {
                "manager_mode": ["4-2-4", "4-3-3 Holding", "4-2-3-1 Wide", "4-3-3 Attack", "4-2-3-1 Narrow", "4-4-2 Holding", "4-2-1-3"],
                "vs_attack": ["4-2-4", "3-5-2", "3-4-1-2", "3-4-2-1", "5-2-2-1", "4-3-3 Attack", "4-2-1-3", "5-3-2", "4-3-3 Holding"],
                "head_to_head": ["4-2-3-1 Wide", "4-2-3-1 Narrow", "3-5-2", "4-2-2-2", "4-3-3 Holding", "4-1-2-1-2 Wide", "4-1-2-1-2 Narrow", "4-4-2 Holding", "4-2-1-3"]
            }
        }

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

def save_redeem_codes(data):
    try:
        with open('redeem_codes.json', 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving redeem codes: {e}")
        return False

def can_manage_redeem_codes(user_id):
    authorized_users = [
        1214456066687893506,
        553418145063239684,
        1221841129151139841
    ]
    return user_id in authorized_users

# ========== TIMEZONE MAPPING ==========

TIMEZONE_MAPPING = {
    "EST": "America/New_York", "EDT": "America/New_York",
    "CST": "America/Chicago", "CDT": "America/Chicago",
    "MST": "America/Denver", "MDT": "America/Denver",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "AKST": "America/Anchorage", "AKDT": "America/Anchorage",
    "HST": "Pacific/Honolulu", "HAST": "Pacific/Honolulu",
    "GMT": "Europe/London", "BST": "Europe/London",
    "UTC": "UTC", "CET": "Europe/Paris", "CEST": "Europe/Paris",
    "EET": "Europe/Helsinki", "EEST": "Europe/Helsinki",
    "WET": "Europe/Lisbon", "WEST": "Europe/Lisbon",
    "IST": "Asia/Kolkata", "JST": "Asia/Tokyo", "KST": "Asia/Seoul",
    "CST_CHINA": "Asia/Shanghai", "HKT": "Asia/Hong_Kong",
    "SGT": "Asia/Singapore", "PHT": "Asia/Manila",
    "WIB": "Asia/Jakarta", "WITA": "Asia/Makassar", "WIT": "Asia/Jayapura",
    "PKT": "Asia/Karachi", "BDT": "Asia/Dhaka", "MMT": "Asia/Yangon",
    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
    "ACST": "Australia/Adelaide", "ACDT": "Australia/Adelaide",
    "AWST": "Australia/Perth", "NZST": "Pacific/Auckland", "NZDT": "Pacific/Auckland",
    "SAST": "Africa/Johannesburg", "EAT": "Africa/Nairobi",
    "MSK": "Europe/Moscow", "GST": "Asia/Dubai",
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

# ========== PAGINATION VIEW ==========

class SnipePagination(discord.ui.View):
    def __init__(self, messages, title_prefix="🗑️ Deleted Message", timeout=60):
        super().__init__(timeout=timeout)
        self.messages = messages
        self.current_page = 0
        self.title_prefix = title_prefix
        self.update_buttons()
    
    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.messages) - 1
    
    def get_embed(self):
        msg = self.messages[self.current_page]
        time_diff = (datetime.now() - msg["time"]).seconds
        
        if time_diff < 60:
            time_text = f"{time_diff}s ago"
        elif time_diff < 3600:
            time_text = f"{time_diff // 60}m ago"
        else:
            time_text = f"{time_diff // 3600}h ago"
        
        total = len(self.messages)
        
        if "before" in msg:  # Edit snipe
            embed = discord.Embed(color=0xF59E0B, timestamp=msg["time"])
            embed.set_author(name=f"✏️ {msg['author']}", icon_url=msg["author_avatar"])
            embed.add_field(name="❌ Before", value=msg["before"][:1024] or "No content", inline=False)
            embed.add_field(name="✅ After", value=msg["after"][:1024] or "No content", inline=False)
            embed.set_footer(text=f"Edited {time_text} • {self.current_page + 1}/{total}")
        else:  # Delete snipe
            embed = discord.Embed(
                description=msg["content"][:2000],
                color=0xDC2626,
                timestamp=msg["time"]
            )
            embed.set_author(name=f"🗑️ {msg['author']}", icon_url=msg["author_avatar"])
            embed.set_footer(text=f"Deleted {time_text} • {self.current_page + 1}/{total}")
            
            if msg["attachments"]:
                attach_text = "\n".join(msg["attachments"][:3])
                embed.add_field(name="📎 Attachments", value=attach_text[:1024], inline=False)
                if msg["attachments"]:
                    embed.set_image(url=msg["attachments"][0])
        
        return embed
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()
    
    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.gray, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.messages) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        # Can't update after timeout without message reference, so we just disable

# ========== HEALTH CHECK SYSTEM ==========

class BotHealthChecker:
    def __init__(self):
        self.start_time = datetime.now()
        self.command_count = 0
        self.error_count = 0
        self.last_error = None
    
    def check_health(self):
        uptime = datetime.now() - self.start_time
        return {
            "uptime": str(uptime).split('.')[0],
            "commands": self.command_count,
            "errors": self.error_count,
            "last_error": str(self.last_error)[:200] if self.last_error else "None"
        }

health_checker = BotHealthChecker()

# ========== BOT CLASS ==========

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
        self.squadhelp_role_id = 1391671605826031626
        self.drhelp_role_id = 1446014580081037314
        self.synced = False

    async def setup_hook(self):
        print("🔄 Bot setup complete - commands will use existing sync")
        
        try:
            await asyncio.sleep(2)
            existing_commands = await self.tree.fetch_commands()
            if not existing_commands:
                print("🔄 No commands found - performing initial sync...")
                try:
                    synced = await self.tree.sync()
                    print(f"✅ Initial sync complete! {len(synced)} commands loaded.")
                    self.synced = True
                except Exception as e:
                    if "429" in str(e):
                        print("⚠️ Rate limited during initial sync - will try later")
                    else:
                        print(f"❌ Initial sync error: {e}")
            else:
                print(f"✅ {len(existing_commands)} commands already registered - skipping sync")
                self.synced = True
        except Exception as e:
            if "429" in str(e):
                print("⚠️ Rate limited checking commands - skipping sync")
            else:
                print(f"⚠️ Could not check commands: {e}")

bot = FCOHomiesBot()

# ========== BOT EVENTS ==========

@bot.event
async def on_ready():
    print(f'⚡ Ω LITE is now operational!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    print(f'🔧 User: {bot.user}')
    print(f'🆔 ID: {bot.user.id}')
    print(f'📢 Announcement system: Active')
    print(f'🎮 LFM system: Active (5-min GLOBAL cooldown)')
    print(f'🛡️ SquadHelp system: Active (15-min GLOBAL cooldown)')
    print(f'⚔️ DRHelp system: Active (5-min GLOBAL cooldown)')
    print(f'🔫 Snipe system: Active (ignoring your messages 😉)')
    print(f'💾 Backup/Restore system: Active')
    print(f'🔄 Self-ping system: Active (every 14 minutes)')
    print(f'🧹 Memory cleanup: Active (every hour)')
    
    bot.loop.create_task(check_announcements())
    bot.loop.create_task(self_ping())
    bot.loop.create_task(memory_cleanup())
    
    await asyncio.sleep(3)
    try:
        commands = await bot.tree.fetch_commands()
        print(f"📝 Global commands registered: {len(commands)}")
        for cmd in commands:
            print(f"  - /{cmd.name}")
    except Exception as e:
        if "429" in str(e):
            print("⚠️ Rate limited fetching commands - will skip display")
        else:
            print(f"⚠️ Could not fetch commands: {e}")
    
    try:
        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.playing, 
            name="Ω Lite | /help"
        ))
    except Exception as e:
        print(f"⚠️ Could not set presence: {e}")

# ========== SNIPE EVENTS ==========

@bot.event
async def on_message_delete(message):
    """Store deleted messages for snipe (ignores users in SNIPE_IGNORE_USERS)"""
    # Don't snipe ignored users or bots
    if message.author.bot or message.author.id in SNIPE_IGNORE_USERS:
        return
    
    # Don't store empty messages with no attachments
    if not message.content and not message.attachments:
        return
    
    if message.channel.id not in deleted_messages:
        deleted_messages[message.channel.id] = []
    
    msg_data = {
        "content": message.content or "*No text*",
        "author": str(message.author),
        "author_id": message.author.id,
        "author_avatar": message.author.display_avatar.url if message.author.display_avatar else None,
        "time": datetime.now(),
        "attachments": [att.url for att in message.attachments] if message.attachments else []
    }
    
    # Add to beginning of list (newest first)
    deleted_messages[message.channel.id].insert(0, msg_data)
    
    # Keep only last 50 messages per channel
    if len(deleted_messages[message.channel.id]) > 50:
        deleted_messages[message.channel.id] = deleted_messages[message.channel.id][:50]

@bot.event
async def on_message_edit(before, after):
    """Store edited messages for editsnipe (ignores users in SNIPE_IGNORE_USERS)"""
    # Don't snipe ignored users, bots, or same content
    if before.author.bot or before.author.id in SNIPE_IGNORE_USERS or before.content == after.content:
        return
    
    if before.channel.id not in edited_messages:
        edited_messages[before.channel.id] = []
    
    msg_data = {
        "before": before.content or "*No text*",
        "after": after.content or "*No text*",
        "author": str(before.author),
        "author_id": before.author.id,
        "author_avatar": before.author.display_avatar.url if before.author.display_avatar else None,
        "time": datetime.now()
    }
    
    # Add to beginning of list (newest first)
    edited_messages[before.channel.id].insert(0, msg_data)
    
    # Keep only last 50 messages per channel
    if len(edited_messages[before.channel.id]) > 50:
        edited_messages[before.channel.id] = edited_messages[before.channel.id][:50]

# ========== BACKGROUND TASKS ==========

async def self_ping():
    """Ping the external URL every 14 minutes with better error handling"""
    await bot.wait_until_ready()
    
    RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://your-bot-name.onrender.com")
    consecutive_failures = 0
    
    await asyncio.sleep(60)
    
    while not bot.is_closed():
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(RENDER_EXTERNAL_URL) as response:
                    if response.status == 200:
                        print(f"🔄 External ping sent at {datetime.now().strftime('%H:%M:%S')} - Bot kept alive")
                        consecutive_failures = 0
                    else:
                        print(f"⚠️ External ping returned status: {response.status}")
                        consecutive_failures += 1
        except asyncio.TimeoutError:
            print(f"⚠️ External ping timed out")
            consecutive_failures += 1
        except Exception as e:
            print(f"⚠️ External ping failed: {e}")
            consecutive_failures += 1
        
        if consecutive_failures > 5:
            print("🔄 Too many ping failures, attempting recovery...")
            consecutive_failures = 0
            gc.collect()
        
        await asyncio.sleep(840)

async def memory_cleanup():
    """Periodically clean up memory to prevent leaks"""
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        await asyncio.sleep(3600)
        try:
            gc.collect()
            # Clean up old snipe messages (older than 6 hours)
            cutoff = datetime.now() - timedelta(hours=6)
            for channel_id in list(deleted_messages.keys()):
                deleted_messages[channel_id] = [m for m in deleted_messages[channel_id] if m["time"] > cutoff]
                if not deleted_messages[channel_id]:
                    del deleted_messages[channel_id]
            for channel_id in list(edited_messages.keys()):
                edited_messages[channel_id] = [m for m in edited_messages[channel_id] if m["time"] > cutoff]
                if not edited_messages[channel_id]:
                    del edited_messages[channel_id]
            print(f"🧹 Memory cleanup performed at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"⚠️ Memory cleanup error: {e}")

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

# ========== ANNOUNCEMENT COMMANDS ==========

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
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    try:
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
        
        announce_time = datetime.fromtimestamp(ts, tz=pytz.UTC)
        now = datetime.now(pytz.UTC)
        
        if announce_time <= now:
            await interaction.followup.send("❌ Announcement time must be in the future!", ephemeral=True)
            return
        
        announcement_id = add_announcement_to_db(
            title, description, str(role.id), str(interaction.channel_id),
            announce_time, str(interaction.user.id), interaction.user.name
        )
        
        if not announcement_id:
            await interaction.followup.send("❌ Failed to schedule announcement. Please try again.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="✅ Announcement Scheduled!",
            description=f"I'll announce this in {interaction.channel.mention}",
            color=0x10B981
        )
        
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="announce_list", description="View all your scheduled announcements")
async def list_announcements(interaction: discord.Interaction):
    health_checker.command_count += 1
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
    health_checker.command_count += 1
    success = cancel_announcement(announcement_id, str(interaction.user.id))
    
    if success:
        await interaction.response.send_message(f"✅ Announcement `{announcement_id}` cancelled!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Announcement `{announcement_id}` not found or doesn't belong to you!", ephemeral=True)

# ========== LFM COMMANDS ==========

@bot.tree.command(name="lfm", description="Looking for match - Pings the LFM role (5-min GLOBAL cooldown)")
async def lfm_command(interaction: discord.Interaction):
    health_checker.command_count += 1
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
            embed.set_footer(text="Ω Lite | LFM System (5-min cooldown)")
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
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="lfm_status", description="Check LFM global cooldown status")
async def lfm_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
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
    
    embed.set_footer(text="Ω Lite | LFM System (5-min cooldown)")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ========== SQUADHELP COMMANDS ==========

@bot.tree.command(name="squadhelp", description="Request help with your squad - Pings the SquadHelp role (15-min GLOBAL cooldown)")
async def squadhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    try:
        on_cooldown, remaining, last_user_id, last_user_name = check_squadhelp_global_cooldown()
        
        if on_cooldown:
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
            
            last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
                
            embed = discord.Embed(
                title="⏳ Global Cooldown Active",
                description=f"SquadHelp is on global cooldown for another **{time_text}**",
                color=0xF59E0B
            )
            embed.add_field(name="Last used by", value=f"{last_user_mention}", inline=False)
            embed.add_field(name="Next use", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=False)
            embed.set_footer(text="Ω Lite | SquadHelp System (15-min cooldown)")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        squadhelp_role = interaction.guild.get_role(bot.squadhelp_role_id)
        
        if not squadhelp_role:
            await interaction.followup.send("❌ SquadHelp role not found! Please contact an admin.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🛡️ Squad Help Requested",
            description=f"{interaction.user.mention} needs help with their squad!",
            color=0x3B82F6,
            timestamp=datetime.now()
        )
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(
            name="💡 How to help",
            value="Ping the player who used this command and offer your advice!",
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | SquadHelp System (15-min global cooldown)")
        
        await interaction.channel.send(content=f"{squadhelp_role.mention}", embed=embed)
        update_squadhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        
        confirm_embed = discord.Embed(
            title="✅ SquadHelp Posted!",
            description="Your squad help request has been posted!",
            color=0x3B82F6
        )
        confirm_embed.add_field(
            name="🌍 Global Cooldown", 
            value="SquadHelp is now on cooldown for **15 minutes** for EVERYONE", 
            inline=False
        )
        confirm_embed.add_field(
            name="Next use",
            value=f"<t:{int((datetime.now() + timedelta(minutes=15)).timestamp())}:R>",
            inline=False
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)
        
    except Exception as e:
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="squadhelp_status", description="Check SquadHelp global cooldown status")
async def squadhelp_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    on_cooldown, remaining, last_user_id, last_user_name = check_squadhelp_global_cooldown()
    
    if on_cooldown:
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
        
        last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
            
        embed = discord.Embed(
            title="⏳ SquadHelp Global Cooldown",
            description=f"SquadHelp is currently on **global cooldown**",
            color=0xF59E0B
        )
        embed.add_field(name="Time remaining", value=time_text, inline=True)
        embed.add_field(name="Ready at", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=True)
        embed.add_field(name="Last used by", value=last_user_mention, inline=False)
    else:
        embed = discord.Embed(
            title="✅ SquadHelp Ready",
            description="SquadHelp is **available** right now! Use `/squadhelp` to ping the role.",
            color=0x3B82F6
        )
    
    embed.set_footer(text="Ω Lite | SquadHelp System (15-min cooldown)")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ========== DRHELP COMMANDS ==========

@bot.tree.command(name="drhelp", description="Request help with Division Rivals - Pings the DRHelp role (5-min GLOBAL cooldown)")
async def drhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    try:
        on_cooldown, remaining, last_user_id, last_user_name = check_drhelp_global_cooldown()
        
        if on_cooldown:
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
            
            last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
                
            embed = discord.Embed(
                title="⏳ Global Cooldown Active",
                description=f"DRHelp is on global cooldown for another **{time_text}**",
                color=0xF59E0B
            )
            embed.add_field(name="Last used by", value=f"{last_user_mention}", inline=False)
            embed.add_field(name="Next use", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=False)
            embed.set_footer(text="Ω Lite | DRHelp System (5-min cooldown)")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        drhelp_role = interaction.guild.get_role(bot.drhelp_role_id)
        
        if not drhelp_role:
            await interaction.followup.send("❌ DRHelp role not found! Please contact an admin.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="⚔️ Division Rivals Help Requested",
            description=f"{interaction.user.mention} needs help with Division Rivals!",
            color=0xEF4444,
            timestamp=datetime.now()
        )
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(
            name="💡 How to help",
            value="Ping the player who used this command and offer your advice!",
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | DRHelp System (5-min global cooldown)")
        
        await interaction.channel.send(content=f"{drhelp_role.mention}", embed=embed)
        update_drhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        
        confirm_embed = discord.Embed(
            title="✅ DRHelp Posted!",
            description="Your Division Rivals help request has been posted!",
            color=0xEF4444
        )
        confirm_embed.add_field(
            name="🌍 Global Cooldown", 
            value="DRHelp is now on cooldown for **5 minutes** for EVERYONE", 
            inline=False
        )
        confirm_embed.add_field(
            name="Next use",
            value=f"<t:{int((datetime.now() + timedelta(minutes=5)).timestamp())}:R>",
            inline=False
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)
        
    except Exception as e:
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="drhelp_status", description="Check DRHelp global cooldown status")
async def drhelp_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    on_cooldown, remaining, last_user_id, last_user_name = check_drhelp_global_cooldown()
    
    if on_cooldown:
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        time_text = f"{minutes} min{'s' if minutes > 1 else ''} {seconds} sec" if minutes > 0 else f"{seconds} seconds"
        
        last_user_mention = f"<@{last_user_id}>" if last_user_id != "0" else "Unknown"
            
        embed = discord.Embed(
            title="⏳ DRHelp Global Cooldown",
            description=f"DRHelp is currently on **global cooldown**",
            color=0xF59E0B
        )
        embed.add_field(name="Time remaining", value=time_text, inline=True)
        embed.add_field(name="Ready at", value=f"<t:{int((datetime.now() + timedelta(seconds=remaining)).timestamp())}:R>", inline=True)
        embed.add_field(name="Last used by", value=last_user_mention, inline=False)
    else:
        embed = discord.Embed(
            title="✅ DRHelp Ready",
            description="DRHelp is **available** right now! Use `/drhelp` to ping the role.",
            color=0xEF4444
        )
    
    embed.set_footer(text="Ω Lite | DRHelp System (5-min cooldown)")
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
    health_checker.command_count += 1
    await interaction.response.defer()
    
    try:
        base_list = [int(x.strip()) for x in base_ovr_values.split('+')]
        rank_list = [int(x.strip()) for x in rankup_values.split('+')]
        
        if count < 11:
            await interaction.followup.send("❌ Minimum 11 players required!", ephemeral=True)
            return
        
        if len(base_list) != count or len(rank_list) != count:
            await interaction.followup.send(f"❌ Expected {count} values each! Got {len(base_list)} base and {len(rank_list)} rankup values.", ephemeral=True)
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
        
    except ValueError:
        await interaction.followup.send("❌ Please enter valid numbers separated by +", ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error calculating OVR. Please check your input format.", ephemeral=True)

# ========== INVEST COMMAND ==========

@bot.tree.command(name="invest", description="Calculate investment profit/loss with 10% tax")
@app_commands.describe(
    buy_price="Buying price per item",
    buy_quantity="Quantity to buy", 
    sell_price="Selling price per item",
    sell_quantity="Quantity to sell"
)
async def invest_calc(interaction: discord.Interaction, buy_price: float, buy_quantity: int, sell_price: float, sell_quantity: int):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ========== TIMEZONE COMMANDS ==========

@bot.tree.command(name="timezone", description="Convert UTC time to any timezone")
@app_commands.describe(
    utc_time="UTC time or 'now'",
    timezone="Target timezone (e.g., EST, GMT, IST)"
)
async def timezone_convert(interaction: discord.Interaction, utc_time: str, timezone: str):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="datetotimestamp", description="Convert date and time to Unix timestamp")
@app_commands.describe(
    date="Date in YYYY-MM-DD",
    time="Time in HH:MM:SS",
    timezone="Timezone abbreviation"
)
async def date_to_timestamp(interaction: discord.Interaction, date: str, time: str = "00:00:00", timezone: str = "UTC"):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ========== FORMATIONS COMMAND ==========

@bot.tree.command(name="formations", description="Get best formations for different game modes")
@app_commands.choices(game_mode=[
    app_commands.Choice(name="Manager Mode", value="manager_mode"),
    app_commands.Choice(name="VS Attack", value="vs_attack"),
    app_commands.Choice(name="Head to Head", value="head_to_head")
])
async def formations_command(interaction: discord.Interaction, game_mode: str):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

# ========== REDEEM CODE COMMANDS ==========

@bot.tree.command(name="redeem", description="View active FC Mobile redeem codes")
async def redeem_codes(interaction: discord.Interaction):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="redeem_add", description="Add redeem code (Authorized only)")
@app_commands.describe(code="Code", reward="Reward", active="Active status")
async def redeem_add(interaction: discord.Interaction, code: str, reward: str, active: bool = True):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.tree.command(name="redeem_remove", description="Remove redeem code (Authorized only)")
@app_commands.describe(code="Code to remove")
async def redeem_remove(interaction: discord.Interaction, code: str):
    health_checker.command_count += 1
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
        health_checker.error_count += 1
        health_checker.last_error = str(e)[:200]
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# ========== UTILITY COMMANDS ==========

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    health_checker.command_count += 1
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="⚡ Ω Lite Status",
        description=f"**Latency:** {latency}ms\n**Servers:** {len(bot.guilds)}",
        color=0x10B981
    )
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="health", description="Check bot health and statistics (Owner only)")
async def health_check_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Authorized only!", ephemeral=True)
        return
    
    health = health_checker.check_health()
    
    embed = discord.Embed(title="🏥 Ω Lite Health Report", color=0x8B5CF6)
    embed.add_field(name="⏱️ Uptime", value=health["uptime"], inline=False)
    embed.add_field(name="📊 Commands Processed", value=health["commands"], inline=True)
    embed.add_field(name="❌ Errors", value=health["errors"], inline=True)
    embed.add_field(name="🔌 Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="💾 Last Error", value=health["last_error"], inline=False)
    embed.add_field(name="🔄 Servers", value=len(bot.guilds), inline=True)
    
    try:
        with db_connection('lfm.db') as conn:
            conn.cursor().execute("SELECT 1")
        embed.add_field(name="🗄️ Database", value="✅ Connected", inline=True)
    except:
        embed.add_field(name="🗄️ Database", value="❌ Error", inline=True)
    
    embed.set_footer(text="Ω Lite | Health Monitor")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="sync", description="Sync commands (Owner only - use sparingly!)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 1214456066687893506:
        await interaction.response.send_message("❌ Owner only!", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        synced = await bot.tree.sync()
        bot.synced = True
        await interaction.followup.send(f"✅ Synced {len(synced)} commands! Use this command sparingly to avoid rate limits.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed: {e}\nWait a few minutes and try again.", ephemeral=True)

@bot.tree.command(name="timezones", description="Show available timezone abbreviations")
async def timezone_help(interaction: discord.Interaction):
    health_checker.command_count += 1
    embed = discord.Embed(title="🌍 Timezone Abbreviations", color=0x8B5CF6)
    embed.add_field(name="Americas", value="EST, CST, MST, PST, EDT, CDT, MDT, PDT", inline=False)
    embed.add_field(name="Europe", value="GMT, BST, UTC, CET, CEST, EET, EEST", inline=False)
    embed.add_field(name="Asia", value="IST, JST, KST, HKT, SGT, PHT, PKT", inline=False)
    embed.add_field(name="Oceania", value="AEST, AEDT, ACST, AWST, NZST", inline=False)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

# ========== SNIPE COMMANDS ==========

@bot.tree.command(name="snipe", description="🔫 Show deleted messages in this channel (use arrows to browse history)")
@app_commands.describe(page="Which deleted message to show (1 = latest, 2 = second latest, etc.)")
async def snipe(interaction: discord.Interaction, page: int = 1):
    health_checker.command_count += 1
    await interaction.response.defer()
    
    if interaction.channel.id not in deleted_messages or not deleted_messages[interaction.channel.id]:
        await interaction.followup.send("🔫 Nothing to snipe! No deleted messages in this channel.", ephemeral=True)
        return
    
    messages = deleted_messages[interaction.channel.id]
    
    if page < 1 or page > len(messages):
        await interaction.followup.send(f"❌ Please choose a page between 1 and {len(messages)}.", ephemeral=True)
        return
    
    # If only one message, show it directly
    if len(messages) == 1:
        msg = messages[0]
        time_diff = (datetime.now() - msg["time"]).seconds
        
        if time_diff < 60:
            time_text = f"{time_diff}s ago"
        elif time_diff < 3600:
            time_text = f"{time_diff // 60}m ago"
        else:
            time_text = f"{time_diff // 3600}h ago"
        
        embed = discord.Embed(
            description=msg["content"][:2000],
            color=0xDC2626,
            timestamp=msg["time"]
        )
        embed.set_author(name=f"🗑️ {msg['author']}", icon_url=msg["author_avatar"])
        embed.set_footer(text=f"Deleted {time_text}")
        
        if msg["attachments"]:
            attach_text = "\n".join(msg["attachments"][:3])
            embed.add_field(name="📎 Attachments", value=attach_text[:1024], inline=False)
            if msg["attachments"]:
                embed.set_image(url=msg["attachments"][0])
        
        await interaction.followup.send(embed=embed)
        return
    
    # Multiple messages - create pagination
    view = SnipePagination(messages, title_prefix="🗑️ Deleted Message")
    view.current_page = page - 1  # Convert to 0-based index
    view.update_buttons()
    
    await interaction.followup.send(embed=view.get_embed(), view=view)


@bot.tree.command(name="editsnipe", description="✏️ Show edited messages in this channel (use arrows to browse history)")
@app_commands.describe(page="Which edited message to show (1 = latest, 2 = second latest, etc.)")
async def editsnipe(interaction: discord.Interaction, page: int = 1):
    health_checker.command_count += 1
    await interaction.response.defer()
    
    if interaction.channel.id not in edited_messages or not edited_messages[interaction.channel.id]:
        await interaction.followup.send("✏️ Nothing to editsnipe! No edited messages in this channel.", ephemeral=True)
        return
    
    messages = edited_messages[interaction.channel.id]
    
    if page < 1 or page > len(messages):
        await interaction.followup.send(f"❌ Please choose a page between 1 and {len(messages)}.", ephemeral=True)
        return
    
    # If only one message, show it directly
    if len(messages) == 1:
        msg = messages[0]
        time_diff = (datetime.now() - msg["time"]).seconds
        
        if time_diff < 60:
            time_text = f"{time_diff}s ago"
        elif time_diff < 3600:
            time_text = f"{time_diff // 60}m ago"
        else:
            time_text = f"{time_diff // 3600}h ago"
        
        embed = discord.Embed(color=0xF59E0B, timestamp=msg["time"])
        embed.set_author(name=f"✏️ {msg['author']}", icon_url=msg["author_avatar"])
        embed.add_field(name="❌ Before", value=msg["before"][:1024] or "No content", inline=False)
        embed.add_field(name="✅ After", value=msg["after"][:1024] or "No content", inline=False)
        embed.set_footer(text=f"Edited {time_text}")
        
        await interaction.followup.send(embed=embed)
        return
    
    # Multiple messages - create pagination
    view = SnipePagination(messages, title_prefix="✏️ Edited Message")
    view.current_page = page - 1  # Convert to 0-based index
    view.update_buttons()
    
    await interaction.followup.send(embed=view.get_embed(), view=view)


@bot.tree.command(name="snipe_list", description="📋 List all sniped messages in this channel")
async def snipe_list(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    
    deleted_count = len(deleted_messages.get(interaction.channel.id, []))
    edited_count = len(edited_messages.get(interaction.channel.id, []))
    
    embed = discord.Embed(
        title="🔫 Snipe History",
        color=0x8B5CF6
    )
    embed.add_field(name="🗑️ Deleted Messages", value=f"**{deleted_count}** stored", inline=True)
    embed.add_field(name="✏️ Edited Messages", value=f"**{edited_count}** stored", inline=True)
    embed.add_field(
        name="💡 Usage",
        value=f"`/snipe page:1` - View deleted (1=latest)\n`/editsnipe page:1` - View edited (1=latest)\n`/snipe_clear` - Clear history",
        inline=False
    )
    embed.set_footer(text="Ω Lite | Snipe System")
    
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="snipe_clear", description="🧹 Clear snipe history in this channel (Manage Messages permission)")
@app_commands.default_permissions(manage_messages=True)
async def snipe_clear(interaction: discord.Interaction):
    health_checker.command_count += 1
    
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You need Manage Messages permission!", ephemeral=True)
        return
    
    cleared = 0
    if interaction.channel.id in deleted_messages:
        del deleted_messages[interaction.channel.id]
        cleared += 1
    if interaction.channel.id in edited_messages:
        del edited_messages[interaction.channel.id]
        cleared += 1
    
    if cleared:
        await interaction.response.send_message(f"🧹 Cleared all snipe history for this channel!", ephemeral=True)
    else:
        await interaction.response.send_message("📭 Nothing to clear!", ephemeral=True)

# ========== BACKUP AND RESTORE COMMANDS ==========

@bot.tree.command(name="backup", description="Download all database files for backup")
async def backup_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Authorized users only!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    files_to_backup = ['announcements.db', 'lfm.db', 'redeem_codes.json', 'formations.json']
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
    health_checker.command_count += 1
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
        valid_extensions = ['.db', '.json']
        if not any(attachment.filename.endswith(ext) for ext in valid_extensions):
            failed_files.append(f"{attachment.filename} (invalid file type)")
            continue
        
        try:
            file_data = await attachment.read()
            
            with open(attachment.filename, 'wb') as f:
                f.write(file_data)
            
            restored_files.append(attachment.filename)
            
        except Exception as e:
            failed_files.append(f"{attachment.filename} ({str(e)})")
    
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

# ========== HELP COMMAND ==========

@bot.tree.command(name="help", description="Get help with commands")
async def help_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    embed = discord.Embed(
        title="⚡ Ω Lite - Help",
        description="**FC Mobile Discord Bot**",
        color=0x8B5CF6
    )
    
    embed.add_field(
        name="🎮 **Game Tools**",
        value="`/ovr` - Calculate team OVR\n`/invest` - Investment calculator\n`/formations` - Best formations",
        inline=False
    )
    
    embed.add_field(
        name="🌍 **Time Tools**",
        value="`/timezone` - Convert timezones\n`/datetotimestamp` - Get Discord timestamps\n`/timezones` - List abbreviations",
        inline=False
    )
    
    embed.add_field(
        name="🎁 **Rewards**",
        value="`/redeem` - View FC Mobile codes",
        inline=False
    )
    
    embed.add_field(
        name="🎮 **Ping Roles**",
        value="`/lfm` - Looking for match (5-min cooldown)\n`/lfm_status` - Check LFM cooldown\n`/squadhelp` - Squad help request (15-min cooldown)\n`/squadhelp_status` - Check SquadHelp cooldown\n`/drhelp` - Division Rivals help (5-min cooldown)\n`/drhelp_status` - Check DRHelp cooldown",
        inline=False
    )
    
    embed.add_field(
        name="📢 **Announcements**",
        value="`/announce` - Schedule announcement (use timestamps)\n`/announce_list` - View yours\n`/announce_cancel` - Cancel",
        inline=False
    )
    
    embed.add_field(
        name="🔫 **Snipe**",
        value="`/snipe` - Show deleted messages (paginated)\n`/editsnipe` - Show edited messages (paginated)\n`/snipe_list` - View snipe counts\n`/snipe_clear` - Clear snipe history",
        inline=False
    )
    
    embed.add_field(
        name="💾 **Backup & Restore**",
        value="`/backup` - Download all database files\n`/restore` - Upload files to restore data",
        inline=False
    )
    
    embed.add_field(
        name="🔧 **Utilities**",
        value="`/ping` - Check status\n`/help` - This menu\n`/health` - Bot health stats (Admin)",
        inline=False
    )
    
    embed.add_field(
        name="📝 **Getting Timestamps**",
        value="Use `/datetotimestamp` to get Unix timestamps for scheduling announcements!",
        inline=False
    )
    
    embed.set_footer(text="Ω Lite | Made for FC Mobile")
    await interaction.response.send_message(embed=embed)

# ========== FLASK KEEP-ALIVE SERVER ==========

app = Flask('')

@app.route('/')
def home():
    try:
        if bot.is_ready():
            latency = round(bot.latency * 1000)
            servers = len(bot.guilds)
            return f"⚡ Ω Lite is running! Servers: {servers} | Latency: {latency}ms"
        else:
            return "⚡ Ω Lite is starting up... Please wait a moment."
    except Exception as e:
        return f"⚡ Ω Lite Status: Bot starting or encountered issue"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# ========== START BOT ==========

if __name__ == "__main__":
    # Start Flask server for Render
    keep_alive()
    
    # Get bot token from environment variable
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("❌ ERROR: BOT_TOKEN environment variable not set!")
        print("Please set your Discord bot token in Render environment variables.")
        sys.exit(1)
    
    print("=" * 50)
    print("🚀 Starting Ω Lite Bot...")
    print("🌐 Flask keep-alive server will run on Render")
    print("📢 Announcement system: Using Unix timestamps")
    print("💾 Backup/Restore system: ACTIVE")
    print("🎮 LFM system: ACTIVE (5-min cooldown)")
    print("🛡️ SquadHelp system: ACTIVE (15-min cooldown)")
    print("⚔️ DRHelp system: ACTIVE (5-min cooldown)")
    print("🔫 Snipe system: ACTIVE (paginated, ignores your msgs)")
    print("🔄 Self-ping system: ACTIVE (every 14 minutes)")
    print("🧹 Memory cleanup: ACTIVE (every hour)")
    print("🏥 Health monitoring: ACTIVE")
    print("⚠️  Commands synced ONLY on first run - use /sync manually if needed")
    print("=" * 50)
    
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
    except discord.LoginFailure:
        print("❌ Invalid bot token! Please check your BOT_TOKEN environment variable.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        sys.exit(1)
