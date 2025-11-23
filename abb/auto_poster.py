import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError
from urllib.parse import quote
from audiobookbay.search import search_audiobookbay
from magnet_scraper import get_magnet_data
from pymongo import MongoClient

# Configuration
TOKEN = "80210VGuaI"
AUTO_POST_CHANNEL = -10012  # Your log channel or create a new one
CHECK_INTERVAL = 3600  # Check every hour (in seconds)

# MongoDB
client = MongoClient("mongodb+srv://backuptelegram5:dR10DRL0CTnbfIName=Cluster0")
db = client.audiobookbot
posted_books = db.posted_books  # Track what we've already posted

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutoPoster:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        
    async def get_latest_books(self, limit=5):
        """Get latest books from homepage"""
        try:
            results = search_audiobookbay(page=1)
            return results[:limit] if results else []
        except Exception as e:
            logger.error(f"Error fetching latest books: {e}")
            return []
    
    async def is_already_posted(self, book_link):
        """Check if we've already posted this book"""
        return posted_books.find_one({"link": book_link}) is not None
    
    async def mark_as_posted(self, book_link, title):
        """Mark book as posted"""
        posted_books.insert_one({
            "link": book_link,
            "title": title,
            "posted_at": datetime.utcnow()
        })
    
    async def post_book_to_channel(self, book_data):
        """Post a single book with magnet link to channel"""
        try:
            # Get detailed data including magnet link
            detailed_data = get_magnet_data(book_data['link'])
            
            title = detailed_data.get("title", book_data['title'])
            description = detailed_data.get("description", "")
            magnet_link = detailed_data.get("magnet_link", "")
            image_url = detailed_data.get("image_url", book_data.get('image'))
            
            if magnet_link == "N/A" or not magnet_link:
                logger.warning(f"No magnet link found for: {title}")
                return False
            
            # Prepare caption
            max_caption_length = 1024
            caption = f"🆕 <b>Latest Audiobook</b>\n\n<b>{title}</b>\n\n"
            
            if description and description != "N/A":
                remaining_length = max_caption_length - len(caption) - 100  # Buffer for magnet link
                if len(description) > remaining_length:
                    description = description[:remaining_length] + "..."
                caption += f"{description}\n\n"
            
            # Add magnet link
            webtor_link = f"https://webtor.io/{quote(magnet_link, safe='')}"
            caption += f"🔗 <b>Magnet Link:</b>\n<code>{magnet_link}</code>"
            
            # Create inline keyboard for streaming
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Stream on Webtor", url=webtor_link)],
                [InlineKeyboardButton("📖 View on AudiobookBay", url=book_data['link'])]
            ])
            
            # Send to channel
            if image_url and image_url != "N/A":
                await self.bot.send_photo(
                    chat_id=AUTO_POST_CHANNEL,
                    photo=image_url,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            else:
                await self.bot.send_message(
                    chat_id=AUTO_POST_CHANNEL,
                    text=caption,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            
            logger.info(f"Posted to channel: {title}")
            return True
            
        except TelegramError as e:
            logger.error(f"Telegram error posting {book_data['title']}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error posting {book_data['title']}: {e}")
            return False
    
    async def check_and_post_latest(self):
        """Main function to check for new books and post them"""
        logger.info("Checking for latest audiobooks...")
        
        latest_books = await self.get_latest_books(limit=3)  # Check top 3
        
        new_posts = 0
        for book in latest_books:
            if not await self.is_already_posted(book['link']):
                success = await self.post_book_to_channel(book)
                if success:
                    await self.mark_as_posted(book['link'], book['title'])
                    new_posts += 1
                    # Add delay between posts to avoid rate limiting
                    await asyncio.sleep(5)
        
        if new_posts > 0:
            logger.info(f"Posted {new_posts} new audiobooks")
        else:
            logger.info("No new audiobooks to post")
    
    async def cleanup_old_records(self):
        """Clean up old posted records (older than 30 days)"""
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        result = posted_books.delete_many({"posted_at": {"$lt": cutoff_date}})
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} old records")
    
    async def run_scheduler(self):
        """Main scheduler loop"""
        logger.info(f"Auto-poster started. Checking every {CHECK_INTERVAL} seconds.")
        
        while True:
            try:
                await self.check_and_post_latest()
                
                # Cleanup old records once a day
                if datetime.now().hour == 0:  # Run at midnight
                    await self.cleanup_old_records()
                    
            except Exception as e:
                logger.error(f"Error in scheduler: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)

async def main():
    poster = AutoPoster()
    await poster.run_scheduler()

if __name__ == "__main__":
    asyncio.run(main())
