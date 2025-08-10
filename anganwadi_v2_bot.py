# anganwadi_v2_bot.py
# Requirements:
#   python-telegram-bot==21.6
#   APScheduler==3.10.4  (not strictly needed now; we use JobQueue built into PTB)
#
# Environment variables to set on Render (or locally):
#   TELEGRAM_BOT_TOKEN = <bot token from @BotFather>
#   ALLOWED_CHAT_ID    = -100xxxxxxxxxxxx  (your group's chat_id; use /id to discover it first time)

import os
import asyncio
import hashlib
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

# --------- Config from environment ----------
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]           # set this on Render
IST = ZoneInfo("Asia/Kolkata")

# For the very first run, you may not know ALLOWED_CHAT_ID yet.
# Temporarily set ALLOWED_CHAT_ID to "0" in Render so /id works anywhere.
ALLOWED_CHAT_ID = int(os.environ.get("ALLOWED_CHAT_ID", "0"))

# Debug fingerprints (safe) to confirm correct values at runtime
print("TOKEN_FINGERPRINT:", hashlib.sha256(TOKEN.encode()).hexdigest()[:12])
print("ALLOWED_CHAT_ID:", ALLOWED_CHAT_ID)

# --------- In-memory state ----------
submissions = {}            # { "YYYY-MM-DD": { user_id: {"name": str, "time": "HH:MM"} } }
streaks = {}                # { user_id: int }
last_submission_date = {}   # { user_id: "YYYY-MM-DD" }
known_users = {}            # { user_id: "FirstName" }

def today_str():
    return datetime.now(tz=IST).strftime("%Y-%m-%d")

def in_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    if ALLOWED_CHAT_ID == 0:
        return True  # during first-setup phase so /id works anywhere
    return chat.id == ALLOWED_CHAT_ID

# --------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_allowed_chat(update):
        return
    print("Group ID seen:", update.effective_chat.id)
    await update.message.reply_text("🙏 स्वागत है! कृपया हर दिन अपने आंगनवाड़ी की फ़ोटो इस समूह में भेजें।")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use this once to discover chat_id, then set ALLOWED_CHAT_ID env var and redeploy.
    chat = update.effective_chat
    await update.message.reply_text(f"chat_id: {chat.id}")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_allowed_chat(update):
        return
    await post_summary(context)
    await asyncio.sleep(1)
    await post_top_streak_awards(context)

# --------- Group membership tracking ----------
async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m: ChatMemberUpdated = update.chat_member
    if ALLOWED_CHAT_ID and m.chat.id != ALLOWED_CHAT_ID and ALLOWED_CHAT_ID != 0:
        return
    member = m.new_chat_member
    if member.status in {"member", "administrator"}:
        user = member.user
        known_users[user.id] = user.first_name or "User"

# --------- Photo handling ----------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_allowed_chat(update):
        return
    if not update.message or not update.message.photo:
        return

    user = update.effective_user
    if not user:
        return
    user_id = user.id
    name = user.first_name or "User"
    known_users[user_id] = name

    date = today_str()
    now = datetime.now(tz=IST).strftime("%H:%M")

    submissions.setdefault(date, {})
    if user_id in submissions[date]:
        return  # already submitted today

    submissions[date][user_id] = {"name": name, "time": now}

    prev_date = last_submission_date.get(user_id)
    yesterday = (datetime.now(tz=IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    if prev_date == yesterday:
        streaks[user_id] = streaks.get(user_id, 0) + 1
    else:
        streaks[user_id] = 1
    last_submission_date[user_id] = date

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ {name}, आपकी आज की फ़ोटो दर्ज कर ली गई है। बहुत अच्छे!"
    )

# --------- Reporting helpers ----------
def _build_summary_text():
    date = today_str()
    today_data = submissions.get(date, {})
    today_ids = set(today_data.keys())
    member_ids = set(known_users.keys())
    pending_ids = member_ids - today_ids

    top_streaks = sorted(
        [(uid, streaks[uid]) for uid in streaks if uid in member_ids],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    leaderboard = "\n".join(
        f"{i+1}. {known_users.get(uid, 'User')} – {count} दिन"
        for i, (uid, count) in enumerate(top_streaks)
    )

    summary = (
        f"📊 {datetime.now(tz=IST).strftime('%I:%M %p')} समूह रिपोर्ट:\n\n"
        f"👥 कुल सदस्य: {len(member_ids)}\n"
        f"✅ आज रिपोर्ट भेजी: {len(today_ids)}\n"
        f"⏳ रिपोर्ट नहीं भेजी: {len(pending_ids)}\n\n"
        f"🏆 लगातार रिपोर्टिंग करने वाले:\n"
        f"{leaderboard if leaderboard else 'अभी कोई डेटा उपलब्ध नहीं है।'}"
    )
    return summary

async def post_summary(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=ALLOWED_CHAT_ID if ALLOWED_CHAT_ID else context._chat_id, text=_build_summary_text())

async def post_top_streak_awards(context: ContextTypes.DEFAULT_TYPE):
    member_ids = set(known_users.keys())
    top_streaks = sorted(
        [(uid, streaks[uid]) for uid in streaks if uid in member_ids],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    if not top_streaks:
        return
    medals = ["🥇", "🥈", "🥉", "🎖️", "🏅"]
    for i, (uid, count) in enumerate(top_streaks):
        name = known_users.get(uid, f"User {uid}")
        msg = f"{medals[i]} *{name}*, आप आज #{i+1} स्थान पर हैं — {count} दिनों की शानदार रिपोर्टिंग के साथ! 🎉👏"
        await context.bot.send_message(chat_id=ALLOWED_CHAT_ID if ALLOWED_CHAT_ID else context._chat_id, text=msg, parse_mode="Markdown")
        await asyncio.sleep(1)

# --------- Scheduling with JobQueue (built into PTB) ----------
def schedule_reports(app):
    jq = app.job_queue
    # Three daily schedules in IST (10:00, 14:00, 18:00) + awards 2 minutes later
    jq.run_daily(callback=post_summary, time=time(hour=10, minute=0, tzinfo=IST))
    jq.run_daily(callback=post_top_streak_awards, time=time(hour=10, minute=2, tzinfo=IST))

    jq.run_daily(callback=post_summary, time=time(hour=14, minute=0, tzinfo=IST))
    jq.run_daily(callback=post_top_streak_awards, time=time(hour=14, minute=2, tzinfo=IST))

    jq.run_daily(callback=post_summary, time=time(hour=18, minute=0, tzinfo=IST))
    jq.run_daily(callback=post_top_streak_awards, time=time(hour=18, minute=2, tzinfo=IST))

# --------- Entrypoint ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))       # temporary; helps you get chat_id
    app.add_handler(CommandHandler("report", cmd_report))

    # Photo handler (groups only)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_photo))

    # Track joins/role changes
    app.add_handler(ChatMemberHandler(track_new_members, ChatMemberHandler.CHAT_MEMBER))

    schedule_reports(app)
    print("Bot online. Waiting for updates...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
