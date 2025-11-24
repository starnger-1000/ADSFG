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
DEFAULT_PREFIX = "!"

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
    if owner_str.startswith('group:'):
        gname = owner_str.replace('group:', '').lower()
        members = db.fetchall("SELECT user_id FROM groups_members WHERE group_name=?", (gname,))
        return owner_str, [m['user_id'] for m in members]
    else:
        return owner_str, [owner_str]

def update_club_level(club_id, wins_gained=0):
    club = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    if not club:
        return None
    
    new_total_wins = club['total_wins'] + wins_gained
    db.query("UPDATE club SET total_wins=? WHERE id=?", (new_total_wins, club_id))
    
    current_level_index = -1
    for i, (wins_required, name, bonus) in enumerate(LEVEL_UP_CONFIG):
        if club['total_wins'] < wins_required <= new_total_wins:
            # Level up occurs!
            db.query("UPDATE club SET level_name=?, value=value+? WHERE id=?", (name, bonus, club_id))
            log_audit(f"Club {club['name']} leveled up to {name}. Bonus: {bonus}")
            return name
        elif new_total_wins >= wins_required:
            current_level_index = i

    return None

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
            log_audit(f"Market updated for {club['name']} to {new_value}")

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
        if " (group)" in str(w):
            g = str(w).replace(" (group)", "")
            group_profits[g] = group_profits.get(g, 0) + r["amount"]
    top = sorted(group_profits.items(), key=lambda x: x[1], reverse=True)[:5]
    report = f"📈 Weekly Report\nTotal Sales: {total_sales}\nVolume: {total_volume}\nTop Groups: {top}\nGenerated: {now}"
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
                log_audit(f"Deducted {amount} from group {gname} after winning auction")
        else: # Personal bid
            db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (amount, bidder_user_id))
            log_audit(f"Deducted {amount} from personal wallet {bidder_str} after winning auction")
        
        if item_type == "club":
            # 7. Update club status and history
            db.query("INSERT INTO club_history (club_id, winner, amount, timestamp, market_value_at_sale) VALUES (?,?,?,'now',?)",
                     (club['id'], bidder_str, amount, (club['value'] if club else None)))
            db.query("UPDATE club SET owner_id=?, last_bid_price=? WHERE id=?", (bidder_str, amount, club['id']))
            
            # 11. Update profile/group shares on acquisition
            if club:
                if gname: # Group ownership
                    # Update profiles of group members (assuming 100% split among joining members for now, complex share logic handled by group_members table)
                    members = db.fetchall("SELECT user_id, share_percentage FROM groups_members WHERE group_name=?", (gname,))
                    for m in members:
                        db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, ?)", 
                                 (m['user_id'], club['id'], m['share_percentage']))
                else: # Solo ownership
                    db.query("INSERT OR REPLACE INTO user_profiles (user_id, owned_club_id, owned_club_share) VALUES (?, ?, 100)", 
                             (bidder_user_id, club['id']))


            if channel:
                await channel.send(f"🏁 Auction ended for club **{club['name']}**! Winner: **{bidder_str}** for **{amount:,}**.")
            log_audit(f"Auction ended for club {item_id}. Winner: {bidder_str} for {amount}")
        
        else: # duelist
            duelist = db.fetchone("SELECT * FROM duelists WHERE id=?", (item_id,))
            if duelist:
                salary = duelist["expected_salary"]
                db.query("INSERT INTO duelist_contracts (duelist_id, club_owner, purchase_price, salary, signed_at) VALUES (?,?,?,?,datetime('now'))",
                          (item_id, bidder_str, amount, salary))
                db.query("UPDATE duelists SET owned_by=?, club_id=? WHERE id=?", (bidder_str, club['id'] if club else None, item_id))
                
                if channel:
                    await channel.send(f"🏁 Duelist auction ended. {duelist['username']} signed to **{bidder_str}** for **{amount:,}**. Salary: {salary:,}")
                log_audit(f"Duelist {duelist['username']} signed to {bidder_str} for {amount}")
    
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
async def registerclub(ctx, name: str, base_price: int, logo_url: str = None, *, slogan: str = ""):
    if db.fetchone("SELECT * FROM club WHERE name=?", (name,)):
        return await ctx.send("Club already registered.")
    db.query("INSERT INTO club (name, base_price, slogan, logo, value, total_wins, level_name) VALUES (?,?,?,?,?,?,?)", 
             (name, base_price, slogan, logo_url, base_price, 0, LEVEL_UP_CONFIG[0][1])) # Default to 5th Division
    db.query("INSERT INTO club_market_history (timestamp, value) VALUES (?,?)", (datetime.now().isoformat(), base_price))
    await ctx.send(f"Club **{name}** registered with base price {base_price:,}. Logo set: {bool(logo_url)}")
    log_audit(f"{ctx.author} registered club {name} (base {base_price})")

@bot.command()
async def listclubs(ctx):
    rows = db.fetchall("SELECT id, name, base_price, value, level_name, total_wins FROM club")
    if not rows:
        return await ctx.send("No clubs registered.")
    msg = "📋 Registered Clubs:\n"
    for r in rows:
        msg += f"- {r['id']}: **{r['name']}** | Value: {r['value']:,} | Level: {r['level_name']} ({r['total_wins']} wins)\n"
    await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def startclubauction(ctx, club_name: str):
    club = db.fetchone("SELECT * FROM club WHERE name=?", (club_name,))
    if not club:
        return await ctx.send("No such registered club.")
    db.query("DELETE FROM bids WHERE item_type='club' AND item_id=?", (str(club["id"]),))
    await ctx.send(f"🔔 Auction started for club **{club_name}**! Starting price: {club['base_price']:,}\nUse `!placebid <amount> club {club['id']}` to bid.")
    log_audit(f"{ctx.author} started auction for club {club_name}")
    schedule_auction_timer("club", str(club["id"]), ctx.channel.id)

# 7. Add specific features in club info command
@bot.command()
async def clubinfo(ctx, club_name_or_id: str):
    try:
        club_id = int(club_name_or_id)
        row = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    except ValueError:
        row = db.fetchone("SELECT * FROM club WHERE name=?", (club_name_or_id,))
    
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
    
    if row["logo"]:
        embed.set_thumbnail(url=row["logo"])
        
    owner_display = owner_str if owner_str else "Unowned/In Auction"
    
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
    embed.add_field(name="Wins / Next Level", value=f"{row['total_wins']} wins / {LEVEL_UP_CONFIG[0][0] if row['level_name'] == 'Unranked' else next((config[0] for config in LEVEL_UP_CONFIG if config[1] == row['level_name']), 'MAX')}", inline=True)

    # 7. Registered Duelists
    duelist_list = "\n".join([d['username'] for d in duelists]) if duelists else "None"
    embed.add_field(name="Registered Duelists", value=duelist_list, inline=False)
    
    await ctx.send(embed=embed)

# 2. Add Battle Register and Result features
@bot.command()
@commands.has_permissions(administrator=True)
async def registerbattle(ctx, club_a_name: str, club_b_name: str):
    club_a = db.fetchone("SELECT id FROM club WHERE name=?", (club_a_name,))
    club_b = db.fetchone("SELECT id FROM club WHERE name=?", (club_b_name,))
    
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
    
    winner_club = db.fetchone("SELECT * FROM club WHERE name=?", (winner_club_name,))
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
async def clublevel(ctx, club_name_or_id: str):
    try:
        club_id = int(club_name_or_id)
        row = db.fetchone("SELECT * FROM club WHERE id=?", (club_id,))
    except ValueError:
        row = db.fetchone("SELECT * FROM club WHERE name=?", (club_name_or_id,))
        
    if not row:
        return await ctx.send("No such club.")

    current_wins = row['total_wins']
    current_level = row['level_name']
    
    next_level_info = None
    required_wins = 0
    
    for i, (wins_required, name, bonus) in enumerate(LEVEL_UP_CONFIG):
        if wins_required > current_wins:
            next_level_info = (name, wins_required, bonus)
            required_wins = wins_required - current_wins
            break
        
    msg = f"**{row['name']}** Current Level: **{current_level}**\nTotal Wins: **{current_wins}**\n"
    
    if next_level_info:
        msg += f"Next Level: **{next_level_info[0]}** (Value Bonus: {next_level_info[2]:,})\n"
        msg += f"Wins Needed: **{required_wins}** more battles."
    else:
        msg += "Club has reached the highest division!"
        
    await ctx.send(msg)
    
# 4. Leaderboard
@bot.command()
async def leaderboard(ctx):
    # Sort by total_wins (proxy for level) then market value
    rows = db.fetchall("SELECT name, level_name, total_wins, value FROM club ORDER BY total_wins DESC, value DESC LIMIT 15")
    
    if not rows:
        return await ctx.send("No clubs registered for the leaderboard.")
        
    msg = "🏆 **Club Leaderboard (Ranked by Level/Wins)** 🏆\n"
    msg += "```\n"
    msg += f"| # | {'Club':<20} | {'Level':<20} | {'Value':<12} |\n"
    msg += "|---|----------------------|----------------------|--------------|\n"
    
    for i, r in enumerate(rows):
        msg += f"| {i+1:<1} | {r['name'][:20]:<20} | {r['level_name'][:20]:<20} | {r['value']:,<12} |\n"
    
    msg += "```"
    await ctx.send(msg)

# Admin command to check owner messages (for Point 1: Live Market)
@bot.command()
@commands.has_permissions(administrator=True)
async def checkclubmessages(ctx, club_name: str, message_count: int):
    club = db.fetchone("SELECT * FROM club WHERE name=?", (club_name,))
    if not club:
        return await ctx.send("No such club.")
        
    # Owner message logic: simplified to check total messages from all owners/group members
    # In a real bot, you'd listen to on_message, but here we simulate the check.
    
    # We update a counter on the club's owner's profile/group (or just update the value directly for simplicity here)
    bonus_units = message_count // OWNER_MSG_COUNT_PER_BONUS
    value_increase = bonus_units * OWNER_MSG_VALUE_BONUS
    
    if value_increase > 0:
        db.query("UPDATE club SET value=value+? WHERE id=?", (value_increase, club['id']))
        await ctx.send(f"Club **{club_name}** market value increased by **{value_increase:,}** for {message_count} owner messages.")
        log_audit(f"Club {club_name} value increased by {value_increase} due to {message_count} owner messages.")
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

# Override the original deposit to only allow group deposit (as per point 6)
@bot.command()
async def deposit(ctx, group_name: str, amount: int):
    g = db.fetchone("SELECT * FROM investor_groups WHERE name=?", (group_name.lower(),))
    if not g:
        return await ctx.send("No such group.")
    new = g["funds"] + amount
    db.query("UPDATE investor_groups SET funds=? WHERE name=?", (new, group_name.lower()))
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} deposited {amount} to {group_name}",))
    await ctx.send(f"Deposited **{amount:,}** to **{group_name}**. New funds: {new:,}")

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
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} withdrew {amount} from {group_name}",))
    await ctx.send(f"Withdrew **{amount:,}** from **{group_name}**. New funds: {new:,}")

# 8. Wallet Limits in Bidding
@bot.command()
async def placebid(ctx, amount: int, item_type: str = "club", item_id: int = None):
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
        
    db.query("INSERT INTO bids (bidder, amount, item_type, item_id) VALUES (?, ?, ?, ?)", (uid, amount, item_type, str(item_id)))
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"{ctx.author} bid {amount} on {item_type} {item_id}",))
    await ctx.send(f"✅ New bid of **{amount:,}** on {item_type} {item_id} by {ctx.author.mention}")
    schedule_auction_timer(item_type, str(item_id), ctx.channel.id)

@bot.command()
async def groupbid(ctx, group_name: str, amount: int, item_type: str = "club", item_id: int = None):
    if bidding_frozen:
        return await ctx.send("Bidding is currently frozen.")
    if item_type not in ("club", "duelist"):
        return await ctx.send("item_type must be 'club' or 'duelist'.")
    if item_id is None:
        return await ctx.send("Provide the item_id.")
    
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
    db.query("INSERT INTO audit_logs (entry) VALUES (?)", (f"Group {group_name} bid {amount} on {item_type} {item_id}",))
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

# 8. Owner salary/bonus adjustment (Owner Only)
@bot.command()
async def adjustsalary(ctx, duelist_id: int, amount: int):
    # Only club owners or group members can run this (admins override via tip/deduct_user)
    
    contract = db.fetchone("SELECT * FROM duelist_contracts WHERE duelist_id=? ORDER BY id DESC LIMIT 1", (duelist_id,))
    if not contract:
        return await ctx.send("Duelist not contracted.")
        
    club_id = db.fetchone("SELECT club_id FROM duelists WHERE id=?", (duelist_id,))['club_id']
    
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
        log_audit(f"Owner {ctx.author} paid bonus {amount} to duelist {duelist_id}")
        await ctx.send(f"💵 Paid **{amount:,}** bonus to duelist {duelist_id}.")
        
    else: # Deduction
        abs_amount = abs(amount)
        duelist_bal = db.fetchone("SELECT balance FROM personal_wallets WHERE user_id=?", (duelist_uid,))
        if not duelist_bal or duelist_bal['balance'] < abs_amount:
            return await ctx.send(f"Duelist does not have **{abs_amount:,}** in their wallet for this deduction.")
            
        # Deduct from duelist
        db.query("UPDATE personal_wallets SET balance=balance-? WHERE user_id=?", (abs_amount, duelist_uid))
        log_audit(f"Owner {ctx.author} deducted salary {abs_amount} from duelist {duelist_id}")
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
    club_id = db.fetchone("SELECT club_id FROM duelists WHERE id=?", (duelist_id,))['club_id']
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
            
    log_audit(f"{ctx.author} applied salary deduction {penalty} for duelist {d['username']} (id {duelist_id})")
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
# We define this last, as it was causing the duplicate registration error.
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


# ---------- UPDATED HELP COMMAND ----------
@bot.command()
async def helpme(ctx):
    header = """
**⚽ Club Auction Bot - Command Guide**
Commands are grouped by function. Use `!<command> <value>` to execute.
[Values in `<>` are required. Values in `[]` are optional.]
"""
    
    part1 = """
--- **💰 Personal / Wallet / Profile** ---
`!profile [@User]`
> Check your profile, owned club, shares, and recent bids.
`!wallet`
> Check your current personal wallet balance.

--- **🤝 Group Management** ---
`!creategroup <Name> <Share % (1-100)>`
> Create a new group and define your initial ownership share.
`!joingroup <Name> <Share % (1-100)>`
> Join an existing group and define your share percentage.
`!leavegroup <Name>`
> Leave a group (requires 0% shares).
`!deposit <Group Name> <Amount>`
> Deposit funds into a Group's shared wallet.
`!withdraw <Group Name> <Amount>`
> Withdraw funds from a Group's shared wallet.
"""
    
    part2 = """
--- **🔨 Auction & Transfers** ---
`!placebid <Amount> <Item Type: club/duelist> <Item ID>`
> Place a bid using your **personal wallet**.
`!groupbid <Group Name> <Amount> <Item Type: club/duelist> <Item ID>`
> Place a bid using your **Group's shared funds**.
`!sellclub <Club Name>`
> Sell your solo-owned club for its current **Market Value**.
`!sellshares <Club Name> <@User to Sell To> <Percentage>`
> Sell a percentage of your group-owned club shares to another user.

--- **📜 Club & Duelist Info** ---
`!listclubs`
> View all registered clubs, their ID, and Market Value.
`!clubinfo <Club Name or ID>`
> View detailed status (Level, Owner, Duelists). (Owner/Admin Only)
`!clublevel <Club Name or ID>`
> Check a club's current level, wins, and requirements for the next level up.
`!leaderboard`
> Show the top clubs ranked by level and market performance.
`!registerduelist <Username> <Base Price> <Expected Salary>`
> Register yourself to be auctioned as a Duelist.
`!listduelists`
> View all registered Duelists, their owner, and salary.
`!retireduelist`
> Retires you as a Duelist (only if you are a free agent).
"""

    part3 = """
--- **⚙️ Club Management (Owner Commands)** ---
`!adjustsalary <Duelist ID> <Amount (+ or -)>`
> Give a bonus (deducted from owner's wallet) or apply a deduction to a Duelist's wallet.
`!deductsalary <Duelist ID> <yes/no>`
> Applies the standard 15% salary deduction penalty for a missed match.

--- **👑 Admin / Moderator Commands** ---
`!setprefix <New Prefix>`
> **Change the bot's command prefix.** (Admin Only)
`!registerclub <Name> <Base Price> [Logo URL] [Slogan]`
> Register a new club into the system.
`!startclubauction <Club Name>`
> Begin the auction for a club.
`!startduelistauction <Duelist ID>`
> Begin the auction for a Duelist.
`!registerbattle <Club A Name> <Club B Name>`
> Register an official battle between two clubs.
`!battleresult <Battle ID> <Winner Club Name>`
> Records the battle winner, updating club market values and win counters.
`!tip <@User> <Amount>`
> Adds funds directly to a user's personal wallet.
`!deduct_user <@User> <Amount>`
> Deducts funds directly from a user's personal wallet.
`!deleteclub <Club Name>`
> Permanently removes a club from the system.
`!admin_reset_all` (Owner Only)
> **WARNING:** Resets all club history, levels, and battle data.
"""

    await ctx.send(header)
    await ctx.send(f"```markdown\n{part1}```")
    await ctx.send(f"```markdown\n{part2}```")
    await ctx.send(f"```markdown\n{part3}```")


# ---------- START BACKGROUND TASKS AFTER READY ----------
@bot.event
async def on_ready():
    print("Bot started as", bot.user)
    # Ensure all clubs have initial level set if running the bot for the first time on old data
    db.query("UPDATE club SET level_name=? WHERE level_name IS NULL", (LEVEL_UP_CONFIG[0][1],))
    bot.loop.create_task(market_simulation_task())
    bot.loop.create_task(weekly_report_scheduler())

# ---------- RUN ----------
if __name__ == "__main__":
    if DISCORD_TOKEN == "PASTE_YOUR_TOKEN_HERE" or not DISCORD_TOKEN:
        print("ERROR: Please set your DISCORD_TOKEN environment variable OR paste your token into DISCORD_TOKEN in this file.")
    else:
        bot.run(DISCORD_TOKEN)