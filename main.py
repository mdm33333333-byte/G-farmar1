import os
import time
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
import firebase_admin
from firebase_admin import credentials, db
from threading import Thread

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8593373295:AAG5KXGqy0lKL1tXZ8z6ZFMm59YD5pEdhIg")
BOT_USERNAME = "gmail_farmar_litebot"   
CHANNEL_USERNAME = "gmail_farmar_lite"    
PAGE_SIZE = 5

FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://farmar-28bb2-default-rtdb.firebaseio.com")

# ================= BOT & FIREBASE =================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})

# ================= STATES =================
submit_state = {}       
withdraw_state = {}     
withdraw_method = {}    
withdraw_amount = {}    
STATE_TIMEOUT = 3600

# ================= STATE CLEANUP THREAD =================
def cleanup_states():
    while True:
        time.sleep(600)
        now = time.time()
        for uid in list(submit_state.keys()):
            if now - submit_state[uid].get("timestamp", 0) > STATE_TIMEOUT:
                submit_state.pop(uid, None)
        for uid in list(withdraw_state.keys()):
            if uid not in submit_state and uid not in withdraw_state:
                withdraw_method.pop(uid, None)
                withdraw_amount.pop(uid, None)

Thread(target=cleanup_states, daemon=True).start()

# ================= HELPERS =================
def is_joined(user_id):
    try:
        status = bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id).status
        return status in ["member", "administrator", "creator"]
    except:
        return False

def is_valid_gmail(email):
    return email.endswith("@gmail.com") and len(email) > 10

def sanitize_key(email):
    return email.replace(".", ",")

def gmail_exists(gmail):
    return db.reference(f"gmails/{sanitize_key(gmail)}").get() is not None

def mark_gmail_used(gmail):
    db.reference(f"gmails/{sanitize_key(gmail)}").set(True)

def update_balance_transaction(current, amount, earned_field=None, total_field=None):
    if current is None: return
    current["balance"] = round(current.get("balance", 0.0) + amount, 2)
    if earned_field:
        current[earned_field] = round(current.get(earned_field, 0.0) + amount, 2)
    if total_field:
        current[total_field] = round(current.get(total_field, 0.0) + amount, 2)
    return current

def safe_firebase_operation(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"Firebase error: {e}")
        return None
# ================= MENU =================
def main_menu(chat_id):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("✏️ Submit my own", "💰 Balance")
    kb.row("💸 Withdraw", "📄 My History")
    kb.row("📣 Share Referral Link", "🏆 Top Referrals")
    kb.row("📌 Help")
    bot.send_message(chat_id, "📌 Main Menu", reply_markup=kb)

# ================= START =================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = str(message.from_user.id)
    args = message.text.split()
    ref_by = args[1] if len(args) > 1 else None

    user_ref = db.reference(f"users/{user_id}")
    if not user_ref.get():
        user_ref.set({
            "name": message.from_user.first_name,
            "balance": 0.0, "total_earned": 0.0,
            "referral_earned": 0.0, "referred_by": ref_by if ref_by != user_id else None,
            "referrals": 0
        })
        if ref_by and ref_by != user_id:
            rref = db.reference(f"users/{ref_by}")
            bonus = safe_firebase_operation(db.reference("settings/referral_bonus").get) or 0.05
            rref.transaction(lambda curr: update_balance_transaction(curr, float(bonus), "referral_earned", "total_earned"))
            rref.child("referrals").transaction(lambda curr: (curr or 0) + 1)

    if not is_joined(message.from_user.id):
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("📣 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}"),
            InlineKeyboardButton("✅ Join & Verify", callback_data="verify")
        )
        bot.send_message(message.chat.id, "👋 Welcome!\nPlease join our channel first.", reply_markup=kb)
    else:
        main_menu(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "verify")
def verify_callback(c):
    if is_joined(c.from_user.id):
        bot.edit_message_text("✅ Verified!", c.message.chat.id, c.message.message_id)
        main_menu(c.message.chat.id)
    else: 
        bot.answer_callback_query(c.id, "❌ Join channel first", show_alert=True)
# ================= SUBMISSION STEPS =================

# Submit Menu
@bot.message_handler(func=lambda m: m.text == "✏️ Submit my own")
def submit_menu(m):
    rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15

    # ✅ State start from menu level
    submit_state[m.from_user.id] = {
        "step": 0,
        "data": {},
        "timestamp": int(time.time())
    }

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📩 Submit Gmail", "📋 View Requirements")
    kb.row("❌ Cancel")

    bot.send_message(
        m.chat.id,
        f"✏️ Rate: {rate} USDT\nApproval: 24–48h",
        reply_markup=kb
    )


# View Requirements
@bot.message_handler(func=lambda m: m.text == "📋 View Requirements")
def view_req(m):
    rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📩 Submit Gmail", "❌ Cancel")

    bot.send_message(
        m.chat.id,
        f"📋 Requirements\n\n"
        f"✅ Gmail 30+ days old\n"
        f"✅ Recovery email set\n"
        f"✅ Password unchanged\n\n"
        f"💰 Rate: {rate} USDT",
        reply_markup=kb
    )


# Start Submit
@bot.message_handler(func=lambda m: m.text == "📩 Submit Gmail")
def start_submit(m):
    submit_state[m.from_user.id] = {
        "step": 1,
        "data": {},
        "timestamp": int(time.time())
    }

    kb = ReplyKeyboardMarkup(resize_keyboard=True).add("❌ Cancel")

    bot.send_message(
        m.chat.id,
        "📩 Step 1/3: Send Gmail address:",
        reply_markup=kb
    )


# Handle Steps
@bot.message_handler(func=lambda m: submit_state.get(m.from_user.id))
def handle_submit_steps(m):
    uid = m.from_user.id
    state = submit_state.get(uid)

    if not state:
        return

    # ✅ Cancel works everywhere
    if m.text in ["❌ Cancel", "/cancel"]:
        submit_state.pop(uid, None)
        main_menu(m.chat.id)
        return

    # ================= MENU STAGE =================
    if state["step"] == 0:
        return  # just waiting for button click

    # ================= STEP 1 =================
    if state["step"] == 1:
        gmail = m.text.strip().lower()

        if not is_valid_gmail(gmail) or gmail_exists(gmail):
            bot.send_message(m.chat.id, "❌ Invalid or already submitted Gmail.")
            return

        state["data"]["gmail"] = gmail
        state["step"] = 2

        bot.send_message(m.chat.id, "📩 Step 2/3: Send Password:")

    # ================= STEP 2 =================
    elif state["step"] == 2:
        state["data"]["password"] = m.text.strip()
        state["step"] = 3

        bot.send_message(m.chat.id, "📩 Step 3/3: Send Recovery Email:")

    # ================= STEP 3 =================
    elif state["step"] == 3:
        recovery = m.text.strip().lower()

        if not is_valid_gmail(recovery):
            bot.send_message(m.chat.id, "❌ Invalid recovery email.")
            return

        data = state["data"]
        now = int(time.time())

        # Save to DB
        sid = db.reference("submissions").push({
            "user_id": str(uid),
            **data,
            "recovery": recovery,
            "status": "pending",
            "timestamp": now
        }).key

        db.reference(f"user_submissions/{uid}/{sid}").set({
            **data,
            "recovery": recovery,
            "status": "pending",
            "timestamp": now
        })

        mark_gmail_used(data["gmail"])
        submit_state.pop(uid, None)

        bot.send_message(m.chat.id, "✅ Submitted! Waiting for approval.")
        main_menu(m.chat.id)
# ================= BALANCE & REFERRAL =================

@bot.message_handler(func=lambda m: m.text == "💰 Balance")
def show_balance(m):
    uid = str(m.from_user.id)
    u = db.reference(f"users/{uid}").get()

    if not u:
        return bot.send_message(m.chat.id, "❌ Account not found. Send /start first.")

    rate = safe_firebase_operation(db.reference("settings/usdt_to_bdt").get) or 115

    bal = u.get("balance", 0.0)
    total = u.get("total_earned", 0.0)
    ref_earn = u.get("referral_earned", 0.0)

    msg = f"""
💰 <b>Your Balance Info</b>

🏦 Balance: {bal:.2f} USDT ({bal*rate:.2f} BDT)
📈 Total Earned: {total:.2f} USDT
👥 Referral Earned: {ref_earn:.2f} USDT
"""

    bot.send_message(m.chat.id, msg)


# ================= REFERRAL =================
@bot.message_handler(func=lambda m: m.text == "📣 Share Referral Link")
def ref_link(m):
    uid = str(m.from_user.id)
    user = db.reference(f"users/{uid}").get()

    if not user:
        return bot.send_message(m.chat.id, "❌ Account not found. Send /start first.")

    ref_rate = safe_firebase_operation(db.reference("settings/referral_bonus").get) or 0.05

    total_refs = user.get("referrals", 0)
    ref_earned = user.get("referral_earned", 0.0)
    balance = user.get("balance", 0.0)

    msg = f"""
📣 <b>Your Referral System</b>

🔗 Link:
https://t.me/{BOT_USERNAME}?start={uid}

💸 Per Referral Bonus: {ref_rate} USDT

👥 Total Referrals: {total_refs}
💰 Referral Earned: {ref_earned:.2f} USDT
🏦 Balance: {balance:.2f} USDT

📢 Share your link & earn more!
"""

    bot.send_message(m.chat.id, msg)


# ================= TOP REFERRALS =================
@bot.message_handler(func=lambda m: m.text == "🏆 Top Referrals")
def top_refs(m):
    users = safe_firebase_operation(db.reference("users").get)

    if not users:
        return bot.send_message(m.chat.id, "❌ No data found")

    clean_users = []
    for u in users.values():
        if isinstance(u, dict):
            clean_users.append({
                "name": u.get("name", "Unknown"),
                "referrals": int(u.get("referrals", 0))
            })

    top = sorted(clean_users, key=lambda x: x["referrals"], reverse=True)[:10]

    txt = "🏆 <b>Top Referrals</b>\n\n"

    for i, u in enumerate(top, 1):
        txt += f"{i}. {u['name']} — {u['referrals']} refs\n"

    bot.send_message(m.chat.id, txt)

# ================= WITHDRAW =================
@bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def start_withdraw(m):
    u = db.reference(f"users/{m.from_user.id}").get()
    if not u: return bot.send_message(m.chat.id, "❌ Account not found. Send /start first.")
    minw = safe_firebase_operation(db.reference("settings/min_withdraw").get) or 2.0
    if u.get("balance", 0.0) < float(minw):
        return bot.send_message(m.chat.id, f"❌ Minimum withdraw is {minw} USDT.")
    kb = ReplyKeyboardMarkup(resize_keyboard=True).row("📱 Bkash", "📱 Nagad", "💰 Binance").add("❌ Cancel")
    withdraw_state[m.from_user.id] = "choose_method"
    bot.send_message(m.chat.id, "💸 Select Method:", reply_markup=kb)

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "choose_method")
def withdraw_m(m):
    if m.text in ["❌ Cancel", "/cancel"]:
        withdraw_state.pop(m.from_user.id, None)
        return main_menu(m.chat.id)
    if m.text in ["📱 Bkash", "📱 Nagad", "💰 Binance"]:
        withdraw_method[m.from_user.id] = m.text
        withdraw_state[m.from_user.id] = "enter_amount"
        bot.send_message(m.chat.id, "Enter amount to withdraw:", reply_markup=ReplyKeyboardRemove())
    else: 
        bot.send_message(m.chat.id, "❌ Invalid method.")

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "enter_amount")
def withdraw_amt(m):
    if m.text in ["❌ Cancel", "/cancel"]:
        withdraw_state.pop(m.from_user.id, None)
        return main_menu(m.chat.id)
    try:
        amt = float(m.text)
        user_ref = db.reference(f"users/{m.from_user.id}")
        if user_ref.get()["balance"] < amt or amt <= 0: raise Exception()
        withdraw_amount[m.from_user.id] = amt
        withdraw_state[m.from_user.id] = "enter_address"
        bot.send_message(m.chat.id, "Enter Phone/Wallet Address:")
    except: 
        bot.send_message(m.chat.id, "❌ Invalid or insufficient amount.")

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "enter_address")
def withdraw_final(m):
    if m.text in ["❌ Cancel", "/cancel"]:
        withdraw_state.pop(m.from_user.id, None)
        return main_menu(m.chat.id)
    uid = m.from_user.id
    amt = withdraw_amount[uid]
    try:
        db.reference(f"users/{uid}").transaction(lambda curr: update_balance_transaction(curr, -amt))
        db.reference("withdraw_requests").push({"user_id": str(uid), "amount": amt, "method": withdraw_method[uid], "address": m.text, "status": "pending", "time": int(time.time())})
        bot.send_message(m.chat.id, "✅ Request sent! Processing time: 24–48 hours.")
    except Exception as e:
        bot.send_message(m.chat.id, "❌ Transaction failed. Please try again.")
    finally:
        withdraw_state.pop(uid, None)
        withdraw_method.pop(uid, None)
        withdraw_amount.pop(uid, None)
        main_menu(m.chat.id)

# ================= HISTORY =================
@bot.message_handler(func=lambda m: m.text == "📄 My History")
def history(m):
    send_gmail_history_page(m.chat.id, m.from_user.id, 0)

def send_gmail_history_page(chat_id, user_id, page):
    ref = db.reference(f"user_submissions/{user_id}").get()
    if not ref:
        return bot.send_message(chat_id, "No history found.")
    items = sorted(ref.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)
    page_items = items[page*PAGE_SIZE : (page+1)*PAGE_SIZE]
    txt = "📄 Submission History\n\n"
    for _, s in page_items:
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.get("timestamp", 0)))
        txt += f"📧 {s.get('gmail', 'N/A')}\nStatus: {s.get('status', 'pending').capitalize()}\nDate: {created_at}\n\n"
    kb = InlineKeyboardMarkup()
    if page > 0: kb.add(InlineKeyboardButton("⬅ Prev", callback_data=f"gmail_{page-1}"))
    if (page+1)*PAGE_SIZE < len(items): kb.add(InlineKeyboardButton("Next ➡", callback_data=f"gmail_{page+1}"))
    bot.send_message(chat_id, txt, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gmail_"))
def gmail_history_nav(c):
    page = int(c.data.split("_")[1])
    send_gmail_history_page(c.message.chat.id, c.from_user.id, page)

from telebot.types import ReplyKeyboardMarkup
# ================= HELP / INSTRUCTIONS =================
@bot.message_handler(func=lambda m: m.text == "📌 Help")
def help_menu(m):
    help_text = """📌 সাহায্য / নির্দেশিকা

1️⃣ Gmail জমা দিন
- "✏️ Submit my own" ক্লিক করুন
- Gmail, Password, Recovery Email দিন
- ২৪–৪৮ ঘণ্টা অপেক্ষা করুন

2️⃣ ব্যালেন্স
- "💰 Balance" ক্লিক করে ব্যালেন্স দেখুন

3️⃣ উইথড্র
- "💸 Withdraw" ক্লিক করুন
- Method + Amount + Address দিন

4️⃣ রেফারেল
- "📣 Share Referral Link" দিয়ে ইনভাইট করুন

5️⃣ ইতিহাস
- "📄 My History" এ সব সাবমিশন দেখুন

⚠️ শর্ত:
- Gmail ৩০+ দিনের হতে হবে
- Recovery email থাকতে হবে
- Password change করা যাবে না

💬 সমস্যা হলে Admin এর সাথে যোগাযোগ করুন
"""

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("👤 Admin", "🔙 Back")

    bot.send_message(m.chat.id, help_text, reply_markup=kb)


# ================= ADMIN CONTACT =================
@bot.message_handler(func=lambda m: m.text == "👤 Admin")
def contact_admin(m):
    admin_username = "@Your_dad_009"  # শুধু username

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔙 Back")

    bot.send_message(
        m.chat.id,
        f"🛡️ Admin Contact:\n\n👉 {admin_username}\n\nUsername এ ক্লিক করে মেসেজ করুন।",
        reply_markup=kb
    )


# ================= BACK BUTTON =================
@bot.message_handler(func=lambda m: m.text == "🔙 Back")
def back_to_main(m):
    main_menu(m.chat.id)

# ================= ADMIN & SYSTEM =================

ADMIN_IDS = [7864372570]
admin_state = {}

# ================= ADMIN MENU =================
@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if m.from_user.id not in ADMIN_IDS:
        return

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📥 Submissions", "💸 Withdraws")
    kb.row("👥 Users", "📊 Stats")
    kb.row("⚙️ Settings", "📢 Broadcast")
    kb.row("🔙 Exit Admin")

    bot.send_message(m.chat.id, "🛠 PRO ADMIN PANEL", reply_markup=kb)


# ================= SUBMISSIONS =================

@bot.message_handler(func=lambda m: m.text == "📥 Submissions" and m.from_user.id in ADMIN_IDS)
def pending_subs(m):
    all_subs = db.reference("submissions").get() or {}

    # manual filter for pending submissions  
    subs = {  
        sid: sub for sid, sub in all_subs.items()  
        if str(sub.get("status", "")).strip().lower() == "pending"  
    }  

    if not subs:  
        return bot.send_message(m.chat.id, "📭 No pending submissions.")  

    for sid, sub in list(subs.items())[:10]:  
        kb = InlineKeyboardMarkup().add(  
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{sid}"),  
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{sid}")  
        )  

        bot.send_message(  
            m.chat.id,  
            f"📧 {sub.get('gmail')}\n👤 {sub.get('user_id')}\n🔑 {sub.get('password')}\n📨 {sub.get('recovery')}",  
            reply_markup=kb  
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith(("approve_", "reject_")))
def handle_approval(c):
    if c.from_user.id not in ADMIN_IDS:
        return bot.answer_callback_query(c.id, "⛔ Unauthorized", show_alert=True)

    action, sid = c.data.split("_", 1)
    sub = db.reference(f"submissions/{sid}").get()
    if not sub:
        return bot.answer_callback_query(c.id, "Not found")

    uid = str(sub["user_id"])

    if action == "approve":
        db.reference(f"submissions/{sid}/status").set("approved")
        db.reference(f"user_submissions/{uid}/{sid}/status").set("approved")

        rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15

        # ✅ FIXED: balance + total_earned only added once
        def update_user(curr):
            if curr is None:
                return None
            curr["balance"] = round(curr.get("balance", 0.0) + rate, 2)
            curr["total_earned"] = round(curr.get("total_earned", 0.0) + rate, 2)
            return curr

        db.reference(f"users/{uid}").transaction(update_user)

        bot.send_message(int(uid), f"✅ Gmail approved! +{rate} USDT added.")

    else:
        db.reference(f"submissions/{sid}/status").set("rejected")
        db.reference(f"user_submissions/{uid}/{sid}/status").set("rejected")

        bot.send_message(int(uid), "❌ Gmail rejected.")

    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)

# ================= WITHDRAW =================
@bot.message_handler(func=lambda m: m.text == "💸 Withdraws" and m.from_user.id in ADMIN_IDS)
def pending_withdraws(m):
    all_reqs = db.reference("withdraw_requests").get() or {}

    # filter pending withdraws
    reqs = {
        rid: r for rid, r in all_reqs.items()
        if str(r.get("status", "")).strip().lower() == "pending"
    }

    if not reqs:
        return bot.send_message(m.chat.id, "📭 No pending withdraw requests.")

    for rid, req in list(reqs.items())[:10]:
        kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ Complete", callback_data=f"complete_{rid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rejectW_{rid}")
        )

        bot.send_message(
            m.chat.id,
            f"💰 {req.get('amount')} USDT\n👤 {req.get('user_id')}\n📱 {req.get('method')}\n🏦 {req.get('address')}",
            reply_markup=kb
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith(("complete_", "rejectW_")))
def handle_withdraw_admin(c):
    if c.from_user.id not in ADMIN_IDS:
        return bot.answer_callback_query(c.id, "⛔ Unauthorized")

    action, rid = c.data.split("_", 1)
    req_ref = db.reference(f"withdraw_requests/{rid}")
    req = req_ref.get()

    if not req:
        return bot.answer_callback_query(c.id, "Not found")

    uid = str(req["user_id"])

    if action == "complete":
        req_ref.update({"status": "completed"})
        bot.send_message(int(uid), f"✅ Withdraw {req['amount']} USDT completed.")

    else:
        db.reference(f"users/{uid}").transaction(
            lambda curr: update_balance_transaction(curr, float(req['amount']), None, "balance")
        )
        req_ref.update({"status": "rejected"})
        bot.send_message(int(uid), "❌ Withdraw rejected.")

    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)


# ================= STATS =================
@bot.message_handler(func=lambda m: m.text == "📊 Stats" and m.from_user.id in ADMIN_IDS)
def show_stats(m):
    users = db.reference("users").get() or {}
    all_subs = db.reference("submissions").get() or {}

    pending = sum(
        1 for s in all_subs.values()
        if str(s.get("status", "")).strip().lower() == "pending"
    )

    bot.send_message(
        m.chat.id,
        f"📊 Users: {len(users)}\n📧 Submissions: {len(all_subs)}\n⏳ Pending: {pending}"
    )


# ================= SETTINGS =================

@bot.message_handler(func=lambda m: m.text == "⚙️ Settings" and m.from_user.id in ADMIN_IDS)
def settings_menu(m):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💰 Rate", "💸 Min Withdraw")
    kb.row("💱 Conversion", "🎁 Referral Bonus")
    kb.row("🔙 Back", "❌ Cancel")

    bot.send_message(m.chat.id, "⚙️ Settings Panel:", reply_markup=kb)


# ================= BACK =================
@bot.message_handler(func=lambda m: m.text == "🔙 Back" and m.from_user.id in ADMIN_IDS)
def settings_back(m):
    admin_state.pop(m.from_user.id, None)
    admin_panel(m)


# ================= SELECT SETTING =================
@bot.message_handler(func=lambda m: m.text in ["💰 Rate", "💸 Min Withdraw", "💱 Conversion", "🎁 Referral Bonus"] and m.from_user.id in ADMIN_IDS)
def settings_input(m):
    mapping = {
        "💰 Rate": "gmail_rate",
        "💸 Min Withdraw": "min_withdraw",
        "💱 Conversion": "usdt_to_bdt",
        "🎁 Referral Bonus": "referral_bonus"
    }

    key = mapping.get(m.text)

    admin_state[m.from_user.id] = {
        "mode": "settings",
        "key": key,
        "label": m.text
    }

    bot.send_message(m.chat.id, f"✏️ Enter new value for {m.text}:")


# ================= SAVE SETTINGS =================
@bot.message_handler(func=lambda m: m.from_user.id in admin_state)
def save_settings(m):
    state = admin_state.get(m.from_user.id)

    # Cancel handling
    if m.text == "❌ Cancel":
        admin_state.pop(m.from_user.id, None)
        return admin_panel(m)

    # Ignore other modes (like broadcast)
    if not isinstance(state, dict) or state.get("mode") != "settings":
        return

    try:
        val = float(m.text)
        key = state["key"]

        db.reference(f"settings/{key}").set(val)

        bot.send_message(
            m.chat.id,
            f"✅ {state['label']} updated to {val}"
        )

        admin_state.pop(m.from_user.id, None)

    except:
        bot.send_message(m.chat.id, "❌ Invalid input. Send a valid number.")

# ================= BROADCAST =================
@bot.message_handler(func=lambda m: m.text == "📢 Broadcast" and m.from_user.id in ADMIN_IDS)
def broadcast_start(m):
    admin_state[m.from_user.id] = "broadcast"
    bot.send_message(m.chat.id, "📢 Send message (or ❌ Cancel):")


@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id) == "broadcast")
def broadcast_send(m):
    if m.text == "❌ Cancel":
        admin_state.pop(m.from_user.id, None)
        return admin_panel(m)

    users = db.reference("users").get() or {}
    user_ids = list(users.keys()) if isinstance(users, dict) else users

    total = len(user_ids)
    success = 0
    failed = 0

    bot.send_message(m.chat.id, f"🚀 Broadcasting to {total} users...")

    for uid in user_ids:
        try:
            bot.send_message(int(uid), m.text)
            success += 1
            time.sleep(0.04)
        except Exception as e:
            failed += 1
            print(f"❌ {uid}: {e}")

    bot.send_message(
        m.chat.id,
        f"✅ Done!\n\n👥 Total: {total}\n✅ Sent: {success}\n❌ Failed: {failed}"
    )

    admin_state.pop(m.from_user.id, None)

# ================= USERS CONTROL WITH PAGINATION =================
USERS_PER_PAGE = 10  # page এ কতজন user দেখানো হবে

@bot.message_handler(func=lambda m: m.text == "👥 Users" and m.from_user.id in ADMIN_IDS)
def show_users_page(m, page=1):
    users = db.reference("users").get() or {}
    if not users:
        return bot.send_message(m.chat.id, "📭 No users found.")

    user_ids = list(users.keys())
    total_pages = (len(user_ids) + USERS_PER_PAGE - 1) // USERS_PER_PAGE

    start = (page - 1) * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = user_ids[start:end]

    for uid in page_users:
        user = users[uid]
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("💰 Balance", callback_data=f"user_balance_{uid}"),
            InlineKeyboardButton("📧 Submissions", callback_data=f"user_subs_{uid}")
        )
        kb.add(
            InlineKeyboardButton("🔒 Block", callback_data=f"user_block_{uid}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"user_delete_{uid}")
        )
        bot.send_message(
            m.chat.id,
            f"👤 User ID: {uid}\n💰 Balance: {user.get('balance', 0)} USDT\n🏦 Total Earned: {user.get('total_earned', 0)} USDT",
            reply_markup=kb
        )

    # Pagination buttons
    kb_nav = InlineKeyboardMarkup()
    if page > 1:
        kb_nav.add(InlineKeyboardButton("⬅ Previous", callback_data=f"user_page_{page-1}"))
    if page < total_pages:
        kb_nav.add(InlineKeyboardButton("Next ➡", callback_data=f"user_page_{page+1}"))

    bot.send_message(m.chat.id, f"Page {page}/{total_pages}", reply_markup=kb_nav)


# ================= USERS CALLBACK WITH ACTIONS =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("user_"))
def handle_user_actions(c):
    if c.from_user.id not in ADMIN_IDS:
        return bot.answer_callback_query(c.id, "⛔ Unauthorized", show_alert=True)

    parts = c.data.split("_")
    action = parts[1]

    # Pagination handling
    if action == "page":
        page = int(parts[2])
        show_users_page(c.message, page)
        bot.answer_callback_query(c.id)
        bot.delete_message(c.message.chat.id, c.message.message_id)
        return

    uid = parts[2]
    user_ref = db.reference(f"users/{uid}")
    user = user_ref.get()
    if not user:
        return bot.answer_callback_query(c.id, "❌ User not found")

    if action == "balance":
        bot.send_message(
            c.message.chat.id,
            f"👤 User ID: {uid}\n💰 Balance: {user.get('balance', 0)} USDT\n🏦 Total Earned: {user.get('total_earned', 0)} USDT"
        )

    elif action == "subs":
        subs = db.reference(f"user_submissions/{uid}").get() or {}
        msg = f"📧 Submissions for User {uid}:\n\n"
        for sid, s in subs.items():
            msg += f"{sid}: {s.get('status', 'unknown')}\n"
        bot.send_message(c.message.chat.id, msg or "No submissions found.")

    elif action == "block":
        user_ref.update({"blocked": True})
        bot.send_message(c.message.chat.id, f"🔒 User {uid} blocked.")
        try:
            bot.send_message(int(uid), "⛔ Your account has been blocked by admin.")
        except: pass

    elif action == "delete":
        db.reference(f"users/{uid}").delete()
        db.reference(f"user_submissions/{uid}").delete()
        bot.send_message(c.message.chat.id, f"🗑 User {uid} deleted.")
        try:
            bot.send_message(int(uid), "🗑 Your account has been deleted by admin.")
        except: pass

    bot.answer_callback_query(c.id)
# ================= EXIT ADMIN =================

@bot.message_handler(func=lambda m: m.text == "🔙 Exit Admin" and m.from_user.id in ADMIN_IDS)
def exit_admin(m):
    admin_state.pop(m.from_user.id, None)
    main_menu(m.chat.id)
    bot.send_message(m.chat.id, "✅ Exited admin panel.")



print(f"@{BOT_USERNAME} is running...")
bot.infinity_polling()