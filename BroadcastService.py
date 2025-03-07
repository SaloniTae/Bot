import nest_asyncio
nest_asyncio.apply()

import asyncio
import datetime
import random
import string
import time
import traceback
from threading import Thread
import os

import aiofiles
import aiohttp
from flask import Flask, request, jsonify
from pyrogram import Client, types
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid

# ---------------- CONFIGURATION ----------------
API_ID = "25270711" 
API_HASH = "6bf18f3d9519a2de12ac1e2e0f5c383e"
BOT_TOKEN = "7140092976:AAFtmOBKi-mIoVighcf4XXassHimU2CtlR8"
BROADCAST_AS_COPY = True
BATCH_SIZE = 1000

# ---------------- FLASK APP SETUP ----------------
flask_app = Flask(__name__)

# ---------------- PYROGRAM CLIENT SETUP ----------------
# Create a global Pyrogram client.
pyro_app = Client("broadcast_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- GLOBAL STATE ----------------
pending_broadcast = {}         # { admin_id: broadcast content dict }
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
                return [int(uid) for uid in data.keys()]
            except Exception as e:
                print("Error processing recipients data:", e)
                return []

# ---------------- ADVANCED SEND FUNCTION ----------------
async def send_msg(user_id, content):
    try:
        if BROADCAST_AS_COPY:
            if content.get("media"):
                await pyro_app.send_photo(
                    chat_id=user_id,
                    photo=content["media"],
                    caption=content.get("text", "")
                )
            else:
                await pyro_app.send_message(
                    chat_id=user_id,
                    text=content.get("text", "")
                )
        else:
            if content.get("media"):
                await pyro_app.send_photo(
                    chat_id=user_id,
                    photo=content["media"],
                    caption=content.get("text", "")
                )
            else:
                await pyro_app.send_message(
                    chat_id=user_id,
                    text=content.get("text", "")
                )
        return 200, None

    except FloodWait as e:
        print(f"FloodWait: Sleeping for {e.x} seconds for user {user_id}.")
        await asyncio.sleep(e.x)
        return await send_msg(user_id, content)
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
    recipients = await fetch_recipients()
    total_users = len(recipients)
    done = 0
    success = 0
    failed = 0
    start_time = time.time()
    broadcast_id = "".join(random.choice(string.ascii_letters) for _ in range(3))
    log_lines = []
    for batch_start in range(0, total_users, BATCH_SIZE):
        batch = recipients[batch_start: batch_start+BATCH_SIZE]
        for user in batch:
            sts, err_msg = await send_msg(user, broadcast_content)
            if err_msg is not None:
                log_lines.append(err_msg)
            if sts == 200:
                success += 1
            else:
                failed += 1
            done += 1
            if done % 10 == 0 or done == total_users:
                elapsed = time.time() - start_time
                avg_time = elapsed/done if done else 0
                remaining = (total_users - done) * avg_time
                print(f"[{broadcast_id}] Progress: {done}/{total_users} ({(done/total_users)*100:.2f}%), Success: {success}, Failed: {failed}, Elapsed: {int(elapsed)}s, Remaining: {int(remaining)}s")
        await asyncio.sleep(3)
    completed_in = time.time() - start_time
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

# ---------------- FLASK ENDPOINTS ----------------

@flask_app.route("/start_broadcast", methods=["POST"])
def start_broadcast_endpoint():
    data = request.json
    user_id = data.get("user_id")
    if not user_id or "text" not in data:
        return jsonify({"error": "Missing required parameters."}), 400

    pending_broadcast[user_id] = {"text": data["text"], "media": data.get("media")}
    
    async def send_confirmation():
        keyboard = [
            [types.InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_broadcast_{user_id}")],
            [types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_broadcast_{user_id}")]
        ]
        await pyro_app.send_message(
            chat_id=user_id,
            text="Do you want to broadcast this message to all recipients?\nClick Confirm or Cancel.",
            reply_markup=types.InlineKeyboardMarkup(keyboard)
        )
    # Schedule send_confirmation on the already running pyro_app loop.
    asyncio.run_coroutine_threadsafe(send_confirmation(), pyro_app.loop).result()
    return jsonify({"status": "Pending confirmation"}), 200

@flask_app.route("/confirm_broadcast", methods=["POST"])
def confirm_broadcast_endpoint():
    data = request.json
    user_id = data.get("user_id")
    if not user_id or user_id not in pending_broadcast:
        return jsonify({"error": "No pending broadcast for this user."}), 400

    broadcast_content = pending_broadcast.pop(user_id)
    summary = asyncio.run_coroutine_threadsafe(broadcast_routine(broadcast_content), pyro_app.loop).result()
    return jsonify({"status": "Broadcast completed", "summary": summary}), 200

@flask_app.route("/cancel_broadcast", methods=["POST"])
def cancel_broadcast_endpoint():
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
    print("Starting Pyrogram client...")
    pyro_app.start()  # Start the client before handling any requests.
    print("Broadcast Service started at http://0.0.0.0:5001")
    flask_app.run(host="0.0.0.0", port=5001)
    pyro_app.stop()
