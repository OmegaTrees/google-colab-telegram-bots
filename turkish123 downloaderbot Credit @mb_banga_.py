
import os
import sys
import time
import re
import asyncio
import threading
import schedule
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
import subprocess
import shutil
import math
import random
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors.exceptions import FloodWait

# Configuration
BASE_URL = 'https://hds.turkish123.com/'
OUTPUT_DIR = Path('txt_files')
DOWNLOAD_FOLDER = "downloads"
DONE_FOLDER = "done"
TEMP_FOLDER = "temp"
QUEUE_FILE = "drama_queue.json"
MONITORED_FILE = "monitored_dramas.json"

# Browser settings
HEADLESS = True
WAIT_SECONDS = 25
M3U8_RE = re.compile(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', re.IGNORECASE)

# Download settings
MIN_STORAGE_GB = 2
MAX_FILE_SIZE_GB = 1.98
CHUNK_DURATION_MINUTES = 45
EDIT_SLEEP_TIME_OUT = 30

# Telegram Configuration - REPLACE WITH YOUR VALUES
TELEGRAM_API_ID = 2592
TELEGRAM_API_HASH = "82066a5912a"
TELEGRAM_BOT_TOKEN = "794220ya_E"
TELEGRAM_CHAT_ID = -10073
ADMIN_ID = 1817

# Progress display constants
FINISHED_PROGRESS_STR = "█"
UN_FINISHED_PROGRESS_STR = "░"

# Global variables
drama_queue = []
monitored_dramas = {}
active_downloads = {}
cancelled_downloads = set()
bot_status = {
    "processing": False, 
    "current_drama": None, 
    "monitoring": True, 
    "queue_running": False,
    "current_episode": None,
    "total_episodes": 0
}

# Thread pool executor for blocking operations
executor = ThreadPoolExecutor(max_workers=3)

# JavaScript injection for capturing m3u8 links
INJECT_JS = r"""
(() => {
    if (window.__playwright_m3u8_hook_installed) return;
    window.__playwright_m3u8_hook_installed = true;
    const seen = new Set();
    function handle(url) {
        try {
            if (!url) return;
            if (typeof url !== 'string') {
                if (url && url.url) url = url.url;
                else return;
            }
            if (url.includes('.m3u8') && !seen.has(url)) {
                seen.add(url);
                console.log('[PLAYWRIGHT_M3U8]', url);
            }
        } catch(e){}
    }

    const origFetch = window.fetch;
    if (origFetch) {
        window.fetch = function(...args) {
            try { const u = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url); handle(u); } catch(e){}
            return origFetch.apply(this, args);
        };
    }

    const origXOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        try { handle(url); } catch(e){}
        return origXOpen.apply(this, arguments);
    };

    try {
        const proto = HTMLMediaElement.prototype;
        const desc = Object.getOwnPropertyDescriptor(proto, 'src');
        if (desc && desc.set) {
            const origSet = desc.set;
            Object.defineProperty(proto, 'src', {
                set: function(val) {
                    try { handle(val); } catch(e){}
                    return origSet.call(this, val);
                }
            });
        }
    } catch(e){}
})();
"""

@dataclass
class Drama:
    name: str
    url: str
    total_episodes: int
    processed_episodes: int = 0
    last_check: Optional[str] = None
    status: str = "queued"  # queued, processing, completed, monitoring, failed
    added_date: Optional[str] = None
    failed_episodes: List[int] = None
    
    def __post_init__(self):
        if self.failed_episodes is None:
            self.failed_episodes = []

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def save_data():
    """Save queue and monitored dramas to files"""
    try:
        with open(QUEUE_FILE, 'w') as f:
            json.dump([drama.__dict__ for drama in drama_queue], f, indent=2)
        
        with open(MONITORED_FILE, 'w') as f:
            json.dump({k: v.__dict__ for k, v in monitored_dramas.items()}, f, indent=2)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    """Load queue and monitored dramas from files"""
    global drama_queue, monitored_dramas
    
    try:
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, 'r') as f:
                data = json.load(f)
                drama_queue = [Drama(**item) for item in data]
                logger.info(f"Loaded {len(drama_queue)} dramas from queue")
        
        if os.path.exists(MONITORED_FILE):
            with open(MONITORED_FILE, 'r') as f:
                data = json.load(f)
                monitored_dramas = {k: Drama(**v) for k, v in data.items()}
                logger.info(f"Loaded {len(monitored_dramas)} monitored dramas")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def humanbytes(size):
    """Convert bytes to human readable format"""
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: "", 1: "K", 2: "M", 3: "G", 4: "T"}
    while size > power:
        size /= power
        n += 1
    return f"{str(round(size, 2))} {Dic_powerN[n]}B"

def TimeFormatter(milliseconds: int) -> str:
    """Format time in milliseconds to readable format"""
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = (
        ((str(days) + "d, ") if days else "")
        + ((str(hours) + "h, ") if hours else "")
        + ((str(minutes) + "m, ") if minutes else "")
        + ((str(seconds) + "s, ") if seconds else "")
        + ((str(milliseconds) + "ms, ") if milliseconds else "")
    )
    return tmp[:-2]

def get_free_space_gb(path='.'):
    """Get free disk space in GB"""
    try:
        total, used, free = shutil.disk_usage(path)
        free_gb = free / (1024 ** 3)
        return free_gb
    except Exception as e:
        logger.error(f"Error getting disk space: {e}")
        return 0

def wait_for_storage():
    """Wait until there's enough storage space"""
    while True:
        free_space = get_free_space_gb()
        if free_space > MIN_STORAGE_GB:
            break
        else:
            logger.warning(f"Low storage ({free_space:.2f} GB). Waiting...")
            time.sleep(300)

def safe_delete_file(file_path, file_type="file"):
    """Safely delete a file with proper error handling"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_type}: {file_path}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete {file_type} {file_path}: {e}")
        return False

def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries',
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
        return 0
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0

def create_thumbnail(video_path, thumbnail_path):
    """Create a random thumbnail from the video"""
    try:
        duration = get_video_duration(video_path)
        if duration <= 0:
            return False
        
        random_time = random.uniform(duration * 0.1, duration * 0.9)
        
        cmd = [
            'ffmpeg', '-i', video_path, '-ss', str(random_time),
            '-vframes', '1', '-q:v', '2', '-y', thumbnail_path
        ]
        
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error creating thumbnail: {e}")
        return False

def split_video(video_path, temp_folder, episode_name):
    """Split video into chunks if it's larger than MAX_FILE_SIZE_GB"""
    try:
        file_size_gb = os.path.getsize(video_path) / (1024 ** 3)
        
        if file_size_gb <= MAX_FILE_SIZE_GB:
            return [video_path]
        
        logger.info(f"Splitting {video_path} - size: {file_size_gb:.2f} GB")
        os.makedirs(temp_folder, exist_ok=True)
        
        duration = get_video_duration(video_path)
        chunk_duration_seconds = CHUNK_DURATION_MINUTES * 60
        num_chunks = math.ceil(duration / chunk_duration_seconds)
        
        chunk_files = []
        for i in range(num_chunks):
            start_time = i * chunk_duration_seconds
            chunk_filename = f"{episode_name}_part_{i+1:02d}.mp4"
            chunk_path = os.path.join(temp_folder, chunk_filename)
            
            cmd = [
                'ffmpeg', '-i', video_path, '-ss', str(start_time),
                '-t', str(chunk_duration_seconds), '-c', 'copy',
                '-avoid_negative_ts', 'make_zero', '-y', chunk_path
            ]
            
            result = subprocess.run(cmd, capture_output=True)
            
            if result.returncode == 0 and os.path.exists(chunk_path):
                chunk_files.append(chunk_path)
        
        return chunk_files
        
    except Exception as e:
        logger.error(f"Error splitting video: {e}")
        return [video_path]

class Progress:
    """Progress display class for uploads"""
    def __init__(self, from_user, client, mess: Message):
        self._from_user = from_user
        self._client = client
        self._mess = mess
        self._cancelled = False

    @property
    def is_cancelled(self):
        chat_id = self._mess.chat.id
        mes_id = self._mess.id
        return f"{chat_id}_{mes_id}" in cancelled_downloads

    async def progress_for_pyrogram(self, current, total, ud_type, start, count=""):
        chat_id = self._mess.chat.id
        mes_id = self._mess.id
        from_user = self._from_user
        now = time.time()
        diff = now - start
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⛔ Cancel ⛔",
                callback_data=f"cancel_{chat_id}_{mes_id}_{from_user}"
            )]
        ])
        
        if self.is_cancelled:
            await self._mess.edit_text(f"⛔ **Cancelled** ⛔ \n\n `{ud_type}` ({humanbytes(total)})")
            return

        if round(diff % float(EDIT_SLEEP_TIME_OUT)) == 0 or current == total:
            percentage = current * 100 / total
            speed = current / diff
            elapsed_time = round(diff) * 1000
            time_to_completion = round((total - current) / speed) * 1000

            elapsed_time = TimeFormatter(milliseconds=elapsed_time)
            estimated_total_time = TimeFormatter(milliseconds=time_to_completion)

            progress = "\n<code>[{0}{1}] {2}%</code>\n".format(
                "".join([FINISHED_PROGRESS_STR for i in range(math.floor(percentage / 5))]),
                "".join([UN_FINISHED_PROGRESS_STR for i in range(20 - math.floor(percentage / 5))]),
                round(percentage, 2),
            )
            
            tmp = (
                progress
                + "\n**⌧ Total 🗃:**` 〚{1}〛`\n**⌧ Done ✅ :**` 〚{0}〛`\n**⌧ Speed 📊 :** ` 〚{2}/s〛`\n**⌧ ETA 🔃 :**` 〚{3}〛`\n {4}".format(
                    humanbytes(current),
                    humanbytes(total),
                    humanbytes(speed),
                    estimated_total_time if estimated_total_time != "" else "0 s",
                    count
                )
            )
            
            try:
                await self._mess.edit_text(
                    text="{}\\n {}".format(ud_type, tmp), 
                    reply_markup=reply_markup
                )
            except FloodWait as fd:
                await asyncio.sleep(fd.x)
            except Exception as e:
                logger.error(f"Progress update error: {e}")

def search_movies(query):
    """Search for dramas on Turkish123"""
    logger.info(f"Searching for {query}")
    
    my_obj = {
        's': query,
        'action': 'searchwp_live_search',
        'swpengine': 'default',
        'swpquery': query
    }
    
    result = requests.post(BASE_URL + 'wp-admin/admin-ajax.php', data=my_obj).text
    
    if len(result) == 0:
        return []
    
    soup = BeautifulSoup(result, "html.parser")
    drama_titles = soup.find_all('a', {'class': 'ss-title'})
    
    results = []
    for drama_title in drama_titles:
        results.append({
            'name': drama_title.text,
            'url': drama_title['href'].replace("'", "")
        })
    
    return results

def get_episodes_list(movie_detail_url):
    """Get list of episode URLs from drama detail page"""
    try:
        result = requests.get(movie_detail_url).text
        soup = BeautifulSoup(result, "html.parser")
        
        episodes = []
        download_links = soup.find_all(attrs={'class': 'episodi'})
        
        for index, link in enumerate(download_links, 1):
            episode_url = link['href']
            episodes.append({
                'number': index,
                'url': episode_url
            })
        
        return episodes
    except Exception as e:
        logger.error(f"Error getting episodes list: {e}")
        return []

def _extract_stream_link_sync(episode_url):
    """Synchronous function to extract m3u8 stream link (runs in thread pool)"""
    found = set()
    
    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            
            mobile_ua = "Mozilla/5.0 (Android 13; Mobile; rv:120.0) Gecko/120.0 Firefox/120.0"
            context = browser.new_context(
                user_agent=mobile_ua,
                viewport={"width": 412, "height": 915},
                locale="en-US",
                java_script_enabled=True,
            )
            
            context.add_init_script(INJECT_JS)
            page = context.new_page()
            
            def on_response(resp):
                try:
                    url = resp.url
                    if ".m3u8" in url and url not in found:
                        found.add(url)
                    
                    try:
                        body = resp.text(timeout=1000)
                        if body and ".m3u8" in body:
                            for m in M3U8_RE.findall(body):
                                if m not in found:
                                    found.add(m)
                    except Exception:
                        pass
                except Exception:
                    pass
            
            def on_console(msg):
                try:
                    text = msg.text
                    if "[PLAYWRIGHT_M3U8]" in text:
                        url = text.split("[PLAYWRIGHT_M3U8]", 1)[1].strip()
                        if url and url not in found:
                            found.add(url)
                except Exception:
                    pass
            
            page.on("response", on_response)
            page.on("console", on_console)
            
            context.set_extra_http_headers({
                "Referer": "https://hds.turkish123.com/",
                "Accept-Language": "en-US,en;q=0.9"
            })
            
            try:
                page.goto(episode_url, wait_until="domcontentloaded", timeout=30000)
            except PWTimeout:
                pass
            
            time.sleep(1)
            
            try:
                vw = page.viewport_size or {"width": 412, "height": 915}
                w, h = vw["width"], vw["height"]
                page.mouse.move(w*0.45, h*0.45, steps=8)
                page.mouse.click(w*0.5, h*0.5)
                time.sleep(0.3)
                
                play_selectors = [
                    'button[aria-label="Play"]', '.vjs-big-play-button',
                    '.jw-icon-play', '.play-button', '.plyr__play', 'button.play'
                ]
                for sel in play_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            el.click(timeout=1500)
                            time.sleep(0.25)
                    except Exception:
                        pass
            except Exception:
                pass
            
            waited = 0
            while waited < WAIT_SECONDS:
                if found:
                    break
                time.sleep(1)
                waited += 1
            
            try:
                main_html = page.content()
                for m in M3U8_RE.findall(main_html):
                    if m not in found:
                        found.add(m)
            except Exception:
                pass
            
            browser.close()
    except Exception as e:
        logger.error(f"Error extracting stream link: {e}")
    
    return list(found)

async def extract_stream_link(episode_url):
    """Async wrapper to extract m3u8 stream link using thread pool"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _extract_stream_link_sync, episode_url)

def sanitize_filename(name):
    """Sanitize drama name for use in filename"""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.replace(' ', '-').lower()
    return name

async def download_episode(m3u8_url, episode_name, download_folder, status_message):
    """Download episode using yt-dlp"""
    try:
        os.makedirs(download_folder, exist_ok=True)
        output_template = os.path.join(download_folder, f"{episode_name}.%(ext)s")
        
        cmd = [
            'yt-dlp',
            '--no-playlist',
            '--format', 'best',
            '--output', output_template,
            '--no-part',
            '--retries', '3',
            '--fragment-retries', '3',
            m3u8_url
        ]
        
        logger.info(f"Downloading: {episode_name}")
        await status_message.edit_text(f"⬇️ **Downloading**\n\n📺 {episode_name}\n\n⏳ Please wait...")
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        
        last_update = time.time()
        for line in process.stdout:
            if '[download]' in line and '%' in line:
                try:
                    if time.time() - last_update > 5:  # Update every 5 seconds
                        await status_message.edit_text(f"⬇️ **Downloading**\n\n📺 {episode_name}\n\n{line.strip()}")
                        last_update = time.time()
                except:
                    pass
        
        return_code = process.wait()
        
        if return_code == 0:
            for file in os.listdir(download_folder):
                if file.startswith(episode_name):
                    return os.path.join(download_folder, file)
        
        return None
            
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

async def upload_to_telegram(client: Client, file_path: str, episode_name: str, progress_message: Message):
    """Upload file to Telegram"""
    try:
        logger.info(f"Uploading: {os.path.basename(file_path)}")
        
        thumbnail_path = os.path.join(TEMP_FOLDER, f"{episode_name}_thumb.jpg")
        thumbnail_created = create_thumbnail(file_path, thumbnail_path)
        
        duration = int(get_video_duration(file_path))
        
        prog = Progress(ADMIN_ID, client, progress_message)
        c_time = time.time()
        
        sent_message = await client.send_video(
            chat_id=TELEGRAM_CHAT_ID,
            video=file_path,
            duration=duration,
            thumb=thumbnail_path if thumbnail_created else None,
            caption=f"📺 **{episode_name}**",
            progress=prog.progress_for_pyrogram,
            progress_args=(
                f"📤 Uploading: `{os.path.basename(file_path)}`",
                c_time,
            ),
        )
        
        logger.info(f"Successfully uploaded: {os.path.basename(file_path)}")
        
        if thumbnail_created and os.path.exists(thumbnail_path):
            safe_delete_file(thumbnail_path, "thumbnail")
        
        return True
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return False

async def process_and_upload(client: Client, m3u8_url, episode_name, status_message: Message):
    """Download and upload episode"""
    try:
        wait_for_storage()
        
        downloaded_file = await download_episode(m3u8_url, episode_name, DOWNLOAD_FOLDER, status_message)
        
        if not downloaded_file or not os.path.exists(downloaded_file):
            await status_message.edit_text(f"❌ Download failed: {episode_name}")
            return False
        
        await status_message.edit_text(f"✅ Download complete!\n\n📋 Processing for upload...")
        
        chunk_files = split_video(downloaded_file, TEMP_FOLDER, episode_name)
        
        upload_success = True
        
        for i, chunk_file in enumerate(chunk_files, 1):
            if len(chunk_files) > 1:
                await status_message.edit_text(f"📤 Uploading part {i}/{len(chunk_files)}")
            
            success = await upload_to_telegram(
                client, 
                chunk_file, 
                f"{episode_name}_part_{i:02d}" if len(chunk_files) > 1 else episode_name,
                status_message
            )
            
            if not success:
                upload_success = False
            
            if chunk_file.startswith(TEMP_FOLDER):
                safe_delete_file(chunk_file)
        
        if upload_success:
            safe_delete_file(downloaded_file)
            await status_message.edit_text(
                f"✅ **Complete!**\n\n"
                f"📺 {episode_name}\n"
                f"📤 Uploaded to Telegram\n"
                f"🗑️ Cleaned up"
            )
        
        return upload_success
        
    except Exception as e:
        logger.error(f"Process and upload error: {e}")
        return False

async def process_drama(drama: Drama, client: Client):
    """Process all episodes of a drama"""
    try:
        drama.status = "processing"
        bot_status["processing"] = True
        bot_status["current_drama"] = drama.name
        save_data()
        
        logger.info(f"Processing drama: {drama.name}")
        
        await client.send_message(
            ADMIN_ID,
            f"🎬 **Processing Drama**\n\n"
            f"📺 **Name:** {drama.name}\n"
            f"🔗 **URL:** {drama.url}\n"
            f"📊 **Status:** Starting extraction..."
        )
        
        episodes = get_episodes_list(drama.url)
        drama.total_episodes = len(episodes)
        bot_status["total_episodes"] = len(episodes)
        save_data()
        
        if not episodes:
            await client.send_message(ADMIN_ID, f"❌ No episodes found for {drama.name}")
            drama.status = "failed"
            save_data()
            return
        
        sanitized_name = sanitize_filename(drama.name)
        
        for episode in episodes[drama.processed_episodes:]:
            if not bot_status["queue_running"]:
                await client.send_message(
                    ADMIN_ID,
                    f"⏹️ **Queue stopped by user**\n\n"
                    f"📺 {drama.name}\n"
                    f"📊 Progress: {drama.processed_episodes}/{drama.total_episodes} episodes"
                )
                break
            
            episode_num = episode['number']
            episode_url = episode['url']
            
            bot_status["current_episode"] = episode_num
            
            logger.info(f"Processing episode {episode_num}/{len(episodes)}")
            
            status_msg = await client.send_message(
                ADMIN_ID,
                f"📺 **{drama.name}**\n"
                f"🎞️ Episode {episode_num}/{len(episodes)}\n"
                f"🔍 Extracting stream link..."
            )
            
            stream_links = await extract_stream_link(episode_url)
            
            if not stream_links:
                await status_msg.edit_text(f"❌ No stream link found for episode {episode_num}")
                drama.failed_episodes.append(episode_num)
                save_data()
                continue
            
            m3u8_url = stream_links[0]
            
            success = await process_and_upload(
                client,
                m3u8_url,
                f"{sanitized_name}-episode-{episode_num}",
                status_msg
            )
            
            if success:
                drama.processed_episodes = episode_num
                save_data()
            else:
                drama.failed_episodes.append(episode_num)
                save_data()
            
            await asyncio.sleep(3)
        
        if drama.processed_episodes >= drama.total_episodes:
            drama.status = "completed"
            
            # Move to monitoring
            monitored_dramas[drama.name] = drama
            monitored_dramas[drama.name].status = "monitoring"
            
            # Remove from queue
            drama_queue[:] = [d for d in drama_queue if d.name != drama.name]
            
            await client.send_message(
                ADMIN_ID,
                f"🎉 **Drama Complete!**\n\n"
                f"📺 **{drama.name}**\n"
                f"✅ **Episodes:** {drama.processed_episodes}/{drama.total_episodes}\n"
                f"❌ **Failed:** {len(drama.failed_episodes)} episodes\n"
                f"📤 **Uploaded to:** Chat ID {TELEGRAM_CHAT_ID}\n"
                f"👁️ **Added to monitoring for new episodes**"
            )
        
        save_data()
        
    except Exception as e:
        logger.error(f"Error processing drama {drama.name}: {e}")
        drama.status = "failed"
        save_data()
        await client.send_message(ADMIN_ID, f"❌ Error processing {drama.name}: {str(e)}")
    finally:
        bot_status["processing"] = False
        bot_status["current_drama"] = None
        bot_status["current_episode"] = None
        bot_status["total_episodes"] = 0

async def check_for_new_episodes(client: Client):
    """Check monitored dramas for new episodes"""
    try:
        if not monitored_dramas or not bot_status["monitoring"]:
            return
        
        logger.info("🔍 Checking for new episodes...")
        
        for drama_name, drama in list(monitored_dramas.items()):
            try:
                episodes = get_episodes_list(drama.url)
                new_total = len(episodes)
                
                if new_total > drama.total_episodes:
                    new_count = new_total - drama.total_episodes
                    
                    await client.send_message(
                        ADMIN_ID,
                        f"🆕 **New Episodes Detected!**\n\n"
                        f"📺 **{drama.name}**\n"
                        f"➕ **{new_count} new episode(s)**\n"
                        f"📊 **Total:** {new_total} episodes\n"
                        f"📈 **Previous:** {drama.total_episodes} episodes\n\n"
                        f"🚀 **Adding back to queue...**"
                    )
                    
                    # Update drama and add back to queue
                    drama.total_episodes = new_total
                    drama.status = "queued"
                    
                    # Remove from monitored and add to queue
                    del monitored_dramas[drama_name]
                    drama_queue.append(drama)
                    
                    logger.info(f"Added {drama.name} back to queue - {new_count} new episodes")
                
                drama.last_check = datetime.now().isoformat()
                
            except Exception as e:
                logger.error(f"Error checking {drama_name}: {e}")
        
        save_data()
        
    except Exception as e:
        logger.error(f"Error in new episodes check: {e}")

# Initialize Telegram client
app = Client(
    "turkish123_bot",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=TELEGRAM_BOT_TOKEN
)

def admin_only(func):
    """Decorator to restrict commands to admin only"""
    async def wrapper(client: Client, message: Message):
        if message.from_user.id != ADMIN_ID:
            await message.reply_text("❌ You are not authorized to use this bot.")
            return
        return await func(client, message)
    return wrapper

@app.on_message(filters.command("start") & filters.private)
@admin_only
async def start_command(client: Client, message: Message):
    """Start command handler"""
    await message.reply_text(
        f"🎬 **Turkish123 Drama Bot - Improved Queue System**\n\n"
        f"**Upload Destination:** Chat ID `{TELEGRAM_CHAT_ID}`\n\n"
        f"**📋 Queue System:**\n"
        f"• `/search <query>` - Search and add dramas\n"
        f"• `/queue` - View queue\n"
        f"• `/go` - Start processing ALL queued dramas\n"
        f"• `/stop` - Stop processing\n"
        f"• `/clear` - Clear entire queue\n\n"
        f"**👁️ Monitoring:**\n"
        f"• `/monitored` - View monitored dramas\n"
        f"• `/toggle_monitoring` - Enable/disable\n\n"
        f"**📊 Status:**\n"
        f"• `/status` - Check bot status\n\n"
        f"**How it works:**\n"
        f"1️⃣ Use `/search` to find and add dramas to queue\n"
        f"2️⃣ Keep searching and adding more dramas\n"
        f"3️⃣ When ready, use `/go` to process everything\n"
        f"4️⃣ Bot processes all dramas one by one\n"
        f"5️⃣ Completed dramas auto-monitored for new episodes"
    )

@app.on_message(filters.command("search") & filters.private)
@admin_only
async def search_command(client: Client, message: Message):
    """Search command handler - adds to queue"""
    try:
        command_parts = message.text.split(' ', 1)
        if len(command_parts) < 2:
            await message.reply_text(
                "❌ **Please provide a search query**\n\n"
                "**Usage:** `/search drama name`\n\n"
                "**Example:** `/search love is in the air`"
            )
            return
        
        query = command_parts[1].strip()
        status_msg = await message.reply_text(f"🔍 **Searching for:** `{query}`\n\n⏳ Please wait...")
        
        results = search_movies(query)
        
        if not results:
            await status_msg.edit_text(f"❌ **No results found for:** `{query}`\n\nTry a different search term.")
            return
        
        keyboard = []
        for i, result in enumerate(results[:10], 1):
            # Check if already added
            already_added = any(d.name == result['name'] for d in drama_queue)
            already_monitored = result['name'] in monitored_dramas
            
            button_text = result['name'][:45]
            if already_added:
                button_text = f"✅ {button_text}"
            elif already_monitored:
                button_text = f"👁️ {button_text}"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{i}. {button_text}",
                    callback_data=f"add_drama_{i-1}"
                )
            ])
        
        # Store search results temporarily
        app.search_results = results
        
        await status_msg.edit_text(
            f"🔍 **Search Results for:** `{query}`\n\n"
            f"**Found {len(results)} drama(s)**\n\n"
            f"**Select dramas to add to queue:**\n"
            f"✅ = Already in queue\n"
            f"👁️ = Already monitored\n\n"
            f"💡 **Tip:** You can add multiple dramas, then use `/go` to process all!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        await message.reply_text(f"❌ **Error:** {str(e)}")

@app.on_message(filters.command("queue") & filters.private)
@admin_only
async def queue_command(client: Client, message: Message):
    """View queue with management options"""
    if not drama_queue:
        await message.reply_text(
            "📋 **Queue is empty**\n\n"
            "Use `/search <drama name>` to add dramas to the queue.\n\n"
            "**Example:** `/search sen cal kapimi`"
        )
        return
    
    queue_text = f"📋 **Queue - {len(drama_queue)} Drama(s)**\n\n"
    
    keyboard = []
    for i, drama in enumerate(drama_queue, 1):
        status_emoji = {
            "queued": "⏳",
            "processing": "🔄",
            "completed": "✅",
            "failed": "❌"
        }.get(drama.status, "❓")
        
        queue_text += (
            f"{i}. {status_emoji} **{drama.name}**\n"
            f"   📊 Progress: {drama.processed_episodes}/{drama.total_episodes or '?'} episodes\n"
            f"   📅 Status: {drama.status.title()}\n"
        )
        
        if drama.failed_episodes:
            queue_text += f"   ❌ Failed: {len(drama.failed_episodes)} episodes\n"
        
        queue_text += "\n"
        
        # Add remove button if not currently processing
        if drama.status != "processing":
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ Remove: {drama.name[:30]}",
                    callback_data=f"remove_drama_{i-1}"
                )
            ])
    
    # Add control buttons
    control_buttons = []
    
    if not bot_status["queue_running"]:
        control_buttons.append(
            InlineKeyboardButton("🚀 Start All (/go)", callback_data="start_all")
        )
    else:
        control_buttons.append(
            InlineKeyboardButton("⏹️ Stop Queue", callback_data="stop_all")
        )
    
    if len(drama_queue) > 0 and not bot_status["processing"]:
        control_buttons.append(
            InlineKeyboardButton("🗑️ Clear All", callback_data="clear_all")
        )
    
    if control_buttons:
        keyboard.append(control_buttons)
    
    queue_text += f"\n**Status:** {'🔄 Processing' if bot_status['queue_running'] else '⏸️ Ready to start'}"
    
    if bot_status["current_drama"]:
        queue_text += f"\n**Current:** {bot_status['current_drama']}"
        if bot_status["current_episode"]:
            queue_text += f" (Ep {bot_status['current_episode']}/{bot_status['total_episodes']})"
    
    await message.reply_text(queue_text, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

@app.on_message(filters.command("go") & filters.private)
@admin_only
async def go_command(client: Client, message: Message):
    """Start processing all queued dramas"""
    if bot_status["processing"] or bot_status["queue_running"]:
        await message.reply_text(
            "⚠️ **Already processing!**\n\n"
            f"Current drama: {bot_status['current_drama']}\n"
            f"Use `/stop` to stop processing."
        )
        return
    
    if not drama_queue:
        await message.reply_text(
            "📋 **Queue is empty!**\n\n"
            "Add dramas using `/search <drama name>` first."
        )
        return
    
    bot_status["queue_running"] = True
    save_data()
    
    # Count total episodes
    total_dramas = len(drama_queue)
    queued_dramas = [d for d in drama_queue if d.status == "queued"]
    
    await message.reply_text(
        f"🚀 **Queue Processing Started!**\n\n"
        f"📋 **Total dramas:** {total_dramas}\n"
        f"⏳ **Queued:** {len(queued_dramas)}\n"
        f"📤 **Upload to:** Chat ID `{TELEGRAM_CHAT_ID}`\n\n"
        f"🔄 **Processing will begin shortly...**\n"
        f"⏹️ **Use `/stop` to stop at any time**"
    )
    
    # Start processing in background
    asyncio.create_task(process_all_dramas(client))

@app.on_message(filters.command("stop") & filters.private)
@admin_only
async def stop_command(client: Client, message: Message):
    """Stop processing queue"""
    if not bot_status["queue_running"]:
        await message.reply_text("⚠️ **Queue is not running.**")
        return
    
    bot_status["queue_running"] = False
    save_data()
    
    await message.reply_text(
        f"⏹️ **Queue Processing Stopped!**\n\n"
        f"⚠️ **Current episode will finish, then stop.**\n"
        f"📊 **Progress saved automatically**\n\n"
        f"Use `/go` to resume processing."
    )

@app.on_message(filters.command("clear") & filters.private)
@admin_only
async def clear_command(client: Client, message: Message):
    """Clear the entire queue"""
    if bot_status["processing"]:
        await message.reply_text(
            "⚠️ **Cannot clear while processing!**\n\n"
            "Use `/stop` first, then try again."
        )
        return
    
    if not drama_queue:
        await message.reply_text("📋 **Queue is already empty.**")
        return
    
    count = len(drama_queue)
    drama_queue.clear()
    save_data()
    
    await message.reply_text(
        f"🗑️ **Queue Cleared!**\n\n"
        f"Removed {count} drama(s) from queue."
    )

@app.on_message(filters.command("status") & filters.private)
@admin_only
async def status_command(client: Client, message: Message):
    """Detailed bot status"""
    free_space = get_free_space_gb()
    
    status_text = (
        f"🤖 **Bot Status Dashboard**\n\n"
        f"**📤 Upload Destination**\n"
        f"└ Chat ID: `{TELEGRAM_CHAT_ID}`\n\n"
        f"**📋 Queue Status**\n"
        f"└ Dramas in queue: {len(drama_queue)}\n"
        f"└ Queue running: {'✅ Yes' if bot_status['queue_running'] else '❌ No'}\n"
        f"└ Currently processing: {'✅ Yes' if bot_status['processing'] else '❌ No'}\n\n"
    )
    
    if bot_status["current_drama"]:
        status_text += (
            f"**🔄 Current Processing**\n"
            f"└ Drama: {bot_status['current_drama']}\n"
        )
        if bot_status["current_episode"]:
            status_text += f"└ Episode: {bot_status['current_episode']}/{bot_status['total_episodes']}\n"
        status_text += "\n"
    
    status_text += (
        f"**👁️ Monitoring**\n"
        f"└ Status: {'✅ Enabled' if bot_status['monitoring'] else '❌ Disabled'}\n"
        f"└ Monitored dramas: {len(monitored_dramas)}\n\n"
        f"**💾 System**\n"
        f"└ Free space: {free_space:.2f} GB\n"
        f"└ Min required: {MIN_STORAGE_GB} GB\n"
        f"└ Max file size: {MAX_FILE_SIZE_GB} GB\n\n"
        f"**Commands:**\n"
        f"• `/search` - Add dramas\n"
        f"• `/queue` - View queue\n"
        f"• `/go` - Start processing\n"
        f"• `/stop` - Stop processing"
    )
    
    await message.reply_text(status_text)

@app.on_message(filters.command("monitored") & filters.private)
@admin_only
async def monitored_command(client: Client, message: Message):
    """View monitored dramas"""
    if not monitored_dramas:
        await message.reply_text(
            "👁️ **No dramas being monitored**\n\n"
            "Complete a drama to start auto-monitoring for new episodes."
        )
        return
    
    monitored_text = f"👁️ **Monitored Dramas - {len(monitored_dramas)}**\n\n"
    keyboard = []
    
    for name, drama in monitored_dramas.items():
        last_check = drama.last_check or "Never"
        if drama.last_check:
            try:
                check_time = datetime.fromisoformat(drama.last_check)
                last_check = check_time.strftime("%m/%d %H:%M")
            except:
                pass
        
        monitored_text += (
            f"📺 **{name}**\n"
            f"   📊 Episodes: {drama.processed_episodes}/{drama.total_episodes}\n"
            f"   📅 Last check: {last_check}\n\n"
        )
        
        keyboard.append([
            InlineKeyboardButton(
                f"🗑️ Remove: {name[:30]}",
                callback_data=f"unmonitor_{name}"
            )
        ])
    
    next_check = datetime.now() + timedelta(hours=3)
    monitored_text += (
        f"\n🔄 **Next check:** {next_check.strftime('%H:%M')}\n"
        f"⚙️ **Check interval:** Every 3 hours"
    )
    
    await message.reply_text(
        monitored_text, 
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

@app.on_message(filters.command("toggle_monitoring") & filters.private)
@admin_only
async def toggle_monitoring_command(client: Client, message: Message):
    """Toggle automatic monitoring"""
    bot_status["monitoring"] = not bot_status["monitoring"]
    status = "enabled" if bot_status["monitoring"] else "disabled"
    
    await message.reply_text(
        f"👁️ **Monitoring {status.upper()}**\n\n"
        f"{'🔄 Will check for new episodes every 3 hours' if bot_status['monitoring'] else '⏸️ No automatic checks will be performed'}\n\n"
        f"**Monitored dramas:** {len(monitored_dramas)}"
    )

@app.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Handle all callback queries"""
    try:
        data = callback_query.data
        
        # Add drama to queue
        if data.startswith("add_drama_"):
            index = int(data.split("_")[-1])
            
            if hasattr(app, 'search_results') and index < len(app.search_results):
                selected = app.search_results[index]
                
                # Check if already exists
                if any(d.name == selected['name'] for d in drama_queue):
                    await callback_query.answer("⚠️ Already in queue!", show_alert=True)
                    return
                
                if selected['name'] in monitored_dramas:
                    await callback_query.answer("⚠️ Already being monitored!", show_alert=True)
                    return
                
                # Create and add drama
                drama = Drama(
                    name=selected['name'],
                    url=selected['url'],
                    total_episodes=0,
                    status="queued",
                    added_date=datetime.now().isoformat()
                )
                
                drama_queue.append(drama)
                save_data()
                
                await callback_query.answer("✅ Added to queue!", show_alert=False)
                await callback_query.edit_message_text(
                    f"✅ **Added to Queue!**\n\n"
                    f"📺 **Drama:** {drama.name}\n"
                    f"📋 **Queue Position:** #{len(drama_queue)}\n"
                    f"📤 **Upload to:** Chat ID `{TELEGRAM_CHAT_ID}`\n\n"
                    f"**Options:**\n"
                    f"• `/search` - Add more dramas\n"
                    f"• `/queue` - View queue\n"
                    f"• `/go` - Start processing all"
                )
        
        # Remove drama from queue
        elif data.startswith("remove_drama_"):
            index = int(data.split("_")[-1])
            
            if 0 <= index < len(drama_queue):
                removed = drama_queue.pop(index)
                save_data()
                
                await callback_query.answer("🗑️ Removed!", show_alert=False)
                await callback_query.edit_message_text(
                    f"🗑️ **Removed from Queue**\n\n"
                    f"📺 **{removed.name}**\n\n"
                    f"Use `/queue` to view current queue."
                )
        
        # Start processing all
        elif data == "start_all":
            if bot_status["processing"] or bot_status["queue_running"]:
                await callback_query.answer("⚠️ Already running!", show_alert=True)
                return
            
            if not drama_queue:
                await callback_query.answer("📋 Queue is empty!", show_alert=True)
                return
            
            bot_status["queue_running"] = True
            save_data()
            
            await callback_query.answer("🚀 Starting...", show_alert=False)
            await callback_query.edit_message_text(
                f"🚀 **Processing Started!**\n\n"
                f"📋 Processing {len(drama_queue)} drama(s)\n"
                f"⏹️ Use `/stop` to stop"
            )
            
            asyncio.create_task(process_all_dramas(client))
        
        # Stop processing
        elif data == "stop_all":
            bot_status["queue_running"] = False
            save_data()
            
            await callback_query.answer("⏹️ Stopping...", show_alert=False)
            await callback_query.edit_message_text(
                f"⏹️ **Stopped!**\n\n"
                f"Current episode will finish.\n"
                f"Use `/go` to resume."
            )
        
        # Clear entire queue
        elif data == "clear_all":
            if bot_status["processing"]:
                await callback_query.answer("⚠️ Cannot clear while processing!", show_alert=True)
                return
            
            count = len(drama_queue)
            drama_queue.clear()
            save_data()
            
            await callback_query.answer("🗑️ Cleared!", show_alert=False)
            await callback_query.edit_message_text(
                f"🗑️ **Queue Cleared!**\n\n"
                f"Removed {count} drama(s)."
            )
        
        # Remove from monitoring
        elif data.startswith("unmonitor_"):
            drama_name = data[10:]  # Remove "unmonitor_" prefix
            
            if drama_name in monitored_dramas:
                del monitored_dramas[drama_name]
                save_data()
                
                await callback_query.answer("🗑️ Removed from monitoring!", show_alert=False)
                await callback_query.edit_message_text(
                    f"🗑️ **Removed from Monitoring**\n\n"
                    f"📺 **{drama_name}**\n\n"
                    f"No longer checking for new episodes."
                )
        
        # Cancel upload/download
        elif data.startswith("cancel_"):
            parts = data.split("_")
            if len(parts) >= 4:
                chat_id = parts[1]
                mes_id = parts[2]
                cancelled_downloads.add(f"{chat_id}_{mes_id}")
                await callback_query.answer("❌ Cancelled!", show_alert=True)
        
        else:
            await callback_query.answer()
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        try:
            await callback_query.answer("❌ Error occurred!", show_alert=True)
        except:
            pass

async def process_all_dramas(client: Client):
    """Process all dramas in queue sequentially"""
    try:
        logger.info("Starting queue processing...")
        
        processed_count = 0
        failed_count = 0
        
        while bot_status["queue_running"]:
            # Find next queued drama
            next_drama = None
            for drama in drama_queue:
                if drama.status == "queued":
                    next_drama = drama
                    break
            
            if not next_drama:
                # No more queued dramas
                break
            
            # Process the drama
            await process_drama(next_drama, client)
            
            if next_drama.status == "completed":
                processed_count += 1
            else:
                failed_count += 1
            
            # Small delay between dramas
            await asyncio.sleep(5)
        
        # Processing complete
        bot_status["queue_running"] = False
        save_data()
        
        remaining = len([d for d in drama_queue if d.status == "queued"])
        
        await client.send_message(
            ADMIN_ID,
            f"✅ **Queue Processing Complete!**\n\n"
            f"📊 **Summary:**\n"
            f"✅ Completed: {processed_count}\n"
            f"❌ Failed: {failed_count}\n"
            f"⏳ Remaining: {remaining}\n\n"
            f"👁️ **Monitoring:** {len(monitored_dramas)} drama(s)\n\n"
            f"{'⚠️ Use `/go` to process remaining dramas' if remaining > 0 else '🎉 All dramas processed!'}"
        )
        
        logger.info(f"Queue processing complete: {processed_count} completed, {failed_count} failed")
        
    except Exception as e:
        logger.error(f"Queue processing error: {e}")
        bot_status["queue_running"] = False
        save_data()
        
        await client.send_message(
            ADMIN_ID,
            f"❌ **Queue Processing Error**\n\n"
            f"Error: {str(e)}\n\n"
            f"Use `/status` to check current state."
        )

async def monitoring_task():
    """Background task to check for new episodes every 3 hours"""
    await asyncio.sleep(60)  # Wait 1 minute after startup
    
    while True:
        try:
            if bot_status["monitoring"] and not bot_status["processing"]:
                logger.info("Running monitoring check...")
                await check_for_new_episodes(app)
            
            # Wait 3 hours
            await asyncio.sleep(3 * 60 * 60)
            
        except Exception as e:
            logger.error(f"Monitoring task error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute before retrying

async def main():
    """Main function"""
    try:
        # Load saved data
        load_data()
        
        # Create directories
        for folder in [OUTPUT_DIR, DOWNLOAD_FOLDER, DONE_FOLDER, TEMP_FOLDER]:
            os.makedirs(folder, exist_ok=True)
        
        # Start the bot
        await app.start()
        logger.info("✅ Bot started successfully")
        
        # Send startup message
        try:
            startup_msg = (
                f"🚀 **Bot Started Successfully!**\n\n"
                f"📤 **Upload to:** Chat ID `{TELEGRAM_CHAT_ID}`\n"
                f"👤 **Admin:** User ID `{ADMIN_ID}`\n\n"
                f"📋 **Queue:** {len(drama_queue)} drama(s)\n"
                f"👁️ **Monitoring:** {len(monitored_dramas)} drama(s)\n"
                f"💾 **Free space:** {get_free_space_gb():.2f} GB\n\n"
            )
            
            if drama_queue:
                queued = len([d for d in drama_queue if d.status == "queued"])
                if queued > 0:
                    startup_msg += f"⚠️ **{queued} drama(s) in queue!**\nUse `/go` to start processing.\n\n"
            
            startup_msg += "✅ **Ready to receive commands!**"
            
            await app.send_message(ADMIN_ID, startup_msg)
        except Exception as e:
            logger.error(f"Could not send startup message: {e}")
        
        # Start monitoring task
        monitoring_task_handle = asyncio.create_task(monitoring_task())
        logger.info("✅ Monitoring task started")
        
        # Keep the bot running
        await idle()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Main error: {e}")
    finally:
        await app.stop()
        logger.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
