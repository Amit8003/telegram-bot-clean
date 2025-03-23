import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import yt_dlp
import firebase_admin
from firebase_admin import credentials, firestore
import asyncio
import os
import json

# Telegram bot token
TOKEN = "7789867310:AAGWhF9vfPzPY4b1nhlBe1j4KcPAPlyxfxg"

# Firebase credentials using environment variable
firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_credentials:
    raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
cred_dict = json.loads(firebase_credentials)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Logging setup
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Start command
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Send me a YouTube link to get download options!")

# Handle YouTube links
async def handle_message(update: Update, context: CallbackContext) -> None:
    url = update.message.text

    if "youtube.com" in url or "youtu.be" in url:
        await update.message.reply_text("Fetching download options...")

        # yt-dlp options for smart links with audio and speed
        ydl_opts_base = {
            'quiet': True,
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'http_chunk_size': '10M',  # Faster streaming
            'no_cache_dir': True,      # No overhead
            'simulate': True,          # Get merged URLs without downloading
            'get_url': True,           # Extract the final merged URL
        }
        try:
            # Step 1: Get all available formats
            with yt_dlp.YoutubeDL(ydl_opts_base) as ydl:
                logger.info(f"Processing URL: {url}")
                # Small delay to avoid rate-limiting (ban safe)
                await asyncio.sleep(1)
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])
                logger.info(f"Found {len(formats)} formats")

                # Log all formats for debugging (detailed)
                for fmt in formats:
                    logger.info(f"Format: {fmt.get('format_id')} - {fmt.get('height', 'unknown')}p - {fmt.get('ext')} - vcodec: {fmt.get('vcodec')}")

                # Step 2: Filter video formats (only check for height)
                video_formats = [
                    fmt for fmt in formats
                    if fmt.get("height") is not None
                ]
                # Sort by height (resolution) in ascending order
                video_formats.sort(key=lambda x: x.get("height"))

                # Log filtered video formats
                logger.info(f"Found {len(video_formats)} video formats after filtering")
                for fmt in video_formats:
                    logger.info(f"Filtered Video Format: {fmt.get('format_id')} - {fmt.get('height')}p - {fmt.get('ext')}")

                # Step 3: For each video format, merge with best audio
                buttons = []
                seen_qualities = set()
                for fmt in video_formats:
                    quality = str(fmt.get("height", "Unknown"))
                    if quality in seen_qualities:
                        continue
                    seen_qualities.add(quality)

                    # Create specific yt-dlp options for this quality
                    ydl_opts = ydl_opts_base.copy()
                    ydl_opts['format'] = f"bestvideo[height={fmt.get('height')}]+bestaudio/best"

                    # Fetch the merged URL for this specific quality
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_specific:
                        info_specific = ydl_specific.extract_info(url, download=False)
                        download_url = info_specific.get("url")
                        if not download_url:
                            logger.warning(f"No URL found for {quality}p")
                            continue

                        size = fmt.get("filesize") or fmt.get("filesize_approx")
                        size_mb = round(size / (1024 * 1024), 2) if size else "Unknown"
                        logger.info(f"Quality: {quality}, URL: {download_url}")

                        # Store in Firebase
                        try:
                            doc_ref = db.collection("video_links").document()
                            doc_ref.set({
                                "url": download_url,
                                "quality": quality,
                                "youtube_link": url,
                                "timestamp": firestore.SERVER_TIMESTAMP
                            })
                        except Exception as e:
                            logger.error(f"Firebase write error: {str(e)}")
                            await update.message.reply_text(f"Error saving {quality}p link.")
                            continue

                        # Smart link button
                        button = InlineKeyboardButton(f"{quality}p ({size_mb} MB)", url=download_url)
                        buttons.append([button])

                if buttons:
                    reply_markup = InlineKeyboardMarkup(buttons)
                    await update.message.reply_text("Choose a quality:", reply_markup=reply_markup)
                else:
                    await update.message.reply_text("No suitable video formats found.")
                    logger.warning("No valid video formats found")
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            await update.message.reply_text(f"Error fetching link: {str(e)}")
    else:
        await update.message.reply_text("Please send a valid YouTube link.")

def main() -> None:
    # Build the application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start polling
    logger.info("Starting bot...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # Ensure clean shutdown
        logger.info("Shutting down bot...")
        import asyncio
        asyncio.run(application.shutdown())

if __name__ == "__main__":
    main()
