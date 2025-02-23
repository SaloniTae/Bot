import time
import logging
import os
from queue import Queue
from threading import Thread
from datetime import datetime, timedelta
import pytz
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

# ================== CONFIGURATION ==================
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")


# Debug: Print environment variables
print("\n=== ENV VARIABLE CHECK ===")
print(f"API_ID exists: {'API_ID' in os.environ}")
print(f"API_HASH exists: {'API_HASH' in os.environ}")
print(f"BOT_TOKEN exists: {'BOT_TOKEN' in os.environ}\n")
# Validate environment variables
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise EnvironmentError(
        "Missing Telegram credentials! Set API_ID, API_HASH, BOT_TOKEN in environment variables."
    )

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram client
app = Client(
    "OTT_Bot",
    api_id=int(API_ID),  # Convert API_ID to integer
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ... [REST OF YOUR CODE REMAINS UNCHANGED] ...


# Message queue for rate limiting (stores function + args + kwargs)
message_queue = Queue()

def message_sender():
    """Process messages from queue with FloodWait handling"""
    while True:
        task = message_queue.get()
        try:
            func, args, kwargs = task
            func(*args, **kwargs)
            logger.info(f"Message sent via {func.__name__}")
        except FloodWait as e:
            logger.warning(f"FloodWait: Waiting {e.value} seconds")
            time.sleep(e.value)
            message_queue.put(task)  # Requeue the task
        message_queue.task_done()

# Start message sender thread
Thread(target=message_sender, daemon=True).start()

def get_dynamic_slot_dates():
    """Returns formatted slot dates based on current IST time"""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    slot_start = now if now.hour >= 9 else now - timedelta(days=1)
    slot_end = slot_start + timedelta(days=1)
    return slot_start.strftime('%d %b').upper(), slot_end.strftime('%d %b').upper()

fixed_gifs = {
    "book_slot": "https://c.tenor.com/CGFmiEU2y6IAAAAd/tenor.gif",
    "confirm_slot": "https://c.tenor.com/axC5ZW9zuWwAAAAd/tenor.gif",
    "approve_txn": "https://c.tenor.com/1x-CIsvU514AAAAd/tenor.gif",
    "reject_txn": "https://c.tenor.com/5hbWq-11J2UAAAAC/tenor.gif"
}

def handle_action_with_gif(client, callback_query, action, action_func):
    """Handle GIF + delayed action through queue"""
    # Send GIF through queue
    message_queue.put((
        client.send_animation,
        [callback_query.message.chat.id],
        {'animation': fixed_gifs[action]}
    ))
    
    # Queue delayed action after 4 seconds
    def queue_delayed_action():
        message_queue.put((action_func, (client, callback_query), {}))
    
    Timer(4.0, queue_delayed_action).start()

# ================= HANDLERS =================
@app.on_message(filters.command("start"))
def start(client, message):
    try:
        logger.info(f"New user: {message.from_user.id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("᪤ Crunchyroll", callback_data="crunchyroll")],
            [InlineKeyboardButton("🆘 Help", callback_data="help")]
        ])
        message_queue.put((
            client.send_message,
            [message.chat.id],
            {'text': "🎟 �𝙒𝙚𝙡𝙘𝙤𝙢𝙚! 𝘊𝘩𝘰𝘰𝘴𝘦 𝘢𝘯 𝘰𝘱𝘵𝘪𝘰𝘯:", 'reply_markup': keyboard}
        ))
    except Exception as e:
        logger.error(f"Start error: {e}")

@app.on_callback_query(filters.regex("^crunchyroll$"))
def show_crunchyroll(client, callback_query):
    try:
        logger.info(f"Crunchyroll menu: {callback_query.from_user.id}")
        message_queue.put((
            client.send_photo,
            [callback_query.message.chat.id],
            {
                'photo': "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT3aBcFnRy8tZ6wGVva-2jgHI49-7vBW3clkQ&usqp=CAU",
                'caption': "᪤ Crunchyroll Premium Access\n\nEnjoy unlimited ad‑free anime with premium features!",
                'reply_markup': InlineKeyboardMarkup([[InlineKeyboardButton("Book Slot Now", callback_data="book_slot")]])
            }
        ))
        callback_query.answer()
    except Exception as e:
        logger.error(f"Crunchyroll error: {e}")

@app.on_callback_query(filters.regex("^book_slot$"))
def book_slot(client, callback_query):
    try:
        logger.info(f"Book slot: {callback_query.from_user.id}")
        handle_action_with_gif(client, callback_query, "book_slot", book_slot_action)
        callback_query.answer()
    except Exception as e:
        logger.error(f"Book slot error: {e}")

def book_slot_action(client, callback_query):
    start_date, end_date = get_dynamic_slot_dates()
    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            'photo': "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQzIBUyTTfDm3DppVyRayEef1xxvrc0e67fjA&usqp=CAU",
            'caption': f"🗓️ 𝙎𝙡𝙤𝙩 𝘿𝙚𝙩𝙖𝙞𝙡𝙨:\n\n• 24‑hour access\n• Ad‑free streaming\n• HD quality\n\nSlot: 9 AM {start_date} - 9 AM {end_date}",
            'reply_markup': InlineKeyboardMarkup([[InlineKeyboardButton("Confirm Slot", callback_data="confirm_slot")]])
        }
    ))

@app.on_callback_query(filters.regex("^confirm_slot$"))
def confirm_slot(client, callback_query):
    try:
        logger.info(f"Confirm slot: {callback_query.from_user.id}")
        handle_action_with_gif(client, callback_query, "confirm_slot", confirm_slot_action)
        callback_query.answer()
    except Exception as e:
        logger.error(f"Confirm slot error: {e}")

def confirm_slot_action(client, callback_query):
    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            'photo': "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRiFG5UuMZcJV8DftO6dr0_evCFnpw-KeQiFwZuWPCQw50P0iJgU_-dap4&s=10",
            'caption': "💸 �𝘊𝘩𝘰𝘰𝘴𝘦 �𝘗𝘢𝘺𝘮𝘦𝘯𝘵 �𝘔𝘦𝘵𝘩𝘰𝘥:",
            'reply_markup': InlineKeyboardMarkup([[InlineKeyboardButton("PhonePe", callback_data="phonepe")]])
        }
    ))

@app.on_callback_query(filters.regex("^phonepe$"))
def show_phonepe(client, callback_query):
    try:
        logger.info(f"PhonePe: {callback_query.from_user.id}")
        message_queue.put((
            client.send_photo,
            [callback_query.message.chat.id],
            {
                'photo': "https://docs.lightburnsoftware.com/legacy/img/QRCode/ExampleCode.png",
                'caption': "📱 �𝙋𝙝𝙤𝙣𝙚𝙋𝙚 �𝙋𝙖𝙮𝙢𝙚𝙣𝙩™\n\n1. Open PhonePe\n2. Scan QR\n3. Pay ₹12\n4. Enter Transaction ID"
            }
        ))
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {'text': "📌 �𝙋𝙡𝙚𝙖𝙨𝙚 �𝙚𝙣𝙩𝙚𝙧 �𝙮𝙤𝙪𝙧 𝙏𝙧𝙖𝙣𝙨𝙖𝙘𝙩𝙞𝙤𝙣 𝙄𝘿"}
        ))
        callback_query.answer()
    except Exception as e:
        logger.error(f"PhonePe error: {e}")

@app.on_message(filters.text & ~filters.command("start"))
def validate_txn(client, message):
    try:
        txn_id = message.text.strip()
        logger.info(f"Validate TXN: {message.from_user.id} - {txn_id}")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{message.from_user.id}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{message.from_user.id}")]
        ])
        message_queue.put((
            client.send_message,
            [message.chat.id],
            {'text': f"🔍 Transaction {txn_id} pending approval.", 'reply_markup': markup}
        ))
    except Exception as e:
        logger.error(f"Validate TXN error: {e}")

@app.on_callback_query(filters.regex(r"^approve_\d+$"))
def approve_txn(client, callback_query):
    try:
        user_id = int(callback_query.data.split("_")[1])
        logger.info(f"Approve TXN: {user_id}")
        message_queue.put((
            client.send_animation,
            [callback_query.message.chat.id],
            {'animation': fixed_gifs["approve_txn"]}
        ))
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {'text': "𝙋𝙖𝙮𝙢𝙚𝙣𝙩 𝙎𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡! 🔐\nEmail: user1234\nPassword: pass456"}
        ))
        callback_query.answer()
    except Exception as e:
        logger.error(f"Approve error: {e}")

@app.on_callback_query(filters.regex(r"^reject_\d+$"))
def reject_txn(client, callback_query):
    try:
        user_id = int(callback_query.data.split("_")[1])
        logger.info(f"Reject TXN: {user_id}")
        message_queue.put((
            client.send_animation,
            [callback_query.message.chat.id],
            {'animation': fixed_gifs["reject_txn"]}
        ))
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {'text': "❌ 𝙏𝙧𝙖𝙣𝙨𝙖𝙘𝙩𝙞𝙤𝙣 𝙍𝙚𝙟𝙚𝙘𝙩𝙚𝙙."}
        ))
        callback_query.answer()
    except Exception as e:
        logger.error(f"Reject error: {e}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    app.run()
