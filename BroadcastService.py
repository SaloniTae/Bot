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
app = Flask(__name__)

# ---------------- PYROGRAM CLIENT SETUP ----------------
# Pyrogram client for broadcasting
pyro_app = Client("broadcast_service", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- FETCH USERS FROM FIREBASE ----------------
async def fetch_recipients():
    firebase_url = "https://get-crunchy-credentials-default-rtdb.firebaseio.com/users.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(firebase_url) as response:
            if response.status != 200:
                print(f"Error fetching recipients: HTTP {response.status}")
                return []
            data = await response.json()
            return [int(uid) for uid in data.keys()] if data else []

# ---------------- MESSAGE SENDING FUNCTION ----------------
async def send_msg(client, user_id, content):
    """
    Sends text or media messages to users.
    """
    try:
        if BROADCAST_AS_COPY:
            if content["media"]:
                await client.send_photo(chat_id=user_id, photo=content["media"], caption=content["text"])
            else:
                await client.send_message(chat_id=user_id, text=content["text"])
        else:
            if content["media"]:
                await client.send_photo(chat_id=user_id, photo=content["media"], caption=content["text"])
            else:
                await client.send_message(chat_id=user_id, text=content["text"])
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

# ---------------- BROADCAST FUNCTION ----------------
async def broadcast_routine(broadcast_content):
    recipients = await fetch_recipients()
    total_users = len(recipients)
    success, failed, done = 0, 0, 0
    start_time = time.time()

    async with pyro_app:
        for batch_start in range(0, total_users, BATCH_SIZE):
            batch = recipients[batch_start: batch_start+BATCH_SIZE]
            for user in batch:
                sts, err_msg = await send_msg(pyro_app, user, broadcast_content)
                if sts == 200:
                    success += 1
                else:
                    failed += 1
                done += 1
                if done % 10 == 0:
                    elapsed = time.time() - start_time
                    remaining = (total_users - done) * (elapsed / done) if done else 0
                    print(f"Progress: {done}/{total_users} ({(done/total_users)*100:.2f}%), Success: {success}, Failed: {failed}, Elapsed: {int(elapsed)}s, Remaining: {int(remaining)}s")
            await asyncio.sleep(3)

# ---------------- FLASK ENDPOINT TO TRIGGER BROADCAST ----------------
@app.route("/start_broadcast", methods=["POST"])
def start_broadcast():
    data = request.json
    if not data or "text" not in data:
        return jsonify({"error": "Invalid request. Must include 'text' field."}), 400

    data.setdefault("media", None)  # Ensure "media" is present in case it's missing

    # Use `asyncio.create_task()` to avoid `asyncio.run()` issues
    asyncio.get_event_loop().create_task(broadcast_routine(data))

    return jsonify({"status": "Broadcast started"}), 200

# ---------------- FLASK KEEP-ALIVE ENDPOINT ----------------
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive"}), 200

# ---------------- START SERVER ----------------
if __name__ == "__main__":
    print("Broadcast Service started at http://127.0.0.1:5001")
    app.run(host="0.0.0.0", port=5001)
