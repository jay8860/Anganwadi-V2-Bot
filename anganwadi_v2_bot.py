# anganwadi_v2_bot.py (multi-group ready)
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

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
IST = ZoneInfo("Asia/Kolkata")

# Either ALLOWED_CHAT_IDS (comma-separated) or ALLOWED_CHAT_ID=0 during setup
_raw_ids = os.environ.get("ALLOWED_CHAT_IDS")
if _raw_ids:
    ALLOWED_CHAT_IDS = {int(x.strip()) for x in _raw_ids.split(",") if x.strip()}
else:
    # Fallback: single value for first-time setup so /id works anywhere
    ALLOWED_CHAT_ID = int(os.environ.get("ALLOWED_CHAT_ID", "0"))
    ALLOWED_CHAT_IDS = set() if ALLOWED_CHAT_ID == 0 else {ALLOWED_CHAT_ID}

print("TOKEN_FINGERPRINT:", hashlib.sha256(TOKEN.encode()).hexdigest()[:12])
print("ALLOWED_CHAT_IDS:", sorted(list(ALLOWED_CHAT_IDS)) if ALLOWED_CHAT_IDS else "ANY (setup)")

# State per chat
submissions = defaultdict(lambda: defaultdict(dict))     # submissions[chat_id][date][user_id] = {...}
streaks = defaultdict(lambda: defaultdict(int))          # streaks[chat_id][user_id] = int
last_submission_date = defaultdict(dict)                 # last_submission_date[chat_id][user_id] = "YYYY-MM-DD"
known_users = defaultdict(dict)                          # known_users[chat_id][user_id] = "FirstName"

def today_str():
    return datetime.now(tz=IST).strftime("%Y-%m-%d")

def is_allowed_chat(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True  # first-time setup so /id works anywhere
    return chat_id in ALLOWED_CHAT_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    await update.message.reply_text("🙏 स्वागत है! कृपया हर दिन अपने आंगनवाड़ी की फ़ोटो इस समूह में भेजें।")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"chat_id: {chat.id}")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    await post_summary_for_chat(context, chat.id)
    await asyncio.sleep(1)
    await post_awards_for_chat(context, chat.id)

async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m: ChatMemberUpdated = update.chat_member
    chat_id = m.chat.id
    if not is_allowed_chat(chat_id):
        return
    member = m.new_chat_member
    if member.status in {"member", "administrator"}:
        user = member.user
        known_users[chat_id][user.id] = user.first_name or "User"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or not is_allowed_chat(chat.id):
        return
    if not update.message or not update.message.photo:
        return
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
        return

    submissions[chat_id][date][user_id] = {"name": name, "time": now}

    prev_date = last_submission_date[chat_id].get(user_id)
    yesterday = (datetime.now(tz=IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    if prev_date == yesterday:
        streaks[chat_id][user_id] = streaks[chat_id].get(user_id, 0) + 1
    else:
        streaks[chat_id][user_id] = 1
    last_submission_date[chat_id][user_id] = date

    await context.bot.send_message(chat_id=chat_id, text=f"✅ {name}, आपकी आज की फ़ोटो दर्ज कर ली गई है। बहुत अच्छे!")

def _build_summary_text(chat_id: int):
    date = today_str()
    today_data = submissions[chat_id].get(date, {})
    today_ids = set(today_data.keys())
    member_ids = set(known_users[chat_id].keys())
    pending_ids = member_ids - today_ids

    top_streaks = sorted(
        [(uid, streaks[chat_id][uid]) for uid in streaks[chat_id] if uid in member_ids],
        key=lambda x: x[1], reverse=True
    )[:5]

    leaderboard = "\n".join(
        f"{i+1}. {known_users[chat_id].get(uid, 'User')} – {count} दिन"
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

async def post_summary_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await context.bot.send_message(chat_id=chat_id, text=_build_summary_text(chat_id))

async def post_awards_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    member_ids = set(known_users[chat_id].keys())
    top_streaks = sorted(
        [(uid, streaks[chat_id][uid]) for uid in streaks[chat_id] if uid in member_ids],
        key=lambda x: x[1], reverse=True
    )[:5]
    if not top_streaks:
        return
    medals = ["🥇", "🥈", "🥉", "🎖️", "🏅"]
    for i, (uid, count) in enumerate(top_streaks):
        name = known_users[chat_id].get(uid, f"User {uid}")
        msg = f"{medals[i]} *{name}*, आप आज #{i+1} स्थान पर हैं — {count} दिनों की शानदार रिपोर्टिंग के साथ! 🎉👏"
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        await asyncio.sleep(1)

# JobQueue callbacks (we pass chat_id via job.data)
async def job_summary(context: ContextTypes.DEFAULT_TYPE):
    await post_summary_for_chat(context, context.job.data)

async def job_awards(context: ContextTypes.DEFAULT_TYPE):
    await post_awards_for_chat(context, context.job.data)

def schedule_reports(app):
    jq = app.job_queue
    times = [(10,0),(14,0),(18,0)]
    target_chats = ALLOWED_CHAT_IDS or set()  # empty when in setup; skip scheduling until set
    for cid in target_chats:
        for hh, mm in times:
            jq.run_daily(callback=job_summary, time=time(hour=hh, minute=0, tzinfo=IST), data=cid)
            jq.run_daily(callback=job_awards,  time=time(hour=hh, minute=2, tzinfo=IST), data=cid)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))   # keep for future groups
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_photo))
    app.add_handler(ChatMemberHandler(track_new_members, ChatMemberHandler.CHAT_MEMBER))
    schedule_reports(app)
    print("Bot online. Waiting for updates...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
