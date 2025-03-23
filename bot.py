import os
import json
import firebase_admin
from firebase_admin import credentials, db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import time
import requests

# ✅ Firebase Setup (Environment Variable Se JSON File Load)
firebase_json_str = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_json_str:
    raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
cred_dict = json.loads(firebase_json_str)  # JSON string ko dictionary me convert karna
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred, {"databaseURL": os.getenv("FIREBASE_DB_URL")})  # Firebase DB URL bhi env me rakho

# ✅ Telegram Bot Token (Secure)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

# ✅ Smart Link Generation (Rebrandly API)
REBRANDLY_API_KEY = os.getenv("REBRANDLY_API_KEY")  # Secure API key

def create_smart_link(original_url):
    """ YouTube direct link ko smart short URL me convert karega """
    if not REBRANDLY_API_KEY:
        return original_url  # Agar API key nahi hai to direct URL return karna
    try:
        headers = {"apikey": REBRANDLY_API_KEY, "Content-Type": "application/json"}
        data = {"destination": original_url, "domain": {"fullName": "rebrand.ly"}}
        response = requests.post("https://api.rebrandly.com/v1/links", json=data, headers=headers)
        if response.status_code == 200:
            return response.json()["shortUrl"]
    except Exception as e:
        print(f"Error creating short link: {str(e)}")
    return original_url

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Send me a YouTube link to get download options!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if "youtube.com" in url or "youtu.be" in url:
        await update.message.reply_text("⏳ Fetching download options...")
        try:
            ydl_opts = {"quiet": True, "format_sort": ["res", "ext:mp4"]}
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
                await update.message.reply_text("❌ No downloadable formats found. Try another video.")
                return

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("🎥 Choose a quality:", reply_markup=reply_markup)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}\nTry another video.")
    else:
        await update.message.reply_text("⚠️ Please send a valid YouTube link!")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    format_id, url = query.data.split("|")

    await query.message.reply_text("🔗 Generating smart download link...")

    try:
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best",
            "get_url": True,
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegMerge", "preferredcodec": "mp4"}],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            direct_url = info.get("url")

            if not direct_url:
                ydl_opts_fallback = {"format": "bestaudio/best", "get_url": True}
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl_fallback:
                    audio_info = ydl_fallback.extract_info(url, download=False)
                    audio_url = audio_info.get("url")
                    if audio_url:
                        direct_url = f"{direct_url}|{audio_url}" if direct_url else audio_url
                    else:
                        await query.message.reply_text("❌ Audio not found. Try another quality or video.")
                        return

        smart_link = create_smart_link(direct_url)

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

        await context.bot.send_message(
            chat_id=update.effective_user.id,  # ✅ Private Message for Safety
            text=(
                f"✅ **Download ready:** [Click Here]({smart_link})\n\n"
                f"⚠️ **Note:** This link may expire soon (within 24 hours). Download quickly!\n\n"
                f"📂 **Stored in Firebase:** [View Metadata]({firebase_link})"
            ),
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
