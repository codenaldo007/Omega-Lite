import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import json
from flask import Flask
import threading
from datetime import datetime, timezone, timedelta
import pytz
import time
import sqlite3
import uuid
import re
import sys
import signal
import aiohttp
import gc
from contextlib import contextmanager
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

# ========== FLASK SERVER ==========
app = Flask('')

@app.route('/')
def home():
    try:
        if bot.is_ready():
            return f"⚡ Ω Lite is running! Servers: {len(bot.guilds)} | Latency: {round(bot.latency * 1000)}ms"
        return "⚡ Ω Lite is starting..."
    except:
        return "⚡ Ω Lite Status: Starting"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ========== DATABASE ==========
@contextmanager
def db_connection(db_name, timeout=10):
    conn = None
    try:
        conn = sqlite3.connect(db_name, timeout=timeout)
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        if conn:
            try: conn.close()
            except: pass

def init_announcements_db():
    try:
        with db_connection('announcements.db') as conn:
            conn.cursor().execute('''CREATE TABLE IF NOT EXISTS announcements
                (id TEXT PRIMARY KEY, title TEXT, description TEXT, role_id TEXT,
                 channel_id TEXT, announce_time TEXT, created_by TEXT,
                 created_by_name TEXT, created_at TEXT, status TEXT)''')
            conn.commit()
    except Exception as e: print(f"❌ DB error: {e}")

def init_lfm_db():
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            for table in ["lfm_global_cooldown", "squadhelp_global_cooldown", "drhelp_global_cooldown", "eventping_global_cooldown"]:
                c.execute(f'''CREATE TABLE IF NOT EXISTS {table}
                    (id INTEGER PRIMARY KEY CHECK (id = 1), last_used TIMESTAMP,
                     last_user_id TEXT, last_user_name TEXT)''')
                c.execute(f"INSERT OR IGNORE INTO {table} VALUES (1, ?, ?, ?)",
                          (datetime.now().isoformat(), "0", "None"))
            conn.commit()
    except Exception as e: print(f"❌ LFM DB error: {e}")

print("📁 Initializing databases...")
init_announcements_db()
init_lfm_db()
print("✅ Databases initialized")

# ========== MULTILINGUAL CHANNEL (HARDCODED) ==========
MULTILINGUAL_CHANNELS = [1535890494968692806]

# ========== ROLE ID FOR SNIPE/AFK ACCESS ==========
SNIPE_AFK_ROLE_ID = 1391671055902572625

# ========== SNIPE STORAGE ==========
SNIPE_IGNORE = [1214456066687893506]
deleted_messages = {}
edited_messages = {}

# ========== AFK STORAGE ==========
afk_users = {}

# ========== COOLDOWNS ==========
def _check_cooldown(table, seconds):
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            c.execute(f"SELECT last_used, last_user_id, last_user_name FROM {table} WHERE id = 1")
            result = c.fetchone()
            if result:
                elapsed = (datetime.now() - datetime.fromisoformat(result[0])).total_seconds()
                if elapsed < seconds:
                    return True, seconds - elapsed, result[1], result[2]
        return False, 0, None, None
    except: return False, 0, None, None

def _update_cooldown(table, user_id, user_name):
    try:
        with db_connection('lfm.db') as conn:
            conn.cursor().execute(f"UPDATE {table} SET last_used = ?, last_user_id = ?, last_user_name = ? WHERE id = 1",
                      (datetime.now().isoformat(), user_id, user_name))
            conn.commit()
    except: pass

def check_lfm_global_cooldown(): return _check_cooldown("lfm_global_cooldown", 300)
def update_lfm_global_cooldown(uid, un): _update_cooldown("lfm_global_cooldown", uid, un)
def check_squadhelp_global_cooldown(): return _check_cooldown("squadhelp_global_cooldown", 900)
def update_squadhelp_global_cooldown(uid, un): _update_cooldown("squadhelp_global_cooldown", uid, un)
def check_drhelp_global_cooldown(): return _check_cooldown("drhelp_global_cooldown", 300)
def update_drhelp_global_cooldown(uid, un): _update_cooldown("drhelp_global_cooldown", uid, un)
def check_eventping_global_cooldown(): return _check_cooldown("eventping_global_cooldown", 900)
def update_eventping_global_cooldown(uid, un): _update_cooldown("eventping_global_cooldown", uid, un)

def has_snipe_afk_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        role = interaction.guild.get_role(SNIPE_AFK_ROLE_ID)
        if role and role in interaction.user.roles: return True
        if interaction.user.id in [1214456066687893506, 553418145063239684]: return True
        await interaction.response.send_message("❌ You need the designated role to use this command!", ephemeral=True)
        return False
    return app_commands.check(predicate)

# ========== HELPERS ==========
def parse_timestamp(ts_str):
    ts_str = ts_str.strip()
    m = re.match(r'<t:(\d+)>', ts_str)
    if m: return int(m.group(1))
    try:
        ts = int(ts_str)
        return ts // 1000 if len(str(ts)) == 13 else ts
    except: return None

def add_announcement_to_db(title, desc, role_id, ch_id, time, by_id, by_name):
    try:
        with db_connection('announcements.db') as conn:
            aid = str(uuid.uuid4())[:8]
            conn.cursor().execute("INSERT INTO announcements VALUES (?,?,?,?,?,?,?,?,?,?)",
                (aid, title, desc, role_id, ch_id, time.isoformat(), by_id, by_name, datetime.now().isoformat(), "pending"))
            conn.commit()
            return aid
    except: return None

def get_pending_announcements():
    try:
        with db_connection('announcements.db') as conn:
            return conn.cursor().execute("SELECT * FROM announcements WHERE status='pending' AND announce_time<=?", (datetime.now().isoformat(),)).fetchall()
    except: return []

def update_announcement_status(aid, status):
    try:
        with db_connection('announcements.db') as conn:
            conn.cursor().execute("UPDATE announcements SET status=? WHERE id=?", (status, aid))
            conn.commit()
    except: pass

def get_user_announcements(uid):
    try:
        with db_connection('announcements.db') as conn:
            return conn.cursor().execute("SELECT * FROM announcements WHERE created_by=? ORDER BY announce_time", (uid,)).fetchall()
    except: return []

def cancel_announcement(aid, uid):
    try:
        with db_connection('announcements.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE announcements SET status='cancelled' WHERE id=? AND created_by=?", (aid, uid))
            rows = c.rowcount; conn.commit()
            return rows > 0
    except: return False

def load_formations():
    try:
        with open('formations.json') as f: return json.load(f)
    except:
        return {"formations": {
            "manager_mode": ["4-2-4","4-3-3 Holding","4-2-3-1 Wide","4-3-3 Attack","4-2-3-1 Narrow","4-4-2 Holding","4-2-1-3"],
            "vs_attack": ["4-2-4","3-5-2","3-4-1-2","3-4-2-1","5-2-2-1","4-3-3 Attack","4-2-1-3","5-3-2","4-3-3 Holding"],
            "head_to_head": ["4-2-3-1 Wide","4-2-3-1 Narrow","3-5-2","4-2-2-2","4-3-3 Holding","4-1-2-1-2 Wide","4-1-2-1-2 Narrow","4-4-2 Holding","4-2-1-3"]
        }}

def load_redeem_codes():
    try:
        with open('redeem_codes.json') as f: return json.load(f)
    except: return {"redeem_codes":[],"redeem_history":{},"last_updated":""}

def save_redeem_codes(data):
    try:
        with open('redeem_codes.json','w') as f: json.dump(data, f, indent=2)
        return True
    except: return False

def can_manage_redeem_codes(uid): return uid in [1214456066687893506, 553418145063239684, 1221841129151139841]

TIMEZONE_MAPPING = {
    "EST":"America/New_York","EDT":"America/New_York","CST":"America/Chicago","CDT":"America/Chicago",
    "MST":"America/Denver","MDT":"America/Denver","PST":"America/Los_Angeles","PDT":"America/Los_Angeles",
    "GMT":"Europe/London","BST":"Europe/London","UTC":"UTC","CET":"Europe/Paris","CEST":"Europe/Paris",
    "EET":"Europe/Helsinki","EEST":"Europe/Helsinki","IST":"Asia/Kolkata","JST":"Asia/Tokyo",
    "KST":"Asia/Seoul","HKT":"Asia/Hong_Kong","SGT":"Asia/Singapore","PHT":"Asia/Manila",
    "AEST":"Australia/Sydney","AEDT":"Australia/Sydney","AWST":"Australia/Perth",
    "NZST":"Pacific/Auckland","NZDT":"Pacific/Auckland","SAST":"Africa/Johannesburg",
    "MSK":"Europe/Moscow","GST":"Asia/Dubai","PKT":"Asia/Karachi","BDT":"Asia/Dhaka",
}

def get_timezone_from_abbreviation(abbr):
    abbr_upper = abbr.upper()
    if abbr_upper in TIMEZONE_MAPPING: return pytz.timezone(TIMEZONE_MAPPING[abbr_upper])
    try: return pytz.timezone(abbr)
    except: return None

class BotHealthChecker:
    def __init__(self):
        self.start_time = datetime.now()
        self.command_count = 0
        self.error_count = 0
        self.last_error = None
    def check_health(self):
        uptime = datetime.now() - self.start_time
        return {"uptime":str(uptime).split('.')[0],"commands":self.command_count,"errors":self.error_count,"last_error":str(self.last_error)[:200] if self.last_error else "None"}

health_checker = BotHealthChecker()

# ========== SNIPE PAGINATION VIEW ==========
class SnipePagination(discord.ui.View):
    def __init__(self, messages, is_edit=False):
        super().__init__(timeout=60)
        self.messages = messages
        self.is_edit = is_edit
        self.current_page = 0
        self.update_buttons()
    
    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.messages) - 1
    
    def get_embed(self):
        msg = self.messages[self.current_page]
        time_diff = (datetime.now() - msg["time"]).seconds
        
        if time_diff < 60: time_text = f"{time_diff}s ago"
        elif time_diff < 3600: time_text = f"{time_diff // 60}m ago"
        else: time_text = f"{time_diff // 3600}h ago"
        
        total = len(self.messages)
        
        if self.is_edit:
            embed = discord.Embed(color=0xF59E0B, timestamp=msg["time"])
            embed.set_author(name=f"✏️ {msg['author']}", icon_url=msg["author_avatar"])
            embed.add_field(name="❌ Before", value=msg["before"][:1024] or "No content", inline=False)
            embed.add_field(name="✅ After", value=msg["after"][:1024] or "No content", inline=False)
            embed.set_footer(text=f"Edited {time_text} • {self.current_page + 1}/{total}")
        else:
            embed = discord.Embed(description=msg["content"][:2000], color=0xDC2626, timestamp=msg["time"])
            embed.set_author(name=f"🗑️ {msg['author']}", icon_url=msg["author_avatar"])
            embed.set_footer(text=f"Deleted {time_text} • {self.current_page + 1}/{total}")
            if msg.get("attachments"):
                embed.add_field(name="📎 Attachments", value="\n".join(msg["attachments"][:3])[:1024], inline=False)
                if msg["attachments"]: embed.set_image(url=msg["attachments"][0])
        
        return embed
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.defer()
    
    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.messages) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.defer()

# ========== BOT CLASS ==========
class FCOHomiesBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.all(), help_command=None)
        self.formations_data = load_formations()
        self.redeem_data = load_redeem_codes()
        self.lfm_role_id = 1391787410182111456
        self.squadhelp_role_id = 1391671605826031626
        self.squadhelp_role_id_2 = 1517837277005484152
        self.drhelp_role_id = 1446014580081037314
        self.eventping_role_id = 1534545908853903511

    async def setup_hook(self):
        print("🔄 Bot ready - use /sync to register commands")

bot = FCOHomiesBot()

# ========== SNIPE EVENTS ==========
@bot.event
async def on_message_delete(message):
    if message.author.bot or message.author.id in SNIPE_IGNORE: return
    if not message.content and not message.attachments: return
    
    if message.channel.id not in deleted_messages:
        deleted_messages[message.channel.id] = []
    
    msg_data = {
        "content": message.content or "*No text*",
        "author": str(message.author),
        "author_avatar": message.author.display_avatar.url if message.author.display_avatar else None,
        "time": datetime.now(),
        "attachments": [att.url for att in message.attachments] if message.attachments else []
    }
    
    deleted_messages[message.channel.id].insert(0, msg_data)
    if len(deleted_messages[message.channel.id]) > 50:
        deleted_messages[message.channel.id] = deleted_messages[message.channel.id][:50]

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.author.id in SNIPE_IGNORE: return
    if before.content == after.content: return
    
    if before.channel.id not in edited_messages:
        edited_messages[before.channel.id] = []
    
    msg_data = {
        "before": before.content or "*No text*",
        "after": after.content or "*No text*",
        "author": str(before.author),
        "author_avatar": before.author.display_avatar.url if before.author.display_avatar else None,
        "time": datetime.now()
    }
    
    edited_messages[before.channel.id].insert(0, msg_data)
    if len(edited_messages[before.channel.id]) > 50:
        edited_messages[before.channel.id] = edited_messages[before.channel.id][:50]

# ========== AFK + AUTO-MOD EVENTS ==========
@bot.event
async def on_message(message):
    if message.author.bot: 
        await bot.process_commands(message)
        return
    
    # ===== AUTO-MOD: Language detection =====
    if message.guild and message.content and len(message.content.strip()) > 10:
        is_exempt = (message.channel.id in MULTILINGUAL_CHANNELS or 
                     message.author.guild_permissions.manage_messages or
                     message.author.id in [1214456066687893506, 553418145063239684])
        
        if not is_exempt:
            # Quick pre-check: if mostly ASCII, skip detection
            ascii_count = sum(1 for c in message.content if ord(c) < 128)
            total_chars = len(message.content)
            
            # Only run langdetect if message has significant non-ASCII content
            if ascii_count / total_chars < 0.85:
                try:
                    lang = detect(message.content)
                    if lang != 'en':
                        try:
                            await message.delete()
                            print(f"🗑️ Auto-Mod: Deleted {lang} msg from {message.author}: {message.content[:50]}")
                        except Exception as e:
                            print(f"⚠️ Auto-Mod delete error: {e}")
                        
                        try:
                            channels = ", ".join([f"<#{ch_id}>" for ch_id in MULTILINGUAL_CHANNELS])
                            embed = discord.Embed(
                                title="⚠️ English Only Channel",
                                description=f"{message.author.mention}, please use **English only** in this channel.\nUse {channels} for other languages.",
                                color=0xDC2626
                            )
                            embed.set_footer(text="Ω Lite | Auto-Mod")
                            await message.channel.send(embed=embed, delete_after=10)
                        except:
                            pass
                        
                        await bot.process_commands(message)
                        return
                except:
                    pass  # Can't detect - let it go
    
    # ===== AFK mention detection =====
    for mention in message.mentions:
        if mention.id in afk_users:
            afk_data = afk_users[mention.id]
            time_diff = (datetime.now() - afk_data["time"]).seconds
            if time_diff < 60: time_text = f"{time_diff}s ago"
            elif time_diff < 3600: time_text = f"{time_diff // 60}m ago"
            else: time_text = f"{time_diff // 3600}h ago"
            
            if "pings" not in afk_data: afk_data["pings"] = []
            afk_data["pings"].append({
                "author": str(message.author), "author_mention": message.author.mention,
                "content": message.content[:100], "time": datetime.now(),
                "jump_url": message.jump_url, "channel": str(message.channel)
            })
            if len(afk_data["pings"]) > 10: afk_data["pings"] = afk_data["pings"][-10:]
            
            embed = discord.Embed(
                description=f"💤 **{mention.display_name}** is AFK: {afk_data['reason']}\n🕐 {time_text}",
                color=0xF59E0B
            )
            await message.reply(embed=embed, delete_after=10)
            break
    
    # ===== AFK return detection =====
    if message.author.id in afk_users:
        afk_data = afk_users[message.author.id]
        embed = discord.Embed(description=f"👋 Welcome back **{message.author.display_name}**! Removed your AFK.", color=0x10B981)
        if "pings" in afk_data and afk_data["pings"]:
            ping_text = ""
            for ping in afk_data["pings"][:5]:
                ping_time_diff = (datetime.now() - ping["time"]).seconds
                if ping_time_diff < 60: ping_time_text = f"{ping_time_diff}s ago"
                elif ping_time_diff < 3600: ping_time_text = f"{ping_time_diff // 60}m ago"
                else: ping_time_text = f"{ping_time_diff // 3600}h ago"
                ping_text += f"• **{ping['author']}** in {ping['channel']}: [Jump to message]({ping['jump_url']})\n  └ {ping_time_text}\n"
            embed.add_field(name=f"📩 You were pinged {len(afk_data['pings'])} time(s):", value=ping_text[:1024], inline=False)
        del afk_users[message.author.id]
        await message.reply(embed=embed)
    
    await bot.process_commands(message)

# ========== EVENTS ==========
@bot.event
async def on_ready():
    print(f'⚡ Ω LITE is now operational!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    print(f'🛡️ Auto-Mod: Active | Multilingual: <#{MULTILINGUAL_CHANNELS[0] if MULTILINGUAL_CHANNELS else "None"}>')
    bot.loop.create_task(check_announcements())
    bot.loop.create_task(self_ping())
    bot.loop.create_task(memory_cleanup())

# ========== BACKGROUND ==========
async def self_ping():
    await bot.wait_until_ready()
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://omega-lite.onrender.com")
    await asyncio.sleep(60)
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    if resp.status == 200: print(f"🔄 Ping OK at {datetime.now().strftime('%H:%M:%S')}")
        except: pass
        await asyncio.sleep(840)

async def memory_cleanup():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        gc.collect()
        cutoff = datetime.now() - timedelta(hours=6)
        for ch_id in list(deleted_messages.keys()):
            deleted_messages[ch_id] = [m for m in deleted_messages[ch_id] if m["time"] > cutoff]
            if not deleted_messages[ch_id]: del deleted_messages[ch_id]
        for ch_id in list(edited_messages.keys()):
            edited_messages[ch_id] = [m for m in edited_messages[ch_id] if m["time"] > cutoff]
            if not edited_messages[ch_id]: del edited_messages[ch_id]

async def check_announcements():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for a in get_pending_announcements():
                try:
                    ch = bot.get_channel(int(a[4]))
                    if ch:
                        role = ch.guild.get_role(int(a[3]))
                        if role:
                            embed = discord.Embed(title=f"📢 {a[1]}", description=a[2], color=0x8B5CF6, timestamp=datetime.now())
                            embed.add_field(name="Scheduled by", value=a[7], inline=True)
                            embed.add_field(name="Announcement ID", value=f"`{a[0]}`", inline=True)
                            embed.set_footer(text="Ω Lite Announcement System")
                            await ch.send(content=f"{role.mention}", embed=embed)
                            update_announcement_status(a[0], "sent")
                        else: update_announcement_status(a[0], "failed")
                    else: update_announcement_status(a[0], "failed")
                except: pass
            await asyncio.sleep(30)
        except: await asyncio.sleep(60)

# ========== ANNOUNCEMENT COMMANDS ==========

@bot.tree.command(name="announce", description="Schedule an announcement with role ping using timestamp")
@app_commands.describe(title="Title", description="Content", role="Role to ping", timestamp="Unix timestamp or <t:...>")
async def schedule_announcement(interaction: discord.Interaction, title: str, description: str, role: discord.Role, timestamp: str):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        ts = parse_timestamp(timestamp)
        if ts is None:
            await interaction.followup.send("❌ Invalid timestamp! Examples: `1734567890` or `<t:1734567890>`", ephemeral=True)
            return
        announce_time = datetime.fromtimestamp(ts, tz=pytz.UTC)
        if announce_time <= datetime.now(pytz.UTC):
            await interaction.followup.send("❌ Must be in the future!", ephemeral=True)
            return
        aid = add_announcement_to_db(title, description, str(role.id), str(interaction.channel_id), announce_time, str(interaction.user.id), interaction.user.name)
        if not aid:
            await interaction.followup.send("❌ Failed!", ephemeral=True)
            return
        embed = discord.Embed(title="✅ Scheduled!", description=f"I'll announce this in {interaction.channel.mention}\n\n**{title}**\n{description}\n\n⏰ <t:{ts}:F>\n🆔 `{aid}`", color=0x10B981)
        embed.set_footer(text="Ω Lite | /announce_list to view")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="announce_list", description="View your announcements")
async def list_announcements(interaction: discord.Interaction):
    announcements = get_user_announcements(str(interaction.user.id))
    if not announcements:
        await interaction.response.send_message("📭 None!", ephemeral=True)
        return
    embed = discord.Embed(title="📋 Your Announcements", color=0x8B5CF6)
    for a in announcements[:10]:
        ts = int(datetime.fromisoformat(a[5]).timestamp())
        embed.add_field(name=f"`{a[0]}` - {a[1]}", value=f"Status: {a[9]} | <t:{ts}:R>", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="announce_cancel", description="Cancel an announcement")
@app_commands.describe(announcement_id="ID to cancel")
async def cancel_announcement_command(interaction: discord.Interaction, announcement_id: str):
    if cancel_announcement(announcement_id, str(interaction.user.id)):
        await interaction.response.send_message(f"✅ Cancelled!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Not found!", ephemeral=True)

# ========== LFM COMMAND ==========

@bot.tree.command(name="lfm", description="Looking for match (5-min cooldown)")
async def lfm_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_lfm_global_cooldown()
        if on_cd:
            await interaction.followup.send(f"⏳ {int(rem)}s left. Last: <@{uid}>", ephemeral=True)
            return
        role = interaction.guild.get_role(bot.lfm_role_id)
        if not role:
            await interaction.followup.send("❌ Role not found!", ephemeral=True)
            return
        embed = discord.Embed(title="🎮 Looking for Match", description=f"{interaction.user.mention} is looking for a match!", color=0x10B981, timestamp=datetime.now())
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="💡 Join", value="Ping the player!", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | 5-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_lfm_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted!", ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="lfm_status", description="Check LFM cooldown")
async def lfm_status_check(interaction: discord.Interaction):
    on_cd, rem, uid, _ = check_lfm_global_cooldown()
    await interaction.response.send_message(f"⏳ {int(rem)}s left. Last: <@{uid}>" if on_cd else "✅ Ready!", ephemeral=True)

# ========== SQUADHELP COMMAND ==========

@bot.tree.command(name="squadhelp", description="Request squad help (15-min cooldown)")
async def squadhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_squadhelp_global_cooldown()
        if on_cd:
            await interaction.followup.send(f"⏳ {int(rem//60)}m left. Last: <@{uid}>", ephemeral=True)
            return
        role = interaction.guild.get_role(bot.squadhelp_role_id)
        if not role:
            await interaction.followup.send("❌ Role not found!", ephemeral=True)
            return
        embed = discord.Embed(title="🛡️ Squad Help", description=f"{interaction.user.mention} needs squad help!", color=0x3B82F6, timestamp=datetime.now())
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="💡 Help", value="Ping the player!", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | 15-min cooldown")
        await interaction.channel.send(content=f"{role.mention} <@&{bot.squadhelp_role_id_2}>", embed=embed)
        update_squadhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted!", ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="squadhelp_status", description="Check SquadHelp cooldown")
async def squadhelp_status_check(interaction: discord.Interaction):
    on_cd, rem, uid, _ = check_squadhelp_global_cooldown()
    await interaction.response.send_message(f"⏳ {int(rem//60)}m left. Last: <@{uid}>" if on_cd else "✅ Ready!", ephemeral=True)

# ========== DRHELP COMMAND ==========

@bot.tree.command(name="drhelp", description="Request DR help (5-min cooldown)")
async def drhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_drhelp_global_cooldown()
        if on_cd:
            await interaction.followup.send(f"⏳ {int(rem)}s left. Last: <@{uid}>", ephemeral=True)
            return
        role = interaction.guild.get_role(bot.drhelp_role_id)
        if not role:
            await interaction.followup.send("❌ Role not found!", ephemeral=True)
            return
        embed = discord.Embed(title="⚔️ DR Help", description=f"{interaction.user.mention} needs DR help!", color=0xEF4444, timestamp=datetime.now())
        embed.add_field(name="Player", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="💡 Help", value="Ping the player!", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | 5-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_drhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted!", ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="drhelp_status", description="Check DRHelp cooldown")
async def drhelp_status_check(interaction: discord.Interaction):
    on_cd, rem, uid, _ = check_drhelp_global_cooldown()
    await interaction.response.send_message(f"⏳ {int(rem)}s left. Last: <@{uid}>" if on_cd else "✅ Ready!", ephemeral=True)

# ========== EVENTPING COMMAND ==========

@bot.tree.command(name="eventping", description="📢 Ping for events (15-min cooldown)")
async def eventping_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_eventping_global_cooldown()
        if on_cd:
            await interaction.followup.send(f"⏳ {int(rem//60)}m left. Last: <@{uid}>", ephemeral=True)
            return
        role = interaction.guild.get_role(bot.eventping_role_id)
        if not role:
            await interaction.followup.send("❌ Role not found!", ephemeral=True)
            return
        embed = discord.Embed(title="📢 Event Alert!", description=f"{interaction.user.mention} has an event!", color=0x8B5CF6, timestamp=datetime.now())
        embed.add_field(name="Posted by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Time", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="💡 Respond", value="React or reply!", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="Ω Lite | 15-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_eventping_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted!", ephemeral=True)
    except Exception as e:
        health_checker.error_count += 1
        await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="eventping_status", description="Check EventPing cooldown")
async def eventping_status_check(interaction: discord.Interaction):
    on_cd, rem, uid, _ = check_eventping_global_cooldown()
    await interaction.response.send_message(f"⏳ {int(rem//60)}m left. Last: <@{uid}>" if on_cd else "✅ Ready!", ephemeral=True)

# ========== OVR COMMAND ==========

@bot.tree.command(name="ovr", description="Calculate team OVR")
@app_commands.describe(count="Players (min 11)", base_ovr_values="Base OVRs separated by +", rankup_values="Rankups separated by +", total_max_badges="Max badges")
async def ovr_calc(interaction: discord.Interaction, count: int, base_ovr_values: str, rankup_values: str, total_max_badges: int = 0):
    health_checker.command_count += 1
    await interaction.response.defer()
    try:
        bl = [int(x.strip()) for x in base_ovr_values.split('+')]
        rl = [int(x.strip()) for x in rankup_values.split('+')]
        if count < 11 or len(bl) != count or len(rl) != count:
            await interaction.followup.send(f"❌ Need {count} values each!", ephemeral=True)
            return
        cb = 1 + (sum(bl) - 1) // count
        cr = 1 + (sum(rl) - 1) // count
        total = cb + cr + total_max_badges
        embed = discord.Embed(title="⚡ Ω Lite OVR Analysis", color=0x1E40AF)
        embed.add_field(name="👥 Players", value=count, inline=True)
        embed.add_field(name="⭐ Base", value=cb, inline=True)
        embed.add_field(name="⬆️ Ranks", value=cr, inline=True)
        embed.add_field(name="🎯 Total", value=f"**{total}**" if total_max_badges else total, inline=False)
        base_req = (cb * count) + 1 - sum(bl)
        rank_req = (cr * count) + 1 - sum(rl)
        if base_req > 0 or rank_req > 0:
            reqs = []
            if base_req > 0: reqs.append(f"• Base OVR: +{base_req}")
            if rank_req > 0: reqs.append(f"• Rankups: +{rank_req}")
            embed.add_field(name="📈 Next Level", value="\n".join(reqs), inline=False)
        embed.set_footer(text="Ω Lite | Use + between values")
        await interaction.followup.send(embed=embed)
    except:
        await interaction.followup.send("❌ Invalid numbers!", ephemeral=True)

# ========== INVEST COMMAND ==========

@bot.tree.command(name="invest", description="Investment calculator (10% tax)")
@app_commands.describe(buy_price="Buy price", buy_quantity="Qty", sell_price="Sell price", sell_quantity="Qty")
async def invest_calc(interaction: discord.Interaction, buy_price: float, buy_quantity: int, sell_price: float, sell_quantity: int):
    health_checker.command_count += 1
    await interaction.response.defer()
    inv = buy_price * buy_quantity
    sales = sell_price * sell_quantity
    tax = sales * 0.10
    profit = (sales - tax) - inv
    embed = discord.Embed(title="💹 Ω Lite Investment Report", color=0x10B981 if profit > 0 else 0xDC2626)
    embed.add_field(name="Investment", value=f"{inv:,.0f} coins", inline=False)
    embed.add_field(name="Sales (Before Tax)", value=f"{sales:,.0f} coins", inline=True)
    embed.add_field(name="Tax (10%)", value=f"{tax:,.0f} coins", inline=True)
    embed.add_field(name="Sales (After Tax)", value=f"{sales - tax:,.0f} coins", inline=False)
    embed.add_field(name="Result", value=f"💰 Profit: {profit:,.0f}" if profit > 0 else f"📉 Loss: {abs(profit):,.0f}" if profit < 0 else "⚖️ Break Even", inline=False)
    if profit > 0: embed.add_field(name="📈 ROI", value=f"{(profit/inv)*100:.2f}%", inline=True)
    embed.set_footer(text="Ω Lite")
    await interaction.followup.send(embed=embed)

# ========== TIMEZONE COMMANDS ==========

@bot.tree.command(name="timezone", description="Convert timezone")
@app_commands.describe(utc_time="UTC time or 'now'", timezone="e.g., EST, IST")
async def timezone_convert(interaction: discord.Interaction, utc_time: str, timezone: str):
    health_checker.command_count += 1
    await interaction.response.defer()
    try:
        if utc_time.lower() == 'now': utc_obj = datetime.now(pytz.UTC)
        else: utc_obj = pytz.UTC.localize(datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S'))
        tz = get_timezone_from_abbreviation(timezone)
        if not tz:
            await interaction.followup.send(f"❌ Unknown: {timezone}", ephemeral=True)
            return
        cv = utc_obj.astimezone(tz)
        embed = discord.Embed(title="🕒 Time Conversion", color=0x8B5CF6)
        embed.add_field(name="🌐 UTC", value=utc_obj.strftime('%Y-%m-%d %H:%M:%S'), inline=False)
        embed.add_field(name="🎯 Converted", value=cv.strftime('%Y-%m-%d %H:%M:%S'), inline=False)
        embed.add_field(name="📍 Timezone", value=timezone.upper(), inline=True)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
    except:
        await interaction.followup.send("❌ Format: YYYY-MM-DD HH:MM:SS", ephemeral=True)

@bot.tree.command(name="datetotimestamp", description="Date to Unix timestamp")
@app_commands.describe(date="YYYY-MM-DD", time="HH:MM:SS", timezone="e.g., UTC")
async def date_to_timestamp(interaction: discord.Interaction, date: str, time: str = "00:00:00", timezone: str = "UTC"):
    health_checker.command_count += 1
    await interaction.response.defer()
    try:
        dt = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M:%S')
        if timezone.upper() != "UTC":
            tz = get_timezone_from_abbreviation(timezone)
            if tz: dt = tz.localize(dt).astimezone(pytz.UTC)
            else: dt = dt.replace(tzinfo=pytz.UTC)
        else: dt = dt.replace(tzinfo=pytz.UTC)
        ts = int(dt.timestamp())
        embed = discord.Embed(title="📅 Timestamp Converter", color=0x10B981)
        embed.add_field(name="Unix", value=f"`{ts}`", inline=False)
        embed.add_field(name="Discord", value=f"<t:{ts}:F>", inline=True)
        embed.add_field(name="Relative", value=f"<t:{ts}:R>", inline=True)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
    except:
        await interaction.followup.send("❌ Invalid date!", ephemeral=True)

# ========== FORMATIONS COMMAND ==========

@bot.tree.command(name="formations", description="Best formations")
@app_commands.choices(game_mode=[app_commands.Choice(name="Manager Mode", value="manager_mode"), app_commands.Choice(name="VS Attack", value="vs_attack"), app_commands.Choice(name="Head to Head", value="head_to_head")])
async def formations_command(interaction: discord.Interaction, game_mode: str):
    formations = bot.formations_data["formations"].get(game_mode, [])
    embed = discord.Embed(title=f"⚡ Ω Lite - {game_mode.replace('_',' ').title()} Formations", color=0x8B5CF6)
    embed.add_field(name="Recommended", value="\n".join([f"• {f}" for f in formations]) if formations else "None", inline=False)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

# ========== REDEEM CODE COMMANDS ==========

@bot.tree.command(name="redeem", description="View FC Mobile codes")
async def redeem_codes(interaction: discord.Interaction):
    await interaction.response.defer()
    codes = [c for c in bot.redeem_data.get("redeem_codes", []) if c.get("active", True)]
    if not codes:
        await interaction.followup.send("🎁 No active codes!")
        return
    desc = f"**{len(codes)} active**\n[Redeem here](https://redeem.fcm.ea.com)\n\n"
    for c in codes: desc += f"`{c['code']}`\n🎁 {c.get('reward', 'N/A')}\n\n"
    embed = discord.Embed(title="🎁 FC Mobile Codes", description=desc, color=0x10B981)
    embed.set_footer(text="Ω Lite")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="redeem_add", description="Add redeem code (Admin)")
@app_commands.describe(code="Code", reward="Reward", active="Active?")
async def redeem_add(interaction: discord.Interaction, code: str, reward: str, active: bool = True):
    if not can_manage_redeem_codes(interaction.user.id):
        await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    for c in bot.redeem_data.get("redeem_codes", []):
        if c["code"].upper() == code.upper():
            await interaction.followup.send("❌ Code exists!", ephemeral=True)
            return
    bot.redeem_data.setdefault("redeem_codes", []).append({"code": code.upper(), "reward": reward, "active": active})
    save_redeem_codes(bot.redeem_data)
    await interaction.followup.send(f"✅ Added `{code.upper()}`!", ephemeral=True)

@bot.tree.command(name="redeem_remove", description="Remove redeem code (Admin)")
@app_commands.describe(code="Code to remove")
async def redeem_remove(interaction: discord.Interaction, code: str):
    if not can_manage_redeem_codes(interaction.user.id):
        await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    bot.redeem_data["redeem_codes"] = [c for c in bot.redeem_data.get("redeem_codes", []) if c["code"].upper() != code.upper()]
    save_redeem_codes(bot.redeem_data)
    await interaction.followup.send(f"✅ Removed `{code.upper()}`!", ephemeral=True)

# ========== SNIPE COMMANDS ==========

@bot.tree.command(name="snipe", description="🔫 Show deleted messages (Role restricted)")
@app_commands.describe(page="Which deleted message (1=latest)")
@has_snipe_afk_role()
async def snipe(interaction: discord.Interaction, page: int = 1):
    await interaction.response.defer(ephemeral=False)
    if interaction.channel.id not in deleted_messages or not deleted_messages[interaction.channel.id]:
        await interaction.followup.send("🔫 Nothing to snipe!", ephemeral=True)
        return
    messages = deleted_messages[interaction.channel.id]
    if page < 1 or page > len(messages):
        await interaction.followup.send(f"❌ Page 1-{len(messages)} only!", ephemeral=True)
        return
    if len(messages) == 1:
        msg = messages[0]
        td = (datetime.now() - msg["time"]).seconds
        time_text = f"{td}s ago" if td < 60 else f"{td//60}m ago" if td < 3600 else f"{td//3600}h ago"
        embed = discord.Embed(description=msg["content"][:2000], color=0xDC2626, timestamp=msg["time"])
        embed.set_author(name=f"🗑️ {msg['author']}", icon_url=msg["author_avatar"])
        embed.set_footer(text=f"Deleted {time_text}")
        if msg.get("attachments"):
            embed.add_field(name="📎 Attachments", value="\n".join(msg["attachments"][:3])[:1024], inline=False)
            if msg["attachments"]: embed.set_image(url=msg["attachments"][0])
        await interaction.followup.send(embed=embed)
        return
    view = SnipePagination(messages, is_edit=False)
    view.current_page = page - 1
    view.update_buttons()
    await interaction.followup.send(embed=view.get_embed(), view=view)

@bot.tree.command(name="editsnipe", description="✏️ Show edited messages (Role restricted)")
@app_commands.describe(page="Which edited message (1=latest)")
@has_snipe_afk_role()
async def editsnipe(interaction: discord.Interaction, page: int = 1):
    await interaction.response.defer(ephemeral=False)
    if interaction.channel.id not in edited_messages or not edited_messages[interaction.channel.id]:
        await interaction.followup.send("✏️ Nothing to editsnipe!", ephemeral=True)
        return
    messages = edited_messages[interaction.channel.id]
    if page < 1 or page > len(messages):
        await interaction.followup.send(f"❌ Page 1-{len(messages)} only!", ephemeral=True)
        return
    if len(messages) == 1:
        msg = messages[0]
        td = (datetime.now() - msg["time"]).seconds
        time_text = f"{td}s ago" if td < 60 else f"{td//60}m ago" if td < 3600 else f"{td//3600}h ago"
        embed = discord.Embed(color=0xF59E0B, timestamp=msg["time"])
        embed.set_author(name=f"✏️ {msg['author']}", icon_url=msg["author_avatar"])
        embed.add_field(name="❌ Before", value=msg["before"][:1024] or "No content", inline=False)
        embed.add_field(name="✅ After", value=msg["after"][:1024] or "No content", inline=False)
        embed.set_footer(text=f"Edited {time_text}")
        await interaction.followup.send(embed=embed)
        return
    view = SnipePagination(messages, is_edit=True)
    view.current_page = page - 1
    view.update_buttons()
    await interaction.followup.send(embed=view.get_embed(), view=view)

@bot.tree.command(name="snipe_clear", description="🧹 Clear snipe history (Role restricted)")
@has_snipe_afk_role()
async def snipe_clear(interaction: discord.Interaction):
    cleared = 0
    if interaction.channel.id in deleted_messages: del deleted_messages[interaction.channel.id]; cleared += 1
    if interaction.channel.id in edited_messages: del edited_messages[interaction.channel.id]; cleared += 1
    await interaction.response.send_message(f"🧹 Cleared {cleared} record(s)!" if cleared else "📭 Nothing!", ephemeral=True)

# ========== AFK COMMANDS ==========

@bot.tree.command(name="afk", description="💤 Set yourself as AFK (Role restricted)")
@app_commands.describe(reason="Reason for being AFK")
@has_snipe_afk_role()
async def afk(interaction: discord.Interaction, reason: str = "No reason"):
    afk_users[interaction.user.id] = {"reason": reason, "time": datetime.now(), "name": interaction.user.display_name, "pings": []}
    embed = discord.Embed(description=f"💤 **{interaction.user.display_name}** is now AFK: {reason}", color=0xF59E0B)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="afk_list", description="📋 Show AFK users (Role restricted)")
@has_snipe_afk_role()
async def afk_list(interaction: discord.Interaction):
    if not afk_users:
        await interaction.response.send_message("✅ No one is AFK!", ephemeral=True)
        return
    embed = discord.Embed(title="💤 AFK Users", color=0xF59E0B)
    for uid, data in afk_users.items():
        td = (datetime.now() - data["time"]).seconds
        time_text = f"{td}s ago" if td < 60 else f"{td//60}m ago" if td < 3600 else f"{td//3600}h ago"
        embed.add_field(name=data['name'], value=f"📝 {data['reason']}\n🕐 {time_text}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========== AUTO-MOD COMMANDS ==========

@bot.tree.command(name="automod_set", description="🔧 Set multilingual channel (Owner)")
@app_commands.describe(channel="Multilingual channel")
async def automod_set(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Owner only!", ephemeral=True)
        return
    MULTILINGUAL_CHANNELS.clear()
    MULTILINGUAL_CHANNELS.append(channel.id)
    embed = discord.Embed(title="✅ Auto-Mod Configured", description=f"**{channel.mention}** is now multilingual.\nAll other channels require English.", color=0x10B981)
    embed.add_field(name="🔍 Detection", value="Language detection", inline=False)
    embed.add_field(name="⚠️ Action", value="Delete + 10s warning", inline=False)
    embed.add_field(name="🛡️ Exempt", value="Admins & owners", inline=False)
    embed.set_footer(text="Ω Lite | Auto-Mod")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="automod_status", description="📊 Auto-mod status")
async def automod_status(interaction: discord.Interaction):
    embed = discord.Embed(title="🛡️ Auto-Mod Status", color=0x8B5CF6)
    if MULTILINGUAL_CHANNELS:
        embed.add_field(name="🌍 Multilingual", value=", ".join([f"<#{ch_id}>" for ch_id in MULTILINGUAL_CHANNELS]), inline=False)
    else:
        embed.add_field(name="🌍 Multilingual", value="None set", inline=False)
    embed.add_field(name="🔍 Detection", value="langdetect library", inline=False)
    embed.add_field(name="⚠️ Action", value="Delete + 10s warn", inline=False)
    embed.add_field(name="🛡️ Exempt", value="Admins & owners", inline=False)
    embed.set_footer(text="Ω Lite | Auto-Mod")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========== UTILITY COMMANDS ==========

@bot.tree.command(name="ping", description="Check latency")
async def ping(interaction: discord.Interaction):
    embed = discord.Embed(title="⚡ Ω Lite Status", description=f"**Latency:** {round(bot.latency*1000)}ms\n**Servers:** {len(bot.guilds)}", color=0x10B981)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="health", description="Bot health (Admin)")
async def health_check_command(interaction: discord.Interaction):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
        return
    h = health_checker.check_health()
    embed = discord.Embed(title="🏥 Health Report", color=0x8B5CF6)
    embed.add_field(name="⏱️ Uptime", value=h["uptime"], inline=False)
    embed.add_field(name="📊 Commands", value=h["commands"], inline=True)
    embed.add_field(name="❌ Errors", value=h["errors"], inline=True)
    embed.add_field(name="🔌 Latency", value=f"{round(bot.latency*1000)}ms", inline=True)
    embed.add_field(name="🔄 Servers", value=len(bot.guilds), inline=True)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="sync", description="Sync commands (Owner - ONCE!)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 1214456066687893506:
        await interaction.response.send_message("❌ Owner only!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ Synced {len(synced)} commands!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="timezones", description="List timezones")
async def timezone_help(interaction: discord.Interaction):
    embed = discord.Embed(title="🌍 Timezones", color=0x8B5CF6)
    embed.add_field(name="Americas", value="EST, CST, MST, PST", inline=False)
    embed.add_field(name="Europe", value="GMT, BST, UTC, CET", inline=False)
    embed.add_field(name="Asia", value="IST, JST, KST, HKT, SGT", inline=False)
    embed.add_field(name="Oceania", value="AEST, ACST, AWST, NZST", inline=False)
    embed.set_footer(text="Ω Lite")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="backup", description="Download backup (Admin)")
async def backup_command(interaction: discord.Interaction):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
        return
    await interaction.response.defer()
    files = [discord.File(f) for f in ['announcements.db', 'lfm.db', 'redeem_codes.json', 'formations.json'] if os.path.exists(f)]
    if files:
        embed = discord.Embed(title="📦 Backup", description=f"**Files:** {len(files)}", color=0x10B981)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed, files=files)
    else:
        await interaction.followup.send("❌ No files!")

@bot.tree.command(name="restore", description="Restore backup (Admin)")
async def restore_command(interaction: discord.Interaction, file: discord.Attachment):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]:
        await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        data = await file.read()
        with open(file.filename, 'wb') as f: f.write(data)
        await interaction.followup.send(f"✅ Restored {file.filename}!", ephemeral=True)
    except:
        await interaction.followup.send("❌ Failed!", ephemeral=True)

@bot.tree.command(name="help", description="Show all commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="⚡ Ω Lite - Help", description="**FC Mobile Discord Bot**", color=0x8B5CF6)
    embed.add_field(name="🎮 Game", value="`/ovr` `/invest` `/formations`", inline=False)
    embed.add_field(name="🌍 Time", value="`/timezone` `/datetotimestamp` `/timezones`", inline=False)
    embed.add_field(name="🎁 Rewards", value="`/redeem`", inline=False)
    embed.add_field(name="🎮 Pings", value="`/lfm` `/squadhelp` `/drhelp` `/eventping`", inline=False)
    embed.add_field(name="📢 Announce", value="`/announce` `/announce_list` `/announce_cancel`", inline=False)
    embed.add_field(name="🔫 Snipe", value="`/snipe` `/editsnipe` `/snipe_clear`", inline=False)
    embed.add_field(name="💤 AFK", value="`/afk` `/afk_list`", inline=False)
    embed.add_field(name="🛡️ Auto-Mod", value="`/automod_set` `/automod_status`", inline=False)
    embed.add_field(name="💾 Backup", value="`/backup` `/restore`", inline=False)
    embed.add_field(name="🔧 Utils", value="`/ping` `/help` `/health` `/sync`", inline=False)
    embed.set_footer(text="Ω Lite | Made for FC Mobile")
    await interaction.response.send_message(embed=embed)

# ========== START ==========
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    token = os.getenv('BOT_TOKEN')
    if not token: print("❌ BOT_TOKEN not set!"); sys.exit(1)
    
    print("=" * 50)
    print("🚀 Starting Ω Lite Bot...")
    print("=" * 50)
    
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    
    try:
        bot.run(token, reconnect=True)
    except discord.LoginFailure:
        print("❌ Invalid token!"); sys.exit(1)
    except Exception as e:
        print(f"❌ {e}"); sys.exit(1)
