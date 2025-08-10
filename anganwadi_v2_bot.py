# anganwadi_v2_bot.py
# Runtime deps:
#   python-telegram-bot==21.6
#
# Env vars (Render -> Environment):
#   TELEGRAM_BOT_TOKEN = <token from @BotFather>
#   ALLOWED_CHAT_ID    = 0                        # (optional) for single group during setup; use /id to get the real one
#   ALLOWED_CHAT_IDS   = -1001111111111,-1002222222222   # (optional) comma-separated for multi-group mode

import os
import asyncio
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import Update, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ---------- Config ----------
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
IST = ZoneInfo("Asia/Kolkata")

# Support either single-group (ALLOWED_CHAT_ID) or multi-group (ALLOWED_CHAT_IDS).
_raw_ids = os.environ.get("ALLOWED_CHAT_IDS")
if _raw_ids:
    ALLOWED_CHAT_IDS = {int(x.strip()) for x in _raw_ids.split(",") if x.strip()}
else:
    ALLOWED_CHAT_ID = int(os.environ.get("ALLOWED_CHAT_ID", "0"))
    ALLOWED_CHAT_IDS = set() if ALLOWED_CHAT_ID == 0 else {ALLOWED_CHAT_ID}

print("TOKEN_FINGERPRINT:", hashlib.sha256(TOKEN.encode()).hexdigest()[:12])
print("ALLOWED_CHAT_IDS:", sorted(list(ALLOWED_CHAT_IDS)) if ALLOWED_CHAT_IDS else "ANY (setup mode)")

# ---------- In-memory state (per chat) ----------
# submissions[chat_id][date][user_id] = {"name": str, "time": "HH:MM"}
submissions = defaultdict(lambda: defaultdict(dict))
# streaks[chat_id][user_id] = int
streaks = defaultdict(lambda: defaultdict(int))
# last_submission_date[chat_id][user_id] = "YYYY-MM-DD"
last_submission_date = defaultdict(dict)
# known_users[chat_id][user_id] = "FirstName"
known_users = defaultdict(dict)
# Track media albums so one album counts as one submission
seen_media_groups = set()

# ---------- Utilities ----------
def today_str():
    return datetime.now(tz=IST).strftime("%Y-%m-%d")

def is_allowed_chat(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True  # setup mode so /id works anywhere
    return chat_id in ALLOWED_CHAT_IDS

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    await update.message.reply_text("🙏 स्वागत है! कृपया हर दिन अपने आंगनवाड़ी की फ़ोटो इस समूह में भेजें।")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    await update.message.reply_text(f"chat_id: {chat.id}")

async def cmd_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    count = await context.bot.get_chat_member_count(chat_id=chat.id)
    await update.message.reply_text(f"👥 Group members right now: {count}")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    await post_summary_for_chat(context, chat.id)
    await asyncio.sleep(1)
    await post_awards_for_chat(context, chat.id)

# ---------- Member tracking ----------
async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m: ChatMemberUpdated = update.chat_member
    chat_id = m.chat.id
    if not is_allowed_chat(chat_id):
        return
    member = m.new_chat_member
    if member.status in {"member", "administrator"}:
        user = member.user
        known_users[chat_id][user.id] = user.first_name or "User"

# ---------- Photo handling ----------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    if not update.message or not update.message.photo:
        return

    # Treat an album (media_group) as one submission
    mgid = update.message.media_group_id
    if mgid:
        key = (chat.id, today_str(), mgid)
        if key in seen_media_groups:
            return
        seen_media_groups.add(key)

    chat_id = chat.id
    user = update.effective_user
    if not user:
        return

    user_id = user.id
    name = user.first_name or "User"
    known_users[chat_id][user_id] = name

    date = today_str()
    now = datetime.now(tz=IST).strftime("%H:%M")

    submissions[chat_id].setdefault(date, {})
    if user_id in submissions[chat_id][date]:
        # Already submitted today; optional gentle reply:
        # await update.message.reply_text("✅ आज की रिपोर्ट पहले से दर्ज है.")
        return

    submissions[chat_id][date][user_id] = {"name": name, "time": now}

    prev_date = last_submission_date[chat_id].get(user_id)
    yesterday = (datetime.now(tz=IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    if prev_date == yesterday:
        streaks[chat_id][user_id] = streaks[chat_id].get(user_id, 0) + 1
    else:
        streaks[chat_id][user_id] = 1
    last_submission_date[chat_id][user_id] = date

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ {name}, आपकी आज की फ़ोटो दर्ज कर ली गई है। बहुत अच्छे!"
    )

# ---------- Summary & Awards (live member count) ----------
async def build_summary_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    date = today_str()

    # LIVE total members from Telegram
    total_members = await context.bot.get_chat_member_count(chat_id=chat_id)

    today_data = submissions[chat_id].get(date, {})
    today_ids = set(today_data.keys())

    # Pending = live total - submitted today
    pending_count = max(total_members - len(today_ids), 0)

    # Top streaks among users we’ve seen in this chat
    top_streaks = sorted(
        [(uid, streaks[chat_id][uid]) for uid in streaks[chat_id]],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    leaderboard = "\n".join(
        f"{i+1}. {known_users[chat_id].get(uid, 'User')} – {count} दिन"
        for i, (uid, count) in enumerate(top_streaks)
    )

    summary = (
        f"📊 {datetime.now(tz=IST).strftime('%I:%M %p')} समूह रिपोर्ट:\n\n"
        f"👥 कुल सदस्य: {total_members}\n"
        f"✅ आज रिपोर्ट भेजी: {len(today_ids)}\n"
        f"⏳ रिपोर्ट नहीं भेजी: {pending_count}\n\n"
       
