from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import re
import logging
import asyncio

API_TOKEN = "75021zc"
ADMIN_USER_ID = 18317  # 🔒 Replace with your Telegram user ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

source_group_ids = []
TARGET_GROUP_ID = None  # Initialize TARGET_GROUP_ID as None

# 🔒 Admin-only decorator
def admin_only(func):
    async def wrapper(update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper

# /start command
async def start(update: Update, context: CallbackContext):
    welcome_message = (
        "👋 Hello! Welcome to the bot.\n"
        "Here are the available commands:\n"
        "1️⃣ /start -> Show this welcome message\n"
        "2️⃣ /addgroup -> Add the current group to the list of monitored groups\n"
        "3️⃣ /removegroup -> Remove the current group from the list of monitored groups\n"
        "4️⃣ /settargetgroup -> Set the target group for forwarding messages\n"
        "5️⃣ /removetargetgroup -> Remove the target group\n"
        "6️⃣ /joingroup -> Ask the bot to join a new group\n"
        "7️⃣ /enableforwardfromgroups -> Enable forwarding from joined groups\n"
        "8️⃣ /info -> Information about this bot\n"
        "9️⃣ /HowToUse -> Instructions on how to use this bot"
    )
    await update.message.reply_text(welcome_message)

# /HowToUse command
async def how_to_use(update: Update, context: CallbackContext):
    instructions = (
        "🛠️ **How to use the bot**:\n"
        "1️⃣ **Add the bot** to a group where you want it to monitor messages.\n"
        "2️⃣ **Use the /addgroup command** from within that group. This command will add the group to the bot’s monitored list.\n"
        "3️⃣ **Set the target group** using the /settargetgroup command. This is the group where the messages will be forwarded.\n"
        "4️⃣ **Remove the target group** using /removetargetgroup command if needed.\n"
        "5️⃣ **The bot will filter and forward** messages from the monitored groups to the target group automatically."
    )
    await update.message.reply_text(instructions)

# 🔒 Set target group
@admin_only
async def set_target_group(update: Update, context: CallbackContext):
    global TARGET_GROUP_ID
    target_group_id = update.message.chat_id

    if TARGET_GROUP_ID is None:
        TARGET_GROUP_ID = target_group_id
        await update.message.reply_text(f"✅ Target group set to {TARGET_GROUP_ID}.")
    else:
        await update.message.reply_text("⚠️ The target group has already been set.")

# 🔒 Remove target group
@admin_only
async def remove_target_group(update: Update, context: CallbackContext):
    global TARGET_GROUP_ID
    if TARGET_GROUP_ID is not None:
        TARGET_GROUP_ID = None
        await update.message.reply_text("✅ The target group has been removed.")
    else:
        await update.message.reply_text("⚠️ No target group is currently set.")

# 🔒 Add group
@admin_only
async def add_group(update: Update, context: CallbackContext):
    group_id = update.message.chat_id
    group_name = update.message.chat.title

    if group_id == TARGET_GROUP_ID:
        await update.message.reply_text("⚠️ You cannot add the target group to the monitored list.")
        return

    if group_id not in source_group_ids:
        if len(source_group_ids) < 5:
            source_group_ids.append(group_id)
            await update.message.reply_text(f"✅ Group '{group_name}' added to monitored list.")
        else:
            await update.message.reply_text("⚠️ You can monitor up to 5 groups only.")
    else:
        await update.message.reply_text(f"⚠️ Group '{group_name}' is already being monitored.")

# 🔒 Remove group
@admin_only
async def remove_group(update: Update, context: CallbackContext):
    group_id = update.message.chat_id
    group_name = update.message.chat.title

    if group_id in source_group_ids:
        source_group_ids.remove(group_id)
        await update.message.reply_text(f"✅ Group '{group_name}' removed from monitored list.")
    else:
        await update.message.reply_text(f"⚠️ Group '{group_name}' is not being monitored.")

# 🔒 Join group via invite link
@admin_only
async def join_group(update: Update, context: CallbackContext):
    await update.message.reply_text("Send the group invite link (e.g., `https://t.me/+abc123`)")

    link = update.message.text
    link_pattern = r"^https:\/\/t\.me\/\+\w+$"

    if re.match(link_pattern, link):
        try:
            await context.bot.join_chat(link)
            await update.message.reply_text("✅ Successfully joined the group!")
        except Exception as e:
            logger.error(f"Join error: {e}")
            await update.message.reply_text("❌ Failed to join. Check the invite link.")
    else:
        await update.message.reply_text("⚠️ Invalid format. Use: `https://t.me/+<code>`")

# 🔒 List monitored groups
@admin_only
async def enable_forward_from_groups(update: Update, context: CallbackContext):
    if not source_group_ids:
        await update.message.reply_text("🛑 No groups are being monitored.")
        return

    group_list = "\n".join([f"{i+1}. Group ID: {gid}" for i, gid in enumerate(source_group_ids)])
    await update.message.reply_text(f"📋 Monitored groups:\n{group_list}")

# Public /info command
async def info(update: Update, context: CallbackContext):
    await update.message.reply_text("ℹ️ modified by @mb_banga, credit to: https://www.linkedin.com/in/01neelesh/" )

# 🔄 Forward messages with sender hidden + throttle
async def forward_message(update: Update, context: CallbackContext) -> None:
    message = update.message

    if message.chat_id not in source_group_ids or not TARGET_GROUP_ID:
        return

    try:
        # Choose based on message type
        if message.text:
            await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=message.text)

        elif message.photo:
            await context.bot.send_photo(
                chat_id=TARGET_GROUP_ID,
                photo=message.photo[-1].file_id,
                caption=message.caption or ""
            )

        elif message.document:
            await context.bot.send_document(
                chat_id=TARGET_GROUP_ID,
                document=message.document.file_id,
                caption=message.caption or ""
            )

        elif message.video:
            await context.bot.send_video(
                chat_id=TARGET_GROUP_ID,
                video=message.video.file_id,
                caption=message.caption or ""
            )

        elif message.audio:
            await context.bot.send_audio(chat_id=TARGET_GROUP_ID, audio=message.audio.file_id)

        elif message.voice:
            await context.bot.send_voice(chat_id=TARGET_GROUP_ID, voice=message.voice.file_id)

        elif message.sticker:
            await context.bot.send_sticker(chat_id=TARGET_GROUP_ID, sticker=message.sticker.file_id)

        else:
            logger.info("⚠️ Unsupported message type.")

        logger.info("✅ Message forwarded (sender hidden).")

        # ⏱️ Delay to stay under 19 messages per minute
        await asyncio.sleep(3.2)

    except Exception as e:
        logger.error(f"❌ Forwarding error: {e}")

# 🔧 Main entry point
def main():
    application = Application.builder().token(API_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("HowToUse", how_to_use))
    application.add_handler(CommandHandler("addgroup", add_group))
    application.add_handler(CommandHandler("removegroup", remove_group))
    application.add_handler(CommandHandler("settargetgroup", set_target_group))
    application.add_handler(CommandHandler("removetargetgroup", remove_target_group))
    application.add_handler(CommandHandler("joingroup", join_group))
    application.add_handler(CommandHandler("enableforwardfromgroups", enable_forward_from_groups))
    application.add_handler(CommandHandler("info", info))

    # Messages (any type, group only)
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, forward_message))

    application.run_polling()

if __name__ == "__main__":
    main()
