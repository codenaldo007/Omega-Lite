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

# ========== FLASK SERVER (Start FIRST) ==========
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

# ========== DATABASE SETUP ==========
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
    except Exception as e: print(f"❌ DB init error: {e}")

def init_lfm_db():
    try:
        with db_connection('lfm.db') as conn:
            c = conn.cursor()
            for table in ["lfm_global_cooldown", "squadhelp_global_cooldown", "drhelp_global_cooldown"]:
                c.execute(f'''CREATE TABLE IF NOT EXISTS {table}
                    (id INTEGER PRIMARY KEY CHECK (id = 1), last_used TIMESTAMP,
                     last_user_id TEXT, last_user_name TEXT)''')
                c.execute(f"INSERT OR IGNORE INTO {table} VALUES (1, ?, ?, ?)",
                          (datetime.now().isoformat(), "0", "None"))
            conn.commit()
    except Exception as e: print(f"❌ LFM DB init error: {e}")

print("📁 Initializing databases...")
init_announcements_db()
init_lfm_db()
print("✅ Databases initialized")

# ========== COOLDOWN HELPERS ==========
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

# ========== BOT CLASS ==========
class FCOHomiesBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.all(), help_command=None)
        self.formations_data = load_formations()
        self.redeem_data = load_redeem_codes()
        self.lfm_role_id = 1391787410182111456
        self.squadhelp_role_id = 1391671605826031626
        self.drhelp_role_id = 1446014580081037314

    async def setup_hook(self):
        # Only sync if no commands exist (first run), skip on restarts
        try:
            existing = await self.tree.fetch_commands()
            if not existing:
                print("🔄 No commands found - performing initial sync...")
                await self.tree.sync()
                print("✅ Commands synced!")
            else:
                print(f"✅ {len(existing)} commands already registered - skipping sync")
        except Exception as e:
            print(f"⚠️ Could not check commands: {e}")
            # If we can't check, try syncing anyway (might be first run with rate limit)
            if "429" not in str(e):
                try:
                    await self.tree.sync()
                    print("✅ Commands synced (fallback)!")
                except: pass

bot = FCOHomiesBot()

# ========== BOT EVENTS ==========
@bot.event
async def on_ready():
    print(f'⚡ Ω LITE is now operational!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    print(f'🔧 User: {bot.user}')
    bot.loop.create_task(check_announcements())
    bot.loop.create_task(self_ping())
    bot.loop.create_task(memory_cleanup())

# ========== BACKGROUND TASKS ==========
async def self_ping():
    await bot.wait_until_ready()
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://omega-lite.onrender.com")
    await asyncio.sleep(60)
    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    if resp.status == 200: print(f"🔄 Ping OK at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e: print(f"⚠️ Ping failed: {e}")
        await asyncio.sleep(840)

async def memory_cleanup():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        gc.collect()
        print(f"🧹 Memory cleanup at {datetime.now().strftime('%H:%M:%S')}")

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
                            embed.set_footer(text="Ω Lite Announcement System")
                            await ch.send(content=f"{role.mention}", embed=embed)
                            update_announcement_status(a[0], "sent")
                        else: update_announcement_status(a[0], "failed")
                    else: update_announcement_status(a[0], "failed")
                except Exception as e: print(f"❌ Announcement {a[0]}: {e}")
            await asyncio.sleep(30)
        except Exception as e: print(f"❌ Checker error: {e}"); await asyncio.sleep(60)

# ========== COMMANDS ==========

@bot.tree.command(name="announce", description="Schedule an announcement with role ping")
@app_commands.describe(title="Title", description="What to announce", role="Role to ping", timestamp="Unix timestamp or <t:...>")
async def schedule_announcement(interaction: discord.Interaction, title: str, description: str, role: discord.Role, timestamp: str):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        ts = parse_timestamp(timestamp)
        if not ts: await interaction.followup.send("❌ Invalid timestamp!", ephemeral=True); return
        announce_time = datetime.fromtimestamp(ts, tz=pytz.UTC)
        if announce_time <= datetime.now(pytz.UTC): await interaction.followup.send("❌ Must be in the future!", ephemeral=True); return
        aid = add_announcement_to_db(title, description, str(role.id), str(interaction.channel_id), announce_time, str(interaction.user.id), interaction.user.name)
        if not aid: await interaction.followup.send("❌ Failed!", ephemeral=True); return
        embed = discord.Embed(title="✅ Scheduled!", description=f"**{title}**\n{description}\n\n⏰ <t:{ts}:F>\n🆔 `{aid}`", color=0x10B981)
        embed.set_footer(text="Ω Lite | /announce_list to view")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e: health_checker.error_count += 1; await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="announce_list", description="View your scheduled announcements")
async def list_announcements(interaction: discord.Interaction):
    health_checker.command_count += 1
    announcements = get_user_announcements(str(interaction.user.id))
    if not announcements: await interaction.response.send_message("📭 No announcements!", ephemeral=True); return
    embed = discord.Embed(title="📋 Your Announcements", color=0x8B5CF6)
    for a in announcements[:10]:
        ts = int(datetime.fromisoformat(a[5]).timestamp())
        embed.add_field(name=f"`{a[0]}` - {a[1]}", value=f"Status: {a[9]} | <t:{ts}:R>", inline=False)
    embed.set_footer(text="Ω Lite | /announce_cancel <id>")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="announce_cancel", description="Cancel an announcement")
@app_commands.describe(announcement_id="ID to cancel")
async def cancel_announcement_command(interaction: discord.Interaction, announcement_id: str):
    health_checker.command_count += 1
    if cancel_announcement(announcement_id, str(interaction.user.id)): await interaction.response.send_message(f"✅ Cancelled `{announcement_id}`!", ephemeral=True)
    else: await interaction.response.send_message("❌ Not found!", ephemeral=True)

@bot.tree.command(name="lfm", description="Looking for match (5-min cooldown)")
async def lfm_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, uname = check_lfm_global_cooldown()
        if on_cd: await interaction.followup.send(f"⏳ Cooldown: {int(rem)}s left. Last by <@{uid}>", ephemeral=True); return
        role = interaction.guild.get_role(bot.lfm_role_id)
        if not role: await interaction.followup.send("❌ Role not found!", ephemeral=True); return
        embed = discord.Embed(title="🎮 Looking for Match", description=f"{interaction.user.mention} is looking for a match!", color=0x10B981, timestamp=datetime.now())
        embed.set_footer(text="Ω Lite | 5-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_lfm_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted! 5-min cooldown.", ephemeral=True)
    except Exception as e: health_checker.error_count += 1; await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="lfm_status", description="Check LFM cooldown")
async def lfm_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
    on_cd, rem, uid, _ = check_lfm_global_cooldown()
    if on_cd: await interaction.response.send_message(f"⏳ LFM cooldown: {int(rem)}s left. Last by <@{uid}>", ephemeral=True)
    else: await interaction.response.send_message("✅ LFM is ready!", ephemeral=True)

@bot.tree.command(name="squadhelp", description="Request squad help (15-min cooldown)")
async def squadhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_squadhelp_global_cooldown()
        if on_cd: await interaction.followup.send(f"⏳ Cooldown: {int(rem//60)}m left. Last by <@{uid}>", ephemeral=True); return
        role = interaction.guild.get_role(bot.squadhelp_role_id)
        if not role: await interaction.followup.send("❌ Role not found!", ephemeral=True); return
        embed = discord.Embed(title="🛡️ Squad Help", description=f"{interaction.user.mention} needs squad help!", color=0x3B82F6, timestamp=datetime.now())
        embed.set_footer(text="Ω Lite | 15-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_squadhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted! 15-min cooldown.", ephemeral=True)
    except Exception as e: health_checker.error_count += 1; await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="squadhelp_status", description="Check SquadHelp cooldown")
async def squadhelp_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
    on_cd, rem, uid, _ = check_squadhelp_global_cooldown()
    if on_cd: await interaction.response.send_message(f"⏳ SquadHelp cooldown: {int(rem//60)}m left. Last by <@{uid}>", ephemeral=True)
    else: await interaction.response.send_message("✅ SquadHelp is ready!", ephemeral=True)

@bot.tree.command(name="drhelp", description="Request Division Rivals help (5-min cooldown)")
async def drhelp_command(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer(ephemeral=True)
    try:
        on_cd, rem, uid, _ = check_drhelp_global_cooldown()
        if on_cd: await interaction.followup.send(f"⏳ Cooldown: {int(rem)}s left. Last by <@{uid}>", ephemeral=True); return
        role = interaction.guild.get_role(bot.drhelp_role_id)
        if not role: await interaction.followup.send("❌ Role not found!", ephemeral=True); return
        embed = discord.Embed(title="⚔️ DR Help", description=f"{interaction.user.mention} needs DR help!", color=0xEF4444, timestamp=datetime.now())
        embed.set_footer(text="Ω Lite | 5-min cooldown")
        await interaction.channel.send(content=f"{role.mention}", embed=embed)
        update_drhelp_global_cooldown(str(interaction.user.id), interaction.user.name)
        await interaction.followup.send("✅ Posted!", ephemeral=True)
    except Exception as e: health_checker.error_count += 1; await interaction.followup.send(f"❌ {e}", ephemeral=True)

@bot.tree.command(name="drhelp_status", description="Check DRHelp cooldown")
async def drhelp_status_check(interaction: discord.Interaction):
    health_checker.command_count += 1
    on_cd, rem, uid, _ = check_drhelp_global_cooldown()
    if on_cd: await interaction.response.send_message(f"⏳ DRHelp cooldown: {int(rem)}s left. Last by <@{uid}>", ephemeral=True)
    else: await interaction.response.send_message("✅ DRHelp is ready!", ephemeral=True)

@bot.tree.command(name="ovr", description="Calculate team OVR")
@app_commands.describe(count="Players (min 11)", base_ovr_values="Base OVRs separated by +", rankup_values="Rankups separated by +", total_max_badges="Max badges (optional)")
async def ovr_calc(interaction: discord.Interaction, count: int, base_ovr_values: str, rankup_values: str, total_max_badges: int = 0):
    health_checker.command_count += 1
    await interaction.response.defer()
    try:
        bl = [int(x.strip()) for x in base_ovr_values.split('+')]
        rl = [int(x.strip()) for x in rankup_values.split('+')]
        if count < 11 or len(bl) != count or len(rl) != count: await interaction.followup.send(f"❌ Need {count} values each!", ephemeral=True); return
        cb = 1 + (sum(bl) - 1) // count
        cr = 1 + (sum(rl) - 1) // count
        total = cb + cr + total_max_badges
        embed = discord.Embed(title="⚡ OVR Analysis", color=0x1E40AF)
        embed.add_field(name="👥 Players", value=count, inline=True)
        embed.add_field(name="⭐ Base", value=cb, inline=True)
        embed.add_field(name="⬆️ Ranks", value=cr, inline=True)
        embed.add_field(name="🎯 Total", value=total, inline=False)
        embed.set_footer(text="Ω Lite")
        await interaction.followup.send(embed=embed)
    except: await interaction.followup.send("❌ Invalid numbers!", ephemeral=True)

@bot.tree.command(name="invest", description="Investment calculator (10% tax)")
@app_commands.describe(buy_price="Buy price", buy_quantity="Qty", sell_price="Sell price", sell_quantity="Qty")
async def invest_calc(interaction: discord.Interaction, buy_price: float, buy_quantity: int, sell_price: float, sell_quantity: int):
    health_checker.command_count += 1
    await interaction.response.defer()
    inv = buy_price * buy_quantity
    sales = sell_price * sell_quantity
    tax = sales * 0.10
    profit = (sales - tax) - inv
    embed = discord.Embed(title="💹 Investment Report", color=0x10B981 if profit > 0 else 0xDC2626)
    embed.add_field(name="Investment", value=f"{inv:,.0f}", inline=True)
    embed.add_field(name="Tax (10%)", value=f"{tax:,.0f}", inline=True)
    embed.add_field(name="Profit", value=f"{profit:,.0f}", inline=True)
    embed.set_footer(text="Ω Lite")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="timezone", description="Convert timezone")
@app_commands.describe(utc_time="UTC time or 'now'", timezone="e.g., EST, IST")
async def timezone_convert(interaction: discord.Interaction, utc_time: str, timezone: str):
    health_checker.command_count += 1
    await interaction.response.defer()
    try:
        if utc_time.lower() == 'now': utc_obj = datetime.now(pytz.UTC)
        else: utc_obj = pytz.UTC.localize(datetime.strptime(utc_time, '%Y-%m-%d %H:%M:%S'))
        tz = get_timezone_from_abbreviation(timezone)
        if not tz: await interaction.followup.send(f"❌ Unknown: {timezone}", ephemeral=True); return
        cv = utc_obj.astimezone(tz)
        await interaction.followup.send(f"🌐 UTC: {utc_obj.strftime('%Y-%m-%d %H:%M:%S')}\n📍 {timezone.upper()}: {cv.strftime('%Y-%m-%d %H:%M:%S')}")
    except: await interaction.followup.send("❌ Use format: YYYY-MM-DD HH:MM:SS", ephemeral=True)

@bot.tree.command(name="datetotimestamp", description="Date to Unix timestamp")
@app_commands.describe(date="YYYY-MM-DD", time="HH:MM:SS", timezone="e.g., UTC, IST")
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
        await interaction.followup.send(f"`{ts}` → <t:{ts}:F>")
    except: await interaction.followup.send("❌ Invalid date!", ephemeral=True)

@bot.tree.command(name="formations", description="Best formations")
@app_commands.choices(game_mode=[app_commands.Choice(name="Manager Mode", value="manager_mode"), app_commands.Choice(name="VS Attack", value="vs_attack"), app_commands.Choice(name="Head to Head", value="head_to_head")])
async def formations_command(interaction: discord.Interaction, game_mode: str):
    health_checker.command_count += 1
    formations = bot.formations_data["formations"].get(game_mode, [])
    await interaction.response.send_message("\n".join([f"• {f}" for f in formations]) if formations else "❌ Not found!")

@bot.tree.command(name="redeem", description="View FC Mobile codes")
async def redeem_codes(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.defer()
    codes = [c for c in bot.redeem_data.get("redeem_codes", []) if c.get("active", True)]
    if not codes: await interaction.followup.send("🎁 No active codes!"); return
    await interaction.followup.send("🎁 **Active Codes**\n" + "\n".join([f"`{c['code']}` - {c.get('reward','N/A')}" for c in codes]))

@bot.tree.command(name="redeem_add", description="Add redeem code (Admin)")
async def redeem_add(interaction: discord.Interaction, code: str, reward: str, active: bool = True):
    if not can_manage_redeem_codes(interaction.user.id): await interaction.response.send_message("❌ Not authorized!", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    bot.redeem_data.setdefault("redeem_codes", []).append({"code": code.upper(), "reward": reward, "active": active})
    save_redeem_codes(bot.redeem_data)
    await interaction.followup.send(f"✅ Added `{code.upper()}`!", ephemeral=True)

@bot.tree.command(name="redeem_remove", description="Remove redeem code (Admin)")
async def redeem_remove(interaction: discord.Interaction, code: str):
    if not can_manage_redeem_codes(interaction.user.id): await interaction.response.send_message("❌ Not authorized!", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    bot.redeem_data["redeem_codes"] = [c for c in bot.redeem_data.get("redeem_codes", []) if c["code"].upper() != code.upper()]
    save_redeem_codes(bot.redeem_data)
    await interaction.followup.send(f"✅ Removed `{code.upper()}`!", ephemeral=True)

@bot.tree.command(name="ping", description="Check latency")
async def ping(interaction: discord.Interaction):
    health_checker.command_count += 1
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms")

@bot.tree.command(name="health", description="Bot health (Admin)")
async def health_check_command(interaction: discord.Interaction):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]: await interaction.response.send_message("❌ Not authorized!", ephemeral=True); return
    h = health_checker.check_health()
    await interaction.response.send_message(f"⏱️ Uptime: {h['uptime']}\n📊 Commands: {h['commands']}\n❌ Errors: {h['errors']}\n🔌 Latency: {round(bot.latency*1000)}ms", ephemeral=True)

@bot.tree.command(name="sync", description="Sync commands (Owner only - use sparingly!)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 1214456066687893506: await interaction.response.send_message("❌ Owner only!", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ Synced {len(synced)} commands!", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)

@bot.tree.command(name="timezones", description="List timezones")
async def timezone_help(interaction: discord.Interaction):
    await interaction.response.send_message("🌍 **Timezones:** EST, CST, MST, PST, GMT, UTC, CET, IST, JST, KST, HKT, SGT, AEST, NZST, MSK, GST, PKT, BDT")

@bot.tree.command(name="backup", description="Download backup (Admin)")
async def backup_command(interaction: discord.Interaction):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]: await interaction.response.send_message("❌ Not authorized!", ephemeral=True); return
    await interaction.response.defer()
    files = [discord.File(f) for f in ['announcements.db', 'lfm.db', 'redeem_codes.json', 'formations.json'] if os.path.exists(f)]
    if files: await interaction.followup.send("📦 Backup:", files=files)
    else: await interaction.followup.send("❌ No files!")

@bot.tree.command(name="restore", description="Restore backup (Admin)")
async def restore_command(interaction: discord.Interaction, file: discord.Attachment):
    if interaction.user.id not in [1214456066687893506, 553418145063239684]: await interaction.response.send_message("❌ Not authorized!", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        data = await file.read()
        with open(file.filename, 'wb') as f: f.write(data)
        await interaction.followup.send(f"✅ Restored {file.filename}!", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Failed: {e}", ephemeral=True)

@bot.tree.command(name="help", description="Show all commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="⚡ Ω Lite - Help", description="**FC Mobile Discord Bot**", color=0x8B5CF6)
    embed.add_field(name="🎮 Game Tools", value="`/ovr` `/invest` `/formations`", inline=False)
    embed.add_field(name="🌍 Time Tools", value="`/timezone` `/datetotimestamp` `/timezones`", inline=False)
    embed.add_field(name="🎁 Rewards", value="`/redeem`", inline=False)
    embed.add_field(name="🎮 Ping Roles", value="`/lfm` `/squadhelp` `/drhelp`", inline=False)
    embed.add_field(name="📢 Announcements", value="`/announce` `/announce_list` `/announce_cancel`", inline=False)
    embed.add_field(name="💾 Backup", value="`/backup` `/restore`", inline=False)
    embed.add_field(name="🔧 Utilities", value="`/ping` `/health` `/sync` `/help`", inline=False)
    embed.set_footer(text="Ω Lite | /sync to register commands")
    await interaction.response.send_message(embed=embed)

# ========== START BOT ==========
if __name__ == "__main__":
    # Start Flask in a thread FIRST (like the working bot)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("❌ BOT_TOKEN not set!")
        sys.exit(1)
    
    print("=" * 50)
    print("🚀 Starting Ω Lite Bot...")
    print("=" * 50)
    
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    
    try:
        bot.run(token, reconnect=True)
    except discord.LoginFailure:
        print("❌ Invalid token!")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Crashed: {e}")
        sys.exit(1)
