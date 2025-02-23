import time
import logging
import random
from queue import Queue
from threading import Thread
from datetime import datetime, timedelta
import pytz
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

# Bot Configuration
API_ID = "25270711"
API_HASH = "6bf18f3d9519a2de12ac1e2e0f5c383e"
BOT_TOKEN = "7140092976:AAEf5sPBIoyJxvs8hLM0xYm1jS-uhJOwlGY"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Client("OTT_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Message queue for rate limiting
message_queue = Queue()

def message_sender():
    while True:
        client, message, text, reply_markup = message_queue.get()
        try:
            client.send_message(message.chat.id, text, reply_markup=reply_markup)
            logger.info(f"Message sent to {message.chat.id}")
        except FloodWait as e:
            logger.warning(f"FloodWait: Waiting {e.value} seconds")
            time.sleep(e.value)
            message_queue.put((client, message, text, reply_markup))
        message_queue.task_done()

# Start the message sender thread
Thread(target=message_sender, daemon=True).start()

def get_dynamic_slot_dates():
    """Returns formatted slot dates based on current IST time."""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    # If before 9 AM, use yesterday as slot start
    slot_start = now if now.hour >= 9 else now - timedelta(days=1)
    slot_end = slot_start + timedelta(days=1)
    return slot_start.strftime('%d %b').upper(), slot_end.strftime('%d %b').upper()

# Fixed GIFs for each action
fixed_gifs = {
    "book_slot": "https://c.tenor.com/CGFmiEU2y6IAAAAd/tenor.gif",
    "confirm_slot": "https://c.tenor.com/axC5ZW9zuWwAAAAd/tenor.gif",
    "approve_txn": "https://c.tenor.com/1x-CIsvU514AAAAd/tenor.gif",
     "reject_txn": "https://c.tenor.com/5hbWq-11J2UAAAAC/tenor.gif"
}

def send_gif(client, chat_id, action):
    """Send a fixed GIF before the action."""
    gif_url = fixed_gifs.get(action)
    if gif_url:
        client.send_animation(chat_id=chat_id, animation=gif_url)

def handle_action_with_gif(client, callback_query, action, action_func):
    """
    Send a fixed GIF corresponding to 'action', wait 4 seconds,
    then execute the action function.
    """
    send_gif(client, callback_query.message.chat.id, action)
    time.sleep(4)  # Delay before executing the actual function
    action_func(client, callback_query)


# Bot Handlers

@app.on_message(filters.command("start"))
def start(client, message):
    try:
        logger.info(f"New user started: {message.from_user.id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("᪤ Crunchyroll", callback_data="crunchyroll")],
            [InlineKeyboardButton("🆘 Help", callback_data="help")]
        ])
        message_queue.put((client, message, "🎟 𝙒𝙚𝙡𝙘𝙤𝙢𝙚! 𝘊𝘩𝘰𝘰𝘴𝘦 𝘢𝘯 𝘰𝘱𝘵𝘪𝘰𝘯:", keyboard))
    except Exception as e:
        logger.error(f"Start handler error: {e}")

@app.on_callback_query(filters.regex("^crunchyroll$"))
def show_crunchyroll(client, callback_query):
    try:
        logger.info(f"Crunchyroll menu shown to {callback_query.from_user.id}")
        callback_query.message.reply_photo(
            photo="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT3aBcFnRy8tZ6wGVva-2jgHI49-7vBW3clkQ&usqp=CAU",
            caption="᪤ Crunchyroll Premium Access\n\nEnjoy unlimited ad‑free anime with premium features!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Book Slot Now", callback_data="book_slot")
            ]])
        )
        callback_query.answer()
    except FloodWait as e:
        logger.warning(f"FloodWait in crunchyroll: {e.value}")
        time.sleep(e.value)
        show_crunchyroll(client, callback_query)

@app.on_callback_query(filters.regex("^book_slot$"))
def book_slot(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        logger.info(f"Booking slot for user {user_id}")
        handle_action_with_gif(client, callback_query, "book_slot", book_slot_action)
        callback_query.answer()
    except FloodWait as e:
        logger.warning(f"FloodWait in book_slot: {e.value}")
        time.sleep(e.value)
        book_slot(client, callback_query)

def book_slot_action(client, callback_query):
    start_date, end_date = get_dynamic_slot_dates()
    callback_query.message.reply_photo(
        photo="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQzIBUyTTfDm3DppVyRayEef1xxvrc0e67fjA&usqp=CAU",
        caption="🗓️ 𝙎𝙡𝙤𝙩 𝘿𝙚𝙩𝙖𝙞𝙡𝙨:\n\n"
                "• 24‑hour access to premium content\n"
                "• Ad‑free streaming experience\n"
                "• HD quality available\n\n"
                "𝘚𝘦𝘭𝘦𝘤𝘵 𝘺𝘰𝘶𝘳 𝘴𝘭𝘰𝘵 𝘵𝘪𝘮𝘪𝘯𝘨:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"9 AM {start_date} - 9 AM {end_date}", callback_data="confirm_slot")
        ]])
    )

@app.on_callback_query(filters.regex("^confirm_slot$"))
def confirm_slot(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        logger.info(f"Slot confirmed by {user_id}")
        handle_action_with_gif(client, callback_query, "confirm_slot", confirm_slot_action)
    except FloodWait as e:
        logger.warning(f"FloodWait in confirm_slot: {e.value}")
        time.sleep(e.value)
        confirm_slot(client, callback_query)
    except Exception as e:
        logger.error(f"Error confirming slot: {e}")
        callback_query.answer()

def confirm_slot_action(client, callback_query):
    callback_query.message.reply_photo(
        photo="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRiFG5UuMZcJV8DftO6dr0_evCFnpw-KeQiFwZuWPCQw50P0iJgU_-dap4&s=10",
        caption="💸 𝘊𝘩𝘰𝘰𝘴𝘦 𝘗𝘢𝘺𝘮𝘦𝘯𝘵 𝘔𝘦𝘵𝘩𝘰𝘥:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("PhonePe", callback_data="phonepe")]
        ])
    )

@app.on_callback_query(filters.regex("^phonepe$"))
def show_phonepe(client, callback_query):
    try:
        logger.info(f"PhonePe payment shown to {callback_query.from_user.id}")
        show_phonepe_action(client, callback_query)
    except FloodWait as e:
        logger.warning(f"FloodWait in phonepe: {e.value}")
        time.sleep(e.value)
        show_phonepe(client, callback_query)

def show_phonepe_action(client, callback_query):
    callback_query.message.reply_photo(
        photo="https://docs.lightburnsoftware.com/legacy/img/QRCode/ExampleCode.png",
        caption="📱 𝙋𝙝𝙤𝙣𝙚𝙋𝙚 𝙋𝙖𝙮𝙢𝙚𝙣𝙩™\n\n"
                "1. 𝘖𝘱𝘦𝘯 𝘗𝘩𝘰𝘯𝘦𝘗𝘦\n"
                "2. 𝘚𝘤𝘢𝘯 𝘵𝘩𝘪𝘴 𝘘𝘙 𝘤𝘰𝘥𝘦\n"
                "3. 𝘗𝘢𝘺 ₹12\n"
                "4. 𝘌𝘯𝘵𝘦𝘳 𝘛𝘳𝘢𝘯𝘴𝘢𝘤𝘵𝘪𝘰𝘯 𝘐𝘋 (eg. T2502221005526250746836"
    )
    callback_query.message.reply_text("📌 𝙋𝙡𝙚𝙖𝙨𝙚 𝙚𝙣𝙩𝙚𝙧 𝙮𝙤𝙪𝙧 𝙏𝙧𝙖𝙣𝙨𝙖𝙘𝙩𝙞𝙤𝙣 𝙄𝘿\n𝙖𝙛𝙩𝙚𝙧 𝙥𝙖𝙮𝙢𝙚𝙣𝙩.")
    
    
@app.on_message(filters.text & ~filters.command("start"))
def validate_txn(client, message):
    try:
        user_id = message.from_user.id
        txn_id = message.text.strip()
        logger.info(f"Validating transaction for user {user_id} with txn_id {txn_id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
        ])
        message_queue.put((client, message, f"🔍 Transaction `{txn_id}` pending approval.", keyboard))
    except FloodWait as e:
        logger.warning(f"FloodWait in validate_txn: {e.value}")
        time.sleep(e.value)
        validate_txn(client, message)

@app.on_callback_query(filters.regex(r"^approve_\d+$"))
def approve_txn(client, callback_query):
    try:
        user_id = int(callback_query.data.split("_")[1])
        logger.info(f"Approving transaction for {user_id}")
        handle_action_with_gif(client, callback_query, "approve_txn", approve_txn_action)
    except Exception as e:
        logger.error(f"Error approving transaction: {e}")
        callback_query.answer()

def approve_txn_action(client, callback_query):
    email, password = "user1234", "pass456"
    callback_query.message.reply_text(
        f"𝙋𝙖𝙮𝙢𝙚𝙣𝙩 𝙎𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨 🎉\n\n"
        f"🔐 𝘓𝘰𝘨𝘪𝘯 𝘸𝘪𝘵𝘩 𝘺𝘰𝘶𝘳 𝘌𝘮𝘢𝘪𝘭 & 𝘗𝘢𝘴𝘴𝘸𝘰𝘳𝘥\n\n"
        f"➤ `{email}`\n"
        f"➤ `{password}`\n\n(𝐓𝐚𝐩 𝐭𝐨 𝐂𝐨𝐩𝐲)™"
    )

@app.on_callback_query(filters.regex(r"^reject_\d+$"))
def reject_txn(client, callback_query):
    try:
        user_id = int(callback_query.data.split("_")[1])
        logger.info(f"Rejecting transaction for {user_id}")
        send_gif(client, callback_query.message.chat.id, "reject_txn")
        time.sleep(2)  # Wait 2 seconds before sending the rejection message
        reject_txn_action(client, callback_query)
    except Exception as e:
        logger.error(f"Reject error: {e}")

def reject_txn_action(client, callback_query):
    callback_query.message.reply_text("❌ 𝙏𝙧𝙖𝙣𝙨𝙖𝙘𝙩𝙞𝙤𝙣 𝙍𝙚𝙟𝙚𝙘𝙩𝙚𝙙.")
    callback_query.answer()

if __name__ == "__main__":
    logger.info("Starting bot...")
    app.run()