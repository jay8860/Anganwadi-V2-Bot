import os
import asyncio
import hashlib
from datetime import datetime, time, timedelta
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
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]  # set this on Render
ALLOWED_CHAT_ID = int(os.environ["ALLOWED_CHAT_ID"])  # your group id (negative)
IST = ZoneInfo("Asia/Kolkata")

# Debug fingerprint (safe) to confirm correct token at runtime
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
    return bool(chat and chat.id == ALLOWED_CHAT_ID)

# --------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_allowed_chat(update):
        return
    print("Group ID seen:", update.effective_chat.id)
    await context.bot.send_message(
        chat_id=ALLOWED_CHAT_ID,
        text="🙏 स्वागत है! कृपया हर दिन अपने आंगनवाड़ी की फ़ोटो इस समूह में भेजें।"
    )

async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m: ChatMemberUpdated = update.chat_member
    member = m.new_chat_member
    if m.chat.id != ALLOWED_CHAT_ID:
        return
    if member.status in {"member", "administrator"}:
        user = member.user
        known_users[user.id] = user.first_name

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
        chat_id=ALLOWED_CHAT_ID,
        text=f"✅ {name}, आपकी आज की फ़ोटो दर्ज कर ली गई है। बहुत अच्छे!"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_allowed_chat(update):
        return
    await post_summary(context)
    await asyncio.sleep(1)
    await post_top_streak_awards(context)

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
    await context.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=_build_summary_text())

async def post_top_streak_awards(context: ContextTypes.DEFAULT_TYPE):
    member_ids = set(known_users.keys())
    top_streaks = sorted(
        [(uid, streaks[uid]) for uid in streaks if uid in member_ids],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    medals = ["🥇", "🥈", "🥉", "🎖️", "🏅"]
    for i, (uid, count) in enumerate(top_streaks):
        name = known_users.get(uid, f"User {uid}")
        msg = f"{medals[i]} *{name}*, आप आज #{i+1} स्थान पर हैं — {count} दिनों की शानदार रिपोर्टिंग के साथ! 🎉👏"
        await context.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=msg, parse_mode="Markdown")
        await asyncio.sleep(1)

# --------- Scheduling with JobQueue (PTB) ----------
def schedule_reports(app):
    jq = app.job_queue
    # Three daily times in IST
    for hh, mm in [(10,0), (14,0), (18,0)]:
        jq.run_daily(callback=post_summary, time=time(hour=hh, minute=mm, tzinfo=IST))
        jq.run_daily(callback=post_top_streak_awards, time=time(hour=hh, minute=mm+2, tzinfo=IST))

# --------- Entrypoint ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_photo))
    app.add_handler(ChatMemberHandler(track_new_members, ChatMemberHandler.CHAT_MEMBER))

    schedule_reports(app)
    print("Bot online. Waiting for updates...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
