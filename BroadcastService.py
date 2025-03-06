# BroadcastService.py

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
API_ID = "25270711"
API_HASH = "6bf18f3d9519a2de12ac1e2e0f5c383e"
BOT_TOKEN = "7140092976:AAFtmOBKi-mIoVighcf4XXassHimU2CtlR8"
BROADCAST_AS_COPY = True  # If True, messages are sent as a copy (not forwarded)
BATCH_SIZE = 1000

# ---------------- FLASK APP SETUP ----------------
flask_app = Flask(__name__)

# ---------------- PYROGRAM CLIENT SETUP ----------------
# We create a Pyrogram client that will be used solely for broadcasting.
pyro_app = Client("broadcast_service", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- UTILITY: Fetch Recipients from Firebase ----------------
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
                # Firebase returns a dictionary with user IDs as keys.
                return [int(uid) for uid in data.keys()]
            except Exception as e:
                print("Error processing recipients data:", e)
                return []

# ---------------- ADVANCED SEND FUNCTION ----------------
async def send_msg(client, user_id, content):
    """
    Sends a message (text or media) to a given user_id.
    The 'content' parameter is expected to be a dictionary with a key "text" and optionally "media" (a file_id).
    """
    try:
        if BROADCAST_AS_COPY:
            if "media" in content:
                await client.send_photo(
                    chat_id=user_id,
                    photo=content["media"],
                    caption=content.get("text", "")
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content.get("text", "")
                )
        else:
            # If not using copy, you might forward a message—but without an original chat context,
            # it’s simpler to also send a new message.
            if "media" in content:
                await client.send_photo(
                    chat_id=user_id,
                    photo=content["media"],
                    caption=content.get("text", "")
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content.get("text", "")
                )
        return 200, None

    except FloodWait as e:
        print(f"FloodWait: Sleeping for {e.x} seconds for user {user_id}.")
        await asyncio.sleep(e.x)
        return await send_msg(client, user_id, content)
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
    # Generate a unique broadcast id for tracking in logs.
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

# ---------------- FLASK ENDPOINT ----------------
@flask_app.route("/start_broadcast", methods=["POST"])
def start_broadcast_endpoint():
    """
    Expects JSON data with broadcast content (e.g. {"text": "Hello everyone!"}).
    Triggers the broadcast routine in a background thread.
    """
    data = request.json
    if not data or "text" not in data:
        return jsonify({"error": "Invalid broadcast content. Must include at least 'text'."}), 400

    def run_broadcast():
        summary = asyncio.run(broadcast_routine(data))
        print("Broadcast summary:", summary)

    # Start the broadcast routine in a separate thread so the HTTP request returns immediately.
    Thread(target=run_broadcast).start()
    return jsonify({"status": "Broadcast started"}), 200

if __name__ == "__main__":
    print("Broadcast Service started on port 5001")
    flask_app.run(host="0.0.0.0", port=5001)
