# bot.py
# Full Club Auction Bot (single-file)
# Dependencies: discord.py, fastapi, uvicorn, jinja2
# Install: pip install discord.py fastapi uvicorn jinja2

import os
import sqlite3
import asyncio
import random
import threading
from datetime import datetime, timedelta

# ---------- CONFIG ----------
# Add your Discord token here OR set environment variable DISCORD_TOKEN
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN") or "PASTE_YOUR_TOKEN_HERE"

# Optional: owner id (int) for owner-only checks
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID")) if os.getenv("BOT_OWNER_ID") else None

# Optional: report channel id for weekly auto report
REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID")) if os.getenv("BOT_OWNER_ID") else None

# Enable a small web dashboard (FastAPI). Set to False if you don't want it.
START_DASHBOARD = False
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8000

# Auction config
TIME_LIMIT = 30 	# seconds after last bid until finalize
MIN_INCREMENT_PERCENT = 5 	# minimum percent increase per new bid
LEAVE_PENALTY_PERCENT = 10 	# if member leaves group mid-auction (applies to group funds)
DUELIST_MISS_PENALTY_PERCENT = 15 # salary deduction percent when a duelist misses a match

DB_FILE = "auction.db"
SCHEMA_FILE = "shared_schema.sql"

# Club Market/Battle Config
WIN_VALUE_BONUS = 100000
LOSS_VALUE_PENALTY = -100000
OWNER_MSG_VALUE_BONUS = 10000
OWNER_MSG_COUNT_PER_BONUS = 100

# Level Up Configuration (Wins Required Since Last Level)
# Mapped as: (wins_to_reach_this_level, division_name, market_value_bonus)
LEVEL_UP_CONFIG = [
    (12, "5th Division", 50000),
    (27, "4th Division", 100000), # 12 + 15
    (45, "3rd Division", 150000), # 27 + 18
    (66, "2nd Division", 200000), # 45 + 21
    (90, "1st Division", 300000), # 66 + 24
    (117, "17th Position", 320000), # 90 + 27
    (147, "15th Position", 360000), # 117 + 30
    (180, "12th Position", 400000), # 147 + 33
    (216, "10th Position", 450000), # 180 + 36
    (255, "8th Position", 500000), # 216 + 39
    (297, "6th Position", 550000), # 255 + 42
    (342, "Conference League", 600000), # 297 + 45
    (390, "5th Position", 650000), # 342 + 48
    (441, "Europa League", 700000), # 390 + 51
    (495, "4th Position", 750000), # 441 + 54
    (552, "3rd Position", 800000), # 495 + 57
    (612, "Champions League", 900000), # 552 + 60
    (675, "2nd Position", 950000), # 612 + 63
    (741, "1st Position and League Winner", 1000000), # 675 + 66
    (810, "UCL Winner", 1500000), # 741 + 69
    (882, "Treble Winner", 2000000), # 810 + 72
]

# ---------- DATABASE HELPER ----------
class DB:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        # Full, updated schema incorporating all new tables and columns
        schema = """
BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS investor_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT UNIQUE, 
    funds INTEGER DEFAULT 0,
    owner_id TEXT 
);
CREATE TABLE IF NOT EXISTS groups_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    group_name TEXT, 
    user_id TEXT,
    share_percentage INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS personal_wallets (
    user_id TEXT PRIMARY KEY, 
    balance INTEGER DEFAULT 0,
    messages_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY, 
    bio TEXT, 
    banner TEXT, 
    color TEXT, 
    created_at TEXT,
    owned_club_id INTEGER,
    owned_club_share INTEGER DEFAULT 100
);
CREATE TABLE IF NOT EXISTS club (
    id INTEGER PRIMARY KEY, 
    name TEXT UNIQUE, 
    base_price INTEGER, 
    slogan TEXT, 
    logo TEXT, 
    banner TEXT, 
    value INTEGER, 
    manager_id TEXT,
    owner_id TEXT,
    level_name TEXT DEFAULT 'Unranked',
    total_wins INTEGER DEFAULT 0,
    last_bid_price INTEGER
);
CREATE TABLE IF NOT EXISTS club_market_history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, value INTEGER);
CREATE TABLE IF NOT EXISTS bids (id INTEGER PRIMARY KEY AUTOINCREMENT, bidder TEXT, amount INTEGER, item_type TEXT, item_id TEXT, timestamp TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS club_history (id INTEGER PRIMARY KEY AUTOINCREMENT, winner TEXT, amount INTEGER, timestamp TEXT, market_value_at_sale INTEGER, club_id INTEGER);
CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT, timestamp TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS duelists (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    discord_user_id TEXT, 
    username TEXT, 
    avatar_url TEXT, 
    base_price INTEGER, 
    expected_salary INTEGER, 
    registered_at TEXT, 
    owned_by TEXT,
    club_id INTEGER
);
CREATE TABLE IF NOT EXISTS duelist_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    duelist_id INTEGER, 
    club_owner TEXT, 
    purchase_price INTEGER, 
    salary INTEGER, 
    signed_at TEXT
);
CREATE TABLE IF NOT EXISTS wallet_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, amount INTEGER, type TEXT, timestamp TEXT DEFAULT (datetime('now')));

-- New table for bot configuration
CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- New tables for Battle Register
CREATE TABLE IF NOT EXISTS battle_register (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    club_a_id INTEGER,
    club_b_id INTEGER,
    status TEXT DEFAULT 'REGISTERED', -- REGISTERED, COMPLETED
    registered_by TEXT,
    registered_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS battle_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER,
    winner_club_id INTEGER,
    loser_club_id INTEGER,
    value_change INTEGER,
    level_up_occurred BOOLEAN DEFAULT FALSE,
    recorded_by TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);
COMMIT;
"""
        self.conn.executescript(schema)
        self.conn.commit()

    def query(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def fetchone(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()

    def fetchall(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

# ---------- SETUP ----------
db = DB(DB_FILE)

# ---------- DISCORD BOT ----------
import discord
from discord.ext import commands

# --- Dynamic Prefix Logic ---
DEFAULT_PREFIX = "."

def get_prefix(bot, message):
    """Retrieves the custom prefix from the database."""
    row = db.fetchone("SELECT value FROM bot_config WHERE key='prefix'")
    prefix = row["value"] if row and row["value"] else DEFAULT_PREFIX
    return commands.when_mentioned_or(prefix)(bot, message)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Initialize bot with the dynamic prefix function
bot = commands.Bot(command_prefix=get_prefix, intents=intents)

# in-memory timer tracking
active_timers = {} 
bidding_frozen = False

# ---------- UTIL FUNCTIONS ----------
def log_audit(entry: str):
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (entry,))

def get_current_bid(item_type=None, item_id=None):
    if item_type and item_id is not None:
        row = db.fetchone("SELECT amount FROM bids WHERE item_type=? AND item_id=? ORDER BY id DESC LIMIT 1", (item_type, str(item_id)))
    else:
        row = db.fetchone("SELECT amount FROM bids ORDER BY id DESC LIMIT 1")
    if row:
        return int(row["amount"])
    
    # fallback values
    if item_type == "club" and item_id is not None:
        row2 = db.fetchone("SELECT base_price FROM club WHERE id=?", (item_id,))
        return int(row2["base_price"]) if row2 else 0
    if item_type == "duelist" and item_id is not None:
        row2 = db.fetchone("SELECT base_price FROM duelists WHERE id=?", (item_id,))
        return int(row2["base_price"]) if row2 else 0
    row2 = db.fetchone("SELECT base_price FROM club WHERE id=1")
    return int(row2["base_price"]) if row2 else 0

def min_required_bid(current):
    add = current * MIN_INCREMENT_PERCENT / 100
    return int(current + max(1, round(add)))

def get_club_owner_info(club_id):
    """Returns the owner string and the associated owner user ID(s)"""
    club = db.fetchone("SELECT owner_id FROM club WHERE id=?", (club_id,))
    if not club or not club['owner_id']:
        return None, []
    
    owner_str = club['owner_id']
    if owner_str and owner_str.startswith('group:'):
        gname = owner_str.replace('group:', '').lower()
        members = db.fetchall("SELECT user_id FROM groups_members WHERE group_name=?", (gname,))
        return owner_str, [m['user_id'] for m in members]
    else:
        return owner_str, [owner_str] if owner_str else []

def get_level_info(current_wins, level_name=None):
    """Calculates the current level and wins needed for the next level."""
    current_level = level_name if level_name else LEVEL_UP_CONFIG[0][1]
    
    next_level_info = None
    required_wins = 0
    
    # Find next level
    for wins_required, name, bonus in LEVEL_UP_CONFIG:
        if wins_required > current_wins:
            next_level_info = (name, wins_required, bonus)
            required_wins = wins_required - current_wins
            break
        elif wins_required <= current_wins:
            current_level = name
            
    return current_level, next_level_info, required_wins


def update_club_level(club_id, wins_gained=0):
    club = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    if not club:
        return None
    
    new_total_wins = club['total_wins'] + wins_gained
    db.query("UPDATE club SET total_wins=? WHERE id=?", (new_total_wins, club_id))
    
    level_up_occurred = None
    for wins_required, name, bonus in LEVEL_UP_CONFIG:
        # Check if we crossed this level threshold
        if club['total_wins'] < wins_required <= new_total_wins:
            # Level up occurs!
            db.query("UPDATE club SET level_name=?, value=value+? WHERE id=?", (name, bonus, club_id))
            log_audit(f"Club {club['name']} leveled up to {name}. Bonus: {bonus:,}")
            level_up_occurred = name
    
    # Returns the name of the division if a level up occurred
    return level_up_occurred

# ---------- BACKGROUND: MARKET SIMULATION & WEEKLY REPORT ----------
async def market_simulation_task():
    while True:
        await asyncio.sleep(3600)  # hourly
        # Original market simulation logic (simplified)
        club_rows = db.fetchall("SELECT * FROM club")
        for club in club_rows:
            base = int(club["value"] or club["base_price"])
            # Simple simulation: 
            change = random.uniform(-0.03, 0.03) 
            new_value = int(max(100, base * (1 + change)))
            db.query("UPDATE club SET value=? WHERE id=?", (new_value, club["id"]))
            db.query("INSERT INTO club_market_history (timestamp, value) VALUES (?,?)", (datetime.now().isoformat(), new_value))
            log_audit(f"Market updated for {club['name']} to {new_value:,}")

async def weekly_report_scheduler():
    while True:
        await asyncio.sleep(7 * 24 * 3600)
        report = generate_weekly_report()
        log_audit("Weekly report generated")
        if REPORT_CHANNEL_ID:
            ch = bot.get_channel(REPORT_CHANNEL_ID)
            if ch:
                await ch.send(report)

def generate_weekly_report():
    now = datetime.now()
    weekago = now - timedelta(days=7)
    rows = db.fetchall("SELECT * FROM club_history WHERE timestamp>?", (weekago.isoformat(),))
    total_sales = len(rows)
    total_volume = sum([r["amount"] for r in rows]) if rows else 0
    group_profits = {}
    for r in rows:
        w = r["winner"]
        if "group:" in str(w):
            g = str(w).replace("group:", "")
            group_profits[g] = group_profits.get(g, 0) + r["amount"]
    top = sorted(group_profits.items(), key=lambda x: x[1], reverse=True)[:5]
    report = f"📈 Weekly Report\nTotal Sales: {total_sales}\nVolume: {total_volume:,}\nTop Groups: {top}\nGenerated: {now}"
    return report

# ---------- TIMER / AUCTION FINALIZER ----------
async def finalize_auction(item_type: str, item_id: str, channel_id: int):
    winner = db.fetchone("SELECT bidder, amount FROM bids WHERE item_type=? AND item_id=? ORDER BY id DESC LIMIT 1", (item_type, str(item_id)))
    channel = bot.get_channel(channel_id)
    club = db.fetchone("SELECT * FROM club WHERE id=?", (item_id,))
    
    if winner:
        bidder_str = winner["bidder"]
        amount = int(winner["amount"])
        
        # 8. Deduct the bid value from the winner's wallet
        gname = None
        bidder_user_id = bidder_str
        
        if bidder_str.startswith('group:'):
            gname = bidder_str.replace('group:', '').lower()
            # Deduct from group funds
            g = db.fetchone("SELECT funds FROM investor_groups WHERE name=?", (gname,))
            if g:
                newfunds = max(0, g["funds"] - amount)
                db.query("UPDATE investor_groups SET funds=? WHERE name=?", (newfunds, gname))
                log_audit(f"Deducted {amount:,} from group {gname} after winning auction")
        else: # Personal bid
            db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (amount, bidder_user_id))
            log_audit(f"Deducted {amount:,} from personal wallet {bidder_str} after winning auction")
        
        if item_type == "club":
            # 7. Update club status and history
            db.query("INSERT INTO club_history (club_id, winner, amount, timestamp, market_value_at_sale) VALUES (?,?,?,'now',?)",
                     (club['id'], bidder_str, amount, (club['value'] if club else None)))
            db.query("UPDATE club SET owner_id=?, last_bid_price=? WHERE id=?", (bidder_str, amount, club['id']))
            
            # 11. Update profile/group shares on acquisition
            if club:
                if gname: # Group ownership
                    # Update profiles of group members 
                    members = db.fetchall("SELECT user_id, share_percentage FROM groups_members WHERE group_name=?", (gname,))
                    for m in members:
                        db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, ?)", 
                                 (m['user_id'], club['id'], m['share_percentage']))
                else: # Solo ownership
                    db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, 100)", 
                             (bidder_user_id, club['id']))


            if channel:
                await channel.send(f"🏁 Auction ended for club **{club['name']}**! Winner: **{bidder_str}** for **{amount:,}**.")
            log_audit(f"Auction ended for club {item_id}. Winner: {bidder_str} for {amount:,}")
        
        else: # duelist
            duelist = db.fetchone("SELECT * FROM duelists WHERE id=?", (item_id,))
            if duelist:
                salary = duelist["expected_salary"]
                db.query("INSERT INTO duelist_contracts (duelist_id, club_owner, purchase_price, salary, signed_at) VALUES (?,?,?,?,datetime('now'))",
                          (item_id, bidder_str, amount, salary))
                
                # ASSIGN TO CLUB (If bidder has a club)
                target_club_id = None
                
                # We prioritize group ownership if the bid was 'group:', otherwise personal club.
                if gname: # Group Bid
                    # Find club owned by this group
                    c_owned = db.fetchone("SELECT id FROM club WHERE owner_id=?", (f"group:{gname}",))
                    if c_owned:
                        target_club_id = c_owned['id']
                else: # Personal Bid
                     # Find club owned by this user
                    c_owned = db.fetchone("SELECT id FROM club WHERE owner_id=?", (bidder_user_id,))
                    if c_owned:
                        target_club_id = c_owned['id']
                
                db.query("UPDATE duelists SET owned_by=?, club_id=? WHERE id=?", (bidder_str, target_club_id, item_id))
                
                club_msg = f" Assigned to club ID {target_club_id}." if target_club_id else " (Free Agent - No Club Owned)"
                
                if channel:
                    await channel.send(f"🏁 Duelist auction ended. {duelist['username']} signed to **{bidder_str}** for **{amount:,}**. Salary: {salary:,}.{club_msg}")
                log_audit(f"Duelist {duelist['username']} signed to {bidder_str} for {amount:,}")
    
    else:
        if channel:
            await channel.send("Auction ended with no bids.")

    # cleanup bids for item
    db.query("DELETE FROM bids WHERE item_type=? AND item_id=?", (item_type, str(item_id)))
    # remove active timer entry
    active_timers.pop((item_type, str(item_id)), None)

def schedule_auction_timer(item_type: str, item_id: str, channel_id: int):
    # cancel existing
    key = (item_type, str(item_id))
    task = active_timers.get(key)
    if task and not task.done():
        task.cancel()
    # schedule new timer
    loop = asyncio.get_event_loop()
    t = loop.create_task(asyncio.sleep(TIME_LIMIT))
    async def wrapper():
        try:
            await t
            await finalize_auction(item_type, item_id, channel_id)
        except asyncio.CancelledError:
            return
    task2 = loop.create_task(wrapper())
    active_timers[key] = task2

# ---------- DISCORD COMMANDS ----------
# 5. Add club logo feature in club registeration command
@bot.command()
@commands.has_permissions(administrator=True)
async def registerclub(ctx, name: str, base_price: int, *, slogan: str = ""):
    # Check if an image is attached
    logo_url = None
    if ctx.message.attachments:
        logo_url = ctx.message.attachments[0].url
    
    if db.fetchone("SELECT * FROM club WHERE name LIKE ?", (name,)):
        return await ctx.send("Club already registered.")
        
    db.query("INSERT INTO club (name, base_price, slogan, logo, value, total_wins, level_name) VALUES (?,?,?,?,?,?,?)", 
             (name, base_price, slogan, logo_url, base_price, 0, LEVEL_UP_CONFIG[0][1])) # Default to 5th Division
    db.query("INSERT INTO club_market_history (timestamp, value) VALUES (?,?)", (datetime.now().isoformat(), base_price))
    
    logo_msg = "Logo uploaded." if logo_url else "No logo provided (attach image to set)."
    await ctx.send(f"Club **{name}** registered with base price {base_price:,}. {logo_msg}")
    log_audit(f"{ctx.author} registered club {name} (base {base_price})")

# --- UPDATED LIST CLUBS (Embed) ---
@bot.command()
async def listclubs(ctx):
    rows = db.fetchall("SELECT id, name, base_price, value, level_name, total_wins FROM club ORDER BY value DESC LIMIT 20")
    if not rows:
        return await ctx.send("No clubs registered.")
    
    embed = discord.Embed(title="📋 Registered Clubs (Top 20 by Value)", color=0x3498db)
    for r in rows:
        embed.add_field(
            name=f"{r['name']} (ID: {r['id']})", 
            value=f"💰 Value: {r['value']:,}\n🏆 {r['level_name']} ({r['total_wins']} wins)\n🏷️ Base: {r['base_price']:,}", 
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def startclubauction(ctx, club_name: str):
    # Case-insensitive lookup
    club = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (club_name.lower(),))
    if not club:
        return await ctx.send("No such registered club.")
    db.query("DELETE FROM bids WHERE item_type='club' AND item_id=?", (str(club["id"]),))
    await ctx.send(f"🔔 Auction started for club **{club['name']}**! Starting price: {club['base_price']:,}\nUse `!placebid <amount> club {club['id']}` to bid.")
    log_audit(f"{ctx.author} started auction for club {club['name']}")
    schedule_auction_timer("club", str(club["id"]), ctx.channel.id)

# --- DUELIST AUCTION START ---
@bot.command()
@commands.has_permissions(administrator=True)
async def startduelistauction(ctx, duelist_id: int):
    d = db.fetchone("SELECT * FROM duelists WHERE id=?", (duelist_id,))
    if not d:
        return await ctx.send("No such duelist ID.")
    db.query("DELETE FROM bids WHERE item_type='duelist' AND item_id=?", (str(duelist_id),))
    await ctx.send(f"🔔 Auction started for duelist **{d['username']}** (ID {duelist_id}). Base price: {d['base_price']:,}\nUse `!placebid <amount> duelist {duelist_id} <Club Name>` to bid.")
    log_audit(f"{ctx.author} started duelist auction id={duelist_id}")
    schedule_auction_timer("duelist", str(duelist_id), ctx.channel.id)
# -----------------------------

# 7. Add specific features in club info command
@bot.command()
async def clubinfo(ctx, *, club_name_or_id: str):
    # Note: Added '*' to allow multi-word club names (e.g. "Real Madrid")
    try:
        club_id = int(club_name_or_id)
        row = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    except ValueError:
        # Case-insensitive lookup
        row = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (club_name_or_id.lower(),))
    
    if not row:
        return await ctx.send("No such club.")
    
    club_id = row['id']
    owner_str, owner_ids = get_club_owner_info(club_id)
    
    # 7. Access Control: Only owners (user or group member) or admin can use this command
    is_owner_or_admin = str(ctx.author.id) in owner_ids or ctx.author.guild_permissions.administrator
    if not is_owner_or_admin:
        return await ctx.send("You must be the club owner or an administrator to view detailed club info.")

    current = get_current_bid("club", club_id)
    duelists = db.fetchall("SELECT username FROM duelists WHERE club_id=?", (club_id,))
    
    embed = discord.Embed(title=f"⚽ {row['name']} | {row['level_name']}", description=row["slogan"] or "", color=0x3498db)
    
    # FIX: Check for valid URL schema before setting thumbnail
    if row["logo"] and (row["logo"].startswith("http://") or row["logo"].startswith("https://")):
        embed.set_thumbnail(url=row["logo"])
        
    owner_display = owner_str if owner_str else "Unowned/In Auction"
    if owner_display.startswith('group:'):
        owner_display = f"Group: {owner_display.replace('group:', '').title()}"
    else:
        # Try to resolve user ID to name for display
        try:
            if owner_display != "Unowned/In Auction":
                owner_user = await bot.fetch_user(int(owner_display))
                owner_display = f"User: {owner_user.display_name}"
        except:
            pass

    # 7. Current Status and Value
    embed.add_field(name="Owner", value=owner_display)
    embed.add_field(name="Current Market Value", value=f"{row['value']:,}", inline=True)
    embed.add_field(name="Last Bid Price", value=f"{row['last_bid_price']:,}" if row['last_bid_price'] else "N/A (Base)", inline=True)
    
    manager_name = "None"
    if row["manager_id"]:
        try:
            manager_user = await bot.fetch_user(int(row["manager_id"]))
            manager_name = manager_user.mention
        except:
            manager_name = "Unknown User"
            
    embed.add_field(name="Manager", value=manager_name, inline=True)
    
    current_level, next_level_info, required_wins = get_level_info(row['total_wins'], row['level_name'])
    embed.add_field(name="Wins / Next Level", value=f"{row['total_wins']} wins / {next_level_info[1] if next_level_info else 'MAX'} wins total", inline=True)

    # 7. Registered Duelists with proper listing
    if duelists:
        duelist_list = "\n".join([f"• {d['username']}" for d in duelists])
    else:
        duelist_list = "No duelists contracted."
        
    embed.add_field(name="📝 Contracted Duelists", value=duelist_list, inline=False)
    
    await ctx.send(embed=embed)

# --- UPDATED: Market Panel Command (Dashboard View) ---
@bot.command()
async def marketpanel(ctx, *, club_name_or_id: str):
    # Note: Added '*' for multi-word names support
    try:
        club_id = int(club_name_or_id)
        row = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    except ValueError:
        # Case-insensitive lookup
        row = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (club_name_or_id.lower(),))
        
    if not row:
        return await ctx.send("No such club.")

    current_level, next_level_info, required_wins = get_level_info(row['total_wins'], row['level_name'])
    
    embed = discord.Embed(
        title=f"📈 Market & Level Panel: {row['name']}", 
        description=f"**Division:** {current_level}", 
        color=0xf1c40f
    )
    
    # FIX: Check for valid URL schema before setting thumbnail
    if row["logo"] and (row["logo"].startswith("http://") or row["logo"].startswith("https://")):
        embed.set_thumbnail(url=row["logo"])

    # Market Value and Battle Stats
    embed.add_field(name="Market Value", value=f"**${row['value']:,}**", inline=True)
    embed.add_field(name="Total Wins", value=f"**{row['total_wins']}**", inline=True)
    embed.add_field(name="Performance", value=f"Win: +${WIN_VALUE_BONUS:,}\nLoss: -${abs(LOSS_VALUE_PENALTY):,}", inline=False)
    
    # Level Up Progression
    if next_level_info:
        embed.add_field(name="Next Division", value=f"**{next_level_info[0]}**", inline=True)
        embed.add_field(name="Wins Needed", value=f"**{required_wins}** more", inline=True)
        embed.add_field(name="Level Up Bonus", value=f"**${next_level_info[2]:,}**", inline=True)
    else:
        embed.add_field(name="Status", value="**🏆 MAX DIVISION REACHED**", inline=False)
        
    embed.set_footer(text="Market value fluctuates hourly and updates with battle results.")
    
    await ctx.send(embed=embed)


# --- NEW: Group Info Command ---
@bot.command()
async def groupinfo(ctx, *, group_name: str):
    """
    Shows detailed information about an investor group.
    """
    group_name = group_name.lower()
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name,))
    if not g:
        return await ctx.send("No such group.")
    
    # Members
    members = db.fetchall("SELECT user_id, share_percentage FROM groups_members WHERE group_name=?", (group_name,))
    
    # Owned Clubs
    clubs = db.fetchall("SELECT name FROM club WHERE owner_id=?", (f"group:{group_name}",))
    
    embed = discord.Embed(title=f"👥 Group: {g['name'].title()}", color=0x9b59b6)
    
    # Owner/Founder logic
    try:
        founder = await bot.fetch_user(int(g['owner_id']))
        founder_name = founder.mention
    except:
        founder_name = "Unknown"
        
    embed.add_field(name="Founder", value=founder_name, inline=True)
    embed.add_field(name="Bank Balance", value=f"${g['funds']:,}", inline=True)
    
    # Member List
    member_list = []
    total_shares = 0
    for m in members:
        try:
            u = await bot.fetch_user(int(m['user_id']))
            name = u.display_name
        except:
            name = m['user_id']
        member_list.append(f"• {name}: {m['share_percentage']}%")
        total_shares += m['share_percentage']
        
    embed.add_field(name=f"Members ({len(members)})", value="\n".join(member_list) if member_list else "None", inline=False)
    embed.add_field(name="Total Shares Allocated", value=f"{total_shares}%", inline=True)
    
    # Clubs
    club_list = [c['name'] for c in clubs]
    embed.add_field(name="Owned Clubs", value=", ".join(club_list) if club_list else "None", inline=False)
    
    await ctx.send(embed=embed)


# 2. Add Battle Register and Result features
@bot.command()
@commands.has_permissions(administrator=True)
async def registerbattle(ctx, club_a_name: str, club_b_name: str):
    # Case insensitive
    club_a = db.fetchone("SELECT id FROM club WHERE lower(name)=?", (club_a_name.lower(),))
    club_b = db.fetchone("SELECT id FROM club WHERE lower(name)=?", (club_b_name.lower(),))
    
    if not club_a or not club_b:
        return await ctx.send("One or both clubs not found.")
    
    db.query("INSERT INTO battle_register (club_a_id, club_b_id, registered_by) VALUES (?,?,?)",
             (club_a['id'], club_b['id'], str(ctx.author.id)))
    battle_id = db.fetchone("SELECT id FROM battle_register ORDER BY id DESC LIMIT 1")['id']
    await ctx.send(f"⚔️ Battle registered: **{club_a_name}** vs **{club_b_name}**. Battle ID: **{battle_id}**")

@bot.command()
@commands.has_permissions(administrator=True)
async def battleresult(ctx, battle_id: int, winner_club_name: str):
    battle = db.fetchone("SELECT * FROM battle_register WHERE id=? AND status='REGISTERED'", (battle_id,))
    if not battle:
        return await ctx.send("Battle not found or already completed.")
    
    winner_club = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (winner_club_name.lower(),))
    if not winner_club:
        return await ctx.send("Winner club not found.")
    
    loser_club_id = battle['club_a_id'] if battle['club_b_id'] == winner_club['id'] else battle['club_b_id']
    loser_club = db.fetchone("SELECT name FROM club WHERE id=?", (loser_club_id,))

    # 1. Live Market Value Update
    db.query("UPDATE club SET value=value+? WHERE id=?", (WIN_VALUE_BONUS, winner_club['id']))
    db.query("UPDATE club SET value=value+? WHERE id=?", (LOSS_VALUE_PENALTY, loser_club_id))
    
    # 3. Level Up Check
    level_up_occurred = update_club_level(winner_club['id'], wins_gained=1)
    
    # 2. Record Result
    db.query("UPDATE battle_register SET status='COMPLETED' WHERE id=?", (battle_id,))
    db.query("INSERT INTO battle_results (battle_id, winner_club_id, loser_club_id, value_change, level_up_occurred, recorded_by) VALUES (?,?,?,?,?,?)",
             (battle_id, winner_club['id'], loser_club_id, WIN_VALUE_BONUS, bool(level_up_occurred), str(ctx.author.id)))
             
    msg = f"🏆 Battle ID {battle_id} completed. Winner: **{winner_club['name']}** (+{WIN_VALUE_BONUS:,}), Loser: **{loser_club['name']}** ({LOSS_VALUE_PENALTY:,})."
    if level_up_occurred:
        msg += f"\n🎉 **{winner_club['name']}** has achieved the **{level_up_occurred}** level!"
    
    await ctx.send(msg)

# 3. Command to check level up
@bot.command()
async def clublevel(ctx, *, club_name_or_id: str):
    # Note: Added '*' for multi-word names
    try:
        club_id = int(club_name_or_id)
        row = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    except ValueError:
        row = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (club_name_or_id.lower(),))
        
    if not row:
        return await ctx.send("No such club.")

    current_level, next_level_info, required_wins = get_level_info(row['total_wins'], row['level_name'])
        
    msg = f"**{row['name']}** Current Level: **{current_level}**\nTotal Wins: **{row['total_wins']}**\n"
    
    if next_level_info:
        msg += f"Next Level: **{next_level_info[0]}** (Value Bonus: {next_level_info[2]:,})\n"
        msg += f"Wins Needed: **{required_wins}** more battles."
    else:
        msg += "Club has reached the highest division!"
        
    await ctx.send(msg)
    
# --- UPDATED LEADERBOARD (Embed) ---
@bot.command()
async def leaderboard(ctx):
    # Sort by total_wins (proxy for level) then market value
    rows = db.fetchall("SELECT name, level_name, total_wins, value FROM club ORDER BY total_wins DESC, value DESC LIMIT 15")
    
    if not rows:
        return await ctx.send("No clubs registered for the leaderboard.")
    
    embed = discord.Embed(title="🏆 Club Leaderboard", color=0xf1c40f)
    description = ""
    for i, r in enumerate(rows):
        description += f"**{i+1}. {r['name']}**\n└ Div: {r['level_name']} | Wins: {r['total_wins']} | Val: {r['value']:,}\n\n"
    
    embed.description = description
    await ctx.send(embed=embed)

# Admin command to check owner messages (for Point 1: Live Market)
@bot.command()
@commands.has_permissions(administrator=True)
async def checkclubmessages(ctx, club_name: str, message_count: int):
    club = db.fetchone("SELECT * FROM club WHERE lower(name)=?", (club_name.lower(),))
    if not club:
        return await ctx.send("No such club.")
        
    # Owner message logic: simplified to check total messages from all owners/group members
    bonus_units = message_count // OWNER_MSG_COUNT_PER_BONUS
    value_increase = bonus_units * OWNER_MSG_VALUE_BONUS
    
    if value_increase > 0:
        db.query("UPDATE club SET value=value+? WHERE id=?", (value_increase, club['id']))
        await ctx.send(f"Club **{club['name']}** market value increased by **{value_increase:,}** for {message_count} owner messages.")
        log_audit(f"Club {club['name']} value increased by {value_increase} due to {message_count} owner messages.")
    else:
        await ctx.send("Not enough messages to trigger a market value increase.")

# 6. Admin Tip and Deduct
@bot.command()
@commands.has_permissions(administrator=True)
async def tip(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("Amount must be positive.")
    uid = str(member.id)
    db.query("INSERT OR IGNORE INTO personal_wallets (user_id, balance) VALUES (?, 0)", (uid,))
    db.query("UPDATE personal_wallets SET balance=balance+? WHERE user_id=?", (amount, uid))
    db.query("INSERT INTO wallet_transactions (user_id, amount, type) VALUES (?,?,?)", (uid, amount, "admin_tip"))
    await ctx.send(f"💰 Admin tipped {member.mention} **{amount:,}**. New balance: {db.fetchone('SELECT balance FROM personal_wallets WHERE user_id=?', (uid,))['balance']:,}")
    log_audit(f"{ctx.author} tipped {member} {amount}")

@bot.command()
@commands.has_permissions(administrator=True)
async def deduct_user(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("Amount must be positive.")
    uid = str(member.id)
    bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (uid,))
    if not bal or bal['balance'] < amount:
        return await ctx.send("User does not have enough funds to deduct that amount.")
    db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (amount, uid))
    db.query("INSERT INTO wallet_transactions (user_id, amount, type) VALUES (?,?,?)", (uid, -amount, "admin_deduct"))
    await ctx.send(f"💸 Admin deducted **{amount:,}** from {member.mention}. New balance: {db.fetchone('SELECT balance FROM personal_wallets WHERE user_id=?', (uid,))['balance']:,}")
    log_audit(f"{ctx.author} deducted {member} {amount}")

# --- RESTORED: Personal Wallet Check ---
@bot.command()
async def wallet(ctx):
    """
    Shows the user's personal wallet balance.
    """
    uid = str(ctx.author.id)
    row = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (uid,))
    bal = int(row["balance"]) if row else 0
    
    embed = discord.Embed(title=f"💰 {ctx.author.display_name}'s Wallet", color=0x2ecc71)
    embed.add_field(name="Current Balance", value=f"**${bal:,}**", inline=False)
    
    if ctx.author.avatar:
        embed.set_thumbnail(url=ctx.author.avatar.url)
        
    await ctx.send(embed=embed)

# --- RESTORED (RESTRICTED): Personal Wallet Deposit ---
@bot.command()
async def depositwallet(ctx, amount: int = None):
    """
    This command is disabled to restrict deposits to group funds only, as per system policy.
    """
    await ctx.send("🚫 **Policy Restriction:** Direct deposits to personal wallets are disabled. Please use `!deposit <Group Name> <Amount>` to fund a group wallet for bidding.")

# Override the original deposit to only allow group deposit (as per point 6)
@bot.command()
async def deposit(ctx, group_name: str, amount: int):
    if amount <= 0:
        return await ctx.send("Amount must be positive.")

    # 1. Check Group Exists
    group_name = group_name.lower()
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name,))
    if not g:
        return await ctx.send("No such group.")

    # 2. Check Membership (User must be in the group)
    mem = db.fetchone("SELECT * FROM groups_members WHERE group_name=? AND user_id=?", (group_name, str(ctx.author.id)))
    if not mem:
        return await ctx.send("🚫 You are not a member of this group. You cannot deposit funds.")

    # 3. Check User Balance
    uid = str(ctx.author.id)
    user_wallet = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (uid,))
    current_balance = int(user_wallet["balance"]) if user_wallet else 0

    if current_balance < amount:
        return await ctx.send(f"🚫 Insufficient funds in your personal wallet. Balance: {current_balance:,}, Required: {amount:,}")

    # 4. Perform Transfer
    # Deduct from user
    db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (amount, uid))
    # Add to group
    db.query("UPDATE investor_groups SET funds=funds+? WHERE name=?", (amount, group_name))
    
    # Log
    db.query("INSERT INTO wallet_transactions (user_id, amount, type) VALUES (?,?,?)", (uid, -amount, f"deposit_to_{group_name}"))
    log_audit(f"{ctx.author} deposited {amount:,} to group {group_name}")
    
    await ctx.send(f"✅ Successfully deposited **{amount:,}** from your wallet to **{group_name}**. Group Funds: {g['funds'] + amount:,}")

# Original withdraw (still valid)
@bot.command()
async def withdraw(ctx, group_name: str, amount: int):
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name.lower(),))
    if not g:
        return await ctx.send("No such group.")
    if amount > g["funds"]:
        return await ctx.send("Not enough group funds.")
    new = g["funds"] - amount
    db.query("UPDATE investor_groups SET funds=? WHERE name=?", (new, group_name.lower()))
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} withdrew {amount:,} from {group_name}",))
    await ctx.send(f"Withdrew **{amount:,}** from **{group_name}**. New funds: {new:,}")

# 8. Wallet Limits in Bidding
@bot.command()
async def placebid(ctx, amount: int, item_type: str, item_id: int, club_name: str = None):
    """
    Bid on an item.
    Usage: !placebid <amount> <club/duelist> <id> [Club Name (if duelist)]
    """
    if bidding_frozen:
        return await ctx.send("Bidding is currently frozen by an admin.")
    if item_type not in ("club", "duelist"):
        return await ctx.send("item_type must be 'club' or 'duelist'.")
    if item_id is None:
        return await ctx.send("Provide the item_id (club id or duelist id).")

    # 8. Check personal wallet balance
    uid = str(ctx.author.id)
    bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (uid,))
    if not bal or bal['balance'] < amount:
        return await ctx.send(f"Insufficient funds. Your wallet balance is {bal['balance'] if bal else 0:,}, but the bid is {amount:,}.")

    # check min
    current = get_current_bid(item_type, str(item_id))
    min_req = min_required_bid(current)
    if amount < min_req:
        return await ctx.send(f"Minimum required bid is {min_req:,} (current {current:,}, +{MIN_INCREMENT_PERCENT}%).")
    
    # NEW: Require Club Name for Duelist Bids
    if item_type == 'duelist':
        if not club_name:
            return await ctx.send("⚠️ You must specify the **Club Name** you are recruiting for!\nUsage: `!placebid <amount> duelist <id> <Club Name>`")
        
        # Verify ownership of that club via LIKE
        c = db.fetchone("SELECT * FROM club WHERE name LIKE ?", (club_name,))
        if not c:
             return await ctx.send(f"Club **{club_name}** not found.")
        
        if str(ctx.author.id) != c['owner_id']:
             return await ctx.send(f"🚫 You do not own **{c['name']}**. You cannot bid for a club you don't own.")
        
    db.query("INSERT INTO bids (bidder, amount, item_type, item_id) VALUES (?, ?, ?, ?)", (uid, amount, item_type, str(item_id)))
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} bid {amount:,} on {item_type} {item_id}",))
    await ctx.send(f"✅ New bid of **{amount:,}** on {item_type} {item_id} by {ctx.author.mention}")
    schedule_auction_timer(item_type, str(item_id), ctx.channel.id)

@bot.command()
async def groupbid(ctx, group_name: str, amount: int, item_type: str, item_id: int, club_name: str = None):
    """
    Group Bid on an item.
    Usage: !groupbid <Group> <amount> <club/duelist> <id> [Club Name (if duelist)]
    """
    if bidding_frozen:
        return await ctx.send("Bidding is currently frozen.")
    if item_type not in ("club", "duelist"):
        return await ctx.send("item_type must be 'club' or 'duelist'.")
    if item_id is None:
        return await ctx.send("Provide the item_id.")
    
    # NEW: Require Club Name for Duelist Bids
    if item_type == 'duelist':
        if not club_name:
            return await ctx.send("⚠️ You must specify the **Club Name** your group is recruiting for!\nUsage: `!groupbid <Group> <amount> duelist <id> <Club Name>`")
        
        # Verify group ownership of that club via LIKE
        c = db.fetchone("SELECT * FROM club WHERE name LIKE ?", (club_name,))
        if not c:
             return await ctx.send(f"Club **{club_name}** not found.")
        
        if c['owner_id'] != f"group:{group_name.lower()}":
             return await ctx.send(f"🚫 Group **{group_name}** does not own **{c['name']}**.")

    
    group_name = group_name.lower()
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name,))
    if not g:
        return await ctx.send("No such group.")
    mem = db.fetchone("SELECT * FROM groups_members WHERE group_name=? AND user_id=?", (group_name, str(ctx.author.id)))
    if not mem:
        return await ctx.send("You are not in that group.")
        
    # 8. Check group wallet balance
    if amount > g["funds"]:
        return await ctx.send(f"Group lacks funds (available {g['funds']:,}). Bid of {amount:,} is too high.")
        
    current = get_current_bid(item_type, str(item_id))
    min_req = min_required_bid(current)
    if amount < min_req:
        return await ctx.send(f"Minimum required bid is {min_req:,}.")
        
    db.query("INSERT INTO bids (bidder, amount, item_type, item_id) VALUES (?, ?, ?, ?)", (f"group:{group_name}", amount, item_type, str(item_id)))
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"Group {group_name} bid {amount:,} on {item_type} {item_id}",))
    await ctx.send(f"✅ Group **{group_name}** placed a bid of **{amount:,}** on {item_type} {item_id}.")
    
    # DM notify group members
    members = db.fetchall("SELECT user_id FROM groups_members WHERE group_name=?", (group_name,))
    for m in members:
        try:
            user = await bot.fetch_user(int(m["user_id"]))
            await user.send(f"📢 Your group **{group_name}** placed a bid of **{amount:,}** on {item_type} {item_id}.")
        except:
            pass
    schedule_auction_timer(item_type, str(item_id), ctx.channel.id)

# --- NEW: Set Club Manager Command (Admin) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setclubmanager(ctx, club_name: str, member: discord.Member):
    """
    Admin command: Assigns a manager to a club.
    """
    club = db.fetchone("SELECT * FROM club WHERE name LIKE ?", (club_name,))
    if not club:
        return await ctx.send("No such club.")
    
    db.query("UPDATE club SET manager_id=? WHERE name=?", (str(member.id), club['name']))
    log_audit(f"{ctx.author} set {member} as manager for {club['name']}")
    await ctx.send(f"✅ **{member.display_name}** has been successfully appointed as the manager for **{club['name']}**.")

# 8. Owner salary/bonus adjustment (Owner Only)
@bot.command()
async def adjustsalary(ctx, duelist_id: int, amount: int):
    # Only club owners or group members can run this (admins override via tip/deduct_user)
    
    contract = db.fetchone("SELECT * FROM duelist_contracts WHERE duelist_id=? ORDER BY id DESC LIMIT 1", (duelist_id,))
    if not contract:
        return await ctx.send("Duelist not contracted.")
        
    club_id_row = db.fetchone("SELECT club_id FROM duelists WHERE id=?", (duelist_id,))
    if not club_id_row or not club_id_row['club_id']:
        return await ctx.send("Duelist is a free agent and not assigned to a club.")
        
    club_id = club_id_row['club_id']
    
    owner_str, owner_ids = get_club_owner_info(club_id)
    if str(ctx.author.id) not in owner_ids:
        return await ctx.send("You must be an owner/group member of the duelist's club to adjust salary/bonus.")

    duelist_uid = db.fetchone("SELECT discord_user_id FROM duelists WHERE id=?", (duelist_id,))['discord_user_id']
    
    if amount > 0:
        # Bonus: must deduct from owner's personal wallet first
        owner_bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (str(ctx.author.id),))
        if not owner_bal or owner_bal['balance'] < amount:
            return await ctx.send(f"You require **{amount:,}** in your personal wallet to give this bonus.")
        
        # Deduct from owner
        db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (amount, str(ctx.author.id)))
        # Add to duelist
        db.query("INSERT OR IGNORE INTO personal_wallets (user_id, balance) VALUES (?, 0)", (duelist_uid,))
        db.query("UPDATE personal_wallets SET balance=balance+? WHERE user_id=?", (amount, duelist_uid))
        log_audit(f"Owner {ctx.author} paid bonus {amount:,} to duelist {duelist_id}")
        await ctx.send(f"💵 Paid **{amount:,}** bonus to duelist {duelist_id}.")
        
    else: # Deduction
        abs_amount = abs(amount)
        duelist_bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (duelist_uid,))
        if not duelist_bal or duelist_bal['balance'] < abs_amount:
            return await ctx.send(f"Duelist does not have **{abs_amount:,}** in their wallet for this deduction.")
            
        # Deduct from duelist
        db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (abs_amount, duelist_uid))
        log_audit(f"Owner {ctx.author} deducted salary {abs_amount:,} from duelist {duelist_id}")
        await ctx.send(f"🔪 Deducted **{abs_amount:,}** from duelist {duelist_id}'s wallet.")

# 15. Apply salary deduction when a duelist misses a match (original command, still valid)
@bot.command()
async def deductsalary(ctx, duelist_id: int, apply: str = "yes"):
    d = db.fetchone("SELECT * FROM duelists WHERE id=?", (duelist_id,))
    if not d:
        return await ctx.send("No such duelist.")
    contract = db.fetchone("SELECT * FROM duelist_contracts WHERE duelist_id=? ORDER BY id DESC LIMIT 1", (duelist_id,))
    if not contract:
        return await ctx.send("Duelist not contracted.")
    club_owner = contract["club_owner"]
    club_id_row = db.fetchone("SELECT club_id FROM duelists WHERE id=?", (duelist_id,))
    
    if not club_id_row or not club_id_row['club_id']:
        return await ctx.send("Duelist is a free agent; no club funds to deduct from.")
        
    club_id = club_id_row['club_id']
    invoker_id = str(ctx.author.id)
    allowed = False
    
    _, owner_ids = get_club_owner_info(club_id)
    if invoker_id in owner_ids or ctx.author.guild_permissions.administrator:
        allowed = True

    if not allowed:
        return await ctx.send("You are not authorized to apply salary deduction for this duelist.")
    
    if apply.lower() not in ("yes", "no", "y", "n"):
        return await ctx.send("apply must be 'yes' or 'no'")
    if apply.lower() in ("no", "n"):
        return await ctx.send("Salary deduction skipped by club decision.")
        
    # apply deduction
    penalty = contract["salary"] * DUELIST_MISS_PENALTY_PERCENT // 100
    
    # deduct from group funds if group owned
    if club_owner.startswith('group:'):
        gname = club_owner.replace("group:", "").lower()
        g = db.fetchone("SELECT funds FROM investor_groups WHERE name=?", (gname,))
        if g:
            new = max(0, g["funds"] - penalty)
            db.query("UPDATE investor_groups SET funds=? WHERE name=?", (new, gname))
            
    log_audit(f"{ctx.author} applied salary deduction {penalty:,} for duelist {d['username']} (id {duelist_id})")
    await ctx.send(f"Salary deduction applied: {penalty:,} (15%) for duelist {d['username']}. Funds deducted from club owner.")

# --- NEW: Set Prefix Command ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setprefix(ctx, new_prefix: str):
    """
    Admin command to dynamically change the bot's command prefix.
    """
    if not new_prefix or len(new_prefix) > 5:
        return await ctx.send("Invalid prefix. Must be 1-5 characters long.")
    
    # Store or replace the new prefix in the config table
    db.query("INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)", ('prefix', new_prefix))
    
    # Inform the user, using the new prefix logic to check the new prefix
    await ctx.send(f"✅ Bot prefix updated to **`{new_prefix}`**. All commands must now start with this prefix.")
    log_audit(f"{ctx.author} changed bot prefix to {new_prefix}")


# 9. Admin reset all
@bot.command()
@commands.has_permissions(administrator=True)
async def admin_reset_all(ctx):
    if not BOT_OWNER_ID or str(ctx.author.id) != str(BOT_OWNER_ID):
        return await ctx.send("This command is restricted to the bot owner.")

    await ctx.send("⚠️ **WARNING:** This will reset ALL club history, wins, levels, and market values. Type `CONFIRM RESET` to proceed.")
    
    def check(m):
        return m.author == ctx.author and m.content == 'CONFIRM RESET'

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("Reset timed out.")
    
    # Perform Reset Operations
    db.query("UPDATE club SET total_wins=0, level_name=?, value=base_price, owner_id=NULL, last_bid_price=NULL", (LEVEL_UP_CONFIG[0][1],))
    db.query("DELETE FROM battle_register")
    db.query("DELETE FROM battle_results")
    db.query("DELETE FROM club_history")
    
    log_audit(f"OWNER **{ctx.author}** executed full club history reset.")
    await ctx.send("✅ **All club history, levels, and battle data have been reset!**")

# --- DUELIST REGISTRATION ---
@bot.command()
async def registerduelist(ctx, username: str, base_price: int, expected_salary: int):
    """
    Duelist registers themselves (or admins can do this)
    !registerduelist <username> <base_price> <expected_salary>
    """
    if db.fetchone("SELECT * FROM duelists WHERE discord_user_id=?", (str(ctx.author.id),)):
        return await ctx.send("You are already registered as a duelist.")
    
    avatar = ctx.author.avatar.url if ctx.author.avatar else ""
    db.query("INSERT INTO duelists (discord_user_id, username, avatar_url, base_price, expected_salary, registered_at) VALUES (?,?,?,?,?,?)",
             (str(ctx.author.id), username, avatar, base_price, expected_salary, datetime.now().isoformat()))
    d = db.fetchone("SELECT id FROM duelists WHERE discord_user_id=? ORDER BY id DESC", (str(ctx.author.id),))
    await ctx.send(f"Duelist **{username}** registered with ID **{d['id']}** (base {base_price:,}, salary {expected_salary:,}).")
    log_audit(f"{ctx.author} registered duelist {username} id={d['id']}")
# ----------------------------------------


# --- UPDATED LIST DUELISTS (Embed) ---
@bot.command()
async def listduelists(ctx):
    rows = db.fetchall("SELECT id, username, base_price, expected_salary, owned_by, club_id FROM duelists LIMIT 25")
    if not rows:
        return await ctx.send("No duelists registered.")
    
    embed = discord.Embed(title="📜 Registered Duelists (Top 25)", color=0x9b59b6)
    for r in rows:
        club_name = "Free Agent"
        if r['club_id']:
            club = db.fetchone("SELECT name FROM club WHERE id=?", (r['club_id'],))
            if club:
                club_name = club['name']
        
        embed.add_field(
            name=f"{r['username']} (ID: {r['id']})", 
            value=f"⚽ Club: {club_name}\n💰 Salary: {r['expected_salary']:,}\n🏷️ Base: {r['base_price']:,}",
            inline=False
        )
    await ctx.send(embed=embed)


# owner/admin overrides
@bot.command()
@commands.is_owner()
async def forcewinner(ctx, item_type: str, item_id: int, winner_str: str, amount: int):
    if item_type not in ("club", "duelist"):
        return await ctx.send("item_type must be club or duelist.")
    if item_type == "club":
        db.query("INSERT INTO club_history (winner, amount, timestamp, market_value_at_sale) VALUES (?,?,datetime('now'),?)",
                 (winner_str, amount, (db.fetchone("SELECT value FROM club WHERE id=1")["value"] if db.fetchone("SELECT value FROM club WHERE id=1") else None)))
        log_audit(f"Owner forced winner {winner_str} for club {item_id} at {amount:,}")
        await ctx.send(f"Owner forced {winner_str} as winner for club {item_id} at {amount:,}")
    else:
        salary = db.fetchone("SELECT expected_salary FROM duelists WHERE id=?", (item_id,))
        salary_val = salary["expected_salary"] if salary else 0
        db.query("INSERT INTO duelist_contracts (duelist_id, club_owner, purchase_price, salary, signed_at) VALUES (?,?,?,?,datetime('now'))",
                 (item_id, winner_str, amount, salary_val))
        db.query("UPDATE duelists SET owned_by=? WHERE id=?", (winner_str, item_id))
        log_audit(f"Owner forced winner {winner_str} for duelist {item_id} at {amount:,}")
        await ctx.send(f"Owner forced {winner_str} as winner for duelist {item_id} at {amount:,}")

@bot.command()
@commands.is_owner()
async def freezeauction(ctx):
    global bidding_frozen
    bidding_frozen = True
    log_audit(f"{ctx.author} froze auctions")
    await ctx.send("All auctions frozen (owner).")

@bot.command()
@commands.is_owner()
async def unfreezeauction(ctx):
    global bidding_frozen
    bidding_frozen = False
    log_audit(f"{ctx.author} unfroze auctions")
    await ctx.send("Auctions unfrozen (owner).")

@bot.command()
@commands.is_owner()
async def auditlog(ctx, lines: int = 50):
    rows = db.fetchall("SELECT entry, timestamp FROM audit_logs ORDER BY id DESC LIMIT ?", (lines,))
    if not rows:
        return await ctx.send("No audit logs.")
    text = "\n".join([f"[{r['timestamp']}] {r['entry']}" for r in rows])
    for chunk in [text[i:i+1900] for i in range(0, len(text), 1900)]:
        await ctx.send(f"```{chunk}```")

@bot.command()
@commands.is_owner()
async def resetauction(ctx):
    db.query("DELETE FROM bids")
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} reset auctions",))
    await ctx.send("All bids cleared and auctions reset.")

@bot.command()
@commands.is_owner()
async def transferclub(ctx, old_group: str, new_group: str):
    # sets latest club_history winner to new_group (quick admin override)
    latest = db.fetchone("SELECT id FROM club_history ORDER BY id DESC LIMIT 1")
    if not latest:
        return await ctx.send("No sale to transfer.")
    db.query("UPDATE club_history SET winner=? WHERE id=?", (new_group + " (group)", latest["id"]))
    log_audit(f"{ctx.author} transferred last sale from {old_group} to {new_group}")
    await ctx.send(f"Transferred club ownership from {old_group} to {new_group} (admin override).")

# admin adjust club/group balance (original command, still valid)
@bot.command()
@commands.has_permissions(administrator=True)
async def adjustgroupfunds(ctx, group_name: str, amount: int):
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name.lower(),))
    if not g:
        return await ctx.send("No such group.")
    new = max(0, g["funds"] + amount)
    db.query("UPDATE investor_groups SET funds=? WHERE name=?", (new, group_name.lower()))
    log_audit(f"{ctx.author} adjusted funds of {group_name} by {amount:,}. New funds {new:,}")
    await ctx.send(f"Adjusted funds of {group_name} by {amount:,}. New funds: {new:,}")


# 10. Delete Club & Retire Duelist
@bot.command()
@commands.has_permissions(administrator=True)
async def deleteclub(ctx, club_name: str):
    club = db.fetchone("SELECT id FROM club WHERE name=?", (club_name,))
    if not club:
        return await ctx.send("No such club.")

    # Delete club and related data
    db.query("DELETE FROM club WHERE id=?", (club['id'],))
    db.query("DELETE FROM club_history WHERE club_id=?", (club['id'],))
    db.query("UPDATE duelists SET owned_by=NULL, club_id=NULL WHERE club_id=?", (club['id'],))
    db.query("UPDATE user_profiles SET owned_club_id=NULL, owned_club_share=NULL WHERE owned_club_id=?", (club['id'],))

    log_audit(f"Admin {ctx.author} deleted club {club_name}.")
    await ctx.send(f"Club **{club_name}** has been deleted.")

@bot.command()
async def retireduelist(ctx, member: discord.Member = None):
    """
    Retire duelist flow.
    - If member provided: Owner initiates 2-step confirmation.
    - If no member: Self-retire (Free Agents only).
    """
    # Scenario 1: Self-Retire (No argument provided)
    if member is None:
        duelist = db.fetchone("SELECT * FROM duelists WHERE discord_user_id=?", (str(ctx.author.id),))
        if not duelist:
            return await ctx.send("You are not registered as a duelist.")
        
        if duelist['owned_by']:
            return await ctx.send("You cannot retire while signed to a club. Ask your club owner to initiate retirement.")
            
        db.query("DELETE FROM duelists WHERE discord_user_id=?", (str(ctx.author.id),))
        db.query("DELETE FROM duelist_contracts WHERE duelist_id=?", (duelist['id'],))
        log_audit(f"Duelist {duelist['username']} retired (Self).")
        return await ctx.send(f"Duelist **{duelist['username']}** has successfully retired.")

    # Scenario 2: Owner Initiates
    duelist = db.fetchone("SELECT * FROM duelists WHERE discord_user_id=?", (str(member.id),))
    if not duelist:
        return await ctx.send(f"{member.mention} is not registered as a duelist.")
        
    if not duelist['club_id']:
         return await ctx.send("This duelist is a Free Agent. They must retire themselves.")

    club_id = duelist['club_id']
    owner_str, owner_ids = get_club_owner_info(club_id)
    
    if str(ctx.author.id) not in owner_ids:
        return await ctx.send("You do not own the club this duelist is signed to.")

    # Step 1: Owner Confirmation
    await ctx.send(f"⚠️ **RETIREMENT CONFIRMATION (Step 1/2)**\n{ctx.author.mention}, are you sure you want to retire **{duelist['username']}**? Type `yes` or `no`.")

    def check_owner(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        msg = await bot.wait_for('message', check=check_owner, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("Owner confirmation timed out.")

    if msg.content.lower() == 'no':
        return await ctx.send("Retirement cancelled by owner.")

    # Step 2: Duelist Confirmation
    await ctx.send(f"⚠️ **RETIREMENT CONFIRMATION (Step 2/2)**\n{member.mention}, your owner wants to retire you. Do you agree? Type `yes` or `no`.")

    def check_duelist(m):
        return m.author == member and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        msg = await bot.wait_for('message', check=check_duelist, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("Duelist confirmation timed out.")

    if msg.content.lower() == 'no':
        return await ctx.send("Retirement rejected by duelist.")

    # Execute Retirement
    db.query("DELETE FROM duelists WHERE id=?", (duelist['id'],))
    db.query("DELETE FROM duelist_contracts WHERE duelist_id=?", (duelist['id'],))
    
    log_audit(f"Duelist {duelist['username']} retired by owner {ctx.author}.")
    await ctx.send(f"✅ **{duelist['username']}** has officially retired from the league.")
    
# 11. Profile command dashboard (updated with club info)
@bot.command()
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    uid = str(member.id)
    prof = db.fetchone("SELECT * FROM user_profiles WHERE user_id=?", (uid,))
    bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (uid,))
    groups = db.fetchall("SELECT group_name, share_percentage FROM groups_members WHERE user_id=?", (uid,))
    bids = db.fetchall("SELECT * FROM bids WHERE bidder=? ORDER BY id DESC LIMIT 5", (uid,))
    
    embed = discord.Embed(title=f"Profile: {member}", color=0x00ff99)
    try:
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
    except:
        pass
        
    embed.add_field(name="Wallet", value=f"{bal['balance']:,}" if bal else "0", inline=False)
    
    # NEW: Duelist Info
    duelist = db.fetchone("SELECT * FROM duelists WHERE discord_user_id=?", (uid,))
    if duelist:
        club_name = "Free Agent"
        if duelist['club_id']:
             club_row = db.fetchone("SELECT name FROM club WHERE id=?", (duelist['club_id'],))
             if club_row: club_name = club_row['name']
        
        embed.add_field(name="Duelist Status", value=f"Signed to: **{club_name}**\nSalary: {duelist['expected_salary']:,}", inline=True)


    # Owned Club Section
    owned_club_name = "None"
    share_text = ""
    if prof and prof['owned_club_id']:
        club = db.fetchone("SELECT name FROM club WHERE id=?", (prof['owned_club_id'],))
        owned_club_name = club['name'] if club else "Unknown Club"
        share_text = f" ({prof['owned_club_share']}%)" if prof['owned_club_share'] and prof['owned_club_share'] < 100 else ""
        
    embed.add_field(name="Owned Club", value=owned_club_name + share_text, inline=True)
    
    # Groups Section
    group_list = []
    for g in groups:
        group_list.append(f"{g['group_name']} ({g['share_percentage']}%)")
    embed.add_field(name="Groups", value=", ".join(group_list) if group_list else "None", inline=True)
    
    # Recent Bids Section
    bid_list = []
    for b in bids:
        club_or_duelist = db.fetchone(f"SELECT name FROM {'club' if b['item_type'] == 'club' else 'duelists'} WHERE id=?", (b['item_id'],))
        item_name = club_or_duelist['name'] if club_or_duelist else f"{b['item_type']} {b['item_id']}"
        bid_list.append(f"{item_name} - {b['amount']:,}")
        
    embed.add_field(name="Recent Bids", value="\n".join(bid_list) if bid_list else "No recent bids", inline=False)
    
    await ctx.send(embed=embed)

# 12. Group Share Management
@bot.command()
async def creategroup(ctx, name: str, share_percentage: int):
    name = name.lower()
    if db.fetchone("SELECT * FROM investor_groups WHERE name=?", (name,)):
        return await ctx.send("Group already exists.")
    if not 1 <= share_percentage <= 100:
        return await ctx.send("Share percentage must be between 1 and 100.")

    db.query("INSERT INTO investor_groups (name, funds, owner_id) VALUES (?, 0, ?)", (name, str(ctx.author.id)))
    db.query("INSERT INTO groups_members (group_name, user_id, share_percentage) VALUES (?, ?, ?)", (name, str(ctx.author.id), share_percentage))
    log_audit(f"{ctx.author} created group {name} with {share_percentage}% share")
    await ctx.send(f"Group **{name}** created! You were added as a member with **{share_percentage}%** share.")

@bot.command()
async def joingroup(ctx, name: str, share_percentage: int):
    name = name.lower()
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (name,))
    if not g:
        return await ctx.send("No such group.")
    if db.fetchone("SELECT * FROM groups_members WHERE group_name=? AND user_id=?", (name, str(ctx.author.id))):
        return await ctx.send("You are already in this group.")
    if not 1 <= share_percentage <= 100:
        return await ctx.send("Share percentage must be between 1 and 100.")
        
    current_total_shares = db.fetchone("SELECT SUM(share_percentage) AS total FROM groups_members WHERE group_name=?", (name,))['total'] or 0
    if current_total_shares + share_percentage > 100:
        return await ctx.send(f"Joining this group with {share_percentage}% share would exceed 100% total shares (current total: {current_total_shares}%).")

    db.query("INSERT INTO groups_members (group_name, user_id, share_percentage) VALUES (?, ?, ?)", (name, str(ctx.author.id), share_percentage))
    log_audit(f"{ctx.author} joined group {name} with {share_percentage}% share")
    await ctx.send(f"{ctx.author.mention} joined **{name}** with **{share_percentage}%** share.")

@bot.command()
async def leavegroup(ctx, name: str):
    name = name.lower()
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (name,))
    if not g:
        return await ctx.send("No such group.")
    mem = db.fetchone("SELECT * FROM groups_members WHERE group_name=? AND user_id=?", (name, str(ctx.author.id)))
    if not mem:
        return await ctx.send("You are not in this group.")
    
    # Check if user has non-zero shares to sell/transfer first (simplified, no actual sell logic enforced here, just shares check)
    if mem['share_percentage'] > 0:
        return await ctx.send("You must sell or transfer your shares before leaving. Use `!sellshares` or contact an admin/group owner.")
    
    # apply penalty on group's funds (Original logic, keep as is)
    penalty = g["funds"] * LEAVE_PENALTY_PERCENT // 100
    new = max(0, g["funds"] - penalty)
    db.query("UPDATE investor_groups SET funds=? WHERE name=?", (new, name))
    
    db.query("DELETE FROM groups_members WHERE group_name=? AND user_id=?", (name, str(ctx.author.id)))
    log_audit(f"{ctx.author} left group {name}, penalty {penalty:,}")
    await ctx.send(f"{ctx.author.mention} left **{name}**. Penalty applied to group funds: **{penalty:,}**.")

# 13. Sell Club / Sell Shares / Buy Club
@bot.command()
async def sellclub(ctx, club_name: str, buyer: discord.Member = None):
    """
    Sell a solo-owned club.
    - If no buyer: Sell to System (Market Value).
    - If buyer: Sell to User (Market Value). Buyer must confirm.
    """
    club = db.fetchone("SELECT * FROM club WHERE name=?", (club_name,))
    if not club:
        return await ctx.send("No such club.")

    owner_str = club['owner_id']
    if owner_str and owner_str.startswith('group:'):
        return await ctx.send("This club is group-owned. Use `!sellshares` to sell individual shares.")
    
    if owner_str != str(ctx.author.id):
        return await ctx.send("You are not the solo owner of this club.")
        
    market_value = club['value']
    
    # -- Logic: P2P SALE (Buyer Specified) --
    if buyer:
        # Validation
        buyer_uid = str(buyer.id)
        buyer_wallet = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (buyer_uid,))
        
        if not buyer_wallet or buyer_wallet['balance'] < market_value:
            return await ctx.send(f"🚫 {buyer.mention} does not have enough funds to buy this club (Cost: {market_value:,}).")

        # Confirmation
        await ctx.send(f"⚠️ **CLUB SALE OFFER**\n{buyer.mention}, do you want to buy **{club_name}** from {ctx.author.mention} for **{market_value:,}**?\nType `yes` or `no`.")

        def check(m):
            return m.author == buyer and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

        try:
            msg = await bot.wait_for('message', check=check, timeout=30.0)
        except asyncio.TimeoutError:
            return await ctx.send("Sale timed out.")

        if msg.content.lower() == 'no':
            return await ctx.send("Sale cancelled by buyer.")

        # Execution (P2P)
        # Deduct Buyer
        db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (market_value, buyer_uid))
        # Credit Seller
        db.query("INSERT OR IGNORE INTO personal_wallets (user_id, balance) VALUES (?, 0)", (str(ctx.author.id),))
        db.query("UPDATE personal_wallets SET balance=balance+? WHERE user_id=?", (market_value, str(ctx.author.id)))
        
        # Transfer Ownership
        db.query("UPDATE club SET owner_id=? WHERE id=?", (buyer_uid, club['id']))
        db.query("UPDATE user_profiles SET owned_club_id=NULL WHERE user_id=?", (str(ctx.author.id),))
        db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, 100)", (buyer_uid, club['id']))
        
        log_audit(f"User {ctx.author} sold club {club_name} to {buyer} for {market_value:,}")
        return await ctx.send(f"✅ **{club_name}** has been sold to {buyer.mention}! Funds transferred.")


    # -- Logic: SYSTEM SALE (No Buyer) --
    
    # Confirmation
    await ctx.send(f"⚠️ **SELL TO MARKET CONFIRMATION**\n{ctx.author.mention}, sell **{club_name}** to the market for **{market_value:,}**? You will lose ownership.\nType `yes` or `no`.")

    def check_sys(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        msg = await bot.wait_for('message', check=check_sys, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("Sale timed out.")

    if msg.content.lower() == 'no':
        return await ctx.send("Sale cancelled.")

    # Execution (System)
    # Credit Seller (System Money)
    db.query("INSERT OR IGNORE INTO personal_wallets (user_id, balance) VALUES (?, 0)", (str(ctx.author.id),))
    db.query("UPDATE personal_wallets SET balance=balance+? WHERE user_id=?", (market_value, str(ctx.author.id)))
    
    # Reset Ownership
    db.query("UPDATE club SET owner_id=NULL, last_bid_price=NULL WHERE id=?", (club['id'],))
    db.query("UPDATE user_profiles SET owned_club_id=NULL, owned_club_share=NULL WHERE user_id=? AND owned_club_id=?", (str(ctx.author.id), club['id']))
    
    log_audit(f"Solo owner {ctx.author} sold club {club_name} to Market for {market_value:,}")
    await ctx.send(f"Club **{club_name}** sold to the Market for **{market_value:,}**. Funds credited to your wallet. Club is now unowned.")

@bot.command()
async def sellshares(ctx, club_name: str, buyer: discord.Member, percentage: int):
    """
    Sell shares to any user. Buyer must confirm with 'yes'.
    """
    # 1. Validation
    club = db.fetchone("SELECT * FROM club WHERE name=?", (club_name,))
    if not club:
        return await ctx.send("No such club.")
    
    club_owner_str = club['owner_id']
    if not club_owner_str or not club_owner_str.startswith('group:'):
        return await ctx.send("This club is not group-owned.")
    
    gname = club_owner_str.replace('group:', '')
    
    seller_uid = str(ctx.author.id)
    seller_shares = db.fetchone("SELECT share_percentage FROM groups_members WHERE group_name=? AND user_id=?", (gname, seller_uid))
    
    if not seller_shares or seller_shares['share_percentage'] < percentage:
        return await ctx.send(f"You do not have enough shares. You have {seller_shares['share_percentage']}% in {gname}.")

    share_value = int(club['value'] * (percentage / 100))
    buyer_uid = str(buyer.id)

    # 2. Buyer Wallet Check
    buyer_wallet = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (buyer_uid,))
    if not buyer_wallet or buyer_wallet['balance'] < share_value:
        return await ctx.send(f"{buyer.mention} does not have enough funds ({share_value:,}) to buy these shares.")

    # 3. Total Share Check (if buyer is new, ensure < 100 total, though this logic usually applies to NEW creation)
    # Here we are transferring, so total remains same. No check needed on total group shares.

    # 4. Confirmation
    await ctx.send(f"{buyer.mention}, do you want to buy **{percentage}%** of **{club_name}** shares from {ctx.author.mention} for **{share_value:,}**? Type `yes` or `no`.")

    def check(m):
        return m.author == buyer and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        return await ctx.send("Sale timed out. Transaction cancelled.")

    if msg.content.lower() == 'no':
        return await ctx.send("Transaction cancelled by buyer.")

    # 5. Execution
    # Transfer Money
    db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (share_value, buyer_uid))
    db.query("INSERT OR IGNORE INTO personal_wallets (user_id, balance) VALUES (?, 0)", (seller_uid,))
    db.query("UPDATE personal_wallets SET balance=balance+? WHERE user_id=?", (share_value, seller_uid))

    # Update Seller Shares
    new_seller_share = seller_shares['share_percentage'] - percentage
    if new_seller_share == 0:
        # Remove seller from group if 0 shares (optional, but usually good practice)
        db.query("DELETE FROM groups_members WHERE group_name=? AND user_id=?", (gname, seller_uid))
        db.query("UPDATE user_profiles SET owned_club_id=NULL, owned_club_share=NULL WHERE user_id=? AND owned_club_id=?", (seller_uid, club['id']))
    else:
        db.query("UPDATE groups_members SET share_percentage=? WHERE group_name=? AND user_id=?", (new_seller_share, gname, seller_uid))
        db.query("UPDATE user_profiles SET owned_club_share=? WHERE user_id=? AND owned_club_id=?", (new_seller_share, seller_uid, club['id']))

    # Update Buyer Shares
    buyer_shares = db.fetchone("SELECT share_percentage FROM groups_members WHERE group_name=? AND user_id=?", (gname, buyer_uid))
    
    if buyer_shares:
        # Buyer is already a member, update shares
        new_buyer_share = buyer_shares['share_percentage'] + percentage
        db.query("UPDATE groups_members SET share_percentage=? WHERE group_name=? AND user_id=?", (new_buyer_share, gname, buyer_uid))
        db.query("UPDATE user_profiles SET owned_club_share=? WHERE user_id=? AND owned_club_id=?", (new_buyer_share, buyer_uid, club['id']))
    else:
        # Buyer is NEW to group, insert them
        db.query("INSERT INTO groups_members (group_name, user_id, share_percentage) VALUES (?,?,?)", (gname, buyer_uid, percentage))
        db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, ?)", (buyer_uid, club['id'], percentage))

    log_audit(f"{ctx.author} sold {percentage}% of {club_name} to {buyer} for {share_value:,}")
    await ctx.send(f"✅ Transaction complete! {buyer.mention} is now the owner of **{percentage}%** shares of **{club_name}**.")


# --- ERROR HANDLER ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors to prevent log spam
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: {error.param}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Bad argument: {error}")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You do not have the required permissions to run this command.")
    else:
        print(f"Error in command {ctx.command}: {error}")
        # Optionally send generic error message to user
        # await ctx.send("An error occurred while executing the command.")


# ---------- UPDATED HELP COMMAND (Clean Embeds) ----------
@bot.command()
async def helpme(ctx):
    current_prefix = get_prefix(bot, ctx.message)
    
    # Embed 1: General & Wallet
    embed1 = discord.Embed(title="💰 ZE AUCTION BOT - General & Wallet", color=0x2ecc71)
    embed1.add_field(name="Personal / Wallet", value=f"""
`{current_prefix}profile [ @User ]`
Check your profile, owned club, share %, and recent bids.
`{current_prefix}wallet`
Check your current personal cash balance.
`{current_prefix}withdrawwallet <Amount>`
Withdraws cash from your personal wallet.
`{current_prefix}retireduelist [@User]`
Retires a duelist (Self or Owner initiated).
`{current_prefix}registerduelist <Name> <Base Price> <Salary>`
Registers yourself as a duelist.
""", inline=False)
    embed1.add_field(name="Group & Shares", value=f"""
`{current_prefix}creategroup <Name> <Share %>`
Creates a new group and sets your initial share percentage (1-100).
`{current_prefix}joingroup <Name> <Share %>`
Joins an existing group and buys a share percentage.
`{current_prefix}groupinfo <Name>`
Shows group details, members, and owned clubs.
`{current_prefix}leavegroup <Name>`
Leaves a group (must sell shares first).
`{current_prefix}deposit <Group Name> <Amount>`
Funds the group wallet for group bidding.
`{current_prefix}withdraw <Group Name> <Amount>`
Withdraws funds from the group wallet.
""", inline=False)
    
    await ctx.send(embed=embed1)

    # Embed 2: Auction, Market & Battles
    embed2 = discord.Embed(title="⚔️ ZE AUCTION BOT - Auction, Market & Battles", color=0xe67e22)
    embed2.add_field(name="Bidding & Auction", value=f"""
`{current_prefix}placebid <Amount> <Item Type> <Item ID>`
Places a personal bid on a club or duelist. (Item Type: club or duelist)
`{current_prefix}groupbid <Group Name> <Amount> <Item Type> <Item ID>`
Places a bid using the group's funds.
`{current_prefix}sellclub <Club Name> [Buyer]`
Sell your solo-owned club to the Market or to a specific User.
`{current_prefix}sellshares <Club Name> <@Buyer> <Share %>`
Sells your percentage of a group-owned club to another user.
""", inline=False)
    embed2.add_field(name="Market & Level Up Panel", value=f"""
`{current_prefix}marketpanel <Club Name or ID>`
Shows a detailed dashboard of current Market Value, Level, and next level requirements.
`{current_prefix}leaderboard`
Shows the club ranking based on level/wins.
`{current_prefix}clublevel <Club Name or ID>`
Shows the current Division/Level and wins needed for the next level.
`{current_prefix}clubinfo <Club Name or ID>`
Shows detailed info (Owner access only): Market Value, Last Bid, Duelists, Manager.
`{current_prefix}listclubs`
Lists all registered clubs.
`{current_prefix}listduelists`
Lists all registered duelists and the club they are contracted to.
""", inline=False)
    embed2.add_field(name="Battle Registration (Admin Only)", value=f"""
`{current_prefix}registerbattle <Club A Name> <Club B Name>`
Registers a new official battle between two clubs.
`{current_prefix}battleresult <Battle ID> <Winner Club Name>`
Records the result, which updates market value and club wins/levels.
""", inline=False)

    await ctx.send(embed=embed2)

    # Embed 3: Admin & Manager
    embed3 = discord.Embed(title="🛠️ ZE AUCTION BOT - Admin & Manager", color=0x95a5a6)
    embed3.add_field(name="Admin & Owner Tools", value=f"""
`{current_prefix}setprefix <New Prefix>`
Dynamically changes the bot's command prefix (e.g., to $).
`{current_prefix}registerclub <Name> <Base Price> [Logo URL] [Slogan]`
Registers a new club for auction.
`{current_prefix}startclubauction <Club Name>`
Starts the auction for a club.
`{current_prefix}startduelistauction <Duelist ID>`
Starts the auction for a duelist.
`{current_prefix}deleteclub <Club Name>`
Permanently removes a club and all associated history.
`{current_prefix}checkclubmessages <Club Name> <Count>`
Manually checks owner messages to increase MV.
`{current_prefix}tip <@User> <Amount>`
Adds balance to a user's personal wallet.
`{current_prefix}deduct_user <@User> <Amount>`
Deducts balance from a user's personal wallet.
`{current_prefix}adjustgroupfunds <Group Name> <+/- Amount>`
Manually adjusts a group's fund balance.
`{current_prefix}forcewinner <Type> <ID> <Winner> <Amount>`
Force sets a winner for an item.
`{current_prefix}freezeauction / {current_prefix}unfreezeauction`
Stops/starts all bidding activity.
`{current_prefix}auditlog [Lines]`
Shows recent bot activity.
`{current_prefix}admin_reset_all`
**WARNING:** Resets all club history, wins, and market data.
""", inline=False)
    embed3.add_field(name="Manager / Salary", value=f"""
`{current_prefix}setclubmanager <Club Name> <@Member>`
Assigns a manager to a club.
`{current_prefix}adjustsalary <Duelist ID> <+/- Amount>`
Gives a bonus (deducted from owner's wallet) or deducts salary from the duelist's wallet.
`{current_prefix}deductsalary <Duelist ID> <yes|no>`
Deducts 15% of salary (for missing match), taken from club owner funds.
""", inline=False)

    await ctx.send(embed=embed3)


# ---------- START BACKGROUND TASKS AFTER READY ----------
@bot.event
async def on_ready():
    print("Bot started as", bot.user)
    # Ensure all clubs have initial level set if running the bot for the first time on old data
    db.query("UPDATE club SET level_name=? WHERE level_name IS NULL", (LEVEL_UP_CONFIG[0][1],))
    
    # Fix for potential duplicate tasks on reconnect
    if not hasattr(bot, 'market_tasks_started'):
        bot.loop.create_task(market_simulation_task())
        bot.loop.create_task(weekly_report_scheduler())
        bot.market_tasks_started = True

# ---------- RUN ----------
if __name__ == "__main__":
    if DISCORD_TOKEN == "PASTE_YOUR_TOKEN_HERE" or not DISCORD_TOKEN:
        print("ERROR: Please set your DISCORD_TOKEN environment variable OR paste your token into DISCORD_TOKEN in this file.")
    else:
        bot.run(DISCORD_TOKEN)