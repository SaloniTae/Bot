import time
import logging
from queue import Queue
from threading import Thread, Timer
from datetime import datetime, timedelta
import pytz
import requests
import json

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

# --------------------- Bot Configuration ---------------------
API_ID = "27708983"
API_HASH = "d0c88b417406f93aa913ecb5f1b58ba6"
BOT_TOKEN = "7642832201:AAGP6ij38eEy9pIaAFTAsehUP_j2jl9Knx0"


# --------------------- PROXY CONFIG ---------------------
PROXY_URL = "https://update-slot-service.onrender.com"  # your proxy
SECRET_TOKEN = "e971197a2f10afe00b826ae6982be6118c525cb1c2905808a0cbf6bafd4eb8cfd114d90724bbbcd6a932f783524eaa75bd3d2db2a81a65f8d64a4ffa23f237ed252ff46959dbb4a8441b8675b2c800d1074ae7398b5eeb897fd0fd74054b5bcf1a9e9f45d4a3c8436677e37fc8e0258f311a83cb85f5922ab03b4f35161b365159ee967bc38f7138153060d850a60224e9a6f72fc946158baf47c1a6b13876ba06fd061680a2941dffc7ec9d618a8e757e182ac223a1bba4062c10f66cacdba1b2363ed1a6d87494bf6f3e86cea82b6205e39ce863e3542204bb327e374c8a301e3941ae0a7efefd68df197b80e80f52463ba6d436d917e892115ea326eaa6ac8902c569e7d611d6e430080b7d826466f647ee06f9d25c75b0d3c6787fa246cdb6d45cce7197b90f4d33f04a3f9917db4b2b451271467317b69cac9170024625"

def read_data_via_proxy():
    headers = {"X-Secret": SECRET_TOKEN}
    try:
        resp = requests.get(f"{PROXY_URL}/getData", headers=headers)
        if resp.status_code == 200:
            return resp.json() or {}
        else:
            logging.error(f"Proxy read error: {resp.text}")
            return {}
    except Exception as e:
        logging.error(f"read_data_via_proxy exception: {e}")
        return {}

def write_data_via_proxy(data):
    headers = {"X-Secret": SECRET_TOKEN}
    try:
        resp = requests.post(f"{PROXY_URL}/setData", json=data, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            logging.error(f"Proxy write error: {resp.text}")
            return {}
    except Exception as e:
        logging.error(f"write_data_via_proxy exception: {e}")
        return {}

def get_ui_config(section):
    db_data = read_data_via_proxy()
    ui_config = db_data.get("ui_config", {})
    return ui_config.get(section, {})

def is_credential(node):
    """
    We require belongs_to_slot so each credential is assigned to a slot.
    """
    if not isinstance(node, dict):
        return False
    required = [
        "email","password","expiry_date",
        "locked","usage_count","max_usage",
        "belongs_to_slot"
    ]
    return all(r in node for r in required)

# Store each user's chosen slot in memory:
user_slot_choice = {}  # e.g. { user_id: "slot_1" }

# --------------------- Logging Setup ---------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Client("MultiSlotBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --------------------- Message Queue Setup ---------------------
message_queue = Queue()
def message_sender():
    while True:
        task = message_queue.get()
        try:
            func, args, kwargs = task
            func(*args, **kwargs)
            logger.info(f"Message sent to {args[0] if args else 'unknown'}")
        except FloodWait as e:
            logger.warning(f"FloodWait: waiting {e.value} seconds")
            time.sleep(e.value)
            message_queue.put(task)
        finally:
            message_queue.task_done()

Thread(target=message_sender, daemon=True).start()

# --------------------- Updating usage / locked in DB ---------------------
def update_credential_usage(cred_key, new_usage):
    logger.info(f"Updating usage_count for {cred_key} => {new_usage}")
    db_data = read_data_via_proxy()
    if not db_data:
        return
    if cred_key not in db_data or not isinstance(db_data[cred_key], dict):
        return
    db_data[cred_key]["usage_count"] = new_usage
    write_data_via_proxy(db_data)

def update_credential_locked(cred_key, new_locked):
    logger.info(f"Updating locked for {cred_key} => {new_locked}")
    db_data = read_data_via_proxy()
    if not db_data:
        return
    if cred_key not in db_data or not isinstance(db_data[cred_key], dict):
        return
    db_data[cred_key]["locked"] = new_locked
    write_data_via_proxy(db_data)

# --------------------- Checking / Marking used ORDERIDs in DB ---------------------
def is_orderid_used(order_id):
    db_data = read_data_via_proxy()
    if not db_data:
        return False
    used_list = db_data.get("used_orderids", {})
    return str(order_id) in used_list

def mark_orderid_used(order_id):
    db_data = read_data_via_proxy()
    if not db_data:
        return
    used_list = db_data.get("used_orderids", {})
    if not isinstance(used_list, dict):
        used_list = {}
    used_list[str(order_id)] = True
    db_data["used_orderids"] = used_list
    write_data_via_proxy(db_data)

# --------------------- get_valid_credential_for_slot ---------------------
def get_valid_credential_for_slot(slot_id):
    """
    Return (cred_key, cred_data) for the first available credential
    that belongs_to_slot == slot_id, usage_count < max_usage,
    locked != 1, not expired, etc.

    If we find locked=1 but no actually valid => return (None, "locked").
    If none found => (None, None).
    """
    db_data = read_data_via_proxy()
    if not db_data:
        return None, None

    locked_found = False
    for key, node in db_data.items():
        if not is_credential(node):
            continue

        if node["belongs_to_slot"] != slot_id:
            continue  # skip if belongs to a different slot

        locked_val = int(node["locked"])
        if locked_val == 1:
            locked_found = True
            continue

        usage_count = int(node["usage_count"])
        max_usage   = int(node["max_usage"])
        expiry_str  = node["expiry_date"]
        try:
            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
        except ValueError:
            continue

        now = datetime.now()
        if usage_count < max_usage and expiry_dt > now:
            # Found a valid credential
            return key, node

    # If we found at least one locked => (None, "locked")
    if locked_found:
        return None, "locked"
    return None, None

def handle_action_with_gif(client, callback_query, gif_url, next_action):
    if gif_url:
        message_queue.put((
            client.send_animation,
            [callback_query.message.chat.id],
            {"animation": gif_url}
        ))
    def delayed():
        message_queue.put((next_action, (client, callback_query), {}))
    Timer(4.0, delayed).start()

# --------------------- Out-of-Stock Helper ---------------------
def handle_out_of_stock(client, callback_query):
    logger.info("No credentials => out_of_stock => user: %s", callback_query.from_user.id)
    ui = get_ui_config("out_of_stock")
    gif_url  = ui.get("gif_url","").replace("\\n","\n")
    messages = ui.get("messages", [])
    if not messages:
        messages = ["Out of stock!", "Please wait..."]

    message_queue.put((
        client.send_animation,
        [callback_query.message.chat.id],
        {"animation": gif_url}
    ))

    def send_line(i):
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {"text": messages[i]}
        ))
    for i in range(len(messages)):
        Timer(2.0*(i+1), send_line, args=[i]).start()

    callback_query.answer()
    

def check_paytm_server():
    """
    Returns True if Paytm server is up, False if it's unreachable/down. using return False above merchant_key
    We do a quick test call with a dummy TXN ID.
    """   
    merchant_key = "MomjnZ28167874166441" 
    test_txn_id  = "T2502251452242231926104" 
    url = f"https://api.projectoid.in/v2/ledger/paytm/?MERCHANT_KEY={merchant_key}&TRANSACTION={test_txn_id}"

    try:
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            logger.warning("Paytm server check => server returned status %s, treating as down", resp.status_code)
            return False

        data = resp.json()  # e.g. { "ok": true, "status_code": 200, ... }
        ok_val    = data.get("ok", False)
        code_val  = data.get("status_code", 0)
        if not ok_val or code_val != 200:
            logger.warning("Paytm server check => 'ok' or 'status_code' not good => server down.")
            return False

        # If we get here => server responded "ok":true and "status_code":200
        logger.info("Paytm server check => server is UP.")
        return True

    except Exception as e:
        logger.warning(f"Paytm server check => exception: {e}")
        return False
        
        
# --------------------- BOT Handlers ---------------------
@app.on_message(filters.command("start"))
def start_command(client, message):
    user_id = str(message.from_user.id)

    # 1) Read entire DB from proxy
    db_data = read_data_via_proxy()
    if not db_data:
        db_data = {}

    # 2) Grab or create "users" node
    users_node = db_data.get("users", {})
    if not isinstance(users_node, dict):
        users_node = {}

    # 3) Mark this user ID as True
    users_node[user_id] = True

    # 4) Put it back into db_data and write
    db_data["users"] = users_node
    write_data_via_proxy(db_data)

    ui = get_ui_config("start_command")
    welcome_text = ui.get("welcome_text", "🎟 Welcome!")
    welcome_text = welcome_text.replace("\\n", "\n")

    # Retrieve welcome photo URL from UI config.
    # If not present, try to retrieve it from the DB schema.
    photo_url = ui.get("photo_url")
    if not photo_url:
        # Schema: Retrieve the welcome photo from DB data if not provided in UI config.
        photo_url = db_data.get("welcome_photo", "https://a.storyblok.com/f/178900/1920x1080/a42c428a0d/68ad7538824e322544830e21fad540e41645653253_main.png/m/filters:quality(95)format(webp)")

    buttons = ui.get("buttons", [])
    if buttons:
        kb = []
        for b in buttons:
            txt = b.get("text", "Button").replace("\\n", "\n")
            cb  = b.get("callback_data", "no_callback")
            kb.append([InlineKeyboardButton(txt, callback_data=cb)])
    else:
        kb = [
            [InlineKeyboardButton("᪤ Crunchyroll", callback_data="crunchyroll")],
            [InlineKeyboardButton("🆘 Help", callback_data="help")]
        ]

    # Send the welcome message as a photo with caption and inline keyboard.
    message_queue.put((
        client.send_photo,
        [message.chat.id],
        {"photo": photo_url, "caption": welcome_text, "reply_markup": InlineKeyboardMarkup(kb)}
    ))

@app.on_callback_query(filters.regex("^help$"))
def help_callback(client, callback_query):
    # Fetch help text from the UI config for the help screen.
    ui = get_ui_config("help")
    help_text = ui.get("help_text", "Contact support @letmebeunknownn")
    help_text = help_text.replace("\\n", "\n")

    # Send a text message with help information.
    message_queue.put((
        client.send_message,
        [callback_query.message.chat.id],
        {"text": help_text}
    ))
    callback_query.answer()
    
    

@app.on_callback_query(filters.regex("^crunchyroll$"))
def show_crunchyroll(client, callback_query):
    # A) Check Paytm server first
    if not check_paytm_server():
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {
                "text": "🔻𝗣𝗮𝘆𝗺𝗲𝗻𝘁 𝘀𝗲𝗿𝘃𝗲𝗿 𝗶𝘀 𝘁𝗲𝗺𝗽𝗼𝗿𝗮𝗿𝗶𝗹𝘆 𝘂𝗻𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲\n\n"
            "• 𝘗𝘭𝘦𝘢𝘴𝘦 𝘵𝘳𝘺 𝘢𝘨𝘢𝘪𝘯 𝘭𝘢𝘵𝘦𝘳 🕑\n"
            "• 𝖶𝖾 𝖺𝗉𝗈𝗅𝗈𝗀𝗂𝗓𝖾 𝖿𝗈𝗋 𝖺𝗇𝗒 𝗂𝗇𝖼𝗈𝗇𝗏𝖾𝗇𝗂𝖾𝗇𝖼𝖾 🙁\n"
            "𝖡𝗎𝗒 𝗆𝖺𝗇𝗎𝖺𝗅𝗅𝗒 𝖿𝗋𝗈𝗆 𝗈𝗎𝗋 𝗌𝗎𝗉𝗉𝗈𝗋𝗍 @𝗅𝖾𝗍𝗆𝖾𝖻𝖾𝗎𝗇𝗄𝗇𝗈𝗐𝗇𝗇"
            }
        ))
        callback_query.answer()
        return  # STOP here

    # B) If server is up => normal flow
    ui = get_ui_config("crunchyroll_screen")
    photo_url   = ui.get("photo_url","")
    caption_raw = ui.get("caption","᪤ Crunchyroll Premium Access...")
    caption     = caption_raw.replace("\\n","\n")

    button_text = ui.get("button_text","Book Slot Now").replace("\\n","\n")
    cb_data     = ui.get("callback_data","book_slot")

    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            "photo": photo_url,
            "caption": caption,
            "reply_markup": InlineKeyboardMarkup([[
                InlineKeyboardButton(button_text, callback_data=cb_data)
            ]])
        }
    ))
    callback_query.answer()


@app.on_callback_query(filters.regex("^book_slot$"))
def book_slot_handler(client, callback_query):
    # A) Check again before letting them pick a slot
    if not check_paytm_server():
        message_queue.put((
            client.send_message,
            [callback_query.message.chat.id],
            {
                "text": "🔻𝗣𝗮𝘆𝗺𝗲𝗻𝘁 𝘀𝗲𝗿𝘃𝗲𝗿 𝗶𝘀 𝘁𝗲𝗺𝗽𝗼𝗿𝗮𝗿𝗶𝗹𝘆 𝘂𝗻𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲\n\n"
            "• 𝘗𝘭𝘦𝘢𝘴𝘦 𝘵𝘳𝘺 𝘢𝘨𝘢𝘪𝘯 𝘭𝘢𝘵𝘦𝘳 🕑\n"
            "• 𝖶𝖾 𝖺𝗉𝗈𝗅𝗈𝗀𝗂𝗓𝖾 𝖿𝗈𝗋 𝖺𝗇𝗒 𝗂𝗇𝖼𝗈𝗇𝗏𝖾𝗇𝗂𝖾𝗇𝖼𝖾 🙁"
            "𝖡𝗎𝗒 𝗆𝖺𝗇𝗎𝖺𝗅𝗅𝗒 𝖿𝗋𝗈𝗆 𝗈𝗎𝗋 𝗌𝗎𝗉𝗉𝗈𝗋𝗍 @𝗅𝖾𝗍𝗆𝖾𝖻𝖾𝗎𝗇𝗄𝗇𝗈𝗐𝗇𝗇"
            }
        ))
        callback_query.answer()
        return  # STOP

    # B) Normal flow
    ui = get_ui_config("slot_booking")
    gif_url = ui.get("gif_url","").replace("\\n","\n")
    handle_action_with_gif(client, callback_query, gif_url, book_slot_action)
    callback_query.answer()

def book_slot_action(client, callback_query):
    """
    Show multiple enabled slots from settings.slots.
    """
    db_data = read_data_via_proxy()
    settings = db_data.get("settings", {})
    all_slots = settings.get("slots", {})

    ui = get_ui_config("slot_booking")
    photo_url   = ui.get("photo_url","")
    caption_raw = ui.get("caption","🗓️ Slot Details ...")
    caption     = caption_raw.replace("\\n","\n")

    button_fmt  = ui.get("button_format","{start_label} - {end_label}")

    kb = []
    if isinstance(all_slots, dict):
        for slot_id, slot_info in all_slots.items():
            if not isinstance(slot_info, dict):
                continue
            if not slot_info.get("enabled", False):
                continue

            s_str = slot_info.get("slot_start","9999-12-31 09:00:00")
            e_str = slot_info.get("slot_end",  "9999-12-31 09:00:00")

            try:
                s_dt = datetime.strptime(s_str, "%Y-%m-%d %H:%M:%S")
            except:
                s_dt = datetime.now()
            try:
                e_dt = datetime.strptime(e_str, "%Y-%m-%d %H:%M:%S")
            except:
                e_dt = s_dt + timedelta(days=1)

            def fmt(dt):
                return dt.strftime("%-I %p %d %b").upper()
            start_label = fmt(s_dt)
            end_label   = fmt(e_dt)

            final_text = button_fmt.format(start_label=start_label, end_label=end_label)
            cb_data    = f"choose_slot_{slot_id}"

            kb.append([InlineKeyboardButton(final_text, callback_data=cb_data)])

    # If no multi-slot found or all disabled, fallback
    if not kb:
        # fallback single line
        final_text = button_fmt.format(start_label="9 AM 01 MAR", end_label="9 AM 02 MAR")
        cb_data    = ui.get("callback_data","confirm_slot")
        kb.append([InlineKeyboardButton(final_text, callback_data=cb_data)])

    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            "photo": photo_url,
            "caption": caption,
            "reply_markup": InlineKeyboardMarkup(kb)
        }
    ))

def show_locked_message(client, chat_id):
    """
    Reads a locked message from DB's ui_config.locked_flow.locked_text
    and sends it to user.
    """
    locked_ui = get_ui_config("locked_flow")  # or whatever key you choose
    locked_text_raw = locked_ui.get(
        "locked_text",
        "⚠️ No available credentials at the moment.\nPlease contact support."
    )
    locked_text = locked_text_raw.replace("\\n", "\n")
    
    message_queue.put((
        client.send_message,
        [chat_id],
        {"text": locked_text}
    ))

@app.on_callback_query(filters.regex("^choose_slot_"))
def choose_slot(client, callback_query):
    user_id = callback_query.from_user.id
    chosen_data = callback_query.data  # e.g. "choose_slot_slot_2"
    slot_id = chosen_data.replace("choose_slot_","")

    # Check if at least one valid credential is available
    cred_key, cred_data = get_valid_credential_for_slot(slot_id)
    if cred_data == "locked":
        # Instead of hard-coded text, fetch from DB
        show_locked_message(client, callback_query.message.chat.id)
        callback_query.answer()
        return

    if not cred_data:
        # No valid => out_of_stock
        handle_out_of_stock(client, callback_query)
        return

    # If we get here => at least one valid credential is available => store slot
    user_slot_choice[user_id] = slot_id
    logger.info(f"User {user_id} chose slot: {slot_id}")

    ui = get_ui_config("confirmation_flow")
    gif_url = ui.get("gif_url","").replace("\\n","\n")
    handle_action_with_gif(client, callback_query, gif_url, confirm_slot_action)
    callback_query.answer()

def confirm_slot_action(client, callback_query):
    ui = get_ui_config("confirmation_flow")
    photo_url   = ui.get("photo_url","")
    caption_raw = ui.get("caption","💸 Choose Payment Method:")
    caption     = caption_raw.replace("\\n","\n")

    btn_text = ui.get("button_text","PhonePe").replace("\\n","\n")
    cb_data  = ui.get("callback_data","phonepe")

    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            "photo": photo_url,
            "caption": caption,
            "reply_markup": InlineKeyboardMarkup([[
                InlineKeyboardButton(btn_text, callback_data=cb_data)
            ]])
        }
    ))

@app.on_callback_query(filters.regex("^phonepe$"))
def show_phonepe(client, callback_query):
    user_id = callback_query.from_user.id
    slot_id = user_slot_choice.get(user_id, "slot_1")  # fallback slot if none
    
    # 1) Read required_amount from DB for that slot
    db_data = read_data_via_proxy()
    slot_info = db_data.get("settings", {}).get("slots", {}).get(slot_id, {})
    required_amount = slot_info.get("required_amount", 12)

    # 2) Fetch UI config from phonepe_screen
    ui = get_ui_config("phonepe_screen")
    # If "photo_url" is not provided in the UI config, use the hardcoded fallback URL
    photo_url = ui.get("photo_url", "https://raw.githubusercontent.com/SaloniTae/trackingPixel/refs/heads/main/IMG_20250302_195634.jpg")
    
    # The DB caption might contain "3. 𝘗𝘢𝘺 ₹{AMOUNT}"
    caption_raw = ui.get("caption", "PhonePe Payment ...")
    caption = caption_raw.replace("\\n", "\n")
    # Inject the dynamic amount
    caption = caption.replace("{AMOUNT}", str(required_amount))

    followup_raw = ui.get("followup_text", "Please enter transaction ID after payment.")
    followup = followup_raw.replace("\\n", "\n")

    # 3) Show the QR image with the replaced caption
    message_queue.put((
        client.send_photo,
        [callback_query.message.chat.id],
        {
            "photo": photo_url,
            "caption": caption
        }
    ))
    
    
    # 4) Then ask the user to enter their Transaction ID
    message_queue.put((
        client.send_message,
        [callback_query.message.chat.id],
        {
            "text": f"{followup}"
        }
    ))
    
    callback_query.answer()

@app.on_message(filters.text & ~filters.command("start"))
def validate_txn(client, message):
    user_id = message.from_user.id
    txn_id  = message.text.strip()
    logger.info(f"Validate TXN from user {user_id} => {txn_id}")

    # 1) call external paytm check
    merchant_key = "RZUqNv45112793295319"
    paytm_url = f"https://api.projectoid.in/v2/ledger/paytm/?MERCHANT_KEY={merchant_key}&TRANSACTION={txn_id}"
    resp = requests.get(paytm_url)
    if resp.status_code != 200:
        do_reject_flow_immediate(client, message, "API request failed.")
        return

    data = resp.json()
    result = data.get("result", {})
    status = result.get("STATUS","")
    order_id = result.get("ORDERID","")
    txn_amount_str = str(result.get("TXNAMOUNT","0"))

    if status != "TXN_SUCCESS":
        do_reject_flow_immediate(client, message)
        return

    # parse user slot
    slot_id = user_slot_choice.get(user_id, "slot_1")
    # read required_amount from DB
    db_data   = read_data_via_proxy()
    slot_info = db_data.get("settings", {}).get("slots", {}).get(slot_id, {})
    required_amount = float(slot_info.get("required_amount", 12))

    # parse paid
    try:
        paid_amount = float(txn_amount_str)
    except ValueError:
        paid_amount = 0.0

    # if mismatch => reject
    if abs(paid_amount - required_amount) > 0.001:
        do_reject_flow_immediate(client, message, "Amount mismatch.")
        return

    # check if order_id used
    if is_orderid_used(order_id):
        do_reject_flow_immediate(client, message, "Transaction ID already used.")
        return

    mark_orderid_used(order_id)
    # proceed to do_approve_flow for that slot
    do_approve_flow_immediate(client, message, slot_id)

def do_approve_flow_immediate(client, message, slot_id):
    """
    Get a valid credential for the chosen slot, show success, etc.
    """
    cred_key, cred_data = get_valid_credential_for_slot(slot_id)
    if cred_data == "locked":
        message_queue.put((
            client.send_message,
            [message.chat.id],
            {"text": "⚠️ Credentials for this slot are locked."}
        ))
        return
    if not cred_data:
        message_queue.put((
            client.send_message,
            [message.chat.id],
            {"text": "No available credentials for this slot."}
        ))
        return

    ui = get_ui_config("approve_flow")
    gif_url   = ui.get("gif_url","").replace("\\n","\n")
    succ_text = ui.get("success_text","Payment Success ✅").replace("\\n","\n")
    acct_fmt  = ui.get("account_format","Email: {email}\nPassword: {password}").replace("\\n","\n")

    if gif_url:
        message_queue.put((
            client.send_animation,
            [message.chat.id],
            {"animation": gif_url}
        ))

    email       = cred_data["email"]
    password    = cred_data["password"]
    usage_count = int(cred_data["usage_count"])
    max_usage   = int(cred_data["max_usage"])

    final_text = f"{succ_text}\n\n{acct_fmt.format(email=email, password=password)}"
    message_queue.put((
        client.send_message,
        [message.chat.id],
        {"text": final_text}
    ))

    if usage_count < max_usage:
        new_usage = usage_count + 1
        update_credential_usage(cred_key, new_usage)

def do_reject_flow_immediate(client, message, reason=None):
    ui = get_ui_config("reject_flow")
    gif_url = ui.get("gif_url","").replace("\\n","\n")
    err_txt = ui.get("error_text","Transaction Rejected.").replace("\\n","\n")

    if gif_url:
        message_queue.put((
            client.send_animation,
            [message.chat.id],
            {"animation": gif_url}
        ))

    # ignoring 'reason'
    message_queue.put((
        client.send_message,
        [message.chat.id],
        {"text": err_txt}
    ))

# --------------------- RUN BOT ---------------------
if __name__ == "__main__":
    logger.info("Starting multi-slot + TXNAMOUNT check bot ...")
    app.run()
