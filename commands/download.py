import os
import time
import asyncio
from datetime import datetime, timedelta
import pytz
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from database import *
from helper_func import *

# Indian Standard Time
IST = pytz.timezone('Asia/Kolkata')

# Global storage
scheduler_tasks = {}
pending_forwards = {}

# from admin_state import admin_conversations

# ==================== CHANNEL MANAGEMENT ====================

from database import settings_data

async def save_channel(channel_id: int, channel_name: str):
    """Save channel to database"""
    try:
        await settings_data.update_one(
            {'_id': 'saved_channels'},
            {'$set': {str(channel_id): channel_name}},
            upsert=True
        )
        print(f"✅ Channel saved: {channel_name} ({channel_id})")
        return True
    except Exception as e:
        print(f"❌ Error saving channel: {e}")
        return False


async def get_saved_channels():
    """Get saved channels from database"""
    try:
        channels = await settings_data.find_one({'_id': 'saved_channels'})
        return channels if channels else {}
    except Exception as e:
        print(f"❌ Error getting channels: {e}")
        return {}

async def remove_channel(channel_id: int):
    """Remove channel from database"""
    try:
        await settings_data.update_one(
            {'_id': 'saved_channels'},
            {'$unset': {str(channel_id): ""}}
        )
        return True
    except Exception as e:
        print(f"❌ Error removing channel: {e}")
        return False

# ==================== POST SCHEDULER FUNCTIONS ====================

async def store_scheduled_post(post_id: str, post_data: dict):
    """Store scheduled post in database"""
    try:
        await settings_data.update_one(
            {'_id': f'scheduled_post_{post_id}'},
            {'$set': {
                'post_id': post_id,
                'post_data': post_data,
                'created_at': datetime.now(IST),
                'status': 'scheduled'
            }},
            upsert=True
        )
        return True
    except Exception as e:
        print(f"❌ Error storing scheduled post: {e}")
        return False

async def get_scheduled_posts():
    """Get all scheduled posts from database"""
    try:
        posts = []
        async for post in settings_data.find({'_id': {'$regex': '^scheduled_post_'}}):
            posts.append(post)
        return posts
    except Exception as e:
        print(f"❌ Error getting scheduled posts: {e}")
        return []

async def remove_scheduled_post(post_id: str):
    """Remove scheduled post from database"""
    try:
        await settings_data.delete_one({'_id': f'scheduled_post_{post_id}'})
        return True
    except Exception as e:
        print(f"❌ Error removing scheduled post: {e}")
        return False

async def schedule_post(client: Client, messages: list, channels: list, schedule_time: datetime):
    """Schedule posts to be sent to multiple channels"""
    try:
        # Convert to IST if not already
        if schedule_time.tzinfo is None:
            schedule_time = IST.localize(schedule_time)
        else:
            schedule_time = schedule_time.astimezone(IST)
        
        # Generate unique post ID
        post_id = f"post_{int(datetime.now(IST).timestamp())}"
        
        # Prepare post data
        post_data = {
            'post_id': post_id,
            'channels': channels,
            'schedule_time': schedule_time.isoformat(),
            'messages': messages,
            'created_at': datetime.now(IST).isoformat()
        }
        
        # Store in database
        success = await store_scheduled_post(post_id, post_data)
        
        if success:
            # Calculate delay in seconds
            now = datetime.now(IST)
            delay = (schedule_time - now).total_seconds()
            
            if delay > 0:
                # Create scheduled task
                task = asyncio.create_task(send_scheduled_post(client, post_id, post_data, delay))
                scheduler_tasks[post_id] = task
                
                print(f"✅ Post scheduled: {post_id} for {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
                return post_id
            else:
                # Send immediately if time has passed
                await execute_scheduled_post(client, post_data)
                await remove_scheduled_post(post_id)
                return post_id
        
        return None
        
    except Exception as e:
        print(f"❌ Error scheduling post: {e}")
        return None

async def send_scheduled_post(client: Client, post_id: str, post_data: dict, delay: float):
    """Send scheduled post after delay"""
    try:
        # Wait for the scheduled time
        await asyncio.sleep(delay)
        
        # Execute the post
        await execute_scheduled_post(client, post_data)
        
        # Clean up
        await remove_scheduled_post(post_id)
        if post_id in scheduler_tasks:
            del scheduler_tasks[post_id]
        
        print(f"✅ Scheduled post {post_id} sent successfully")
        
    except asyncio.CancelledError:
        print(f"⚠️ Scheduled post {post_id} was cancelled")
    except Exception as e:
        print(f"❌ Error sending scheduled post {post_id}: {e}")

async def execute_scheduled_post(client: Client, post_data: dict):
    """Execute the actual posting to channels"""
    try:
        channels = post_data.get('channels', [])
        messages = post_data.get('messages', [])
        
        for channel_id in channels:
            try:
                # Group messages by message group ID to handle media groups
                message_groups = {}
                single_messages = []
                
                for msg_data in messages:
                    group_id = msg_data.get('media_group_id')
                    if group_id:
                        if group_id not in message_groups:
                            message_groups[group_id] = []
                        message_groups[group_id].append(msg_data)
                    else:
                        single_messages.append(msg_data)
                
                # Send media groups first
                for group_id, group_messages in message_groups.items():
                    try:
                        # Get all message IDs in the group
                        message_ids = [msg['message_id'] for msg in group_messages if msg.get('message_id')]
                        original_chat_id = group_messages[0].get('original_chat_id')
                        
                        if message_ids and original_chat_id:
                            await client.forward_messages(
                                chat_id=channel_id,
                                from_chat_id=original_chat_id,
                                message_ids=message_ids
                            )
                    except Exception as e:
                        print(f"❌ Error forwarding media group: {e}")
                
                # Send single messages
                for msg_data in single_messages:
                    try:
                        original_msg_id = msg_data.get('message_id')
                        original_chat_id = msg_data.get('original_chat_id')
                        
                        if original_msg_id and original_chat_id:
                            await client.forward_messages(
                                chat_id=channel_id,
                                from_chat_id=original_chat_id,
                                message_ids=original_msg_id
                            )
                        
                        # Small delay between messages
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        print(f"❌ Error forwarding single message: {e}")
                
                print(f"✅ Posts sent to channel: {channel_id}")
                
            except Exception as e:
                print(f"❌ Error sending to channel {channel_id}: {e}")
                continue
        
    except Exception as e:
        print(f"❌ Error executing scheduled post: {e}")

async def cancel_scheduled_post(post_id: str):
    """Cancel a scheduled post"""
    try:
        # Cancel the task if running
        if post_id in scheduler_tasks:
            scheduler_tasks[post_id].cancel()
            del scheduler_tasks[post_id]
        
        # Remove from database
        await remove_scheduled_post(post_id)
        
        print(f"✅ Scheduled post {post_id} cancelled")
        return True
        
    except Exception as e:
        print(f"❌ Error cancelling scheduled post: {e}")
        return False

# ==================== TIME PICKER FUNCTIONS ====================

async def show_date_picker(message: Message):
    """Show date picker interface"""
    try:
        buttons = [
            [
                InlineKeyboardButton("📅 Today", callback_data="date_today"),
                InlineKeyboardButton("📅 Tomorrow", callback_data="date_tomorrow")
            ],
            [
                InlineKeyboardButton("📅 +2 Days", callback_data="date_plus2"),
                InlineKeyboardButton("📅 +3 Days", callback_data="date_plus3")
            ],
            [
                InlineKeyboardButton("📅 +1 Week", callback_data="date_plus7"),
                InlineKeyboardButton("📅 Custom Date", callback_data="date_custom")
            ]
        ]
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        await message.reply_text(
            "<b>📅 SELECT DATE</b>\n\n"
            "Choose when you want to schedule your messages:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error showing date picker: {e}")

async def show_time_picker(callback_query, selected_date):
    """Show time picker interface"""
    try:
        buttons = [
            [
                InlineKeyboardButton("🌅 9:00 AM", callback_data=f"time_{selected_date}_09:00"),
                InlineKeyboardButton("🌞 12:00 PM", callback_data=f"time_{selected_date}_12:00")
            ],
            [
                InlineKeyboardButton("🌆 3:00 PM", callback_data=f"time_{selected_date}_15:00"),
                InlineKeyboardButton("🌇 6:00 PM", callback_data=f"time_{selected_date}_18:00")
            ],
            [
                InlineKeyboardButton("🌙 9:00 PM", callback_data=f"time_{selected_date}_21:00"),
                InlineKeyboardButton("🕛 Custom Time", callback_data=f"time_{selected_date}_custom")
            ],
            [
                InlineKeyboardButton("⬅️ Back to Date", callback_data="back_to_date")
            ]
        ]
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        date_text = {
            'today': 'Today',
            'tomorrow': 'Tomorrow', 
            'plus2': 'Day After Tomorrow',
            'plus3': 'In 3 Days',
            'plus7': 'Next Week'
        }.get(selected_date, selected_date)
        
        await callback_query.edit_message_text(
            f"<b>🕐 SELECT TIME</b>\n\n"
            f"<b>Selected Date:</b> {date_text}\n"
            f"Choose the time to schedule:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error showing time picker: {e}")

# ==================== CHANNEL COMMANDS ====================

@Client.on_message(filters.command("add_channel") & filters.private)
async def add_channel_command(client: Client, message: Message):
    """Add channel for scheduling - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if len(args) < 2:
            await message.reply_text(
                "❌ Usage: <code>/add_channel channel_id channel_name</code>\n"
                "Example: <code>/add_channel -1001234567890 My Channel</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            channel_id = int(args[0])
            channel_name = ' '.join(args[1:])
            
            success = await save_channel(channel_id, channel_name)
            
            if success:
                await message.reply_text(f"✅ Channel added: <b>{channel_name}</b> (<code>{channel_id}</code>)", parse_mode=ParseMode.HTML)
            else:
                await message.reply_text("❌ Failed to add channel.")
                
        except ValueError:
            await message.reply_text("❌ Invalid channel ID. Must be a number.")
            
    except Exception as e:
        print(f"❌ Error in add_channel command: {e}")

@Client.on_message(filters.command("list_channels") & filters.private)
async def list_channels_command(client: Client, message: Message):
    """List saved channels - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        channels = await get_saved_channels()
        
        if not channels or len(channels) <= 1:
            await message.reply_text("📭 No channels saved.")
            return
        
        text = "<b>📋 SAVED CHANNELS</b>\n\n"
        
        for channel_id, channel_name in channels.items():
            if channel_id != '_id':
                text += f"<b>{channel_name}</b>\n<code>{channel_id}</code>\n\n"
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        print(f"❌ Error in list_channels command: {e}")

@Client.on_message(filters.command("remove_channel") & filters.private)
async def remove_channel_command(client: Client, message: Message):
    """Remove channel - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply_text("❌ Usage: <code>/remove_channel channel_id</code>", parse_mode=ParseMode.HTML)
            return
        
        try:
            channel_id = int(args[0])
            success = await remove_channel(channel_id)
            
            if success:
                await message.reply_text(f"✅ Channel <code>{channel_id}</code> removed.", parse_mode=ParseMode.HTML)
            else:
                await message.reply_text("❌ Failed to remove channel.")
                
        except ValueError:
            await message.reply_text("❌ Invalid channel ID.")
            
    except Exception as e:
        print(f"❌ Error in remove_channel command: {e}")

# ==================== FORWARD SCHEDULER ====================

@Client.on_message(filters.command("schedule") & filters.private)
async def schedule_command(client: Client, message: Message):
    """Schedule forwarded messages - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        # If no arguments, show date picker
        if not args:
            await show_date_picker(message)
            return
        
        # Legacy support for manual time input
        if len(args) >= 2:
            try:
                date_str = args[0]
                time_str = args[1]
                datetime_str = f"{date_str} {time_str}"
                schedule_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                schedule_time = IST.localize(schedule_time)
                
                # Store user in pending forwards
                user_id = message.from_user.id
                pending_forwards[user_id] = {
                    'schedule_time': schedule_time,
                    'messages': [],
                    'step': 'collecting_messages',
                    'media_groups': {}
                }
                
                await message.reply_text(
                    f"✅ <b>Forward Collection Started!</b>\n\n"
                    f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
                    f"📤 Now forward me the messages you want to schedule.\n"
                    f"Send <code>/done</code> when finished.",
                    parse_mode=ParseMode.HTML
                )
                
            except ValueError as e:
                await message.reply_text(f"❌ Invalid date/time format: {e}")
        else:
            await show_date_picker(message)
            
    except Exception as e:
        print(f"❌ Error in schedule command: {e}")

# ==================== TIME PICKER CALLBACKS ====================

@Client.on_callback_query(filters.regex(r"^date_"))
async def handle_date_selection(client: Client, callback_query):
    """Handle date selection"""
    try:
        user_id = callback_query.from_user.id
        
        if not is_admin_user(user_id):
            await callback_query.answer("❌ Not authorized")
            return
        
        date_type = callback_query.data.split("_")[1]
        
        if date_type == "custom":
            await callback_query.edit_message_text(
                "<b>📅 CUSTOM DATE</b>\n\n"
                "Please send the date in format: <code>YYYY-MM-DD HH:MM</code>\n"
                "Example: <code>2024-01-15 14:30</code>\n\n"
                "Or use /cancel to go back.",
                parse_mode=ParseMode.HTML
            )
            
            # Store state for custom input
            pending_forwards[user_id] = {
                'step': 'waiting_custom_datetime'
            }
            return
        
        await show_time_picker(callback_query, date_type)
        
    except Exception as e:
        print(f"❌ Error handling date selection: {e}")

@Client.on_callback_query(filters.regex(r"^time_"))
async def handle_time_selection(client: Client, callback_query):
    """Handle time selection"""
    try:
        user_id = callback_query.from_user.id
        
        if not is_admin_user(user_id):
            await callback_query.answer("❌ Not authorized")
            return
        
        parts = callback_query.data.split("_")
        date_type = parts[1]
        time_part = parts[2]
        
        if time_part == "custom":
            await callback_query.edit_message_text(
                f"<b>🕐 CUSTOM TIME</b>\n\n"
                f"Please send the time in format: <code>HH:MM</code>\n"
                f"Example: <code>14:30</code> for 2:30 PM\n\n"
                f"Or use /cancel to go back.",
                parse_mode=ParseMode.HTML
            )
            
            # Store state for custom time input
            pending_forwards[user_id] = {
                'step': 'waiting_custom_time',
                'selected_date': date_type
            }
            return
        
        # Calculate schedule time
        now = datetime.now(IST)
        
        if date_type == "today":
            target_date = now.date()
        elif date_type == "tomorrow":
            target_date = now.date() + timedelta(days=1)
        elif date_type == "plus2":
            target_date = now.date() + timedelta(days=2)
        elif date_type == "plus3":
            target_date = now.date() + timedelta(days=3)
        elif date_type == "plus7":
            target_date = now.date() + timedelta(days=7)
        
        # Parse time
        hour, minute = map(int, time_part.split(":"))
        schedule_time = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=minute))
        schedule_time = IST.localize(schedule_time)
        
        # Check if time is in the past
        if schedule_time <= now:
            await callback_query.answer("❌ Selected time is in the past!")
            return
        
        # Store user in pending forwards
        pending_forwards[user_id] = {
            'schedule_time': schedule_time,
            'messages': [],
            'step': 'collecting_messages',
            'media_groups': {}
        }
        
        await callback_query.edit_message_text(
            f"✅ <b>Forward Collection Started!</b>\n\n"
            f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
            f"📤 Now forward me the messages you want to schedule.\n"
            f"Send <code>/done</code> when finished.",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error handling time selection: {e}")

@Client.on_callback_query(filters.regex("^back_to_date$"))
async def back_to_date_callback(client: Client, callback_query):
    """Go back to date picker"""
    try:
        await show_date_picker(callback_query.message)
    except Exception as e:
        print(f"❌ Error going back to date picker: {e}")

# ==================== CUSTOM INPUT HANDLERS ====================

@Client.on_message(filters.text & filters.private)
async def handle_custom_datetime_input(client: Client, message: Message):
    """Handle custom datetime input"""
    try:
        user_id = message.from_user.id
        
        if not is_admin_user(user_id):
            return
        
        if user_id not in pending_forwards:
            return
        
        step = pending_forwards[user_id].get('step')
        
        if step == 'waiting_custom_datetime':
            try:
                # Parse full datetime
                schedule_time = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
                schedule_time = IST.localize(schedule_time)
                
                # Check if time is in the past
                if schedule_time <= datetime.now(IST):
                    await message.reply_text("❌ Selected time is in the past! Please choose a future time.")
                    return
                
                # Update pending forwards
                pending_forwards[user_id] = {
                    'schedule_time': schedule_time,
                    'messages': [],
                    'step': 'collecting_messages',
                    'media_groups': {}
                }
                
                await message.reply_text(
                    f"✅ <b>Forward Collection Started!</b>\n\n"
                    f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
                    f"📤 Now forward me the messages you want to schedule.\n"
                    f"Send <code>/done</code> when finished.",
                    parse_mode=ParseMode.HTML
                )
                
            except ValueError:
                await message.reply_text("❌ Invalid format! Use: YYYY-MM-DD HH:MM\nExample: 2024-01-15 14:30")
                
        elif step == 'waiting_custom_time':
            try:
                # Parse time only
                time_parts = message.text.strip().split(":")
                hour, minute = int(time_parts[0]), int(time_parts[1])
                
                # Get selected date
                date_type = pending_forwards[user_id]['selected_date']
                now = datetime.now(IST)
                
                if date_type == "today":
                    target_date = now.date()
                elif date_type == "tomorrow":
                    target_date = now.date() + timedelta(days=1)
                elif date_type == "plus2":
                    target_date = now.date() + timedelta(days=2)
                elif date_type == "plus3":
                    target_date = now.date() + timedelta(days=3)
                elif date_type == "plus7":
                    target_date = now.date() + timedelta(days=7)
                
                schedule_time = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=minute))
                schedule_time = IST.localize(schedule_time)
                
                # Check if time is in the past
                if schedule_time <= now:
                    await message.reply_text("❌ Selected time is in the past! Please choose a future time.")
                    return
                
                # Update pending forwards
                pending_forwards[user_id] = {
                    'schedule_time': schedule_time,
                    'messages': [],
                    'step': 'collecting_messages',
                    'media_groups': {}
                }
                
                await message.reply_text(
                    f"✅ <b>Forward Collection Started!</b>\n\n"
                    f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
                    f"📤 Now forward me the messages you want to schedule.\n"
                    f"Send <code>/done</code> when finished.",
                    parse_mode=ParseMode.HTML
                )
                
            except (ValueError, IndexError):
                await message.reply_text("❌ Invalid time format! Use: HH:MM\nExample: 14:30")
        
    except Exception as e:
        print(f"❌ Error handling custom datetime input: {e}")

@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client: Client, message: Message):
    """Cancel current operation"""
    try:
        user_id = message.from_user.id
        
        if user_id in pending_forwards:
            del pending_forwards[user_id]
            await message.reply_text("❌ Operation cancelled.")
        else:
            await message.reply_text("ℹ️ No active operation to cancel.")
            
    except Exception as e:
        print(f"❌ Error in cancel command: {e}")

# ==================== MESSAGE HANDLERS ====================

@Client.on_message(filters.forwarded & filters.private)
async def handle_forwarded_message(client: Client, message: Message):
    """Handle forwarded messages for scheduling"""
    try:
        user_id = message.from_user.id
        
        if not is_admin_user(user_id):
            return
        
        if user_id not in pending_forwards:
            return
        
        if pending_forwards[user_id]['step'] != 'collecting_messages':
            return
        
        print(f"📤 Processing forwarded message from user {user_id}")
        
        # Process the forwarded message
        msg_data = {
            'message_id': message.id,
            'original_chat_id': message.chat.id,
            'type': 'forwarded'
        }
        
        # Handle media groups
        if message.media_group_id:
            msg_data['media_group_id'] = message.media_group_id
            media_groups = pending_forwards[user_id]['media_groups']
            if message.media_group_id not in media_groups:
                media_groups[message.media_group_id] = []
            media_groups[message.media_group_id].append(msg_data)
        else:
            pending_forwards[user_id]['messages'].append(msg_data)
        
        # Count total messages
        single_count = len(pending_forwards[user_id]['messages'])
        group_count = len(pending_forwards[user_id]['media_groups'])
        total_count = single_count + group_count
        
        # Create Done button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Done Collecting", callback_data="done_collecting")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_forward")]
        ])
        
        await message.reply_text(
            f"✅ <b>Message {total_count} collected!</b>\n\n"
            f"📤 Forward more messages or click <b>Done</b> to proceed:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error handling forwarded message: {e}")

# Add this callback handler
@Client.on_callback_query(filters.regex("^done_collecting$"))
async def done_collecting_callback(client: Client, callback_query):
    """Handle done collecting callback"""
    try:
        user_id = callback_query.from_user.id
        
        if not is_admin_user(user_id):
            await callback_query.answer("❌ Not authorized")
            return
        
        if user_id not in pending_forwards:
            await callback_query.answer("❌ No active session")
            return
        
        if pending_forwards[user_id]['step'] != 'collecting_messages':
            await callback_query.answer("❌ Not in collection mode")
            return
        
        # Combine messages
        messages = pending_forwards[user_id]['messages']
        media_groups = pending_forwards[user_id]['media_groups']
        
        for group_id, group_messages in media_groups.items():
            messages.extend(group_messages)
        
        if not messages:
            await callback_query.answer("❌ No messages collected")
            return
        
        # Get saved channels
        channels = await get_saved_channels()
        
        if not channels or len(channels) <= 1:
            await callback_query.edit_message_text("❌ No channels saved. Use <code>/add_channel</code> first.", parse_mode=ParseMode.HTML)
            return
        
        # Create channel selection buttons
        buttons = []
        for channel_id, channel_name in channels.items():
            if channel_id != '_id':
                buttons.append([InlineKeyboardButton(f"📢 {channel_name}", callback_data=f"select_channel_{channel_id}")])
        
        buttons.append([InlineKeyboardButton("✅ Schedule Selected", callback_data="schedule_selected")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_forward")])
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        # Update step
        pending_forwards[user_id]['step'] = 'selecting_channels'
        pending_forwards[user_id]['selected_channels'] = []
        
        schedule_time = pending_forwards[user_id]['schedule_time']
        
        await callback_query.edit_message_text(
            f"📋 <b>Select Channels</b>\n\n"
            f"<b>Messages Collected:</b> {len(messages)}\n"
            f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
            f"Select the channels where you want to send these messages:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error in done collecting callback: {e}")

# ==================== CHANNEL SELECTION CALLBACKS ====================

@Client.on_callback_query(filters.regex(r"^select_channel_"))
async def select_channel_callback(client: Client, callback_query):
    """Handle channel selection"""
    try:
        user_id = callback_query.from_user.id
        
        if not is_admin_user(user_id):
            await callback_query.answer("❌ Not authorized")
            return
        
        if user_id not in pending_forwards:
            await callback_query.answer("❌ No active session")
            return
        
        channel_id = int(callback_query.data.split("_")[2])
        selected_channels = pending_forwards[user_id]['selected_channels']
        
        if channel_id in selected_channels:
            selected_channels.remove(channel_id)
            await callback_query.answer("❌ Channel deselected")
        else:
            selected_channels.append(channel_id)
            await callback_query.answer("✅ Channel selected")
        
        # Update button text to show selection
        channels = await get_saved_channels()
        buttons = []
        
        for ch_id, ch_name in channels.items():
            if ch_id != '_id':
                ch_id_int = int(ch_id)
                prefix = "✅" if ch_id_int in selected_channels else "📢"
                buttons.append([InlineKeyboardButton(f"{prefix} {ch_name}", callback_data=f"select_channel_{ch_id}")])
        
        buttons.append([InlineKeyboardButton("✅ Schedule Selected", callback_data="schedule_selected")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_forward")])
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        schedule_time = pending_forwards[user_id]['schedule_time']
        total_items = len(pending_forwards[user_id]['messages']) + len(pending_forwards[user_id]['media_groups'])
        
        await callback_query.edit_message_text(
            f"📋 <b>Select Channels</b>\n\n"
            f"<b>Messages Collected:</b> {total_items}\n"
            f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"<b>Selected Channels:</b> {len(selected_channels)}\n\n"
            f"Select the channels where you want to send these messages:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        print(f"❌ Error in channel selection: {e}")

@Client.on_callback_query(filters.regex("^schedule_selected$"))
async def schedule_selected_callback(client: Client, callback_query):
    """Schedule the selected messages"""
    try:
        user_id = callback_query.from_user.id
        
        if not is_admin_user(user_id):
            await callback_query.answer("❌ Not authorized")
            return
        
        if user_id not in pending_forwards:
            await callback_query.answer("❌ No active session")
            return
        
        selected_channels = pending_forwards[user_id]['selected_channels']
        
        if not selected_channels:
            await callback_query.answer("❌ Please select at least one channel")
            return
        
        # Combine messages and media groups
        messages = pending_forwards[user_id]['messages']
        media_groups = pending_forwards[user_id]['media_groups']
        
        # Add media groups to messages
        for group_id, group_messages in media_groups.items():
            messages.extend(group_messages)
        
        schedule_time = pending_forwards[user_id]['schedule_time']
        
        # Schedule the post
        post_id = await schedule_post(client, messages, selected_channels, schedule_time)
        
        if post_id:
            channels = await get_saved_channels()
            channel_names = [channels.get(str(ch_id), f"Channel {ch_id}") for ch_id in selected_channels]
            
            await callback_query.edit_message_text(
                f"✅ <b>Messages Scheduled Successfully!</b>\n\n"
                f"<b>Post ID:</b> <code>{post_id}</code>\n"
                f"<b>Schedule Time:</b> {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
                f"<b>Messages:</b> {len(messages)}\n"
                f"<b>Channels:</b> {', '.join(channel_names)}",
                parse_mode=ParseMode.HTML
            )
        else:
            await callback_query.edit_message_text("❌ Failed to schedule messages.")
        
        # Clean up
        del pending_forwards[user_id]
        
    except Exception as e:
        print(f"❌ Error scheduling selected: {e}")

@Client.on_callback_query(filters.regex("^cancel_forward$"))
async def cancel_forward_callback(client: Client, callback_query):
    """Cancel forward scheduling"""
    try:
        user_id = callback_query.from_user.id
        
        if user_id in pending_forwards:
            del pending_forwards[user_id]
        
        await callback_query.edit_message_text("❌ Forward scheduling cancelled.")
        
    except Exception as e:
        print(f"❌ Error cancelling forward: {e}")

# ==================== LIST AND CANCEL COMMANDS ====================

@Client.on_message(filters.command("schedule_list") & filters.private)
async def schedule_list_command(client: Client, message: Message):
    """List all scheduled posts - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        posts = await get_scheduled_posts()
        
        if not posts:
            await message.reply_text("📭 No scheduled posts found.")
            return
        
        text = "<b>📅 SCHEDULED POSTS</b>\n\n"
        
        for post in posts[:10]:
            post_data = post.get('post_data', {})
            post_id = post_data.get('post_id', 'Unknown')
            schedule_time = post_data.get('schedule_time', '')
            channels = post_data.get('channels', [])
            messages = post_data.get('messages', [])
            
            if schedule_time:
                try:
                    dt = datetime.fromisoformat(schedule_time)
                    time_str = dt.strftime('%Y-%m-%d %H:%M IST')
                except:
                    time_str = schedule_time
            else:
                time_str = 'Unknown'
            
            text += (
                f"<b>ID:</b> <code>{post_id}</code>\n"
                f"<b>Time:</b> {time_str}\n"
                f"<b>Messages:</b> {len(messages)}\n"
                f"<b>Channels:</b> {len(channels)}\n\n"
            )
        
        if len(posts) > 10:
            text += f"<i>... and {len(posts) - 10} more posts</i>"
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        print(f"❌ Error in schedule_list command: {e}")

@Client.on_message(filters.command("schedule_cancel") & filters.private)
async def schedule_cancel_command(client: Client, message: Message):
    """Cancel a scheduled post - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply_text("❌ Please provide post ID. Usage: /schedule_cancel post_id")
            return
        
        post_id = args[0]
        success = await cancel_scheduled_post(post_id)
        
        if success:
            await message.reply_text(f"✅ Scheduled post <code>{post_id}</code> cancelled successfully.", parse_mode=ParseMode.HTML)
        else:
            await message.reply_text(f"❌ Failed to cancel post <code>{post_id}</code>. Post may not exist.", parse_mode=ParseMode.HTML)
            
    except Exception as e:
        print(f"❌ Error in schedule_cancel command: {e}")

# ==================== STARTUP FUNCTION ====================

async def load_scheduled_posts_on_startup(client: Client):
    """Load and reschedule posts on bot startup"""
    try:
        posts = await get_scheduled_posts()
        now = datetime.now(IST)
        
        for post in posts:
            try:
                post_data = post.get('post_data', {})
                post_id = post_data.get('post_id')
                schedule_time_str = post_data.get('schedule_time')
                
                if not post_id or not schedule_time_str:
                    continue
                
                # Parse schedule time
                schedule_time = datetime.fromisoformat(schedule_time_str)
                if schedule_time.tzinfo is None:
                    schedule_time = IST.localize(schedule_time)
                else:
                    schedule_time = schedule_time.astimezone(IST)
                
                # Check if post should be sent
                if schedule_time <= now:
                    # Send immediately if time has passed
                    await execute_scheduled_post(client, post_data)
                    await remove_scheduled_post(post_id)
                    print(f"✅ Sent overdue post: {post_id}")
                else:
                    # Reschedule for future
                    delay = (schedule_time - now).total_seconds()
                    task = asyncio.create_task(send_scheduled_post(client, post_id, post_data, delay))
                    scheduler_tasks[post_id] = task
                    print(f"✅ Rescheduled post: {post_id} for {schedule_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
                    
            except Exception as e:
                print(f"❌ Error loading scheduled post: {e}")
                continue
        
        print(f"✅ Loaded {len(scheduler_tasks)} scheduled posts")
        
    except Exception as e:
        print(f"❌ Error loading scheduled posts on startup: {e}")

# ==================== INITIALIZATION ====================

async def init_scheduler(client: Client):
    """Initialize scheduler on bot startup"""
    try:
        print("🔄 Initializing post scheduler...")
        await load_scheduled_posts_on_startup(client)
        print("✅ Post scheduler initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing scheduler: {e}")

# ==================== HELP COMMAND ====================

@Client.on_message(filters.command("schedule_help") & filters.private)
async def schedule_help_command(client: Client, message: Message):
    """Show scheduler help - Admin only"""
    try:
        if not is_admin_user(message.from_user.id):
            await message.reply_text("❌ You are not authorized to use this command.")
            return
        
        help_text = (
            "<b>📅 POST SCHEDULER HELP</b>\n\n"
            
            "<b>🏗️ SETUP COMMANDS:</b>\n"
            "• <code>/add_channel channel_id name</code> - Add channel\n"
            "• <code>/list_channels</code> - List saved channels\n"
            "• <code>/remove_channel channel_id</code> - Remove channel\n\n"
            
            "<b>📤 SCHEDULING COMMANDS:</b>\n"
            "• <code>/schedule</code> - Schedule forwarded messages\n"
            "• <code>/schedule YYYY-MM-DD HH:MM</code> - Manual time input\n\n"
            
            "<b>📋 MANAGEMENT COMMANDS:</b>\n"
            "• <code>/schedule_list</code> - View scheduled posts\n"
            "• <code>/schedule_cancel post_id</code> - Cancel scheduled post\n"
            "• <code>/cancel</code> - Cancel current operation\n\n"
            
            "<b>🔄 WORKFLOW:</b>\n"
            "1. Add channels with <code>/add_channel</code>\n"
            "2. Use <code>/schedule</code>\n"
            "3. Select date and time from buttons\n"
            "4. Forward messages to bot\n"
            "5. Send <code>/done</code>\n"
            "6. Select channels\n"
            "7. Confirm scheduling\n\n"
            
            "<b>⏰ Time Picker Features:</b>\n"
            "• Quick date selection (Today, Tomorrow, etc.)\n"
            "• Common time slots (9AM, 12PM, 3PM, 6PM, 9PM)\n"
            "• Custom date/time input option\n"
            "• All times are in IST (Asia/Kolkata)"
        )
        
        await message.reply_text(help_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        print(f"❌ Error in schedule_help command: {e}")

print("✅ Post Scheduler loaded successfully")
