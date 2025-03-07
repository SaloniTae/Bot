import asyncio
import datetime
import os
import random
import string
import time
import traceback
import json

import aiofiles
import aiohttp
from pyrogram import Client, filters, types
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid

# ---------------- CONFIGURATION ----------------
API_ID = "25270711" 
API_HASH = "6bf18f3d9519a2de12ac1e2e0f5c383e"
BOT_TOKEN = "7140092976:AAFtmOBKi-mIoVighcf4XXassHimU2CtlR8"

ADMIN_ID = [7506651658, 2031595742]

# Remove the local users.json reading
# with open("users.json", "r") as f:
#     users_data = json.load(f)
# RECIPIENTS = [int(uid) for uid in users_data["users"].keys()]

# Broadcast settings
BROADCAST_AS_COPY = True
BATCH_SIZE = 1000

# ---------------- GLOBAL STATE ----------------
pending_broadcast = {}
cancel_broadcast_flag = {}

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

# ---------------- PYROGRAM CLIENT ----------------

app = Client("broadcast_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- ADVANCED SEND FUNCTION ----------------
async def send_msg(client, user_id, content_msg):
    try:
        if BROADCAST_AS_COPY:
            if content_msg.media:
                await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=content_msg.chat.id,
                    message_id=content_msg.id
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content_msg.text or ""
                )
        else:
            if content_msg.media:
                await client.forward_messages(
                    chat_id=user_id,
                    from_chat_id=content_msg.chat.id,
                    message_ids=content_msg.id
                )
            else:
                await client.send_message(
                    chat_id=user_id,
                    text=content_msg.text or ""
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

# ---------------- HANDLERS ----------------

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID))
async def broadcast_command(client, message):
    """
    Admin initiates broadcast with /broadcast.
    """
    pending_broadcast[message.from_user.id] = None  # Clear any previous pending broadcast
    cancel_broadcast_flag[message.from_user.id] = False  # Reset cancel flag
    await message.reply_text("Please send me the content (text or media) that you want to broadcast.")

@app.on_message(filters.user(ADMIN_ID) & ~filters.command(["broadcast", "cancelbroadcast"]))
async def capture_broadcast_content(client, message):
    """
    Capture broadcast content from the admin and prompt for confirmation.
    """
    admin_id = message.from_user.id
    if admin_id in pending_broadcast and pending_broadcast[admin_id] is None:
        pending_broadcast[admin_id] = message
        keyboard = [
            [
                types.InlineKeyboardButton("Confirm", callback_data="confirm_broadcast"),
                types.InlineKeyboardButton("Cancel", callback_data="cancel_broadcast")
            ]
        ]
        await message.reply_text(
            "Do you want to broadcast the following content to all recipients?\nClick Confirm to proceed or Cancel to abort.",
            reply_markup=types.InlineKeyboardMarkup(keyboard)
        )

@app.on_message(filters.command("cancelbroadcast") & filters.user(ADMIN_ID))
async def cancel_broadcast_command(client, message):
    """
    Admin can cancel an ongoing broadcast using /cancelbroadcast.
    """
    admin_id = message.from_user.id
    cancel_broadcast_flag[admin_id] = True
    await message.reply_text("Broadcast cancellation requested. The process will stop shortly.")

@app.on_callback_query(filters.user(ADMIN_ID))
async def broadcast_confirmation(client, callback_query):
    """
    Handle confirmation or cancellation.
    Implements batch processing, progress updates, and final reporting.
    Also checks for cancellation flag during the broadcast.
    """
    admin_id = callback_query.from_user.id

    if callback_query.data == "confirm_broadcast":
        if admin_id not in pending_broadcast or pending_broadcast[admin_id] is None:
            await callback_query.answer("No broadcast content found.", show_alert=True)
            return

        # Reset cancel flag at start
        cancel_broadcast_flag[admin_id] = False

        content_msg = pending_broadcast[admin_id]
        
        # Fetch recipients from Firebase using REST API
        recipients = await fetch_recipients()
        if not recipients:
            await callback_query.answer("No recipients found from Firebase.", show_alert=True)
            return

        progress_msg = await callback_query.message.edit_text("Broadcast started...")

        # Generate a broadcast id for tracking
        broadcast_id = "".join(random.choice(string.ascii_letters) for _ in range(3))
        start_time = time.time()
        total_users = len(recipients)
        done = 0
        success = 0
        failed = 0

        # Open a log file to record errors
        async with aiofiles.open("broadcast.txt", "w") as log_file:
            # Process recipients in batches
            for batch_start in range(0, total_users, BATCH_SIZE):
                if cancel_broadcast_flag.get(admin_id, False):
                    print("Cancellation flag detected. Stopping broadcast.")
                    break

                batch = recipients[batch_start: batch_start + BATCH_SIZE]
                for user in batch:
                    if cancel_broadcast_flag.get(admin_id, False):
                        break

                    sts, err_msg = await send_msg(client, user, content_msg)
                    if err_msg is not None:
                        await log_file.write(err_msg + "\n")
                    if sts == 200:
                        success += 1
                    else:
                        failed += 1
                    done += 1

                    # Update progress every 10 messages or on completion
                    if done % 10 == 0 or done == total_users:
                        elapsed = time.time() - start_time
                        avg_time = elapsed / done if done else 0
                        remaining = (total_users - done) * avg_time
                        percentage = (done / total_users) * 100
                        progress_text = (
                            f"Broadcast Progress (ID: {broadcast_id}):\n"
                            f"Sent: {done}/{total_users} ({percentage:.2f}%)\n"
                            f"Success: {success} | Failed: {failed}\n"
                            f"Elapsed: {datetime.timedelta(seconds=int(elapsed))}\n"
                            f"Remaining: {datetime.timedelta(seconds=int(remaining))}"
                        )
                        try:
                            await progress_msg.edit_text(progress_text)
                        except Exception as e:
                            print("Progress update error:", e)
                        await asyncio.sleep(0.5)
                # Optional pause between batches
                await asyncio.sleep(3)

        if cancel_broadcast_flag.get(admin_id, False):
            summary = f"Broadcast CANCELLED (ID: {broadcast_id}). Processed: {done}/{total_users} messages.\nSuccess: {success} | Failed: {failed}"
        else:
            completed_in = datetime.timedelta(seconds=int(time.time() - start_time))
            summary = (
                f"Broadcast Completed (ID: {broadcast_id}) in {completed_in}\n"
                f"Total: {total_users}\n"
                f"Processed: {done}\n"
                f"Success: {success}\n"
                f"Failed: {failed}"
            )

        pending_broadcast.pop(admin_id, None)
        cancel_broadcast_flag.pop(admin_id, None)

        if failed > 0 and os.path.exists("broadcast.txt"):
            await client.send_document(chat_id=admin_id, document="broadcast.txt", caption=summary)
        else:
            await client.send_message(chat_id=admin_id, text=summary)

        if os.path.exists("broadcast.txt"):
            os.remove("broadcast.txt")
        await callback_query.answer("Broadcast process ended.", show_alert=True)

    elif callback_query.data == "cancel_broadcast":
        cancel_broadcast_flag[admin_id] = True
        await callback_query.answer("Broadcast cancelled.", show_alert=True)
        await callback_query.message.edit_text("Broadcast cancelled.")
        pending_broadcast.pop(admin_id, None)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive"}), 200
    
if __name__ == "__main__":
    print("Broadcasting Bot started!")
    app.run()



