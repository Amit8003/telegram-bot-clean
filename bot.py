import os
import json
import firebase_admin
from firebase_admin import credentials, db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import time
import pyshorteners

# ✅ Firebase Setup (Environment variable se load karo)
firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_credentials:
    raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
cred_dict = json.loads(firebase_credentials)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://telegram-15b0b.firebaseio.com"
})

# ✅ Telegram Bot Token (Environment variable se load karo)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

# ✅ TinyURL Setup (Smart link ke liye)
shortener = pyshorteners.Shortener()

def create_smart_link(original_url):
    """ YouTube ka direct download link ko TinyURL me convert karega """
    try:
        return shortener.tinyurl.short(original_url)
    except Exception as e:
        print(f"Error creating TinyURL: {str(e)}")
        return original_url

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube link to get download options!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if "youtube.com" in url or "youtu.be" in url:
        await update.message.reply_text("Fetching download options...")
        try:
            ydl_opts = {
                "quiet": True,
                "format_sort": ["res", "ext:mp4"],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])

            keyboard = []
            seen_resolutions = set()
            for f in formats:
                if f.get("format_id") in ["18", "22", "137", "399", "400"]:
                    quality = f.get("format_note", "Unknown")
                    if quality in seen_resolutions:
                        continue
                    seen_resolutions.add(quality)
                    size = f.get("filesize", 0)
                    size_mb = size / (1024 * 1024) if size else "Unknown"
                    button = InlineKeyboardButton(f"{quality} ({size_mb:.2f} MB)" if size else f"{quality} (Size Unknown)",
                                                callback_data=f"{f['format_id']}|{url}")
                    keyboard.append([button])

            if not keyboard:
                await update.message.reply_text("No downloadable formats found. Please try another video.")
                return

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Choose a quality:", reply_markup=reply_markup)
        except Exception as e:
            await update.message.reply_text(f"Error fetching link: {str(e)}\nTry another video.")
    else:
        await update.message.reply_text("Please send a valid YouTube link!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    format_id, url = query.data.split("|")

    await query.message.reply_text("Generating smart download link...")

    try:
        # ✅ Force audio aur video merge
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best",  # Video + Best Audio
            "get_url": True,  # Sirf URL nikaal, download mat karo
            "merge_output_format": "mp4",  # Force MP4 output with audio
            "postprocessors": [{  # Ensure audio aur video merge ho
                "key": "FFmpegMerge",
                "preferredcodec": "mp4",
            }],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            direct_url = info.get("url")

            # ✅ Agar audio nahi hai, toh alag se audio stream fetch karo
            if not direct_url:
                # Fallback: Audio alag se fetch karo
                ydl_opts_fallback = {
                    "format": "bestaudio/best",
                    "get_url": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl_fallback:
                    audio_info = ydl_fallback.extract_info(url, download=False)
                    audio_url = audio_info.get("url")
                    if audio_url:
                        # Audio aur video URL combine karo (client-side merging ke liye)
                        direct_url = f"{direct_url}|{audio_url}" if direct_url else audio_url
                    else:
                        await query.message.reply_text("❌ Audio not found for this video. Try another quality or video.")
                        return

        # ✅ Smart Link Generate Karo (TinyURL)
        smart_link = create_smart_link(direct_url)

        # ✅ Firebase me Link Store karein
        ref = db.reference("downloads").push({
            "title": info.get("title", "Unknown Title"),
            "url": url,
            "direct_url": direct_url,
            "smart_link": smart_link,
            "format_id": format_id,
            "timestamp": int(time.time())
        })
        link_id = ref.key
        firebase_link = f"https://telegram-15b0b.firebaseio.com/downloads/{link_id}.json"

        # ✅ User ko Smart Link Send Karo
        await query.message.reply_text(
            f"✅ Download ready: [Click Here]({smart_link})\n\n"
            f"⚠️ Note: This link may expire soon (usually within 24 hours). Download quickly!\n\n"
            f"Stored in Firebase: [View Metadata]({firebase_link})",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Error: {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
