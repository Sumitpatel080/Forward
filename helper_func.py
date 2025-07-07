import os
import re
import time
import asyncio
import subprocess
import aiofiles
from datetime import datetime
from urllib.parse import urlparse
from config import Config
import os
import math
import subprocess
from pathlib import Path

# ==================== ADMIN CHECK ====================

def check_admin(client, user, message=None):
    """Check if user is admin - synchronous function"""
    try:
        OWNER_ID = int(os.environ.get("OWNER_ID", "7560922302"))
        ADMIN_LIST = os.environ.get("ADMINS", "").split()
        ADMINS = [int(admin) for admin in ADMIN_LIST if admin.isdigit()]
        ADMINS.append(OWNER_ID)
        
        return user.id in ADMINS
    except Exception as e:
        print(f"❌ Error in check_admin: {e}")
        return False


# Alternative approach - create a separate admin check function
def is_admin_user(user_id: int) -> bool:
    """Simple admin check function"""
    try:
        return Config.is_admin(user_id)
    except:
        return False


# ==================== TIME FORMATTING ====================

def format_time(seconds):
    """Format seconds to human readable time"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        if remaining_seconds == 0:
            return f"{minutes}m"
        return f"{minutes}m {remaining_seconds}s"
    else:
        hours = seconds // 3600
        remaining_minutes = (seconds % 3600) // 60
        if remaining_minutes == 0:
            return f"{hours}h"
        return f"{hours}h {remaining_minutes}m"

def format_bytes(bytes_value):
    """Format bytes to human readable format"""
    if bytes_value == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(bytes_value, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_value / p, 2)
    return f"{s} {size_names[i]}"

# ==================== PROGRESS BAR ====================

def create_progress_bar(percentage, length=10):
    """Create a progress bar"""
    filled = int(length * percentage / 100)
    bar = '█' * filled + '░' * (length - filled)
    return bar

# ==================== URL UTILITIES ====================

def extract_domain(url):
    """Extract domain from URL"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception as e:
        print(f"❌ Error extracting domain: {e}")
        return "unknown"

# ==================== VIDEO UTILITIES ====================

async def get_video_metadata(url):
    """Get video metadata using yt-dlp"""
    try:
        import yt_dlp
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            metadata = {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
                'thumbnail': info.get('thumbnail', ''),
                'filesize': info.get('filesize', 0) or info.get('filesize_approx', 0)
            }
            
            return metadata
            
    except Exception as e:
        print(f"❌ Error getting video metadata: {e}")
        return {}

async def get_video_dimensions(file_path):
    """Get video dimensions using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', file_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            import json
            data = json.loads(stdout.decode())
            
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    width = stream.get('width', 1280)
                    height = stream.get('height', 720)
                    return width, height
        
        return 1280, 720
        
    except Exception as e:
        print(f"❌ Error getting video dimensions: {e}")
        return 1280, 720

async def generate_thumbnail(video_path, thumb_path, time_offset=10):
    """Generate thumbnail from video"""
    try:
        cmd = [
            'ffmpeg', '-i', video_path, '-ss', str(time_offset),
            '-vframes', '1', '-y', thumb_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
        
        if process.returncode == 0 and os.path.exists(thumb_path):
            return True
        
        return False
        
    except Exception as e:
        print(f"❌ Error generating thumbnail: {e}")
        return False

# ==================== FILE UTILITIES ====================

async def get_video_duration_from_file(file_path):
    """Get video duration from file with better error handling"""
    try:
        if not os.path.exists(file_path):
            print(f"File does not exist: {file_path}")
            return 0
        
        meta = await get_video_metadata(f"file:{file_path}")
        duration = meta.get("duration", 0) if meta else 0
        print(f"Video duration: {duration} seconds")
        return duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return 0

async def split_video(file_path, max_size=1.95 * 1024 * 1024 * 1024):
    """
    Split video file into parts by duration if larger than max_size (default 1.95GB).
    Uses get_video_metadata to get duration.
    """
    try:
        print(f"Starting video split for: {file_path}")
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"❌ File does not exist: {file_path}")
            return [file_path]
        
        file_size = os.path.getsize(file_path)
        print(f"File size: {file_size} bytes ({file_size / (1024*1024*1024):.2f} GB)")
        
        if file_size <= max_size:
            print("File is under size limit, no splitting needed")
            return [file_path]

        # Get video duration
        duration = await get_video_duration_from_file(file_path)
        if duration <= 0:
            print("⚠️ Unable to get video duration or duration is zero.")
            # Try alternative method to get duration
            try:
                import subprocess
                cmd = [
                    "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(file_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0 and result.stdout.strip():
                    duration = float(result.stdout.strip())
                    print(f"Got duration from ffprobe: {duration}")
                else:
                    print("Failed to get duration from ffprobe")
                    return [file_path]
            except Exception as probe_error:
                print(f"ffprobe error: {probe_error}")
                return [file_path]

        if duration <= 0:
            print("Still no valid duration, cannot split")
            return [file_path]

        num_parts = math.ceil(file_size / max_size)
        part_duration = duration / num_parts  # float division
        
        print(f"Splitting into {num_parts} parts, each ~{part_duration:.2f} seconds")

        chunks = []
        chunk_num = 1

        p = Path(file_path)
        base_name = p.stem
        extension = p.suffix
        folder = p.parent

        # Check if ffmpeg is available
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=10)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"❌ ffmpeg not available: {e}")
            return [file_path]

        for i in range(num_parts):
            start_time = part_duration * i
            if i == num_parts - 1:
                current_duration = duration - start_time
                if current_duration <= 0:
                    print(f"Skipping part {chunk_num} - invalid duration")
                    break
            else:
                current_duration = part_duration

            output_file = folder / f"{base_name}.part{chunk_num:03d}{extension}"
            
            print(f"Creating part {chunk_num}: {output_file}")
            print(f"Start time: {start_time:.2f}s, Duration: {current_duration:.2f}s")

            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", str(start_time),
                "-i", str(file_path),
                "-t", str(current_duration),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-y", str(output_file)
            ]

            try:
                print(f"Running command: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE,
                    timeout=300  # 5 minute timeout per part
                )

                if result.returncode == 0 and output_file.exists():
                    chunk_size = os.path.getsize(output_file)
                    print(f"✅ Successfully created part {chunk_num}: {chunk_size} bytes")
                    chunks.append(str(output_file))
                    chunk_num += 1
                else:
                    error_msg = result.stderr.decode().strip() if result.stderr else "Unknown error"
                    print(f"❌ Failed to split part {chunk_num}: {error_msg}")
                    print(f"Return code: {result.returncode}")
                    
                    # If this is the first part and it fails, return original file
                    if chunk_num == 1:
                        print("First part failed, returning original file")
                        return [file_path]
                    
            except subprocess.TimeoutExpired:
                print(f"❌ Timeout while creating part {chunk_num}")
                break
            except Exception as cmd_error:
                print(f"❌ Command execution error for part {chunk_num}: {cmd_error}")
                break

        if chunks:
            print(f"✅ Successfully split video into {len(chunks)} parts")
            return chunks
        else:
            print("❌ No chunks created, returning original file")
            return [file_path]

    except Exception as e:
        print(f"❌ Error splitting video: {e}")
        import traceback
        traceback.print_exc()
        return [file_path]

# Alternative splitting function for non-video files
def split_file(file_path, max_size=1.95 * 1024 * 1024 * 1024):
    """
    Split any file into parts by size
    """
    try:
        print(f"Starting file split for: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"❌ File does not exist: {file_path}")
            return [file_path]
        
        file_size = os.path.getsize(file_path)
        print(f"File size: {file_size} bytes")
        
        if file_size <= max_size:
            print("File is under size limit, no splitting needed")
            return [file_path]

        chunks = []
        chunk_num = 1
        
        p = Path(file_path)
        base_name = p.stem
        extension = p.suffix
        folder = p.parent

        with open(file_path, 'rb') as input_file:
            while True:
                chunk_data = input_file.read(int(max_size))
                if not chunk_data:
                    break
                
                output_file = folder / f"{base_name}.part{chunk_num:03d}{extension}"
                
                with open(output_file, 'wb') as output_chunk:
                    output_chunk.write(chunk_data)
                
                if os.path.exists(output_file):
                    chunk_size = os.path.getsize(output_file)
                    print(f"✅ Created chunk {chunk_num}: {chunk_size} bytes")
                    chunks.append(str(output_file))
                    chunk_num += 1
                else:
                    print(f"❌ Failed to create chunk {chunk_num}")
                    break

        if chunks:
            print(f"✅ Successfully split file into {len(chunks)} parts")
            return chunks
        else:
            print("❌ No chunks created, returning original file")
            return [file_path]

    except Exception as e:
        print(f"❌ Error splitting file: {e}")
        import traceback
        traceback.print_exc()
        return [file_path]

# Helper function to check if a file is a video
def is_video_file(file_path):
    """Check if file is a video based on extension and mime type"""
    try:
        import mimetypes
        
        # Check by extension first
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.3gp']
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext in video_extensions:
            return True
        
        # Check by mime type
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and mime_type.startswith('video/'):
            return True
            
        return False
        
    except Exception as e:
        print(f"Error checking if file is video: {e}")
        # Fallback to extension check
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.3gp']
        return Path(file_path).suffix.lower() in video_extensions


def cleanup_files(directory):
    """Clean up files in directory"""
    try:
        if os.path.exists(directory):
            for file in os.listdir(directory):
                file_path = os.path.join(directory, file)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except Exception as e:
                    print(f"❌ Error removing file {file_path}: {e}")
            
            try:
                os.rmdir(directory)
            except Exception as e:
                print(f"❌ Error removing directory {directory}: {e}")
                
        print(f"✅ Cleaned up directory: {directory}")
        
    except Exception as e:
        print(f"❌ Error cleaning up files: {e}")

# ==================== MESSAGE UTILITIES ====================

async def safe_edit_message(message, text, parse_mode=None, reply_markup=None):
    """Safely edit message with error handling"""
    try:
        await message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        print(f"❌ Error editing message: {e}")
        return False

async def safe_delete_message(client, chat_id, message_id):
    """Safely delete message with error handling"""
    try:
        await client.delete_messages(chat_id, message_id)
        return True
    except Exception as e:
        print(f"❌ Error deleting message: {e}")
        return False

# ==================== VALIDATION UTILITIES ====================

def is_valid_url(url):
    """Check if URL is valid"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False

def is_supported_site(url):
    """Check if site is supported"""
    try:
        domain = extract_domain(url)
        supported_sites = [
            'youtube.com', 'youtu.be', 'instagram.com', 'facebook.com',
            'twitter.com', 'tiktok.com', 'pornhub.com', 'xvideos.com',
            'xnxx.com', 'xhamster.com', 'redtube.com', 'youporn.com'
        ]
        
        return any(site in domain for site in supported_sites)
    except Exception:
        return False

# ==================== SYSTEM UTILITIES ====================

def get_system_info():
    """Get system information"""
    try:
        import psutil
        
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_used': memory.used,
            'memory_total': memory.total,
            'disk_percent': disk.percent,
            'disk_used': disk.used,
            'disk_total': disk.total
        }
    except Exception as e:
        print(f"❌ Error getting system info: {e}")
        return {
            'cpu_percent': 0,
            'memory_percent': 0,
            'memory_used': 0,
            'memory_total': 0,
            'disk_percent': 0,
            'disk_used': 0,
            'disk_total': 0
        }

# ==================== AUTO DELETE UTILITY ====================

async def auto_delete_message(client, chat_id, message_id, delay_seconds):
    """Auto delete message after specified time"""
    try:
        await asyncio.sleep(delay_seconds)
        await client.delete_messages(chat_id, message_id)
        print(f"✅ Auto-deleted message {message_id} from chat {chat_id}")
    except Exception as e:
        print(f"❌ Error auto-deleting message: {e}")

# ==================== CAPTION UTILITIES ====================

def create_file_caption(file_name, file_size, metadata=None, show_metadata=True):
    """Create file caption with metadata"""
    try:
        caption = f"<b>📁 {file_name}</b>\n<b>📦 {format_bytes(file_size)}</b>"
        
        if show_metadata and metadata:
            if metadata.get('title') and metadata['title'] != 'Unknown':
                caption += f"\n<b>🎬 ᴛɪᴛʟᴇ:</b> {metadata['title'][:50]}..."
            
            if metadata.get('duration') and metadata['duration'] > 0:
                caption += f"\n<b>⏱️ ᴅᴜʀᴀᴛɪᴏɴ:</b> {format_time(metadata['duration'])}"
            
            if metadata.get('uploader') and metadata['uploader'] != 'Unknown':
                caption += f"\n<b>👤 ᴜᴘʟᴏᴀᴅᴇʀ:</b> {metadata['uploader'][:30]}..."
        
        return caption
        
    except Exception as e:
        print(f"❌ Error creating file caption: {e}")
        return f"<b>📁 {file_name}</b>\n<b>📦 {format_bytes(file_size)}</b>"

async def create_user_keyboard(is_premium=False):
    """Create user keyboard with dynamic settings"""
    try:
        from database import get_file_settings
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        settings = await get_file_settings()
        button_name = settings.get('button_name', '📺 ᴍᴏʀᴇ ᴠɪᴅᴇᴏs')
        button_url = settings.get('button_url', 'https://t.me/shizukawachan')
        
        buttons = []
        
        buttons.extend([
            [
                InlineKeyboardButton(button_name, url=button_url)
            ]
        ])
        
        return InlineKeyboardMarkup(buttons)
        
    except Exception as e:
        print(f"❌ Error creating user keyboard: {e}")
        # Fallback keyboard
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 ᴍᴏʀᴇ ᴠɪᴅᴇᴏs", url="https://t.me/shizukawachan")]
        ])


# ==================== DOWNLOAD UTILITIES ====================

def get_download_options(url):
    """Get download options based on URL with Instagram-specific headers"""
    try:
        domain = extract_domain(url)
        
        options = {
            'format': 'best[filesize<2G]/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'concurrent_fragment_downloads': 4,
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
            'http_chunk_size': 1024 * 1024,
        }
        
        # Site-specific optimizations
        if 'youtube' in domain:
            options.update({
                'format': 'best[height<=720][protocol^=https]/best[height<=480]/best',
                'concurrent_fragment_downloads': 4,
            })
        elif 'instagram' in domain:
            options.update({
                'format': 'best[height<=1080]/best/worst',
                'concurrent_fragment_downloads': 2,
                # Add headers to mimic browser behavior
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                },
                # Try different extraction methods
                'extractor_args': {
                    'instagram': {
                        'variant': 'base'
                    }
                }
            })
            print("🔧 Using Instagram-optimized headers and options")
            
        elif 'tiktok' in domain:
            options.update({
                'format': 'best[height<=720]/best',
                'concurrent_fragment_downloads': 3,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
            })
        elif 'facebook' in domain or 'fb.watch' in domain:
            options.update({
                'format': 'best[height<=720]/best',
                'concurrent_fragment_downloads': 2,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
            })
        elif 'twitter' in domain or 'x.com' in domain:
            options.update({
                'format': 'best[height<=720]/best',
                'concurrent_fragment_downloads': 3,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
            })
        elif any(adult_site in domain for adult_site in ['pornhub', 'xvideos', 'xnxx', 'xhamster']):
            options.update({
                'format': 'best[height<=720]/best',
                'concurrent_fragment_downloads': 6,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }
            })
        
        return options
        
    except Exception as e:
        print(f"❌ Error getting download options: {e}")
        return {
            'format': 'best/worst',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }


# ==================== VALIDATION AND SECURITY ====================

def sanitize_filename(filename):
    """Sanitize filename for safe storage"""
    try:
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip()
        
        # Limit length
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[:190] + ext
        
        return filename
        
    except Exception as e:
        print(f"❌ Error sanitizing filename: {e}")
        return "download_file"

def is_safe_file_type(filename):
    """Check if file type is safe"""
    try:
        safe_extensions = [
            '.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv',
            '.mp3', '.m4a', '.wav', '.flac', '.ogg',
            '.jpg', '.jpeg', '.png', '.gif', '.webp',
            '.pdf', '.txt', '.doc', '.docx'
        ]
        
        ext = os.path.splitext(filename)[1].lower()
        return ext in safe_extensions
        
    except Exception as e:
        print(f"❌ Error checking file type: {e}")
        return False

print("✅ Helper functions loaded successfully")
