import asyncio
import datetime
import os
import random
import string
import time
import traceback
import json
from threading import Thread

import aiofiles
import aiohttp
from flask import Flask, request, jsonify
from pyrogram import Client, types
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid

# ---------------- CONFIGURATION ----------------
API_ID = os.getenv("API_ID", "25270711")
API_HASH = os.getenv("API_HASH", "6bf18f3d9519a2de12ac1e2e0f5c383e")
BOT_TOKEN = os.getenv("BOT_TOKEN", "7140092976:AAFtmOBKi-mIoVighcf4XXassHimU2CtlR8")
BROADCAST_AS_COPY = True
BATCH_SIZE = 1000

# ---------------- FLASK APP SETUP ----------------
flask_app = Flask(__name__)

# ---------------- PYROGRAM CLIENT SETUP ----------------
# This Pyrogram client is used solely for broadcast processing.
pyro_app = Client("broadcast_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- GLOBAL STATE ----------------
pending_broadcast = {}         # { admin_id: message (content) }
cancel_broadcast_flag = {}     # { admin_id: bool }

# ---------------- UTILITY FUNCTION TO FETCH RECIPIENTS FROM FIREBASE ----------------
async def fetch_recipients():
    firebase_url = "https://get-crunchy-credentials-default-rtdb.firebaseio.com/users.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(firebase_url) as response:
            if response.status != 200:
                print(f"Error fetching recipients: HTTP {response.status}")
                return []
            data = await response.json()
            if data is None:
                return []
            try:
                # Firebase returns a dictionary with user IDs as keys
                return [int(uid) for uid in data.keys()]
            except Exception as e:
                print("Error processing recipients data:", e)
                return []

# ---------------- ADVANCED SEND FUNCTION ----------------
async def send_msg(client, user_id, content_msg):
    try:
        if BROADCAST_AS_COPY:
            if content_msg.get("media"):
                await client.send_photo(
                    chat_id=user_id,
                    photo=content_msg["media"],
                    caption=content_msg.get("text", "")
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content_msg.get("text", "")
                )
        else:
            if content_msg.get("media"):
                await client.send_photo(
                    chat_id=user_id,
                    photo=content_msg["media"],
                    caption=content_msg.get("text", "")
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content_msg.get("text", "")
                )
        return 200, None

    except FloodWait as e:
        print(f"FloodWait: Sleeping for {e.x} seconds for user {user_id}.")
        await asyncio.sleep(e.x)
        return await send_msg(client, user_id, content_msg)
    except InputUserDeactivated:
        return 400, f"{user_id} : deactivated"
    except UserIsBlocked:
        return 400, f"{user_id} : blocked the bot"
    except PeerIdInvalid:
        return 400, f"{user_id} : user id invalid"
    except Exception:
        return 500, f"{user_id} : {traceback.format_exc()}"

# ---------------- BROADCAST ROUTINE ----------------
async def broadcast_routine(broadcast_content):
    """
    Broadcasts the provided content to all recipients.
    broadcast_content: a dict containing at least a "text" field, optionally a "media" field.
    Returns a summary dictionary.
    """
    recipients = await fetch_recipients()
    total_users = len(recipients)
    done = 0
    success = 0
    failed = 0
    start_time = time.time()
    # Generate a unique broadcast id for tracking.
    broadcast_id = "".join(random.choice(string.ascii_letters) for _ in range(3))
    log_lines = []
    async with pyro_app:
        for batch_start in range(0, total_users, BATCH_SIZE):
            batch = recipients[batch_start: batch_start+BATCH_SIZE]
            for user in batch:
                sts, err_msg = await send_msg(pyro_app, user, broadcast_content)
                if err_msg is not None:
                    log_lines.append(err_msg)
                if sts == 200:
                    success += 1
                else:
                    failed += 1
                done += 1
                # Print progress to the console every 10 messages.
                if done % 10 == 0 or done == total_users:
                    elapsed = time.time() - start_time
                    avg_time = elapsed/done if done else 0
                    remaining = (total_users - done) * avg_time
                    print(f"[{broadcast_id}] Progress: {done}/{total_users} ({(done/total_users)*100:.2f}%), Success: {success}, Failed: {failed}, Elapsed: {int(elapsed)}s, Remaining: {int(remaining)}s")
            await asyncio.sleep(3)  # Pause between batches.
    completed_in = time.time() - start_time
    # Optionally, write error log to a file.
    log_filename = f"broadcast_{broadcast_id}.txt"
    async with aiofiles.open(log_filename, "w") as log_file:
        await log_file.write("\n".join(log_lines))
    summary = {
        "broadcast_id": broadcast_id,
        "total_users": total_users,
        "processed": done,
        "success": success,
        "failed": failed,
        "completed_in": str(datetime.timedelta(seconds=int(completed_in)))
    }
    if failed == 0 and os.path.exists(log_filename):
        os.remove(log_filename)
    return summary

# ---------------- HELPER: RUN COROUTINE IN NEW EVENT LOOP ----------------
def run_async(coro):
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    result = new_loop.run_until_complete(coro)
    new_loop.close()
    return result

# ---------------- FLASK ENDPOINTS ----------------

@flask_app.route("/start_broadcast", methods=["POST"])
def start_broadcast_endpoint():
    """
    Expects JSON data with broadcast content (e.g. {"user_id": 7506651658, "text": "Hello everyone!", "media": "file_id_here"}).
    Saves the pending broadcast and sends a confirmation UI to the admin.
    """
    data = request.json
    user_id = data.get("user_id")
    if not user_id or "text" not in data:
        return jsonify({"error": "Missing required parameters."}), 400

    pending_broadcast[user_id] = {"text": data["text"], "media": data.get("media")}
    
    async def send_confirmation():
        async with pyro_app:
            keyboard = [
                [types.InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_broadcast_{user_id}")],
                [types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_broadcast_{user_id}")]
            ]
            await pyro_app.send_message(
                chat_id=user_id,
                text="Do you want to broadcast this message to all recipients?\nClick Confirm or Cancel.",
                reply_markup=types.InlineKeyboardMarkup(keyboard)
            )
    # Use our helper to run the coroutine in a new event loop.
    run_async(send_confirmation())
    return jsonify({"status": "Pending confirmation"}), 200

@flask_app.route("/confirm_broadcast", methods=["POST"])
def confirm_broadcast_endpoint():
    """
    Expects JSON data with {"user_id": admin_id} to confirm and start the broadcast.
    """
    data = request.json
    user_id = data.get("user_id")
    if not user_id or user_id not in pending_broadcast:
        return jsonify({"error": "No pending broadcast for this user."}), 400

    broadcast_content = pending_broadcast.pop(user_id)
    summary = run_async(broadcast_routine(broadcast_content))
    return jsonify({"status": "Broadcast completed", "summary": summary}), 200

@flask_app.route("/cancel_broadcast", methods=["POST"])
def cancel_broadcast_endpoint():
    """
    Expects JSON data with {"user_id": admin_id} to cancel the pending broadcast.
    """
    data = request.json
    user_id = data.get("user_id")
    if user_id in pending_broadcast:
        pending_broadcast.pop(user_id, None)
    return jsonify({"status": "Broadcast cancelled"}), 200

@flask_app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive"}), 200

# ---------------- START FLASK SERVER ----------------
if __name__ == "__main__":
    print("Broadcast Service started at http://0.0.0.0:5001")
    flask_app.run(host="0.0.0.0", port=5001)
