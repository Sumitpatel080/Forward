import asyncio
import signal
import sys
from datetime import datetime
from threading import Thread

import pytz
from flask import Flask
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import Config

# Set minimum channel ID for pyrogram
import pyrogram.utils
pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

# Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 ɪs ʀᴜɴɴɪɴɢ!"

@app.route('/status')
def status():
    return {
        "status": "active",
        "timestamp": datetime.now().isoformat(),
        "service": "ʙᴏᴛ"
    }

def start_flask():
    """Start Flask server in background thread"""
    try:
        app.run(host="0.0.0.0", port=8087, debug=False, use_reloader=False)
    except Exception as e:
        print(f"❌ Flask server error: {e}")

def keep_alive():
    """Start keep-alive server"""
    thread = Thread(target=start_flask, daemon=True)
    thread.start()
    print("✅ Keep-alive server started on port 8087")

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="ytdl_bot",
            api_hash=Config.API_HASH,
            api_id=Config.API_ID,
            plugins={"root": "commands"},
            bot_token=Config.BOT_TOKEN
        )

    async def start(self):
        await super().start()
        
        bot_info = await self.get_me()
        self.username = bot_info.username
        self.uptime = datetime.now(pytz.timezone("Asia/Kolkata"))
        
        print(f"🚀 Started {bot_info.first_name} (@{bot_info.username})")
        
        self.set_parse_mode(ParseMode.HTML)
        await self._send_startup_notification()
        
        print("🎉 Bot is now fully operational!")

    async def _send_startup_notification(self):
        """Send startup notification to admin"""
        if not Config.ADMIN_USERS:
            return
            
        try:
            message = (
                f"<b>🚀 Bot Started Successfully!</b>\n\n"
                f"⏰ <i>Started:</i> {self.uptime.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
                f"😴 <i>Ready to serve...</i>"
            )
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("» ᴍᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ", url="https://t.me/nyxgenie"),
                    InlineKeyboardButton("» ᴜᴘᴅᴀᴛᴇs", url="https://t.me/shizukawachan")
                ]
            ])
            
            await self.send_photo(
                chat_id=Config.ADMIN_USERS[0],
                photo=Config.FORCE_PIC,
                caption=message,
                reply_markup=keyboard
            )
            print("✅ Startup notification sent")
            
        except Exception as e:
            print(f"❌ Failed to send startup notification: {e}")

def setup_signal_handlers(bot, loop):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down...")
        asyncio.create_task(bot.stop())
        loop.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def main():
    print("🚀 Initializing ᴠɪᴅxᴛʀᴀᴄᴛᴏʀ ʙᴏᴛ...")
    print("=" * 50)
    
    # Validate configuration
    Config.print_config()
    config_errors = Config.validate_config()
    if config_errors:
        print("❌ Configuration errors found:")
        for error in config_errors:
            print(f"   - {error}")
        sys.exit(1)
    
    print("✅ Configuration validated")
    print("=" * 50)
    
    # Start keep-alive server
    keep_alive()
    
    # Initialize and run bot
    bot = Bot()
    
    try:
        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Setup signal handlers
        setup_signal_handlers(bot, loop)
        
        # Start bot
        loop.run_until_complete(bot.start())
        print("🔄 Bot event loop started")
        
        # Run forever
        loop.run_forever()
        
    except KeyboardInterrupt:
        print("\n🛑 Keyboard interrupt received")
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
    finally:
        # Cleanup
        try:
            if not loop.is_closed():
                loop.run_until_complete(bot.stop())
                loop.close()
            print("✅ Cleanup completed")
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")

if __name__ == "__main__":
    main()
