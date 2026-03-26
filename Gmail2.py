import os
import time
import json
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
import firebase_admin
from firebase_admin import credentials, db

# ================= CONFIG =================
BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ADMIN_BOT_TOKEN environment variable not set")

FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://post-c7e41-default-rtdb.firebaseio.com")
DEFAULT_PASSWORD = "12457"
SESSION_TIMEOUT = 3600
ITEMS_PER_PAGE = 5

# ================= BOT =================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================= FIREBASE INIT =================
def init_firebase():
    firebase_cred_json = os.getenv("serviceAccountKey.json")
    if firebase_cred_json:
        try:
            cred_dict = json.loads(firebase_cred_json)
            cred = credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid FIREBASE_CRED_JSON format: {e}")
            raise
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})
    print("✅ Firebase initialized")

init_firebase()

# ================= SESSION MANAGEMENT =================
authenticated_users = {}

def is_authenticated(user_id):
    if user_id not in authenticated_users:
        return False
    if time.time() - authenticated_users[user_id] > SESSION_TIMEOUT:
        authenticated_users.pop(user_id, None)
        return False
    return True

def authenticate(user_id):
    authenticated_users[user_id] = time.time()

def require_auth(func):
    def wrapper(message):
        if not is_authenticated(message.from_user.id):
            bot.reply_to(message, "🔐 Please send /start and enter password first.")
            return
        return func(message)
    return wrapper

# ================= PASSWORD MANAGEMENT =================
def get_admin_password():
    pwd = db.reference("settings/admin_password").get()
    return pwd if pwd else DEFAULT_PASSWORD

def set_admin_password(new_password):
    db.reference("settings/admin_password").set(new_password)

# ================= HELPERS =================
def update_balance_transaction(current, amount, earned_field=None, total_field=None):
    if current is None:
        return
    current["balance"] = current.get("balance", 0.0) + amount
    if earned_field:
        current[earned_field] = current.get(earned_field, 0.0) + amount
    if total_field:
        current[total_field] = current.get(total_field, 0.0) + amount
    return current

def safe_firebase_operation(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"Firebase error: {e}")
        return None

def paginate_items(items_dict, page):
    items = list(items_dict.items())
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    return items[start:end]

# ================= ADMIN MENU =================
def admin_menu(chat_id):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📥 Pending Gmail", "💸 Pending Withdraw")
    kb.row("⚙️ Set Gmail Rate", "🎁 Set Referral Bonus")
    kb.row("💰 Set Min Withdraw", "🔑 Change Password")
    kb.row("🔑 Logout")
    bot.send_message(chat_id, "🛠 Admin Panel", reply_markup=kb)

# ================= AUTHENTICATION FLOW =================
@bot.message_handler(commands=["start"])
def start_auth(message):
    if is_authenticated(message.from_user.id):
        admin_menu(message.chat.id)
        return
    msg = bot.reply_to(message, "🔐 Enter admin password:")
    bot.register_next_step_handler(msg, check_password)

def check_password(message):
    if message.text.strip() == get_admin_password():
        authenticate(message.from_user.id)
        bot.send_message(message.chat.id, "✅ Authentication successful!")
        admin_menu(message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Wrong password. Use /start to try again.")

@bot.message_handler(func=lambda m: m.text == "🔑 Logout")
@require_auth
def logout(message):
    authenticated_users.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "🔒 Logged out. Use /start to login.", reply_markup=ReplyKeyboardRemove())

# ================= CHANGE PASSWORD =================
@bot.message_handler(func=lambda m: m.text == "🔑 Change Password")
@require_auth
def change_password_start(message):
    msg = bot.send_message(message.chat.id, "✏️ Send new password (min 4 chars):")
    bot.register_next_step_handler(msg, change_password_set)

def change_password_set(message):
    new_pwd = message.text.strip()
    if len(new_pwd) < 4:
        bot.send_message(message.chat.id, "❌ Password too short. Try again.")
        return
    set_admin_password(new_pwd)
    bot.send_message(message.chat.id, f"✅ Password changed to: `{new_pwd}`\nPlease login again.", parse_mode="Markdown")
    authenticated_users.pop(message.from_user.id, None)

# ================= PENDING GMAIL (USER GROUP) =================
@bot.message_handler(func=lambda m: m.text == "📥 Pending Gmail")
@require_auth
def btn_pending_gmail(m):
    send_user_list_page(m.chat.id, 0)

def send_user_list_page(chat_id, page):
    subs = safe_firebase_operation(db.reference("submissions").get)
    if not subs:
        bot.send_message(chat_id, "📭 No pending submissions.")
        return
    pending = {sid: s for sid, s in subs.items() if s.get("status") == "pending"}
    if not pending:
        bot.send_message(chat_id, "📭 No pending submissions.")
        return

    users = {}
    for sid, s in pending.items():
        uid = s.get("user_id")
        users.setdefault(uid, []).append((sid, s))
    user_items = list(users.items())

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for uid, subs_list in user_items[start:end]:
        name = subs_list[0][1].get("name", "Unknown")
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(name, callback_data=f"showg_{uid}_0"))
        bot.send_message(chat_id, f"👤 {name}", reply_markup=kb)

    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"userp_{page-1}"))
    if end < len(user_items):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"userp_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(chat_id, f"📄 Page {page+1}", reply_markup=kb_page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("userp_"))
def user_list_pagination(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    page = int(call.data.split("_")[1])
    send_user_list_page(call.message.chat.id, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("showg_"))
def show_user_gmails(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    _, uid, page = call.data.split("_")
    page = int(page)
    subs = safe_firebase_operation(db.reference("submissions").get)
    if not subs:
        bot.answer_callback_query(call.id, "No data")
        return
    user_pending = [(sid, s) for sid, s in subs.items() if s.get("status") == "pending" and str(s.get("user_id")) == uid]
    if not user_pending:
        bot.answer_callback_query(call.id, "No pending Gmail for this user")
        return

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for sid, s in user_pending[start:end]:
        text = (
            f"📩 Gmail Submission\n\n"
            f"📧 {s.get('gmail')}\n🔑 {s.get('password')}\n📨 Recovery: {s.get('recovery')}\n"
            f"👤 {s.get('name', 'N/A')}\n🆔 {s.get('user_id')}"
        )
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"ga_{sid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"gr_{sid}")
        )
        bot.send_message(call.message.chat.id, text, reply_markup=kb)

    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"showg_{uid}_{page-1}"))
    if end < len(user_pending):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"showg_{uid}_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(call.message.chat.id, f"📄 Page {page+1}", reply_markup=kb_page)

# ================= GMAIL APPROVE / REJECT =================
@bot.callback_query_handler(func=lambda call: call.data.startswith(("ga_", "gr_")))
def handle_gmail_approval(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    action, sid = call.data.split("_")
    sub_ref = db.reference(f"submissions/{sid}")
    sub = sub_ref.get()
    if not sub or sub.get("status") != "pending":
        bot.answer_callback_query(call.id, "Already processed")
        return
    user_id = sub["user_id"]
    if action == "ga":
        rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15
        db.reference(f"users/{user_id}").transaction(lambda cur: update_balance_transaction(cur, rate, "balance", "total_earned"))
        sub_ref.update({"status": "approved"})
        bot.answer_callback_query(call.id, "✅ Approved")
        try:
            bot.send_message(user_id, f"✅ Your Gmail approved! +{rate} USDT added.")
        except:
            pass
    else:
        sub_ref.update({"status": "rejected"})
        bot.answer_callback_query(call.id, "❌ Rejected")
        try:
            bot.send_message(user_id, "❌ Your Gmail was rejected.")
        except:
            pass
    # Update user history
    db.reference(f"user_submissions/{user_id}/{sid}").set({
        "gmail": sub.get("gmail"),
        "password": sub.get("password"),
        "recovery": sub.get("recovery"),
        "status": sub_ref.get().get("status"),
        "timestamp": sub.get("timestamp", time.time())
    })
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass

# ================= PENDING WITHDRAW =================
@bot.message_handler(func=lambda m: m.text == "💸 Pending Withdraw")
@require_auth
def btn_pending_withdraw(m):
    send_withdraw_page(m.chat.id, 0)

def send_withdraw_page(chat_id, page):
    reqs = safe_firebase_operation(db.reference("withdraw_requests").order_by_child("status").equal_to("pending").get)
    if not reqs:
        bot.send_message(chat_id, "📭 No pending withdraw requests.")
        return
    items = paginate_items(reqs, page)
    for rid, req in items:
        text = (
            f"💸 Withdraw Request\n"
            f"User: {req.get('user_id')}\n"
            f"Amount: {req.get('amount')} USDT\n"
            f"Method: {req.get('method')}\n"
            f"Address: {req.get('address')}"
        )
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"wa_{rid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wr_{rid}")
        )
        bot.send_message(chat_id, text, reply_markup=kb)
    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"wp_{page-1}"))
    if (page+1)*ITEMS_PER_PAGE < len(reqs):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"wp_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(chat_id, f"📄 Page {page+1}", reply_markup=kb_page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("wp_"))
def withdraw_pagination(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    page = int(call.data.split("_")[1])
    send_withdraw_page(call.message.chat.id, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("wa_", "wr_")))
def handle_withdraw(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    action, rid = call.data.split("_")
    req_ref = db.reference(f"withdraw_requests/{rid}")
    req = req_ref.get()
    if not req or req.get("status") != "pending":
        bot.answer_callback_query(call.id, "Already processed")
        return
    user_id = req["user_id"]
    if action == "wa":
        req_ref.update({"status": "completed"})
        bot.answer_callback_query(call.id, "✅ Completed")
        try:
            bot.send_message(user_id, f"✅ Withdraw of {req['amount']} USDT completed.")
        except:
            pass
    else:
        # refund
        db.reference(f"users/{user_id}").transaction(lambda cur: update_balance_transaction(cur, req['amount'], None, None))
        req_ref.update({"status": "rejected"})
        bot.answer_callback_query(call.id, "❌ Rejected (balance refunded)")
        try:
            bot.send_message(user_id, f"❌ Withdraw rejected. {req['amount']} USDT refunded.")
        except:
            pass
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass

# ================= SETTINGS =================
settings_state = {}
@bot.message_handler(func=lambda m: m.text in ["⚙️ Set Gmail Rate", "🎁 Set Referral Bonus", "💰 Set Min Withdraw"])
@require_auth
def btn_settings(m):
    if m.text == "⚙️ Set Gmail Rate":
        settings_state[m.from_user.id] = "rate"
        bot.send_message(m.chat.id, "✏️ New Gmail rate (e.g., 0.15):")
    elif m.text == "🎁 Set Referral Bonus":
        settings_state[m.from_user.id] = "ref"
        bot.send_message(m.chat.id, "✏️ New referral bonus (e.g., 0.05):")
    else:
        settings_state[m.from_user.id] = "min"
        bot.send_message(m.chat.id, "✏️ New minimum withdraw (e.g., 2.0):")

@bot.message_handler(func=lambda m: m.from_user.id in settings_state)
def set_value(m):
    state = settings_state.pop(m.from_user.id)
    try:
        val = float(m.text)
        if state == "rate":
            db.reference("settings/gmail_rate").set(val)
            bot.send_message(m.chat.id, f"✅ Gmail rate set to {val} USDT")
        elif state == "ref":
            db.reference("settings/referral_bonus").set(val)
            bot.send_message(m.chat.id, f"✅ Referral bonus set to {val} USDT")
        elif state == "min":
            db.reference("settings/min_withdraw").set(val)
            bot.send_message(m.chat.id, f"✅ Min withdraw set to {val} USDT")
    except:
        bot.send_message(m.chat.id, "❌ Invalid number. Try again.")

# ================= RUN =================
if __name__ == "__main__":
    print("Admin bot running...")
    bot.infinity_polling()        return
    msg = bot.reply_to(message, "🔐 Enter admin password:")
    bot.register_next_step_handler(msg, check_password)

def check_password(message):
    if message.text.strip() == get_admin_password():
        authenticate(message.from_user.id)
        bot.send_message(message.chat.id, "✅ Authentication successful!")
        admin_menu(message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Wrong password. Use /start to try again.")

@bot.message_handler(func=lambda m: m.text == "🔑 Logout")
@require_auth
def logout(message):
    authenticated_users.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "🔒 Logged out. Use /start to login.", reply_markup=ReplyKeyboardRemove())

# ================= CHANGE PASSWORD =================
@bot.message_handler(func=lambda m: m.text == "🔑 Change Password")
@require_auth
def change_password_start(message):
    msg = bot.send_message(message.chat.id, "✏️ Send new password (min 4 chars):")
    bot.register_next_step_handler(msg, change_password_set)

def change_password_set(message):
    new_pwd = message.text.strip()
    if len(new_pwd) < 4:
        bot.send_message(message.chat.id, "❌ Password too short. Try again.")
        return
    set_admin_password(new_pwd)
    bot.send_message(message.chat.id, f"✅ Password changed to: `{new_pwd}`\nPlease login again.", parse_mode="Markdown")
    authenticated_users.pop(message.from_user.id, None)

# ================= PENDING GMAIL (USER GROUP) =================
@bot.message_handler(func=lambda m: m.text == "📥 Pending Gmail")
@require_auth
def btn_pending_gmail(m):
    send_user_list_page(m.chat.id, 0)

def send_user_list_page(chat_id, page):
    subs = safe_firebase_operation(db.reference("submissions").get)
    if not subs:
        bot.send_message(chat_id, "📭 No pending submissions.")
        return
    pending = {sid: s for sid, s in subs.items() if s.get("status") == "pending"}
    if not pending:
        bot.send_message(chat_id, "📭 No pending submissions.")
        return

    users = {}
    for sid, s in pending.items():
        uid = s.get("user_id")
        users.setdefault(uid, []).append((sid, s))
    user_items = list(users.items())

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for uid, subs_list in user_items[start:end]:
        name = subs_list[0][1].get("name", "Unknown")
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(name, callback_data=f"showg_{uid}_0"))
        bot.send_message(chat_id, f"👤 {name}", reply_markup=kb)

    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"userp_{page-1}"))
    if end < len(user_items):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"userp_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(chat_id, f"📄 Page {page+1}", reply_markup=kb_page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("userp_"))
def user_list_pagination(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    page = int(call.data.split("_")[1])
    send_user_list_page(call.message.chat.id, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("showg_"))
def show_user_gmails(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    _, uid, page = call.data.split("_")
    page = int(page)
    subs = safe_firebase_operation(db.reference("submissions").get)
    if not subs:
        bot.answer_callback_query(call.id, "No data")
        return
    user_pending = [(sid, s) for sid, s in subs.items() if s.get("status") == "pending" and str(s.get("user_id")) == uid]
    if not user_pending:
        bot.answer_callback_query(call.id, "No pending Gmail for this user")
        return

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for sid, s in user_pending[start:end]:
        text = (
            f"📩 Gmail Submission\n\n"
            f"📧 {s.get('gmail')}\n🔑 {s.get('password')}\n📨 Recovery: {s.get('recovery')}\n"
            f"👤 {s.get('name', 'N/A')}\n🆔 {s.get('user_id')}"
        )
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"ga_{sid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"gr_{sid}")
        )
        bot.send_message(call.message.chat.id, text, reply_markup=kb)

    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"showg_{uid}_{page-1}"))
    if end < len(user_pending):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"showg_{uid}_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(call.message.chat.id, f"📄 Page {page+1}", reply_markup=kb_page)

# ================= GMAIL APPROVE / REJECT =================
@bot.callback_query_handler(func=lambda call: call.data.startswith(("ga_", "gr_")))
def handle_gmail_approval(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    action, sid = call.data.split("_")
    sub_ref = db.reference(f"submissions/{sid}")
    sub = sub_ref.get()
    if not sub or sub.get("status") != "pending":
        bot.answer_callback_query(call.id, "Already processed")
        return
    user_id = sub["user_id"]
    if action == "ga":
        rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15
        db.reference(f"users/{user_id}").transaction(lambda cur: update_balance_transaction(cur, rate, "balance", "total_earned"))
        sub_ref.update({"status": "approved"})
        bot.answer_callback_query(call.id, "✅ Approved")
        try:
            bot.send_message(user_id, f"✅ Your Gmail approved! +{rate} USDT added.")
        except:
            pass
    else:
        sub_ref.update({"status": "rejected"})
        bot.answer_callback_query(call.id, "❌ Rejected")
        try:
            bot.send_message(user_id, "❌ Your Gmail was rejected.")
        except:
            pass
    # Update user history
    db.reference(f"user_submissions/{user_id}/{sid}").set({
        "gmail": sub.get("gmail"),
        "password": sub.get("password"),
        "recovery": sub.get("recovery"),
        "status": sub_ref.get().get("status"),
        "timestamp": sub.get("timestamp", time.time())
    })
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass

# ================= PENDING WITHDRAW =================
@bot.message_handler(func=lambda m: m.text == "💸 Pending Withdraw")
@require_auth
def btn_pending_withdraw(m):
    send_withdraw_page(m.chat.id, 0)

def send_withdraw_page(chat_id, page):
    reqs = safe_firebase_operation(db.reference("withdraw_requests").order_by_child("status").equal_to("pending").get)
    if not reqs:
        bot.send_message(chat_id, "📭 No pending withdraw requests.")
        return
    items = paginate_items(reqs, page)
    for rid, req in items:
        text = (
            f"💸 Withdraw Request\n"
            f"User: {req.get('user_id')}\n"
            f"Amount: {req.get('amount')} USDT\n"
            f"Method: {req.get('method')}\n"
            f"Address: {req.get('address')}"
        )
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"wa_{rid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wr_{rid}")
        )
        bot.send_message(chat_id, text, reply_markup=kb)
    kb_page = InlineKeyboardMarkup()
    if page > 0:
        kb_page.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"wp_{page-1}"))
    if (page+1)*ITEMS_PER_PAGE < len(reqs):
        kb_page.add(InlineKeyboardButton("➡️ Next", callback_data=f"wp_{page+1}"))
    if kb_page.keyboard:
        bot.send_message(chat_id, f"📄 Page {page+1}", reply_markup=kb_page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("wp_"))
def withdraw_pagination(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    page = int(call.data.split("_")[1])
    send_withdraw_page(call.message.chat.id, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("wa_", "wr_")))
def handle_withdraw(call):
    if not is_authenticated(call.from_user.id):
        bot.answer_callback_query(call.id, "Login required")
        return
    action, rid = call.data.split("_")
    req_ref = db.reference(f"withdraw_requests/{rid}")
    req = req_ref.get()
    if not req or req.get("status") != "pending":
        bot.answer_callback_query(call.id, "Already processed")
        return
    user_id = req["user_id"]
    if action == "wa":
        req_ref.update({"status": "completed"})
        bot.answer_callback_query(call.id, "✅ Completed")
        try:
            bot.send_message(user_id, f"✅ Withdraw of {req['amount']} USDT completed.")
        except:
            pass
    else:
        # refund
        db.reference(f"users/{user_id}").transaction(lambda cur: update_balance_transaction(cur, req['amount'], None, None))
        req_ref.update({"status": "rejected"})
        bot.answer_callback_query(call.id, "❌ Rejected (balance refunded)")
        try:
            bot.send_message(user_id, f"❌ Withdraw rejected. {req['amount']} USDT refunded.")
        except:
            pass
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass

# ================= SETTINGS =================
settings_state = {}
@bot.message_handler(func=lambda m: m.text in ["⚙️ Set Gmail Rate", "🎁 Set Referral Bonus", "💰 Set Min Withdraw"])
@require_auth
def btn_settings(m):
    if m.text == "⚙️ Set Gmail Rate":
        settings_state[m.from_user.id] = "rate"
        bot.send_message(m.chat.id, "✏️ New Gmail rate (e.g., 0.15):")
    elif m.text == "🎁 Set Referral Bonus":
        settings_state[m.from_user.id] = "ref"
        bot.send_message(m.chat.id, "✏️ New referral bonus (e.g., 0.05):")
    else:
        settings_state[m.from_user.id] = "min"
        bot.send_message(m.chat.id, "✏️ New minimum withdraw (e.g., 2.0):")

@bot.message_handler(func=lambda m: m.from_user.id in settings_state)
def set_value(m):
    state = settings_state.pop(m.from_user.id)
    try:
        val = float(m.text)
        if state == "rate":
            db.reference("settings/gmail_rate").set(val)
            bot.send_message(m.chat.id, f"✅ Gmail rate set to {val} USDT")
        elif state == "ref":
            db.reference("settings/referral_bonus").set(val)
            bot.send_message(m.chat.id, f"✅ Referral bonus set to {val} USDT")
        elif state == "min":
            db.reference("settings/min_withdraw").set(val)
            bot.send_message(m.chat.id, f"✅ Min withdraw set to {val} USDT")
    except:
        bot.send_message(m.chat.id, "❌ Invalid number. Try again.")

# ================= RUN =================
if __name__ == "__main__":
    print("Admin bot running...")
    bot.infinity_polling()    user_id = str(message.from_user.id)
    args = message.text.split()
    ref_by = args[1] if len(args) > 1 else None

    # ভ্যালিড রেফারার চেক
    if ref_by and ref_by != user_id:
        ref_user = safe_firebase_operation(db.reference(f"users/{ref_by}").get)
        if not ref_user:
            ref_by = None  # ইনভ্যালিড রেফারার ইগনোর

    user_ref = db.reference(f"users/{user_id}")
    if not user_ref.get():
        user_ref.set({
            "name": message.from_user.first_name,
            "balance": 0.0,
            "total_earned": 0.0,
            "referral_earned": 0.0,
            "referred_by": ref_by,
            "referrals": 0
        })

        if ref_by and ref_by != user_id:
            # রেফারার রেফারেল কাউন্ট বাড়াও
            rref = db.reference(f"users/{ref_by}")
            rref.transaction(lambda current: update_referral_count_transaction(current))
            # রেফারেল বোনাস যোগ করো
            add_referral_bonus(ref_by)

    if not is_joined(message.from_user.id):
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("📣 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}"),
            InlineKeyboardButton("✅ Join & Verify", callback_data="verify")
        )
        bot.send_message(
            message.chat.id,
            "👋 Welcome!\n\nPlease join channel first.",
            reply_markup=kb
        )
    else:
        main_menu(message.chat.id)

def update_referral_count_transaction(current):
    if current is None:
        return
    current["referrals"] = current.get("referrals", 0) + 1
    return current

@bot.callback_query_handler(func=lambda c: c.data == "verify")
def verify(c):
    if is_joined(c.from_user.id):
        bot.edit_message_text(
            "✅ Verified successfully!",
            c.message.chat.id,
            c.message.message_id
        )
        main_menu(c.message.chat.id)
    else:
        bot.answer_callback_query(c.id, "❌ Join channel first", show_alert=True)

# ================= SUBMIT MY OWN =================
@bot.message_handler(func=lambda m: m.text == "✏️ Submit my own")
def submit_menu(m):
    rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📩 Submit Gmail", "📋 View Requirements")
    kb.row("❌ Cancel")

    bot.send_message(
        m.chat.id,
        f"✏️ Submit Your Own Gmail\n\n"
        f"💰 Rate: {rate} USDT per Gmail\n"
        f"⏳ Approval: 24–48h",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "📋 View Requirements")
def view_req(m):
    rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15
    bot.send_message(
        m.chat.id,
        "📋 Requirements\n\n"
        "✅ Gmail 30+ days old\n"
        "✅ Recovery email set\n"
        "✅ Password unchanged\n"
        f"💰 Rate: {rate} USDT"
    )

@bot.message_handler(func=lambda m: m.text == "📩 Submit Gmail")
def start_submit(m):
    submit_state[m.from_user.id] = {
        "step": 1,
        "data": {},
        "timestamp": int(time.time())
    }
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("❌ Cancel")
    bot.send_message(
        m.chat.id,
        "📩 Step 1/3\n\nSend Gmail address:",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: submit_state.get(m.from_user.id))
def submit_steps(m):
    uid = m.from_user.id
    state = submit_state[uid]

    # CANCEL
    if m.text in ["/cancel", "❌ Cancel"]:
        submit_state.pop(uid, None)
        bot.send_message(
            m.chat.id,
            "❌ Submission cancelled",
            reply_markup=ReplyKeyboardRemove()
        )
        main_menu(m.chat.id)
        return

    # BACK (শুধু স্টেপ ২ ও ৩ এর জন্য)
    if m.text == "🔙 Back":
        if state["step"] > 1:
            state["step"] -= 1
        else:
            state["step"] = 1
        # ফিরিয়ে দেওয়ার জন্য আগের ধাপের ইনপুট চাওয়া
        if state["step"] == 1:
            bot.send_message(m.chat.id, "📩 Step 1/3\n\nSend Gmail address:")
        elif state["step"] == 2:
            bot.send_message(m.chat.id, "📩 Step 2/3\n\nSend Password:")
        elif state["step"] == 3:
            bot.send_message(m.chat.id, "📩 Step 3/3\n\nSend Recovery Gmail:")
        return

    step = state["step"]
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔙 Back", "❌ Cancel")

    # STEP 1: GMAIL
    if step == 1:
        gmail = m.text.strip().lower()
        if not is_valid_gmail(gmail):
            bot.send_message(m.chat.id, "❌ Invalid Gmail format", reply_markup=kb)
            return
        if gmail_exists(gmail):
            bot.send_message(m.chat.id, "❌ This Gmail already submitted before!", reply_markup=kb)
            return
        state["data"]["gmail"] = gmail
        state["step"] = 2
        state["timestamp"] = int(time.time())
        bot.send_message(m.chat.id, "📩 Step 2/3\n\nSend Password:", reply_markup=kb)

    # STEP 2: PASSWORD
    elif step == 2:
        password = m.text.strip()
        if len(password) < 4:
            bot.send_message(m.chat.id, "❌ Password too short", reply_markup=kb)
            return
        state["data"]["password"] = password
        state["step"] = 3
        state["timestamp"] = int(time.time())
        bot.send_message(m.chat.id, "📩 Step 3/3\n\nSend Recovery Gmail:", reply_markup=kb)

    # STEP 3: RECOVERY
    elif step == 3:
        recovery = m.text.strip().lower()
        if not is_valid_gmail(recovery):
            bot.send_message(m.chat.id, "❌ Invalid Recovery Gmail", reply_markup=kb)
            return
        data = state["data"]
        submission_id = db.reference("submissions").push({
            "user_id": str(uid),
            "gmail": data["gmail"],
            "password": data["password"],
            "recovery": recovery,
            "status": "pending",
            "timestamp": int(time.time())
        }).key

        # ইউজারের নিজের হিস্ট্রি সংরক্ষণ
        db.reference(f"user_submissions/{uid}/{submission_id}").set({
            "gmail": data["gmail"],
            "password": data["password"],
            "recovery": recovery,
            "status": "pending",
            "timestamp": int(time.time())
        })

        # Gmail ইউজড মার্ক করুন
        mark_gmail_used(data["gmail"])

        submit_state.pop(uid, None)
        bot.send_message(
            m.chat.id,
            "✅ Submitted successfully!\n⏳ Waiting for approval",
            reply_markup=ReplyKeyboardRemove()
        )
        main_menu(m.chat.id)

# ================= BALANCE =================
@bot.message_handler(func=lambda m: m.text == "💰 Balance")
def balance(m):
    uref = db.reference(f"users/{m.from_user.id}")
    u = uref.get()
    if not u:
        bot.send_message(m.chat.id, "❌ Your account not found.\n\nPlease send /start first.")
        return

    balance_usdt = float(u.get("balance", 0.0))
    ref_earned_usdt = float(u.get("referral_earned", 0.0))
    total_usdt = float(u.get("total_earned", 0.0))
    usdt_to_bdt = safe_firebase_operation(db.reference("settings/usdt_to_bdt").get) or 115

    balance_bdt = balance_usdt * usdt_to_bdt
    ref_earned_bdt = ref_earned_usdt * usdt_to_bdt
    total_bdt = total_usdt * usdt_to_bdt

    txt = (
        f"💰 Balance\n\n"
        f"Balance: {balance_usdt:.2f} USDT | {balance_bdt:.2f} BDT\n"
        f"Referral Earned: {ref_earned_usdt:.2f} USDT | {ref_earned_bdt:.2f} BDT\n"
        f"Total Earned: {total_usdt:.2f} USDT | {total_bdt:.2f} BDT"
    )
    bot.send_message(m.chat.id, txt)

# ================= REFERRAL =================
@bot.message_handler(func=lambda m: m.text == "📣 Share Referral Link")
def ref_link(m):
    bot.send_message(
        m.chat.id,
        f"📣 Your Referral Link\n\n"
        f"https://t.me/{BOT_USERNAME}?start={m.from_user.id}"
    )

@bot.message_handler(func=lambda m: m.text == "🏆 Top Referrals")
def top_refs(m):
    users = safe_firebase_operation(db.reference("users").get)
    if not users or not isinstance(users, dict):
        bot.send_message(m.chat.id, "❌ No referral data found")
        return

    clean_users = []
    for uid, u in users.items():
        if not isinstance(u, dict):
            continue
        referrals = u.get("referrals", 0)
        try:
            referrals = int(referrals)
        except:
            referrals = 0
        clean_users.append({
            "name": u.get("name", "Unknown"),
            "referrals": referrals
        })

    if not clean_users:
        bot.send_message(m.chat.id, "❌ No referral data found")
        return

    top = sorted(clean_users, key=lambda x: x["referrals"], reverse=True)[:10]
    txt = "🏆 Top Referrals\n\n"
    for i, u in enumerate(top, 1):
        txt += f"{i}. {u['name']} – {u['referrals']} referrals\n"
    bot.send_message(m.chat.id, txt)

# ================= WITHDRAW =================
@bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def withdraw(m):
    user_id = m.from_user.id
    uref = db.reference(f"users/{user_id}")
    u = uref.get()
    if not u:
        bot.send_message(m.chat.id, "❌ Account not found.\nSend /start first.")
        return

    minw = safe_firebase_operation(db.reference("settings/min_withdraw").get) or 2.0
    try:
        minw = float(minw)
    except:
        minw = 2.0

    balance = float(u.get("balance", 0))
    if balance < minw:
        bot.send_message(
            m.chat.id,
            f"❌ Minimum withdraw {minw} USDT\nYour balance: {balance:.2f} USDT"
        )
        return

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📱 Bkash"), KeyboardButton("📱 Nagad"), KeyboardButton("💰 Binance"))
    kb.row("❌ Cancel")
    bot.send_message(m.chat.id, "💸 Select Withdraw Method:", reply_markup=kb)
    withdraw_state[user_id] = "choose_method"

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "choose_method")
def select_withdraw_method(m):
    user_id = m.from_user.id
    if m.text in ["❌ Cancel", "/cancel"]:
        withdraw_state.pop(user_id, None)
        bot.send_message(m.chat.id, "❌ Withdraw cancelled", reply_markup=ReplyKeyboardRemove())
        main_menu(m.chat.id)
        return
    if m.text not in ["📱 Bkash", "📱 Nagad", "💰 Binance"]:
        bot.send_message(m.chat.id, "❌ Please select a valid method")
        return
    withdraw_method[user_id] = m.text
    withdraw_state[user_id] = "enter_amount"
    bot.send_message(m.chat.id, f"✅ Method selected: {m.text}\n\nSend the amount you want to withdraw:", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "enter_amount")
def enter_withdraw_amount(m):
    user_id = m.from_user.id
    if m.text in ["❌ Cancel", "/cancel"]:
        withdraw_state.pop(user_id, None)
        withdraw_method.pop(user_id, None)
        bot.send_message(m.chat.id, "❌ Withdraw cancelled")
        main_menu(m.chat.id)
        return
    try:
        amount = float(m.text)
    except:
        bot.send_message(m.chat.id, "❌ Invalid amount")
        return
    if amount <= 0:
        bot.send_message(m.chat.id, "❌ Amount must be greater than 0")
        return

    uref = db.reference(f"users/{user_id}")
    u = uref.get()
    balance = float(u.get("balance", 0))
    minw = safe_firebase_operation(db.reference("settings/min_withdraw").get) or 2.0
    try:
        minw = float(minw)
    except:
        minw = 2.0

    if amount < minw:
        bot.send_message(m.chat.id, f"❌ Minimum withdraw is {minw} USDT")
        return
    if amount > balance:
        bot.send_message(m.chat.id, f"❌ Insufficient balance\nYour balance: {balance:.2f} USDT")
        return

    withdraw_amount[user_id] = amount
    withdraw_state[user_id] = "enter_address"
    method = withdraw_method[user_id]
    input_type = "phone number" if method in ["📱 Bkash", "📱 Nagad"] else "wallet address"
    bot.send_message(m.chat.id, f"✅ Amount received: {amount} USDT\n\nNow send your {input_type}:", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: withdraw_state.get(m.from_user.id) == "enter_address")
def enter_withdraw_address(m):
    user_id = m.from_user.id
    if m.text in ["/cancel", "❌ Cancel"]:
        withdraw_state.pop(user_id, None)
        withdraw_method.pop(user_id, None)
        withdraw_amount.pop(user_id, None)
        bot.send_message(m.chat.id, "❌ Withdraw cancelled")
        main_menu(m.chat.id)
        return

    address = m.text.strip()
    method = withdraw_method[user_id]
    if method in ["📱 Bkash", "📱 Nagad"]:
        if not address.isdigit() or len(address) < 10:
            bot.send_message(m.chat.id, "❌ Invalid phone number")
            return
    else:
        if len(address) < 10:
            bot.send_message(m.chat.id, "❌ Invalid wallet address")
            return

    amount = withdraw_amount[user_id]

    # ট্রানজেকশনালি ব্যালেন্স ডিডাক্ট ও রিকোয়েস্ট সেভ
    def transaction(current):
        if current is None:
            return
        bal = current.get("balance", 0.0)
        if bal >= amount:
            current["balance"] = bal - amount
            return current
        else:
            # ব্যালেন্স কমে গেলে ট্রানজেকশন ব্যর্থ
            raise Exception("Insufficient balance")

    user_ref = db.reference(f"users/{user_id}")
    try:
        result = user_ref.transaction(transaction)
        if result is None:
            bot.send_message(m.chat.id, "❌ Insufficient balance. Please try again.")
            return
        # রিকোয়েস্ট সেভ
        db.reference("withdraw_requests").push({
            "user_id": str(user_id),
            "amount": amount,
            "address": address,
            "method": method,
            "status": "pending",
            "time": int(time.time())
        })
        # স্টেট ক্লিয়ার
        withdraw_state.pop(user_id, None)
        withdraw_method.pop(user_id, None)
        withdraw_amount.pop(user_id, None)
        bot.send_message(m.chat.id, "✅ Withdraw request submitted!\n⏳ Processing time: 24–48 hours")
        main_menu(m.chat.id)
    except Exception as e:
        bot.send_message(m.chat.id, "❌ Transaction failed. Please try again.")
        print(f"Withdraw transaction error: {e}")

# ================= MY GMAIL HISTORY =================
@bot.message_handler(func=lambda m: m.text == "📄 My History")
def history(m):
    send_gmail_history_page(m.chat.id, m.from_user.id, 0)

def send_gmail_history_page(chat_id, user_id, page):
    user_id = str(user_id)
    try:
        ref = db.reference(f"user_submissions/{user_id}").get()
    except Exception as e:
        bot.send_message(chat_id, f"❌ History লোড করতে ব্যর্থ: {e}")
        return

    if not ref or not isinstance(ref, dict):
        bot.send_message(chat_id, "📄 আপনার কোনো Gmail submission history পাওয়া যায়নি")
        return

    # latest first
    subs_list = sorted(ref.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)
    total = len(subs_list)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = subs_list[start:end]

    txt = "📄 আপনার Gmail Submission History\n\n"
    for sid, s in page_items:
        gmail = s.get("gmail", "N/A")
        password = s.get("password", "N/A")
        recovery = s.get("recovery", "N/A")
        status = s.get("status", "pending")
        timestamp = s.get("timestamp", 0)
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

        if status == "approved":
            s_text = "🟢 Approved"
        elif status == "rejected":
            s_text = "❌ Rejected"
        else:
            s_text = "⏳ Pending"

        txt += (
            f"📧 Gmail: {gmail}\n"
            f"🔑 Password: {password}\n"
            f"📨 Recovery: {recovery}\n"
            f"📄 Status: {s_text}\n"
            f"🕒 Created At: {created_at}\n\n"
        )

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    txt += f"Page {page+1}/{total_pages}"
    kb = InlineKeyboardMarkup()
    if page > 0:
        kb.add(InlineKeyboardButton("⬅ Prev", callback_data=f"gmail_{page-1}"))
    if end < total:
        kb.add(InlineKeyboardButton("Next ➡", callback_data=f"gmail_{page+1}"))
    bot.send_message(chat_id, txt, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gmail_"))
def gmail_history_nav(c):
    page = int(c.data.split("_")[1])
    send_gmail_history_page(c.message.chat.id, c.from_user.id, page)

# ================= ADMIN FUNCTIONS (অতিরিক্ত) =================
# অ্যাডমিন আইডি নির্ধারণ করুন (একাধিক)
ADMIN_IDS = [7864372570]  # আপনার টেলিগ্রাম আইডি দিন

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if m.from_user.id not in ADMIN_IDS:
        return
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📥 Pending Submissions", "💸 Pending Withdraws")
    kb.row("📊 Stats", "🔙 Back to User Menu")
    bot.send_message(m.chat.id, "🛠 Admin Panel", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "📥 Pending Submissions" and m.from_user.id in ADMIN_IDS)
def pending_subs(m):
    submissions = safe_firebase_operation(db.reference("submissions").order_by_child("status").equal_to("pending").get)
    if not submissions:
        bot.send_message(m.chat.id, "📭 No pending submissions.")
        return
    # প্রথম ১০টা দেখান (পেজিনেশন দরকার হলে বাড়ানো যাবে)
    for sid, sub in list(submissions.items())[:10]:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Approve", callback_data=f"approve_{sid}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"reject_{sid}"))
        bot.send_message(
            m.chat.id,
            f"📧 Gmail: {sub.get('gmail')}\n👤 User: {sub.get('user_id')}\n🔑 Pass: {sub.get('password')}\n📨 Recovery: {sub.get('recovery')}",
            reply_markup=kb
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_") or c.data.startswith("reject_"))
def handle_approval(c):
    if c.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(c.id, "⛔ Unauthorized", show_alert=True)
        return
    parts = c.data.split("_")
    action = parts[0]
    sid = parts[1]
    sub = safe_firebase_operation(db.reference(f"submissions/{sid}").get)
    if not sub:
        bot.answer_callback_query(c.id, "Submission not found")
        return

    user_id = sub["user_id"]
    if action == "approve":
        # স্টেটাস আপডেট
        db.reference(f"submissions/{sid}/status").set("approved")
        db.reference(f"user_submissions/{user_id}/{sid}/status").set("approved")
        # রেট অনুযায়ী ব্যালেন্স যোগ
        rate = safe_firebase_operation(db.reference("settings/gmail_rate").get) or 0.15
        user_ref = db.reference(f"users/{user_id}")
        user_ref.transaction(lambda current: update_balance_transaction(current, rate, "balance", "total_earned"))
        bot.send_message(user_id, f"✅ Your Gmail submission has been approved! +{rate} USDT added.")
        bot.answer_callback_query(c.id, "Approved")
    else:  # reject
        db.reference(f"submissions/{sid}/status").set("rejected")
        db.reference(f"user_submissions/{user_id}/{sid}/status").set("rejected")
        bot.send_message(user_id, "❌ Your Gmail submission was rejected.")
        bot.answer_callback_query(c.id, "Rejected")
    # মেসেজ এডিট করে ডিলিট করা যায়
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)

@bot.message_handler(func=lambda m: m.text == "💸 Pending Withdraws" and m.from_user.id in ADMIN_IDS)
def pending_withdraws(m):
    reqs = safe_firebase_operation(db.reference("withdraw_requests").order_by_child("status").equal_to("pending").get)
    if not reqs:
        bot.send_message(m.chat.id, "📭 No pending withdraw requests.")
        return
    for rid, req in list(reqs.items())[:10]:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Complete", callback_data=f"complete_{rid}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw_{rid}"))
        bot.send_message(
            m.chat.id,
            f"💰 Amount: {req.get('amount')} USDT\n👤 User: {req.get('user_id')}\n📱 Method: {req.get('method')}\n🏦 Address: {req.get('address')}",
            reply_markup=kb
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("complete_") or c.data.startswith("reject_withdraw_"))
def handle_withdraw(c):
    if c.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(c.id, "⛔ Unauthorized", show_alert=True)
        return
    parts = c.data.split("_")
    action = parts[0]
    rid = parts[1] if action == "complete" else parts[2]  # reject_withdraw_{rid}
    req_ref = db.reference(f"withdraw_requests/{rid}")
    req = req_ref.get()
    if not req:
        bot.answer_callback_query(c.id, "Request not found")
        return
    if action == "complete":
        req_ref.update({"status": "completed"})
        bot.send_message(req["user_id"], f"✅ Your withdraw request of {req['amount']} USDT has been completed.")
        bot.answer_callback_query(c.id, "Completed")
    else:
        # রিজেক্ট করলে ব্যালেন্স ফেরত
        user_ref = db.reference(f"users/{req['user_id']}")
        user_ref.transaction(lambda current: update_balance_transaction(current, req['amount'], "balance", None))
        req_ref.update({"status": "rejected"})
        bot.send_message(req["user_id"], f"❌ Your withdraw request of {req['amount']} USDT was rejected.")
        bot.answer_callback_query(c.id, "Rejected")
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)

@bot.message_handler(func=lambda m: m.text == "📊 Stats" and m.from_user.id in ADMIN_IDS)
def stats(m):
    users = safe_firebase_operation(db.reference("users").get) or {}
    submissions = safe_firebase_operation(db.reference("submissions").get) or {}
    total_users = len(users)
    pending_subs = sum(1 for s in submissions.values() if s.get("status") == "pending")
    approved_subs = sum(1 for s in submissions.values() if s.get("status") == "approved")
    total_withdraws = sum(1 for _ in (safe_firebase_operation(db.reference("withdraw_requests").get) or {}).values())
    txt = f"📊 Bot Statistics\n\n👥 Total Users: {total_users}\n📝 Pending Submissions: {pending_subs}\n✅ Approved Submissions: {approved_subs}\n💰 Withdraw Requests: {total_withdraws}"
    bot.send_message(m.chat.id, txt)

@bot.message_handler(func=lambda m: m.text == "🔙 Back to User Menu" and m.from_user.id in ADMIN_IDS)
def back_to_user(m):
    main_menu(m.chat.id)

# ================= HELP =================
@bot.message_handler(func=lambda m: m.text == "📌 Help")
def help_cmd(m):
    txt = (
        "📌 Help\n\n"
        "✏️ Submit my own – Submit Gmail accounts\n"
        "💰 Balance – Check your balance\n"
        "💸 Withdraw – Request withdrawal\n"
        "📄 My History – View your submissions\n"
        "📣 Share Referral Link – Get referral link\n"
        "🏆 Top Referrals – Leaderboard\n"
        "📌 Help – This message\n\n"
        "If you face any issues, contact admin."
    )
    bot.send_message(m.chat.id, txt)

# ================= RUN =================
if __name__ == "__main__":
    print("Bot running...")
    bot.infinity_polling()
