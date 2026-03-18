import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import re
import zipfile
import tempfile
import aiohttp
import aiofiles
import logging
import shutil
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.enums import ParseMode

try:
    from config import API_ID, API_HASH, BOT_TOKEN, COMMAND_PREFIX
except ImportError:
    print("ERROR: config.py not found or missing required variables!")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

bot_session_name = f"session_{BOT_TOKEN.split(':')[0]}"

bot = Client(
    bot_session_name,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1000,
    parse_mode=ParseMode.MARKDOWN
)

START_MSG = """Welcome to {bot_name}!

I can fetch and package the full source code of any website, including:
HTML | CSS | JS | Images | Fonts | Media

How to use:
- Send /ws <url> or /websource <url>
- I will grab all assets and send you a neat .zip file

Works in Private, Groups & Supergroups.  
Max archive size: 50 MB
Ready? Just send me a website link!
"""

class UrlDownloader:
    def __init__(self, imgFlg=True, linkFlg=True, scriptFlg=True):
        self.soup = None
        self.imgFlg = imgFlg
        self.linkFlg = linkFlg
        self.scriptFlg = scriptFlg
        self.extensions = {
            'css': 'css', 'js': 'js', 'mjs': 'js', 'png': 'images',
            'jpg': 'images', 'jpeg': 'images', 'gif': 'images', 'svg': 'images',
            'ico': 'images', 'webp': 'images', 'avif': 'images', 'woff': 'fonts',
            'woff2': 'fonts', 'ttf': 'fonts', 'eot': 'fonts', 'otf': 'fonts',
            'json': 'json', 'xml': 'xml', 'txt': 'txt', 'pdf': 'documents',
            'mov': 'media', 'mp4': 'media', 'webm': 'media', 'ogg': 'media', 'mp3': 'media'
        }
        self.size_limit = 50 * 1024 * 1024
        self.semaphore = asyncio.Semaphore(25)
        self.downloaded_files = set()
        self.failed_urls = set()

    async def savePage(self, url, pagefolder='page', session=None):
        logger.info(f"Downloading Source Code: {url}")
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            }
            
            async with session.get(url, timeout=20, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return False, f"HTTP error {response.status}: {response.reason}", []

                content = await response.read()
                if len(content) > self.size_limit:
                    return False, "Size limit of 50 MB exceeded.", []

                try:
                    self.soup = BeautifulSoup(content, features="lxml")
                except Exception:
                    try:
                        self.soup = BeautifulSoup(content, features="html.parser")
                    except Exception as e2:
                        return False, f"Failed to parse HTML: {str(e2)}", []

            if not os.path.exists(pagefolder):
                os.makedirs(pagefolder, exist_ok=True)

            file_paths = []
            all_resource_urls = set()

            if self.linkFlg: all_resource_urls.update(self._extract_css_resources(url))
            if self.scriptFlg: all_resource_urls.update(self._extract_js_resources(url))
            if self.imgFlg: all_resource_urls.update(self._extract_image_resources(url))
            all_resource_urls.update(self._extract_other_resources(url))
            all_resource_urls.update(self._extract_inline_urls(str(self.soup), url))
            all_resource_urls.update(self._extract_meta_resources(url))

            all_resource_urls = [u for u in all_resource_urls if u and self._is_valid_url(u)]

            if all_resource_urls:
                downloaded_resources = await self._download_all_resources(all_resource_urls, pagefolder, session)
                file_paths.extend(downloaded_resources)

            await self._update_html_paths(url, pagefolder)

            html_path = os.path.join(pagefolder, 'index.html')
            try:
                html_content = self.soup.prettify('utf-8')
                async with aiofiles.open(html_path, 'wb') as file:
                    await file.write(html_content)
                file_paths.append(html_path)
            except Exception as e:
                logger.error(f"HTML save error: {e}")
                return False, "Failed to save HTML file.", file_paths

            return True, None, file_paths

        except asyncio.TimeoutError:
            return False, "Request timed out. The website took too long to respond.", []
        except aiohttp.ClientError as e:
            return False, f"Network error occurred: {str(e)}", []
        except Exception as e:
            logger.error(f"Unexpected scraping error: {e}", exc_info=True)
            return False, "An unexpected parsing error occurred.", []

    def _is_valid_url(self, url):
        if not url or not isinstance(url, str): return False
        return not url.startswith(('data:', 'blob:', 'javascript:', 'mailto:', 'tel:', '#', 'about:'))

    def _extract_css_resources(self, base_url):
        urls = set()
        if not self.soup: return urls
        for link in self.soup.find_all('link', href=True):
            rel = link.get('rel', [])
            if isinstance(rel, str): rel = [rel]
            if 'stylesheet' in rel or link.get('type') == 'text/css':
                urls.add(urljoin(base_url, link.get('href').strip()))
        return urls

    def _extract_js_resources(self, base_url):
        urls = set()
        if not self.soup: return urls
        for script in self.soup.find_all('script', src=True):
            urls.add(urljoin(base_url, script.get('src').strip()))
        return urls

    def _extract_image_resources(self, base_url):
        urls = set()
        if not self.soup: return urls
        for img in self.soup.find_all('img'):
            if img.get('src'): urls.add(urljoin(base_url, img.get('src').strip()))
            if img.get('data-src'): urls.add(urljoin(base_url, img.get('data-src').strip()))
        return urls

    def _extract_other_resources(self, base_url):
        urls = set()
        if not self.soup: return urls
        for tag, attr in [('audio', 'src'), ('video', 'src'), ('embed', 'src'), ('object', 'data')]:
            for el in self.soup.find_all(tag, **{attr: True}):
                urls.add(urljoin(base_url, el.get(attr).strip()))
        return urls

    def _extract_meta_resources(self, base_url):
        urls = set()
        if not self.soup: return urls
        for meta in self.soup.find_all('meta', content=True):
            content = meta.get('content', '')
            if content.startswith(('http://', 'https://', '/')):
                urls.add(urljoin(base_url, content))
        return urls

    def _extract_css_urls(self, css_content, base_url):
        urls = set()
        for css_url in re.findall(r'url\s*\(\s*["\']?([^"\'()]+)["\']?\s*\)', css_content, re.IGNORECASE):
            if not css_url.startswith(('data:', 'blob:', 'javascript:')):
                urls.add(urljoin(base_url, css_url.strip()))
        return urls

    def _extract_inline_urls(self, html_content, base_url):
        urls = set()
        for style_block in re.findall(r'<style[^>]*>(.*?)</style>', html_content, re.DOTALL | re.IGNORECASE):
            urls.update(self._extract_css_urls(style_block, base_url))
        return urls

    async def _download_all_resources(self, resource_urls, pagefolder, session):
        tasks, file_paths = [], []
        for resource_url in resource_urls:
            if resource_url not in self.downloaded_files and resource_url not in self.failed_urls:
                self.downloaded_files.add(resource_url)
                file_path = self._get_resource_path(resource_url, pagefolder)
                if file_path:
                    file_paths.append(file_path)
                    tasks.append(self._download_single_resource(resource_url, file_path, session))

        if tasks:
            try:
                for i in range(0, len(tasks), 25):
                    await asyncio.gather(*tasks[i:i+25], return_exceptions=True)
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Batch download error: {e}")
        return file_paths

    def _get_resource_path(self, resource_url, pagefolder):
        try:
            parsed_url = urlparse(resource_url)
            path = unquote(parsed_url.path)
            if not path or path == '/': return None
            
            filename = path.strip('/').split('/')[-1]
            file_ext = filename.split('.')[-1].lower() if '.' in filename else 'html'
            folder_name = self.extensions.get(file_ext, 'assets')
            
            target_folder = os.path.join(pagefolder, folder_name)
            os.makedirs(target_folder, exist_ok=True)
            
            full_path = os.path.join(target_folder, filename)
            counter = 1
            while os.path.exists(full_path):
                name, ext = os.path.splitext(filename)
                full_path = os.path.join(target_folder, f"{name}_{counter}{ext}")
                counter += 1
            return full_path
        except Exception:
            return None

    async def _download_single_resource(self, resource_url, file_path, session):
        async with self.semaphore:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(resource_url, timeout=10, headers=headers) as response:
                    if response.status != 200:
                        self.failed_urls.add(resource_url)
                        return False
                    
                    content = await response.read()
                    if not content or len(content) > self.size_limit:
                        return False

                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(content)
                    return True
            except Exception:
                self.failed_urls.add(resource_url)
                return False

    async def _update_html_paths(self, base_url, pagefolder):
        if not self.soup: return
        for tag, attr in [('img', 'src'), ('link', 'href'), ('script', 'src')]:
            for el in self.soup.find_all(tag, **{attr: True}):
                original_url = urljoin(base_url, el.get(attr))
                local_path = self._get_local_path(original_url)
                if local_path: el[attr] = local_path

    def _get_local_path(self, resource_url):
        try:
            parsed_url = urlparse(resource_url)
            path = unquote(parsed_url.path)
            if not path or path == '/': return None
            
            filename = path.strip('/').split('/')[-1]
            file_ext = filename.split('.')[-1].lower() if '.' in filename else 'html'
            folder_name = self.extensions.get(file_ext, 'assets')
            return f"{folder_name}/{filename}"
        except Exception:
            return None

async def create_zip(folder_path):
    temp_file = None
    try:
        if not os.path.exists(folder_path): return None
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_file.close()

        def _create_zip_sync():
            with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zip_file.write(file_path, os.path.relpath(file_path, folder_path))
            return temp_file.name

        return await asyncio.get_event_loop().run_in_executor(None, _create_zip_sync)
    except Exception as e:
        logger.error(f"Zip Creation Error: {e}")
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        return None

async def clean_download(target_path):
    if not target_path or not os.path.exists(target_path):
        return
    try:
        if os.path.isfile(target_path):
            await asyncio.get_event_loop().run_in_executor(None, os.unlink, target_path)
        elif os.path.isdir(target_path):
            await asyncio.get_event_loop().run_in_executor(None, shutil.rmtree, target_path)
    except Exception as e:
        logger.error(f"Cleanup Error on {target_path}: {e}")

@bot.on_message(filters.command("start", prefixes=COMMAND_PREFIX) & (filters.group | filters.private))
async def start_command(client: Client, message):
    try:
        formatted_msg = START_MSG.format(bot_name=client.me.first_name)
        await message.reply_text(text=formatted_msg)
    except Exception as e:
        logger.error(f"Start command failed: {e}")

@bot.on_message(filters.command(["ws", "websource"], prefixes=COMMAND_PREFIX) & (filters.group | filters.private))
async def websource(client: Client, message):
    url = message.text.split()[1] if len(message.text.split()) > 1 else None
    if not url:
        return await message.reply_text("Please provide a valid URL.\nExample: `/ws google.com`")

    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"

    loading_msg = await message.reply_text("Downloading Source Code...\n`Extracting assets...`")
    
    pagefolder = os.path.join("downloads", f"page_{message.chat.id}_{message.id}")
    zip_file_path = None
    
    start_time = asyncio.get_event_loop().time()

    try:
        connector = aiohttp.TCPConnector(limit=100)
        async with aiohttp.ClientSession(connector=connector) as session:
            downloader = UrlDownloader()
            success, error, _ = await downloader.savePage(url, pagefolder, session)

            if not success:
                return await loading_msg.edit_text(f"Failed to download.\n`{error}`")

            await loading_msg.edit_text("Compressing files into ZIP...")
            zip_file_path = await create_zip(pagefolder)

            if not zip_file_path:
                return await loading_msg.edit_text("Failed to create archive.")

            zip_size_mb = os.path.getsize(zip_file_path) / (1024 * 1024)
            time_taken = asyncio.get_event_loop().time() - start_time
            domain = urlparse(url).netloc.replace('www.', '')

            caption = (
                "Website Source Download Successful\n"
                "----------------------\n"
                f"Website: `{domain}`\n"
                f"Archive Size: `{zip_size_mb:.2f} MB`\n"
                f"Time Taken: `{time_taken:.2f}s`\n"
                "----------------------\n"
                f"Downloaded By: {message.from_user.mention}"
            )

            await loading_msg.delete()
            await message.reply_document(
                document=zip_file_path,
                file_name=f"Source_{domain}.zip",
                caption=caption
            )

    except aiohttp.InvalidURL:
        await loading_msg.edit_text("The provided URL is invalid.")
    except Exception as e:
        logger.error(f"Process Error: {e}", exc_info=True)
        try:
            await loading_msg.edit_text("An unexpected error occurred while processing.")
        except Exception:
            pass
    finally:
        await clean_download(pagefolder)
        await clean_download(zip_file_path)

if __name__ == "__main__":
    logger.info("Starting Bot...")
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Bot initialization failed: {e}")