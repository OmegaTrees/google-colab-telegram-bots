"""Download all reddit posts on a users page.
This is a basic script I mashed together. Nothing else I found seemed to
work well, so I added support for all the media types I came across.
The code isn't particularly clean or optimised, but it gets the job done.

What you need to do:
    - Create `rdl-user.bat` file and put it on the system path:
        @echo off
        py "%~dp0%~n0.py" %*

    - You will need to request your own Imgur API key.

    - Optionally place a "cookies.txt" file in the folder for yt-dlp to
        use, but be warned that there are reports accounts being banned.

Usage:
    Call `rdl-user username` to download all photos/videos.
    It will download to `current_dir/username/filename.ext`.
    An SQLite database saved in the same folder is used to ignore
    duplicate urls and file hashes.

Requirements:
    yt-dlp
    redvid
"""

import os
import logging
import hashlib
import requests
import sqlite3
import sys
from typing import Optional

import pywintypes, win32file, win32con
import redvid
import yt_dlp


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.basicConfig()

IMGUR_CLIENT_ID = '<fill in your API key here>'

IMGUR_API_URL = 'https://api.imgur.com/3/album/{album_id}/images'

REDDIT_API_URL = "https://www.reddit.com/user/{username}/submitted.json"

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36'


def set_file_time(fname, newtime):
    if fname is None:
        return

    wintime = pywintypes.Time(newtime)
    winfile = win32file.CreateFile(
        fname, win32con.GENERIC_WRITE,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL, None)
    win32file.SetFileTime(winfile, wintime, wintime, wintime)
    winfile.close()


def remap_url(url):
    if 'imgur' in url:
        url = url.split('?')[0]
    if 'preview.redd.it' in url:
        return f'https://i.redd.it/{url.rsplit("/", 1)[-1].split("?", 1)[0]}'
    if 'i.imgur.com' in url and '.gifv' in url:
        return url.replace('.gifv', '.mp4')
    return url


def generate_hash(data: str | bytes) -> str:
    if not isinstance(data, bytes) and os.path.exists(data):
        with open(data, 'rb') as f:
            data = f.read()
    return hashlib.md5(data).hexdigest()


def list_imgur_album(album_url):
    # Extract the album ID from the URL
    album_id = album_url.rstrip('/').rsplit('/', 1)[-1]

    # Set the headers for Imgur API request
    headers = {
        'Authorization': f'Client-ID {IMGUR_CLIENT_ID}',
        'User-Agent': USER_AGENT,
    }

    # Send a GET request to the Imgur API endpoint
    url = IMGUR_API_URL.format(album_id=album_id)
    response = requests.get(url, headers=headers)

    # Check if the request was successful (status code 200)
    if response.status_code == 404:
        logger.debug('Album not found')
        return
    if response.status_code >= 300:
        raise RuntimeError(f'got status code for {url}: {response.status_code}')

    # Extract the JSON data from the response
    data = response.json()

    # Loop through the images in the album
    for image in data['data']:
        yield image


def download_youtube(youtube_url, download_dir):
    logger.debug('Downloading %s...', youtube_url)

    # Set options for the downloader
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
        'cookiefile': 'cookies.txt',
    }
    # Disabled as this potentially gets accounts banned
    # if not os.path.exists('cookies.txt'):
    #     ydl_opts['cookiesfrombrowser'] = (YT_DLP_BROWSER, YT_DLP_BROWSER_DIR)

    # Create a YouTubeDL object
    ydl = yt_dlp.YoutubeDL(ydl_opts)
    ydl.cookiejar.save()

    try:
        info = ydl.extract_info(youtube_url, download=False)
        path = ydl.prepare_filename(info)

        if os.path.exists(path):
            logger.info('%s already exists', path)
            return None

        # Download the video
        ydl.download([youtube_url])

    except yt_dlp.utils.DownloadError as e:
        if 'Private video' in str(e):
            logger.debug('Private video')
            return None
        elif 'This video has been disabled' in str(e):
            logger.debug('Disabled video')
            return None
        elif 'Unable to download webpage: HTTP Error 404: Not Found' in str(e):
            logger.debug('Deleted video')
            return None
        elif 'This video is no longer available because the YouTube account associated with this video has been terminated.' in str(e):
            logger.debug('Deleted account')
            return None
        elif 'Video unavailable' in str(e):
            logger.debug('Unavailable video')
            return None
        elif '404: Not Found' in str(e):
            logger.debug('Video not found')
            return None
        elif 'HTTP Error 410: Gone' in str(e):
            logger.debug('Video gone')
            return None
        else:
            raise

    logger.info('Downloaded %s to %s', youtube_url, path)
    return path


class UserDatabase(object):
    def __init__(self, path, autocommit=1):
        self.path = path
        self.conn = self.cursor = None
        self.count = 0
        self.autocommit = autocommit

    def __enter__(self):
        self.conn = sqlite3.connect(self.path)
        self.cursor = self.conn.cursor()
        self.create_table()
        return self

    def __exit__(self, *args):
        if any(args):
            return False
        if self.autocommit:
            self.conn.commit()
        self.conn.close()

    def commit(self):
        self.conn.commit()

    def create_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT NOT NULL,
                created_at INT,
                title TEXT,
                author TEXT,
                subreddit TEXT,
                filename TEXT,
                media_url TEXT,
                media_hash BLOB
            )
        ''')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_id ON posts (post_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_hash ON posts (media_hash)')

        # Write the "removed" imgur image to use for hash checks
        if not self.url_exists('https://i.imgur.com/removed.png'):
            response = requests.get('https://i.imgur.com/removed.png', headers={'User-Agent': USER_AGENT})
            if response.status_code < 300:
                media_hash = generate_hash(response.content)
            else:
                media_hash = 'd835884373f4d6c8f24742ceabe74946'  # It should be this but better to check if possible

            self.insert(
                post_id='',
                title='',
                created_at=0,
                subreddit='',
                filename='',
                author='',
                media_url='https://i.imgur.com/removed.png',
                media_hash=media_hash,
            )

    def insert(self, post_id: str, created_at: int, author: str, title: str, subreddit: str, filename: str, media_url: str, media_hash: bytes):
        self.cursor.execute('''
            INSERT INTO posts (post_id, title, author, subreddit, created_at, filename, media_url, media_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (post_id, title, author, subreddit, created_at, filename, media_url, media_hash))
        self.count += 1

        if not self.count % self.autocommit:
            self.conn.commit()

    def hash_exists(self, hash):
        if not hash:
            return False
        self.cursor.execute('SELECT EXISTS(SELECT 1 FROM posts WHERE media_hash = ?)', (hash,))
        return self.cursor.fetchone()[0]

    def url_exists(self, url):
        if not url:
            return False
        self.cursor.execute('SELECT EXISTS(SELECT 1 FROM posts WHERE media_url = ?)', (url,))
        return self.cursor.fetchone()[0]

    def filename_from_url(self, url):
        self.cursor.execute('SELECT filename FROM posts WHERE media_url = ?', (url,))
        return self.cursor.fetchone()[0]

    def delete_url(self, url):
        self.cursor.execute('DELETE FROM posts WHERE media_url = ?', (url,))
        return bool(self.cursor.rowcount)


class UserDownloader(object):
    API_URL = 'https://www.reddit.com/user/{username}/submitted.json'

    def __init__(self, username, path=os.getcwd()):
        self.username = username
        self.path = path

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path):
        if self.username != os.path.split(path)[-1]:
            path = os.path.join(path, self.username)
        self._path = path
        if not os.path.exists(self._path):
            os.makedirs(self._path)

    @property
    def url(self):
        return f'https://www.reddit.com/user/{self.username}/submitted.json'

    def fetch_posts(self):
        params = {'limit': 100}

        # Send GET requests to the Reddit API until all posts are retrieved
        while True:
            # Send GET request to the Reddit API
            logger.info('Fetching data: %s?%s', REDDIT_API_URL.format(username=self.username), '&'.join(f'{k}={v}' for k, v in params.items()))
            response = requests.get(REDDIT_API_URL.format(username=self.username), params=params, headers={'User-Agent': USER_AGENT})

            if response.status_code == 403: # Deleted account
                return
            if response.status_code >= 300:
                raise RuntimeError(response.json()['message'])

            data = response.json()['data']
            yield from data['children']

            # Check if there are more posts to retrieve
            if not data.get('after'):
                break
            params['after'] = data['after']


    def download(self, refresh_items=None):
        """Perform the download.

        Parameters:
            refresh_items: List of strings to trigger a redownload for.
                For example this could be the youtube video ID or Imgur image ID.
        """
        refresh_items = {item.lower() for item in refresh_items or ()}

        with UserDatabase(os.path.join(self.path, '.metadata.v1.db')) as db:

            for post in self.fetch_posts():

                files = {}
                data = post['data']
                #logger.debug('Processing https://www.reddit.com%s (%s)...', data['permalink'], data['title']),

                # Handle crossposts
                while data.get('crosspost_parent_list'):
                    data = data['crosspost_parent_list'][0]

                media_url = data.get('url_overridden_by_dest')
                if not media_url:
                    logger.debug('Post has no link')
                    continue

                media_url = remap_url(media_url)
                logger.debug('Downloading %s...', media_url)
                if db.url_exists(media_url):
                    for item in refresh_items:
                        if item in media_url.lower():
                            refresh_items.remove(item)
                            logger.info('Removing existing URL contents')
                            old_filename = db.filename_from_url(media_url)
                            db.delete_url(media_url)
                            os.remove(os.path.join(self.path, old_filename))
                            break

                    else:
                        logger.debug('Duplicate URL detected')
                        continue

                if 'v.redd.it' in media_url:
                    d = redvid.Downloader(url=media_url, path=self.path, max_q=True)
                    d.download()
                    d.clean_temp()
                    logger.info('Downloaded %s to %s', media_url, d.file_name)
                    files[media_url] = (d.file_name, hash, data, True)

                elif 'i.imgur.com' in media_url or 'i.redd.it' in media_url:
                    result = self.dl_raw_data(media_url, db)
                    if result is not None:
                        path, hash = result
                        files[media_url] = (path, hash, data, True)

                elif 'imgur.com/a/' in media_url:
                    files[media_url] = (None, '', data, True)
                    for image in list_imgur_album(media_url):
                        image_url = image["link"]
                        image_id = image["id"]
                        image_ext = image["type"].split("/")[-1]
                        if image_ext.lower() == 'jpeg':
                            image_ext = 'jpg'

                        # Send a GET request to download the image
                        response = requests.get(image_url, headers={'User-Agent': USER_AGENT})
                        if response.status_code >= 300:
                            raise RuntimeError(f'got status code: {response.status_code}')

                        hash = generate_hash(response.content)
                        if db.hash_exists(hash):
                            logger.debug('Duplicate hash detected')
                            files[media_url] = ('', hash, data, True)

                        else:
                            # Write the image
                            path = os.path.join(self.path, f'{image_id}.{image_ext}')
                            logger.debug('Saving to %s...', path)
                            with open(path, 'wb') as file:
                                file.write(response.content)
                            logger.info('Downloaded %s to %s', image_url, path)
                            files[image_url] = (path, hash, data, True)

                elif 'reddit.com/gallery' in media_url:
                    files[media_url] = (None, '', data, True)
                    if 'gallery_data' not in data:
                        logger.debug('Post is private')
                        continue
                    if data['gallery_data'] is None:
                        logger.debug('Post was removed')
                        continue

                    for item in data['gallery_data']['items']:
                        url = f'https://i.redd.it/{item["media_id"]}.jpg'
                        result = self.dl_raw_data(url, db)
                        if result is not None:
                            path, hash = result
                            files[url] = (path, hash, data, True)

                elif 'redgifs.com' in media_url:
                    # Send a GET request to the RedGifs URL
                    response = requests.get(media_url, headers={'User-Agent': USER_AGENT})
                    # Check if the request was successful (status code 200)
                    if response.status_code in (404, 410):
                        files[media_url] = (None, None, data, True)
                        logger.debug('Redgif was deleted')

                    elif response.status_code >= 300:
                        raise RuntimeError(f'got status code: {response.status_code}')

                    else:
                        # Find the video URL in the HTML response
                        #video_url = re.match('.*"contentUrl":"(.*)".*', response.text).group(1)
                        start_index = response.text.find('"contentUrl":') + len('"contentUrl":"')
                        video_url = response.text[start_index:].split('"', 1)[0]
                        # 'https://api.redgifs.com/v2/gifs/meagervillainousapatosaur/files/MeagerVillainousApatosaur.mp4'

                        # Extract the filename from the URL
                        filename = video_url.split('/')[-1]
                        path = os.path.join(self.path, filename)

                        # Work around blocked direct file access - https://github.com/Redgifs/api/wiki/Embedding-gifs
                        video_url = f'https://www.redgifs.com/ifr/{os.path.splitext(filename)[0]}'
                        logger.debug('Remapped redgifs URL to %s', video_url)

                        # Send a GET request to the video URL
                        video_response = requests.get(video_url, headers={'User-Agent': USER_AGENT})
                        if video_response.status_code == 404:
                            logger.debug('Redgif not found')
                        elif video_response.status_code >= 300:
                            raise RuntimeError(f'got status code: {video_response.status_code}')

                        hash = generate_hash(response.content)
                        if db.hash_exists(hash):
                            logger.debug('Duplicate hash detected')
                            files[url] = (None, hash, data, True)

                        # Write the video
                        else:
                            logger.debug('Saving to %s...', path)
                            with open(path, 'wb') as file:
                                file.write(video_response.content)
                            logger.info('Downloaded %s to %s', media_url, path)
                            files[media_url] = (path, hash, data, True)

                elif 'youtube.com' in media_url or 'youtu.be' in media_url  or 'pornhub.com/view_video' in media_url or 'redgifs.com' in media_url:
                    path = download_youtube(media_url, download_dir=self.path)
                    files[media_url] = (path, None, data, False)

                else:
                    logger.warning('Unsupported URL: %s', media_url)

                # Update file dates and insert into database
                for media_url, (path, hash, data, update_mtime) in files.items():
                    if not path:
                        path = hash = ''
                        if hash is None:
                            hash = ''
                    elif hash is None:
                        hash = generate_hash(path)
                    db.insert(post_id=data['id'], created_at=data['created_utc'], title=data['title'], author=data['author'], subreddit=data['subreddit'], filename=os.path.basename(path), media_url=media_url, media_hash=hash)

                    if path:
                        if update_mtime:
                            set_file_time(path, data['created_utc'])
                        else:
                            mtime = os.path.getmtime(path)
                            set_file_time(path, data['created_utc'])
                            os.utime(path, (data['created_utc'], mtime))

    def dl_raw_data(self, url: str, db: Optional[UserDatabase] = None):
        # Extract the filename from the URL
        name, ext = os.path.splitext(url.rsplit('/', 1)[-1])
        if ext == '.jpeg':
            ext = '.jpg'
        path = os.path.join(self.path, name + ext)

        while True:
            response = requests.get(url, headers={'User-Agent': USER_AGENT})
            if response.status_code == 404:
                logger.debug('Media not found')
                return None
            elif 'i.imgur.com' in url and '.mp4' in url and response.status_code == 400:
                logger.debug('Image uploaded as gifv, trying jpg')
                url = url.replace('.mp4', '.jpg')
                continue
            elif response.status_code >= 300:
                raise RuntimeError(f'got status code: {response.status_code}')

            # Some Imgur links redirect to the 404 page with the 200 status code
            # I wasn't able to figure out a robust way of detecting this, so just presume deleted
            elif 'i.imgur.com' in url and response.status_code == 200 and '</html>' in response.text:
                logger.debug('Media is probably deleted')
                return None
            break

        hash = generate_hash(response.content)
        if db is not None and db.hash_exists(hash):
            logger.debug('Duplicate hash detected')
            return '', hash

        # Write the image
        logger.debug('Saving to %s...', path)
        with open(path, 'wb') as file:
            file.write(response.content)
        logger.info('Downloaded %s to %s', url, path)
        return path, hash


if __name__ == '__main__':
    UserDownloader(sys.argv[1]).download()
