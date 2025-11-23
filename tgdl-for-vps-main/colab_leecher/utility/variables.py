# copyright 2023 © Xron Trix | https://github.com/Xrontrix10

import os
import platform
from time import time
from datetime import datetime
from pathlib import Path
from pyrogram.types import Message


class ProxyConfig:
    enabled = True
    proxy_type = "socks5"
    url = "tor.socks.ipvanish.com"
    username = "RxA6fFnT"
    password = "FNNI12SXAS"


class BOT:
    SOURCE = []
    TASK = None
    
    class Setting:
        stream_upload = "Media"
        convert_video = "Yes"
        convert_quality = "Low"
        caption = "Monospace"
        split_video = "Split Videos"
        prefix = ""
        suffix = ""
        thumbnail = False

    class Options:
        stream_upload = True
        convert_video = True
        convert_quality = False
        is_split = True
        caption = "code"
        video_out = "mp4"
        custom_name = ""
        zip_pswd = ""
        unzip_pswd = ""

    class Mode:
        mode = "leech"
        type = "normal"
        ytdl = False

    class State:
        started = False
        task_going = False
        prefix = False
        suffix = False


class YTDL:
    header = ""
    speed = ""
    percentage = 0.0
    eta = ""
    done = ""
    left = ""


class Transfer:
    down_bytes = [0, 0]
    up_bytes = [0, 0]
    total_down_size = 0
    sent_file = []
    sent_file_names = []


class TaskError:
    state = False
    text = ""


class BotTimes:
    current_time = time()
    start_time = datetime.now()
    task_start = datetime.now()


class Paths:
    # Detect environment and set appropriate paths
    _is_colab = os.path.exists('/content')
    _is_windows = platform.system() == 'Windows'
    
    # Base paths
    if _is_colab:
        # Google Colab environment
        BASE_PATH = "/content/tgdl"
        WORK_PATH = "/content/tgdl/BOT_WORK"
        MOUNTED_DRIVE = "/content/drive"
        access_token = "/content/token.pickle"
    elif _is_windows:
        # Windows VPS/local
        BASE_PATH = os.path.join(os.path.expanduser("~"), "tgdl")
        WORK_PATH = os.path.join(BASE_PATH, "BOT_WORK")
        MOUNTED_DRIVE = os.path.join(BASE_PATH, "gdrive")
        access_token = os.path.join(BASE_PATH, "token.pickle")
    else:
        # Linux VPS/server
        BASE_PATH = os.path.join(os.path.expanduser("~"), "tgdl")
        WORK_PATH = os.path.join(BASE_PATH, "BOT_WORK")
        MOUNTED_DRIVE = os.path.join(BASE_PATH, "gdrive")
        access_token = os.path.join(BASE_PATH, "token.pickle")
    
    # Derived paths
    THMB_PATH = os.path.join(BASE_PATH, "colab_leecher", "Thumbnail.jpg")
    VIDEO_FRAME = os.path.join(WORK_PATH, "video_frame.jpg")
    HERO_IMAGE = os.path.join(WORK_PATH, "Hero.jpg")
    DEFAULT_HERO = os.path.join(BASE_PATH, "custom_thmb.jpg")
    
    down_path = os.path.join(WORK_PATH, "Downloads")
    temp_dirleech_path = os.path.join(WORK_PATH, "dir_leech_temp")
    mirror_dir = os.path.join(MOUNTED_DRIVE, "MyDrive", "Downloads", "tgdl") if _is_colab else os.path.join(MOUNTED_DRIVE, "Downloads", "tgdl")
    temp_zpath = os.path.join(WORK_PATH, "Leeched_Files")
    temp_unzip_path = os.path.join(WORK_PATH, "Unzipped_Files")
    temp_files_dir = os.path.join(WORK_PATH, "leech_temp")
    thumbnail_ytdl = os.path.join(WORK_PATH, "ytdl_thumbnails")
    
    @classmethod
    def initialize_paths(cls):
        """Create all necessary directories if they don't exist"""
        paths_to_create = [
            cls.BASE_PATH,
            cls.WORK_PATH,
            cls.down_path,
            cls.temp_dirleech_path,
            cls.temp_zpath,
            cls.temp_unzip_path,
            cls.temp_files_dir,
            cls.thumbnail_ytdl,
            os.path.dirname(cls.THMB_PATH),  # colab_leecher directory
        ]
        
        for path in paths_to_create:
            try:
                os.makedirs(path, exist_ok=True)
                print(f"✅ Created/verified directory: {path}")
            except Exception as e:
                print(f"❌ Failed to create directory {path}: {e}")
        
        # Create mounted drive directory but don't fail if it can't be created
        try:
            os.makedirs(cls.MOUNTED_DRIVE, exist_ok=True)
            print(f"✅ Created/verified drive directory: {cls.MOUNTED_DRIVE}")
        except Exception as e:
            print(f"⚠️  Warning: Could not create drive directory {cls.MOUNTED_DRIVE}: {e}")
    
    @classmethod
    def get_environment_info(cls):
        """Get information about the current environment"""
        return {
            "is_colab": cls._is_colab,
            "is_windows": cls._is_windows,
            "platform": platform.system(),
            "base_path": cls.BASE_PATH,
            "work_path": cls.WORK_PATH,
            "mounted_drive": cls.MOUNTED_DRIVE
        }


class Messages:
    caution_msg = "\n\n<i>💖 When I'm Doin This, Do Something Else ! <b>Because, Time Is Precious ✨</b></i>"
    download_name = ""
    task_msg = ""
    status_head = f"<b>📥 DOWNLOADING » </b>\n"
    dump_task = ""
    src_link = ""
    link_p = ""


class MSG:
    sent_msg = Message(id=1)
    status_msg = Message(id=2)


class Aria2c:
    link_info = False
    pic_dwn_url = "https://picsum.photos/900/600"


class Gdrive:
    service = None


# Initialize paths when module is imported
try:
    Paths.initialize_paths()
    env_info = Paths.get_environment_info()
    print(f"🚀 Environment detected: {env_info['platform']}")
    print(f"📁 Working directory: {env_info['work_path']}")
except Exception as e:
    print(f"❌ Error initializing paths: {e}")