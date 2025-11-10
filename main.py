from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.functions.channels import GetFullChannelRequest
import asyncio
import os
import logging
import json
import glob
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
import openai
from dotenv import load_dotenv
import time
from colorama import Fore, Back, Style, init as colorama_init
import re
import sys

# Initialize colorama for cross-platform color support
colorama_init(autoreset=True)

# Load environment variables from .env file
load_dotenv()

# Set up logging with colors
logging_level = os.environ.get("LOGGING_LEVEL", "INFO")  # Changed default to INFO

# Configure Telethon logging
telethon_logger = logging.getLogger("telethon")
telethon_logger.setLevel(logging.WARNING)  # Only show WARNING and above for Telethon

# Custom formatter that adds colors to log messages
class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log messages"""
    
    COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT
    }
    
    def format(self, record):
        # Save original levelname to restore later
        orig_levelname = record.levelname
        # Add color to levelname
        record.levelname = f"{self.COLORS.get(record.levelname, Fore.WHITE)}{record.levelname}{Style.RESET_ALL}"
        
        # Color-code client IDs in the message if present
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            # Highlight Client ID pattern
            client_pattern = r'(Client \w+:)'
            record.msg = re.sub(client_pattern, f"{Fore.MAGENTA}\\1{Style.RESET_ALL}", record.msg)
            
            # Highlight Session ID pattern
            session_pattern = r'(Session \w+:)'
            record.msg = re.sub(session_pattern, f"{Fore.BLUE}\\1{Style.RESET_ALL}", record.msg)
            
            # Highlight 'matched', 'found', 'error', etc.
            highlight_words = {
                'matched': Fore.GREEN,
                'found': Fore.GREEN + Style.BRIGHT,
                'error': Fore.RED,
                'failed': Fore.RED,
                'skipping': Fore.YELLOW,
                'rate limiting': Fore.YELLOW + Style.BRIGHT,
                'responded': Fore.GREEN,
                'generated': Fore.GREEN,
            }
            
            for word, color in highlight_words.items():
                if word.lower() in record.msg.lower():
                    pattern = re.compile(r'(\b' + word + r'\w*\b)', re.IGNORECASE)
                    record.msg = pattern.sub(f"{color}\\1{Style.RESET_ALL}", record.msg)
        
        # Format with parent formatter
        result = super().format(record)
        # Restore original levelname
        record.levelname = orig_levelname
        return result

# Configure the logger with the custom formatter
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, logging_level))

# Remove existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create console handler with the custom formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# For root logger (affects all other loggers)
logging.basicConfig(
    level=getattr(logging, logging_level),
    handlers=[]  # No handlers in the basic config, we'll add our own
)
root_logger = logging.getLogger()
# Remove existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
# Add our custom handler
root_logger.addHandler(console_handler)

# Enhance menu display with colors
def print_colored_menu():
    """Display colorful main menu"""
    print(f"\n{Fore.CYAN + Style.BRIGHT}=== Telegram Session Manager ==={Style.RESET_ALL}")
    print(f"{Fore.GREEN}1. {Style.RESET_ALL}Create new session")
    print(f"{Fore.GREEN}2. {Style.RESET_ALL}List active sessions")
    print(f"{Fore.GREEN}3. {Style.RESET_ALL}View channels for a session")
    print(f"{Fore.GREEN}4. {Style.RESET_ALL}Synchronize channels from file")
    print(f"{Fore.GREEN}5. {Style.RESET_ALL}Set DeepSeek API Key")
    print(f"{Fore.GREEN}6. {Style.RESET_ALL}Start monitoring")
    print(f"{Fore.GREEN}7. {Style.RESET_ALL}Exit")

# Shared clients dictionary
clients = {}

# Client-specific API clients
api_clients = {}

# DeepSeek API configuration
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# AI parameters from environment variables
AI_TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.7"))
AI_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "100"))

# AI personality and style settings from environment variables
AI_PERSONALITY = os.environ.get("AI_PERSONALITY", "default")  # Options: default, friendly, witty, expert, provocative
AI_FORMALITY = os.environ.get("AI_FORMALITY", "casual")       # Options: casual, neutral, formal

# Ensure sessions directory exists
os.makedirs('sessions', exist_ok=True)

# Track last response time per chat to implement rate limiting
last_response_time = {}

def debug_object(obj, name="object", max_depth=2, _current_depth=0):
    """Helper function to inspect object attributes for debugging"""
    if _current_depth > max_depth:
        return "..."
    
    if obj is None:
        return "None"
    
    if isinstance(obj, (str, int, float, bool)):
        return repr(obj)
    
    if _current_depth == 0:
        logger.debug(f"Inspecting {name}:")
    
    indent = "  " * _current_depth
    next_indent = "  " * (_current_depth + 1)
    
    result = ""
    
    try:
        # Try to get attributes
        for attr_name in dir(obj):
            if attr_name.startswith("_"):
                continue
            
            try:
                attr_value = getattr(obj, attr_name)
                
                if callable(attr_value):
                    continue
                
                if _current_depth == 0:
                    result_line = f"{attr_name}: {debug_object(attr_value, attr_name, max_depth, _current_depth + 1)}"
                    logger.debug(f"{next_indent}{result_line}")
                    result += result_line + "\n"
                else:
                    result += f"{attr_name}: {debug_object(attr_value, attr_name, max_depth, _current_depth + 1)}, "
            except Exception as e:
                result += f"{attr_name}: <error: {str(e)}>, "
        
        return result if _current_depth > 0 else None
    except Exception as e:
        return f"<error inspecting: {str(e)}>"

def save_credentials(api_id, api_hash, phone):
    """Save API credentials to a file"""
    credentials = {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone": phone
    }
    
    credentials_file = f"sessions/credentials_{api_id}.json"
    with open(credentials_file, 'w') as f:
        json.dump(credentials, f)
        
    logger.info(f"Saved credentials for {api_id} to {credentials_file}")
    print(f"Saved credentials for future use")

def load_credentials(api_id):
    """Load API credentials from file"""
    credentials_file = f"sessions/credentials_{api_id}.json"
    
    if not os.path.exists(credentials_file):
        return None
        
    try:
        with open(credentials_file, 'r') as f:
            credentials = json.load(f)
            
        return credentials
    except Exception as e:
        logger.error(f"Error loading credentials for {api_id}: {str(e)}")
        return None

async def list_channels(client, display_to_user=False):
    """List all channels the client is part of"""
    logger.info("Starting channel listing")
    channels = []
    
    async for dialog in client.iter_dialogs():
        if dialog.is_channel:
            channel_info = {
                "name": dialog.name,
                "id": dialog.id,
                "has_comments": False,
                "comment_section_id": None,
                "unread_count": dialog.unread_count
            }
            
            logger.info(f"Found channel: {dialog.name} (ID: {dialog.id})")
            try:
                full_channel = await client(GetFullChannelRequest(channel=dialog.entity))
                has_comments = hasattr(full_channel.full_chat, 'linked_chat_id')
                channel_info["has_comments"] = has_comments
                
                logger.info(f"Channel {dialog.name} - Has comments: {has_comments}")
                if has_comments:
                    comment_id = full_channel.full_chat.linked_chat_id
                    channel_info["comment_section_id"] = comment_id
                    logger.info(f"Channel {dialog.name} - Comment section ID: {comment_id}")
            except Exception as e:
                logger.error(f"Error getting channel info for {dialog.name}: {str(e)}")
            
            channels.append(channel_info)
    
    if display_to_user and channels:
        print(f"\n{Fore.CYAN + Style.BRIGHT}" + "="*70 + Style.RESET_ALL)
        print(f"{Fore.GREEN + Style.BRIGHT}{'CHANNEL NAME':<40} {'CHANNEL ID':<15} {'COMMENTS':<8} {'UNREAD':<6}{Style.RESET_ALL}")
        print(f"{Fore.CYAN + Style.BRIGHT}" + "="*70 + Style.RESET_ALL)
        
        for channel in channels:
            name = channel["name"]
            if len(name) > 37:
                name = name[:34] + "..."
                
            comments_status = "Yes" if channel["has_comments"] else "No"
            if channel["comment_section_id"]:
                comments_status += f" ({channel['comment_section_id']})"
                
            # Color the channel name based on whether it has comments
            name_color = Fore.GREEN if channel["has_comments"] else Fore.WHITE
            unread_color = Fore.RED if channel["unread_count"] > 0 else Fore.WHITE
                
            print(f"{name_color}{name:<40}{Style.RESET_ALL} {Fore.YELLOW}{channel['id']:<15}{Style.RESET_ALL} {Fore.CYAN}{comments_status:<8}{Style.RESET_ALL} {unread_color}{channel['unread_count']:<6}{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN + Style.BRIGHT}" + "="*70 + Style.RESET_ALL)
        print(f"{Fore.GREEN + Style.BRIGHT}Total channels: {len(channels)}{Style.RESET_ALL}")
    
    return channels

async def display_channels_for_session():
    """Display channels for a specific session"""
    if not clients:
        print("\nNo active sessions found. Please create or load a session first.")
        return
    
    # List available sessions
    print("\nAvailable sessions:")
    sessions_list = []
    for i, (api_id, client) in enumerate(clients.items(), 1):
        try:
            me = await client.get_me()
            print(f"{i}. API ID: {api_id} - User: {me.first_name} ({me.id})")
            sessions_list.append((api_id, client))
        except Exception as e:
            print(f"{i}. API ID: {api_id} - Error: {str(e)}")
            sessions_list.append((api_id, client))
    
    # Get user choice
    choice = input("\nSelect a session (number) or press Enter to cancel: ").strip()
    if not choice:
        return
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(sessions_list):
            api_id, client = sessions_list[idx]
            me = await client.get_me()
            print(f"\nListing channels for session {api_id} ({me.first_name})...")
            await list_channels(client, display_to_user=True)
        else:
            print("Invalid selection.")
    except ValueError:
        print("Please enter a valid number.")
    except Exception as e:
        print(f"Error displaying channels: {str(e)}")

async def create_new_session():
    """Create a new Telegram session"""
    print(f"\n{Fore.CYAN + Style.BRIGHT}=== Create New Session ==={Style.RESET_ALL}")
    api_id = input(f"{Fore.YELLOW}Enter API ID: {Style.RESET_ALL}").strip()
    api_hash = input(f"{Fore.YELLOW}Enter API Hash: {Style.RESET_ALL}").strip()
    phone = input(f"{Fore.YELLOW}Enter phone number (with country code): {Style.RESET_ALL}").strip()
    
    try:
        client = TelegramClient(
            f"sessions/session_{api_id}",
            int(api_id),
            api_hash
        )
        
        await client.connect()
        if not await client.is_user_authorized():
            await client.start(phone=phone)
        
        me = await client.get_me()
        print(f"{Fore.GREEN + Style.BRIGHT}Successfully logged in as {me.first_name} ({me.id}){Style.RESET_ALL}")
        
        # Save credentials for future use
        save_credentials(api_id, api_hash, phone)
        
        # Add event handler
        client.add_event_handler(on_new_message, events.NewMessage())
        
        # List channels
        print(f"\n{Fore.CYAN}Scanning and listing channels...{Style.RESET_ALL}")
        await list_channels(client, display_to_user=True)
        
        clients[api_id] = client
        print(f"{Fore.GREEN + Style.BRIGHT}Session created and initialized successfully{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED + Style.BRIGHT}Error creating session: {str(e)}{Style.RESET_ALL}")
        if client.is_connected():
            await client.disconnect()

async def load_existing_sessions():
    """Load all existing sessions from the sessions directory"""
    session_files = glob.glob('sessions/session_*.session')
    
    if not session_files:
        print(f"{Fore.YELLOW}No existing sessions found in the sessions directory.{Style.RESET_ALL}")
        return
        
    print(f"\n{Fore.CYAN}Found existing sessions:{Style.RESET_ALL}")
    for session_file in session_files:
        api_id = session_file.split('_')[1].split('.')[0]
        print(f"- {Fore.MAGENTA}Session for API ID: {api_id}{Style.RESET_ALL}")
    
    for session_file in session_files:
        try:
            # Extract API ID from session filename
            api_id = session_file.split('_')[1].split('.')[0]
            
            # Skip if client already exists
            if api_id in clients:
                continue
            
            # Try to load credentials from file
            credentials = load_credentials(api_id)
            if credentials:
                print(f"\n{Fore.CYAN}Loading session for API ID: {api_id} (using saved credentials){Style.RESET_ALL}")
                api_hash = credentials['api_hash']
                phone = credentials['phone']
            else:
                print(f"\n{Fore.CYAN}Loading session for API ID: {api_id}{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}No saved credentials found. Please enter API hash:{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}(or press Enter to skip this session){Style.RESET_ALL}")
                api_hash = input().strip()
                
                if not api_hash:
                    print(f"{Fore.YELLOW}Skipping session {api_id}{Style.RESET_ALL}")
                    continue
                
                phone = None  # Not needed for existing sessions
            
            client = TelegramClient(
                f"sessions/session_{api_id}",
                int(api_id),
                api_hash
            )
            
            await client.connect()
            if not await client.is_user_authorized():
                if phone:
                    print(f"{Fore.YELLOW}Session requires authentication. Attempting to authenticate with saved phone number.{Style.RESET_ALL}")
                    await client.start(phone=phone)
                else:
                    print(f"{Fore.YELLOW}Session requires authentication but no phone number is saved.{Style.RESET_ALL}")
                    phone = input(f"{Fore.YELLOW}Enter phone number (with country code): {Style.RESET_ALL}").strip()
                    await client.start(phone=phone)
                    # Save credentials after successful authentication
                    save_credentials(api_id, api_hash, phone)
            
            me = await client.get_me()
            print(f"{Fore.GREEN}Successfully loaded session for {me.first_name} ({me.id}){Style.RESET_ALL}")
            
            # Add event handler
            client.add_event_handler(on_new_message, events.NewMessage())
            
            # List channels (log only)
            await list_channels(client)
            
            clients[api_id] = client
            print(f"{Fore.GREEN}Session {api_id} loaded successfully{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.RED}Error loading session {api_id}: {str(e)}{Style.RESET_ALL}")
            if client.is_connected():
                await client.disconnect()

async def load_channels_from_file():
    """Load channel list from a JSON file"""
    while True:
        print("\n=== Load Channels from JSON File ===")
        filename = input("Enter the path to your channels JSON file (or press Enter to cancel): ").strip()
        
        if not filename:
            return None
            
        if not os.path.exists(filename):
            print(f"Error: File '{filename}' not found.")
            continue
            
        try:
            with open(filename, 'r') as f:
                channels_data = json.load(f)
                
            if not isinstance(channels_data, list):
                print("Error: JSON file must contain a list of channel links.")
                continue
                
            print(f"Successfully loaded {len(channels_data)} channels from {filename}")
            return channels_data
            
        except json.JSONDecodeError:
            print("Error: Invalid JSON format. Please check your file.")
        except Exception as e:
            print(f"Error loading channels: {str(e)}")

async def join_channel(client, channel_link):
    """Join a specific channel using a Telegram link"""
    try:
        logger.info(f"Attempting to join channel: {channel_link}")
        
        # Strip the URL prefix if present
        if channel_link.startswith("https://t.me/"):
            channel_link = channel_link.replace("https://t.me/", "")
            
        # Handle different types of channel links
        if channel_link.startswith("+"):
            # Private channel with hash
            invite_hash = channel_link.replace("+", "")
            logger.info(f"Processing as private channel with hash: {invite_hash}")
            try:
                result = await client(ImportChatInviteRequest(invite_hash))
                return True, f"Joined private channel: {result.chats[0].title}"
            except Exception as e:
                error_str = str(e).lower()
                if "already in chat" in error_str or "already a participant" in error_str:
                    logger.info(f"Already a member of channel: {channel_link}")
                    return True, f"Already a member of channel: {channel_link}"
                
                logger.error(f"Error joining channel with hash {invite_hash}: {str(e)}")
                return False, f"Failed to join {channel_link}: {str(e)}"
                
        elif channel_link.startswith("joinchat/"):
            # Old-style private channel
            invite_hash = channel_link.replace("joinchat/", "")
            logger.info(f"Processing as old-style private channel with hash: {invite_hash}")
            try:
                result = await client(ImportChatInviteRequest(invite_hash))
                return True, f"Joined private channel: {result.chats[0].title}"
            except Exception as e:
                error_str = str(e).lower()
                if "already in chat" in error_str or "already a participant" in error_str:
                    logger.info(f"Already a member of channel: {channel_link}")
                    return True, f"Already a member of channel: {channel_link}"
                
                logger.error(f"Error joining channel with hash {invite_hash}: {str(e)}")
                return False, f"Failed to join {channel_link}: {str(e)}"
                
        else:
            # Public channel
            logger.info(f"Processing as public channel: {channel_link}")
            try:
                # Simply attempt to join - Telegram will handle "already a member" case
                result = await client(ResolveUsernameRequest(channel_link))
                await client(JoinChannelRequest(result.chats[0]))
                return True, f"Joined public channel: {result.chats[0].title}"
            except Exception as e:
                error_str = str(e).lower()
                if "already in chat" in error_str or "already a participant" in error_str:
                    logger.info(f"Already a member of channel: {channel_link}")
                    return True, f"Already a member of channel: {channel_link}"
                elif "banned" in error_str or "not allowed" in error_str:
                    logger.error(f"Cannot join channel {channel_link}: User is banned")
                    return False, f"❌ Banned in channel: {channel_link}"
                elif "wait for admin approval" in error_str or "needs admin approval" in error_str or "successfully requested to join" in error_str:
                    logger.info(f"Channel {channel_link} requires admin approval")
                    return "pending", f"⏳ Pending admin approval: {channel_link}"
                elif "floodwait" in error_str:
                    wait_time = re.search(r'(\d+)', error_str)
                    seconds = int(wait_time.group(1)) if wait_time else 60
                    logger.warning(f"Rate limited joining {channel_link}, must wait {seconds} seconds")
                    return "floodwait", f"⏱️ Rate limited: Must wait {seconds} seconds for {channel_link}"
                
                logger.error(f"Error joining public channel {channel_link}: {str(e)}")
                return False, f"Failed to join {channel_link}: {str(e)}"
            
    except Exception as e:
        error_str = str(e).lower()
        if "already in chat" in error_str or "already a participant" in error_str:
            logger.info(f"Already a member of channel: {channel_link}")
            return True, f"Already a member of channel: {channel_link}"
        elif "banned" in error_str or "not allowed" in error_str:
            logger.error(f"Cannot join channel {channel_link}: User is banned")
            return False, f"❌ Banned in channel: {channel_link}"
        elif "wait for admin approval" in error_str or "needs admin approval" in error_str or "successfully requested to join" in error_str:
            logger.info(f"Channel {channel_link} requires admin approval")
            return "pending", f"⏳ Pending admin approval: {channel_link}"
        elif "floodwait" in error_str:
            wait_time = re.search(r'(\d+)', error_str)
            seconds = int(wait_time.group(1)) if wait_time else 60
            logger.warning(f"Rate limited joining {channel_link}, must wait {seconds} seconds")
            return "floodwait", f"⏱️ Rate limited: Must wait {seconds} seconds for {channel_link}"
            
        logger.error(f"Unexpected error joining {channel_link}: {str(e)}")
        return False, f"Failed to join {channel_link}: {str(e)}"

async def synchronize_channels(client, channels_list, all_channels=False):
    """Synchronize channels for a specific client"""
    colorama_init()
    
    # Skip empty channel links
    channels_to_join = [channel for channel in channels_list if channel.strip()]
    
    if not channels_to_join:
        print(f"\n{Fore.YELLOW}No channels to join.{Style.RESET_ALL}")
        return True, "No channels to join"
    
    join_count = 0
    success_count = 0
    failed_count = 0
    pending_count = 0
    banned_count = 0
    flood_wait_count = 0
    already_member_count = 0
    pending_channels = []
    
    total_channels = len(channels_to_join)
    print(f"\n{Fore.CYAN}Starting channel synchronization...{Style.RESET_ALL}")
    print(f"  • Attempting to join {total_channels} channels")
    
    for i, channel in enumerate(channels_to_join):
        # Show progress
        progress = (i + 1) / total_channels * 100
        print(f"{Fore.YELLOW}[{progress:.1f}%] Processing {i+1}/{total_channels}: {channel}{Style.RESET_ALL}")
        
        # Join channel
        status, message = await join_channel(client, channel)
        print(f"  • {message}")
        
        # Update statistics based on result
        if status is True:
            if "Already a member" in message:
                already_member_count += 1
            else:
                success_count += 1
                join_count += 1
        elif status == "pending":
            pending_count += 1
            pending_channels.append(channel)
        elif status == "floodwait":
            flood_wait_count += 1
            wait_match = re.search(r'Must wait (\d+) seconds', message)
            if wait_match:
                wait_seconds = int(wait_match.group(1))
                print(f"{Fore.YELLOW}⏱️ Rate limited by Telegram. Waiting {wait_seconds} seconds...{Style.RESET_ALL}")
                
                # Display a countdown
                for remaining in range(wait_seconds, 0, -1):
                    sys.stdout.write(f"\r  Waiting: {remaining} seconds remaining...  ")
                    sys.stdout.flush()
                    await asyncio.sleep(1)
                print("\n  Continuing after wait period")
            else:
                # Default wait if we couldn't parse the time
                print(f"{Fore.YELLOW}⏱️ Rate limited by Telegram. Waiting 60 seconds...{Style.RESET_ALL}")
                await asyncio.sleep(60)
        elif "Banned in channel" in message:
            banned_count += 1
        else:
            failed_count += 1
            
        # If we've joined 4 new channels, take a break
        if join_count > 0 and join_count % 4 == 0:
            wait_time = 300  # 5 minutes in seconds
            print(f"{Fore.CYAN}🕒 Joined 4 channels. Taking a 5-minute break to avoid rate limits...{Style.RESET_ALL}")
            
            # Display a countdown during the wait
            for remaining in range(wait_time, 0, -1):
                mins, secs = divmod(remaining, 60)
                countdown = f"{mins:02d}:{secs:02d}"
                emoji = "⏳" if remaining % 2 == 0 else "⌛"
                sys.stdout.write(f"\r{emoji} Cooldown: {countdown} remaining until next batch  ")
                sys.stdout.flush()
                await asyncio.sleep(1)
            print("\n✅ Cooldown complete. Continuing with channel joins...")
        else:
            # Add a small delay between joins to avoid immediate rate limiting
            await asyncio.sleep(1)
    
    # Print summary
    print(f"\n{Fore.CYAN}Channel Synchronization Summary:{Style.RESET_ALL}")
    print(f"  • {Fore.GREEN}Successfully joined: {success_count}{Style.RESET_ALL}")
    print(f"  • {Fore.CYAN}Already a member of: {already_member_count}{Style.RESET_ALL}")
    print(f"  • {Fore.YELLOW}Pending admin approval: {pending_count}{Style.RESET_ALL}")
    print(f"  • {Fore.RED}Failed to join: {failed_count}{Style.RESET_ALL}")
    print(f"  • {Fore.RED}Banned in channels: {banned_count}{Style.RESET_ALL}")
    print(f"  • {Fore.YELLOW}Rate limited: {flood_wait_count}{Style.RESET_ALL}")
    
    # If there are pending channels, display them
    if pending_channels:
        print(f"\n{Fore.YELLOW}Channels awaiting admin approval:{Style.RESET_ALL}")
        for channel in pending_channels:
            print(f"  • {channel}")
    
    if success_count == 0 and pending_count == 0 and already_member_count == 0:
        return False, "Failed to join any channels"
    else:
        return True, f"Joined {success_count} channels, {pending_count} pending approval, {already_member_count} already a member"

async def synchronize_channels_for_all():
    """Synchronize channels across all sessions"""
    if not clients:
        print(f"\n{Fore.RED}No active sessions found. Please create or load a session first.{Style.RESET_ALL}")
        return
        
    # Load channels from JSON file
    channels = await load_channels_from_file()
    if not channels:
        return
        
    print(f"\n{Fore.GREEN}Preparing to synchronize {Fore.YELLOW}{len(channels)}{Fore.GREEN} channels across {Fore.YELLOW}{len(clients)}{Fore.GREEN} sessions...{Style.RESET_ALL}")
    
    # Process each session
    for api_id, client in clients.items():
        try:
            me = await client.get_me()
            print(f"\n{Fore.CYAN + Style.BRIGHT}=== Synchronizing channels for {Fore.GREEN}{me.first_name}{Fore.CYAN} (API ID: {api_id}) ==={Style.RESET_ALL}")
            
            # Use our enhanced synchronize_channels function for this client
            success, message = await synchronize_channels(client, channels)
            
            if success:
                print(f"\n{Fore.GREEN}Successfully synchronized channels for {me.first_name} (API ID: {api_id}){Style.RESET_ALL}")
            else:
                print(f"\n{Fore.YELLOW}Completed synchronization for {me.first_name} (API ID: {api_id}) with some issues: {message}{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.RED}Error processing session {api_id}: {str(e)}{Style.RESET_ALL}")
            
    print(f"\n{Fore.GREEN + Style.BRIGHT}Channel synchronization complete for all sessions!{Style.RESET_ALL}")
    
    # Ask if user wants to view channels
    view_channels = input(f"\n{Fore.YELLOW}Do you want to view channels for a session now? (y/n): {Style.RESET_ALL}").strip().lower()
    if view_channels == 'y':
        await display_channels_for_session()

async def show_menu():
    """Show the main menu and handle user choices"""
    colorama_init(autoreset=True)  # Initialize colorama
    
    while True:
        print(f"\n{Fore.CYAN + Style.BRIGHT}=== Telegram Auto-Responder Bot ==={Style.RESET_ALL}")
        print(f"1. Create new session")
        print(f"2. Load existing session")
        print(f"3. List active sessions")
        print(f"4. List channels for a session")
        print(f"5. Synchronize channels across sessions")
        print(f"6. Start monitoring")
        print(f"7. Set DeepSeek API Key")
        print(f"8. Set AI personality")
        print(f"9. Exit")
        
        choice = input(f"{Fore.YELLOW}Enter your choice (1-9): {Style.RESET_ALL}")
        
        if choice == '1':
            await create_new_session()
        elif choice == '2':
            await load_existing_sessions()
        elif choice == '3':
            print(f"\n{Fore.CYAN}Active Sessions:{Style.RESET_ALL}")
            for api_id, client in clients.items():
                try:
                    me = await client.get_me()
                    print(f"{Fore.MAGENTA}API ID: {api_id}{Style.RESET_ALL} - User: {Fore.GREEN}{me.first_name}{Style.RESET_ALL} ({me.id})")
                except Exception as e:
                    print(f"{Fore.MAGENTA}API ID: {api_id}{Style.RESET_ALL} - {Fore.RED}Error getting user info: {str(e)}{Style.RESET_ALL}")
        elif choice == '4':
            await display_channels_for_session()
        elif choice == '5':
            await synchronize_channels_for_all()
        elif choice == '6':
            if not clients:
                print(f"{Fore.RED}No active sessions. Please create at least one session first.{Style.RESET_ALL}")
                continue
                
            if not DEEPSEEK_API_KEY:
                print(f"{Fore.RED}DeepSeek API Key not set. Please set it first.{Style.RESET_ALL}")
                await set_deepseek_api_key()
                if not DEEPSEEK_API_KEY:
                    continue
                    
            print(f"\n{Fore.GREEN}Starting monitoring for all sessions...{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Press Ctrl+C to stop monitoring.{Style.RESET_ALL}")
            
            try:
                # Set up event handlers for all clients
                for client in clients.values():
                    client.add_event_handler(on_new_message, events.NewMessage)
                    client.add_event_handler(handle_channel_post, events.NewChannelMessage)
                    
                # Keep the program running
                await asyncio.gather(*[client.run_until_disconnected() for client in clients.values()])
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}Monitoring stopped by user.{Style.RESET_ALL}")
            except Exception as e:
                print(f"\n{Fore.RED}Error during monitoring: {str(e)}{Style.RESET_ALL}")
        elif choice == '7':
            await set_deepseek_api_key()
        elif choice == '8':
            await set_ai_personality()
        elif choice == '9':
            print(f"{Fore.GREEN}Exiting program. Goodbye!{Style.RESET_ALL}")
            # Clean up and close clients
            for client in clients.values():
                await client.disconnect()
            break
        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

async def set_deepseek_api_key():
    """Set the DeepSeek API key"""
    global DEEPSEEK_API_KEY, api_clients
    print(f"\n{Fore.CYAN + Style.BRIGHT}=== Set DeepSeek API Key ==={Style.RESET_ALL}")
    api_key = input(f"{Fore.YELLOW}Enter your DeepSeek API key (or press Enter to keep current): {Style.RESET_ALL}").strip()
    
    if api_key:
        DEEPSEEK_API_KEY = api_key
        os.environ["DEEPSEEK_API_KEY"] = api_key
        
        # Clear all API clients to force recreation with new key
        api_clients = {}
        
        print(f"{Fore.GREEN}DeepSeek API key has been set. All API clients will be recreated.{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}DeepSeek API key unchanged.{Style.RESET_ALL}")
    
    return DEEPSEEK_API_KEY

async def generate_response(api_id, channel_name, channel_bio, message_text):
    """Generate a response using DeepSeek API"""
    try:
        # Get or create a client-specific OpenAI client
        if api_id not in api_clients:
            api_clients[api_id] = openai.OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com"
            )
            logger.info(f"Created new DeepSeek API client for session {api_id}")
        
        client = api_clients[api_id]
        logger.info(f"Using DeepSeek API client for session {api_id}")
        
        # Get personality and formality settings
        personality = AI_PERSONALITY.lower()
        formality = AI_FORMALITY.lower()
        
        # Define personality traits
        personality_traits = {
            "default": "сбалансированную личность с умеренной эмоциональностью",
            "friendly": "дружелюбную, отзывчивую личность, которая всегда поддерживает собеседника",
            "witty": "остроумную личность с лёгким сарказмом и юмором",
            "expert": "компетентную личность, демонстрирующую глубокие знания в обсуждаемой теме",
            "provocative": "личность, которая вежливо ставит под сомнение утверждения и провоцирует дискуссию"
        }
        
        # Define formality levels
        formality_styles = {
            "casual": "неформальный разговорный стиль с использованием сленга и простых конструкций",
            "neutral": "повседневный нейтральный стиль, подходящий для большинства ситуаций",
            "formal": "более формальный стиль с правильными речевыми конструкциями и минимумом сленга"
        }
        
        personality_trait = personality_traits.get(personality, personality_traits["default"])
        formality_style = formality_styles.get(formality, formality_styles["casual"])
        
        # Enhanced system role with Russian personality instruction
        system_role = f"""Ты - русскоговорящий участник Telegram-сообщества.
Ты демонстрируешь {personality_trait}.
Ты используешь {formality_style}.
Твоя задача - писать естественные, разговорные ответы, которые звучат как сообщения от реального человека, а не как формальные ответы AI.
Используй уместные русские выражения и интонации.
Ты должен ВСЕГДА отвечать ТОЛЬКО на русском языке, независимо от языка сообщения пользователя.
Ты умеешь подстраивать свой стиль под тематику канала, в котором участвуешь."""
        
        # Determine channel category to adjust the personality
        channel_category = "общий"  # default - general
        tech_keywords = ["программирование", "python", "код", "разработк", "технолог", "IT", "компьютер", "software", "hardware"]
        politics_keywords = ["политик", "власт", "президент", "правительств", "экономик", "оппозиц", "выбор", "партия", "дума"]
        entertainment_keywords = ["кино", "фильм", "сериал", "музык", "игр", "развлечен", "юмор", "мем", "шутк"]
        
        lowercase_name = (channel_name + " " + channel_bio).lower()
        
        if any(keyword in lowercase_name for keyword in tech_keywords):
            channel_category = "технологии"
        elif any(keyword in lowercase_name for keyword in politics_keywords):
            channel_category = "политика"
        elif any(keyword in lowercase_name for keyword in entertainment_keywords):
            channel_category = "развлечения"
            
        # Add personality variations based on the channel category
        personality_instructions = {
            "общий": "Используй нейтральный разговорный стиль с умеренной эмоциональностью.",
            "технологии": "Используй более точный технический язык с некоторыми профессиональными терминами, но оставаясь понятным. Можешь проявлять умеренный энтузиазм к технологиям.",
            "политика": "Будь сдержанным и рассудительным, избегай крайне радикальных взглядов. Старайся обсуждать события с разных точек зрения.",
            "развлечения": "Будь более эмоциональным и неформальным, используй современный разговорный русский язык. Можешь использовать больше эмодзи и популярных выражений."
        }
        
        # Prepare the enhanced prompt
        prompt = f"""
Информация о канале:
Название канала: {channel_name}
Описание канала: {channel_bio}
Категория канала: {channel_category}

Сообщение пользователя: 
{message_text}

Инструкции по ответу:
{personality_instructions.get(channel_category, personality_instructions["общий"])}

1. Твой ответ должен быть ОБЯЗАТЕЛЬНО на русском языке
2. Сделай ответ коротким (не более 20 слов) и естественным
3. Включи 1-2 эмодзи где уместно (но не переусердствуй)
4. Используй разговорный стиль, как будто пишешь в настоящем чате
5. Не используй штампы вроде "Привет! Спасибо за ваше сообщение..."
6. Либо поддержи обсуждаемую тему, либо вежливо выскажи альтернативную точку зрения
7. Избегай штампованных фраз вроде "Интересная точка зрения!" или "Это действительно так!"
8. Не упоминай о том, что ты AI

Отвечай ТОЛЬКО текстом сообщения, без кавычек, преамбул или пояснений. Ответ должен выглядеть как обычное сообщение от человека в Telegram.
"""
        
        # Log the personality and formality settings used
        logger.debug(f"Session {api_id}: Using personality: {personality}, formality: {formality}")
        
        # Make the API call with environment-configured parameters
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt}
            ],
            max_tokens=AI_MAX_TOKENS,
            temperature=AI_TEMPERATURE
        )
        
        # Extract the response text
        reply_text = response.choices[0].message.content.strip()
        
        # Ensure response is in Russian - fallback if AI generates non-Russian response
        if not any(ord(char) >= 1040 and ord(char) <= 1103 for char in reply_text):
            logger.warning(f"Session {api_id}: Response not in Russian, applying fallback")
            
            # Different fallback responses based on personality
            fallback_responses = {
                "default": [
                    "Интересная мысль! 🤔", 
                    "Согласен с тобой! 👍",
                    "А что если посмотреть с другой стороны? 🧐", 
                    "Хороший вопрос! Дай подумать...",
                ],
                "friendly": [
                    "Отличная идея, мне нравится! 😊", 
                    "Полностью поддерживаю тебя в этом! 👍", 
                    "Как здорово, что ты это заметил! ✨",
                    "Всегда приятно обсудить такие темы! 💬",
                ],
                "witty": [
                    "И как ты до такого додумался? 😏", 
                    "Ну это смотря с какой стороны посмотреть... 🙃", 
                    "В этом определённо что-то есть! Или нет? 🤔",
                    "А вот и ещё один эксперт подъехал! 😁",
                ],
                "expert": [
                    "С технической точки зрения, тут есть нюансы...", 
                    "Если проанализировать глубже, можно прийти к иному выводу.", 
                    "В профессиональной среде это называется иначе.",
                    "Интересный тезис, хотя фактически ситуация сложнее.",
                ],
                "provocative": [
                    "А ты уверен, что это так? 🤨", 
                    "Весьма спорное утверждение, если честно.", 
                    "А доказательства этому есть? 🧐",
                    "Я бы поспорил с этим мнением! 💭",
                ]
            }
            
            # Get the appropriate list based on personality, defaulting to "default" if not found
            responses_list = fallback_responses.get(personality, fallback_responses["default"])
            
            import random
            reply_text = random.choice(responses_list)
        
        logger.info(f"Session {api_id}: Generated response: {reply_text}")
        return reply_text
        
    except Exception as e:
        logger.error(f"Session {api_id}: Error generating response: {str(e)}")
        return None

async def on_new_message(event):
    """Message handler"""
    try:
        # Get client info
        client = event.client
        api_id = None
        for id, cl in clients.items():
            if cl == client:
                api_id = id
                break
        
        if not api_id:
            logger.warning("Received message event for unknown client, skipping")
            return
        
        logger.info(f"New message event received for client {api_id}")
        
        # Get message details
        chat = await event.get_chat()
        sender = await event.get_sender()
        
        # Skip our own messages - More thorough check
        me = await client.get_me()
        is_our_message = False
        
        # Check by sender ID
        if sender and hasattr(sender, 'id') and sender.id == me.id:
            is_our_message = True
            
        # Also check by message attributes (some API responses may not have proper sender info)
        if hasattr(event.message, 'out') and event.message.out:
            is_our_message = True
            
        if is_our_message:
            logger.debug(f"Client {api_id}: Skipping our own message")
            return
        
        # Check if this chat is a private conversation (skip DMs)
        if not hasattr(chat, 'title') or not chat.title:
            logger.debug(f"Client {api_id}: Skipping private conversation message")
            return
            
        # Log basic message info
        chat_title = getattr(chat, 'title', 'Unknown')
        logger.info(f"Client {api_id}: Message in chat: {chat_title} ({chat.id})")
        logger.info(f"Client {api_id}: Sender: {getattr(sender, 'first_name', 'Unknown')} ({getattr(sender, 'id', 'Unknown')})")
        logger.info(f"Client {api_id}: Message text: {event.message.text}")
        logger.info(f"Client {api_id}: Is channel: {event.is_channel}")
        
        # Add rate limiting to prevent sending too many responses
        # Create a unique key for this chat
        chat_key = f"{api_id}_{chat.id}"
        current_time = time.time()
        
        # Check if we've recently responded in this chat
        if chat_key in last_response_time:
            time_since_last = current_time - last_response_time[chat_key]
            # If less than 30 seconds have passed, don't respond
            if time_since_last < 30:
                logger.info(f"Client {api_id}: Rate limiting - last response was {time_since_last:.1f} seconds ago")
                return
                
        # Get chat bio if available
        try:
            if hasattr(chat, 'about'):
                chat_bio = chat.about
            else:
                full_chat = await client(GetFullChannelRequest(channel=chat))
                chat_bio = full_chat.full_chat.about if hasattr(full_chat.full_chat, 'about') else ""
        except Exception as e:
            logger.error(f"Client {api_id}: Error getting chat bio: {str(e)}")
            chat_bio = ""
        
        # Determine message type
        is_channel_post = event.is_channel and getattr(event.message, 'post', False)
        is_forwarded = hasattr(event.message, 'fwd_from') and event.message.fwd_from is not None
        
        # CASE 1: Handle original channel posts (respond in their discussion groups)
        if is_channel_post:
            logger.info(f"Client {api_id}: Detected a channel post, will respond in comments section if available")
            await handle_channel_post(client, api_id, event, chat, chat_title, chat_bio)
            
        # CASE 2: Handle messages in discussion groups (only respond to original messages, not forwarded)
        elif not is_channel_post and not is_forwarded:
            # This is a regular message in a group chat
            logger.info(f"Client {api_id}: Detected regular group message, responding directly")
            
            # Generate response using DeepSeek API - specific for this client and message
            response_text = await generate_response(
                api_id=api_id,
                channel_name=chat_title,
                channel_bio=chat_bio,
                message_text=event.message.text
            )
            
            if response_text:
                logger.info(f"Client {api_id}: Sending direct response: {response_text}")
                await event.respond(response_text)
                
                # Update the last response time for this chat
                last_response_time[chat_key] = current_time
        else:
            logger.info(f"Client {api_id}: Skipping forwarded message in group chat")
            
    except Exception as e:
        logger.error(f"Error in message handler: {str(e)}", exc_info=True)

async def handle_channel_post(client, api_id, event, chat, chat_title, chat_bio):
    """Handle a channel post - find discussion group and respond there"""
    try:
        # Get full channel info to find the linked discussion group
        full_channel = await client(GetFullChannelRequest(channel=chat))
        linked_chat_id = full_channel.full_chat.linked_chat_id if hasattr(full_channel.full_chat, 'linked_chat_id') else None
        
        if not linked_chat_id:
            logger.warning(f"Client {api_id}: Channel {chat_title} has no linked discussion group, skipping")
            return
            
        logger.info(f"Client {api_id}: Found linked discussion group ID: {linked_chat_id}")
        
        # Create unique key for this discussion group and original post
        chat_post_key = f"{api_id}_{linked_chat_id}_{event.message.id}"
        current_time = time.time()
        
        # Check if we've recently responded to this post
        if chat_post_key in last_response_time:
            time_since_last = current_time - last_response_time[chat_post_key]
            # If less than 10 minutes have passed, don't respond to the same post again
            if time_since_last < 600:  # 10 minutes
                logger.info(f"Client {api_id}: Already responded to this post {time_since_last:.1f} seconds ago, skipping")
                return
        
        # Generate response using DeepSeek API - specific for this client and message
        response_text = await generate_response(
            api_id=api_id,
            channel_name=chat_title,
            channel_bio=chat_bio,
            message_text=event.message.text
        )
        
        if response_text:
            # First check if we can access the linked discussion group
            try:
                # Try to get the discussion group entity
                linked_chat = await client.get_entity(linked_chat_id)
                logger.info(f"Client {api_id}: Accessing discussion group: {getattr(linked_chat, 'title', 'Unknown')}")
                
                # Check if we can send messages to this chat
                # In Telegram, one way to check this is to see if we can get messages from the group
                try:
                    # Try to get a few messages from the group to verify access
                    messages = await client.get_messages(linked_chat, limit=1)
                    can_access = True
                    logger.info(f"Client {api_id}: Successfully verified access to discussion group")
                    
                    # Additional check: try to get chat permissions if available
                    try:
                        full_chat = await client(GetFullChannelRequest(channel=linked_chat))
                        
                        # Check for restricted rights if relevant fields exist 
                        if (hasattr(full_chat, 'full_chat') and 
                            hasattr(full_chat.full_chat, 'default_banned_rights')):
                            rights = full_chat.full_chat.default_banned_rights
                            
                            # Check if sending messages is prohibited
                            if hasattr(rights, 'send_messages') and rights.send_messages:
                                logger.warning(f"Client {api_id}: No permission to send messages in discussion group")
                                return
                            
                            logger.info(f"Client {api_id}: Confirmed sending rights in discussion group")
                    except Exception as e:
                        # If we can't check permissions, log warning but proceed anyway
                        logger.warning(f"Client {api_id}: Couldn't verify detailed permissions: {str(e)}")
                        
                except Exception as e:
                    error_msg = str(e).lower()
                    if "not accessible" in error_msg or "restricted" in error_msg or "banned" in error_msg:
                        logger.error(f"Client {api_id}: Cannot access discussion group (banned or needs approval): {str(e)}")
                        return
                    elif "authorization" in error_msg or "privacy" in error_msg:
                        logger.error(f"Client {api_id}: Cannot access discussion group due to privacy settings: {str(e)}")
                        return
                    else:
                        # Other errors might be temporary, we can try to proceed
                        logger.warning(f"Client {api_id}: Issue checking discussion group access: {str(e)}, will try anyway")
                
                # Send message to the linked discussion group, with reply to the forwarded post
                # We need to find the forwarded message in the discussion group
                forwarded_post_found = False
                async for message in client.iter_messages(linked_chat, limit=15):
                    # Debug details about each message
                    if message.fwd_from:
                        logger.debug(f"Client {api_id}: Checking message: {message.id}")
                        debug_object(message.fwd_from, f"Client {api_id}: fwd_from for message {message.id}")
                        
                        # Try various ways to match the post
                        channel_match = False
                        
                        # Method 1: Check via from_id.channel_id
                        if (hasattr(message.fwd_from, 'from_id') and 
                            hasattr(message.fwd_from.from_id, 'channel_id') and 
                            message.fwd_from.from_id.channel_id == chat.id):
                            channel_match = True
                            logger.debug(f"Client {api_id}: Matched via from_id.channel_id")
                        
                        # Method 2: Check via channel_id directly
                        elif hasattr(message.fwd_from, 'channel_id') and message.fwd_from.channel_id == chat.id:
                            channel_match = True
                            logger.debug(f"Client {api_id}: Matched via direct channel_id")
                        
                        # Method 3: Check via saved_from_peer if available
                        elif (hasattr(message.fwd_from, 'saved_from_peer') and 
                              hasattr(message.fwd_from.saved_from_peer, 'channel_id') and
                              message.fwd_from.saved_from_peer.channel_id == chat.id):
                            channel_match = True
                            logger.debug(f"Client {api_id}: Matched via saved_from_peer.channel_id")
                        
                        # Method 4: Check via from_name matching channel title
                        elif (hasattr(message.fwd_from, 'from_name') and 
                              message.fwd_from.from_name and 
                              chat_title.lower() in message.fwd_from.from_name.lower()):
                            channel_match = True
                            logger.debug(f"Client {api_id}: Matched via from_name similarity")
                        
                        # If channel matches, check for matching post ID
                        if channel_match:
                            post_match = False
                            
                            # Check direct channel_post attribute
                            if hasattr(message.fwd_from, 'channel_post') and message.fwd_from.channel_post == event.message.id:
                                post_match = True
                                logger.debug(f"Client {api_id}: Matched via channel_post")
                            
                            # Check saved_from_msg_id
                            elif hasattr(message.fwd_from, 'saved_from_msg_id') and message.fwd_from.saved_from_msg_id == event.message.id:
                                post_match = True
                                logger.debug(f"Client {api_id}: Matched via saved_from_msg_id")
                            
                            # Last resort: match by content and proximity 
                            # (message was posted shortly after the channel post)
                            elif (message.text == event.message.text and 
                                  abs(message.date.timestamp() - event.message.date.timestamp()) < 300):  # 5 minutes
                                post_match = True
                                logger.debug(f"Client {api_id}: Matched via content and time proximity")
                            
                            if post_match:
                                # We found a match!
                                logger.info(f"Client {api_id}: Found forwarded post in discussion group, message ID: {message.id}")
                                try:
                                    await client.send_message(
                                        entity=linked_chat,
                                        message=response_text,
                                        reply_to=message.id
                                    )
                                    logger.info(f"Client {api_id}: Response sent as reply in discussion group")
                                    
                                    # Record that we responded to this post
                                    last_response_time[chat_post_key] = current_time
                                    
                                    forwarded_post_found = True
                                    break
                                except Exception as e:
                                    error_msg = str(e).lower()
                                    if "not allowed" in error_msg or "restricted" in error_msg or "banned" in error_msg:
                                        logger.error(f"Client {api_id}: Cannot reply in discussion group (banned or restricted): {str(e)}")
                                        return
                                    elif "wait for admin approval" in error_msg or "must be approved" in error_msg:
                                        logger.warning(f"Client {api_id}: Need admin approval to comment in discussion group: {str(e)}")
                                        return
                                    elif "floodwait" in error_msg:
                                        wait_time = re.search(r'(\d+)', error_msg)
                                        seconds = int(wait_time.group(1)) if wait_time else 60
                                        logger.warning(f"Client {api_id}: Rate limited when replying, must wait {seconds} seconds")
                                        return
                                    else:
                                        logger.error(f"Client {api_id}: Error responding to post: {str(e)}")
                                        return
                
                # If we couldn't find the forwarded message, just post in the discussion group
                if not forwarded_post_found:
                    logger.warning(f"Client {api_id}: Couldn't find forwarded post in discussion group, sending message without reply")
                    try:
                        await client.send_message(linked_chat, response_text)
                        logger.info(f"Client {api_id}: Response sent to discussion group (without reply)")
                        
                        # Still record that we responded to the post
                        last_response_time[chat_post_key] = current_time
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "not allowed" in error_msg or "restricted" in error_msg or "banned" in error_msg:
                            logger.error(f"Client {api_id}: Cannot send messages in discussion group (banned or restricted): {str(e)}")
                        elif "wait for admin approval" in error_msg or "must be approved" in error_msg:
                            logger.warning(f"Client {api_id}: Need admin approval to comment in discussion group: {str(e)}")
                        elif "floodwait" in error_msg:
                            wait_time = re.search(r'(\d+)', error_msg)
                            seconds = int(wait_time.group(1)) if wait_time else 60
                            logger.warning(f"Client {api_id}: Rate limited when sending message, must wait {seconds} seconds")
                        else:
                            logger.error(f"Client {api_id}: Error sending message to discussion group: {str(e)}")
                
            except Exception as e:
                error_msg = str(e).lower()
                if "not found" in error_msg or "access" in error_msg:
                    logger.error(f"Client {api_id}: Cannot access discussion group (not joined or not found): {str(e)}")
                elif "banned" in error_msg or "restricted" in error_msg:
                    logger.error(f"Client {api_id}: Cannot access discussion group (banned): {str(e)}")
                elif "join" in error_msg or "approval" in error_msg:
                    logger.warning(f"Client {api_id}: Cannot access discussion group (need to join or get approval): {str(e)}")
                else:
                    logger.error(f"Client {api_id}: Error accessing discussion group: {str(e)}")
                    
        else:
            logger.warning(f"Client {api_id}: Could not generate response for channel post")
        
    except Exception as e:
        logger.error(f"Client {api_id}: Error handling channel post: {str(e)}", exc_info=True)

async def keep_clients_alive():
    """Keep checking client connections"""
    while True:
        for api_id, client in clients.items():
            try:
                if not client.is_connected():
                    logger.warning(f"Client {api_id} disconnected, attempting to reconnect")
                    await client.connect()
                    if not client.is_connected():
                        logger.error(f"Failed to reconnect client {api_id}")
                else:
                    logger.debug(f"Client {api_id} is connected")
            except Exception as e:
                logger.error(f"Error checking client {api_id}: {str(e)}")
        await asyncio.sleep(60)  # Check every minute

async def main():
    # Load existing sessions
    await load_existing_sessions()
    
    # Show menu and wait for user choice
    if not await show_menu():
        print(f"{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.GREEN + Style.BRIGHT}Starting monitoring...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Bot is now active and listening for messages in {len(clients)} session(s){Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Press Ctrl+C to stop{Style.RESET_ALL}")
    
    # Create tasks for client connections and monitoring
    tasks = [
        keep_clients_alive(),
        *(client.run_until_disconnected() for client in clients.values())
    ]
    
    # Run everything concurrently
    await asyncio.gather(*tasks)

async def set_ai_personality():
    """Set the AI personality settings"""
    global AI_PERSONALITY, AI_FORMALITY
    
    print(f"\n{Fore.CYAN + Style.BRIGHT}=== Set AI Personality Settings ==={Style.RESET_ALL}")
    
    # Personality setting
    print(f"\n{Fore.CYAN}Available personality types:{Style.RESET_ALL}")
    print(f"1. {Fore.GREEN}Default{Style.RESET_ALL} - Balanced personality with moderate emotions")
    print(f"2. {Fore.GREEN}Friendly{Style.RESET_ALL} - Supportive and encouraging personality")
    print(f"3. {Fore.GREEN}Witty{Style.RESET_ALL} - Humorous personality with light sarcasm")
    print(f"4. {Fore.GREEN}Expert{Style.RESET_ALL} - Knowledgeable personality demonstrating expertise")
    print(f"5. {Fore.GREEN}Provocative{Style.RESET_ALL} - Personality that politely challenges statements")
    
    current_personality = AI_PERSONALITY
    choice = input(f"\n{Fore.YELLOW}Select personality (1-5) [Current: {current_personality}]: {Style.RESET_ALL}").strip()
    
    if choice:
        if choice == "1":
            AI_PERSONALITY = "default"
        elif choice == "2":
            AI_PERSONALITY = "friendly"
        elif choice == "3":
            AI_PERSONALITY = "witty"
        elif choice == "4":
            AI_PERSONALITY = "expert"
        elif choice == "5":
            AI_PERSONALITY = "provocative"
        else:
            print(f"{Fore.RED}Invalid choice. Keeping current setting.{Style.RESET_ALL}")
    
    # Formality setting
    print(f"\n{Fore.CYAN}Available formality levels:{Style.RESET_ALL}")
    print(f"1. {Fore.GREEN}Casual{Style.RESET_ALL} - Informal conversational style")
    print(f"2. {Fore.GREEN}Neutral{Style.RESET_ALL} - Everyday neutral style")
    print(f"3. {Fore.GREEN}Formal{Style.RESET_ALL} - More formal style with proper constructions")
    
    current_formality = AI_FORMALITY
    choice = input(f"\n{Fore.YELLOW}Select formality (1-3) [Current: {current_formality}]: {Style.RESET_ALL}").strip()
    
    if choice:
        if choice == "1":
            AI_FORMALITY = "casual"
        elif choice == "2":
            AI_FORMALITY = "neutral"
        elif choice == "3":
            AI_FORMALITY = "formal"
        else:
            print(f"{Fore.RED}Invalid choice. Keeping current setting.{Style.RESET_ALL}")
    
    # Save settings to environment variables
    os.environ["AI_PERSONALITY"] = AI_PERSONALITY
    os.environ["AI_FORMALITY"] = AI_FORMALITY
    
    print(f"\n{Fore.GREEN}AI personality set to: {AI_PERSONALITY}, formality: {AI_FORMALITY}{Style.RESET_ALL}")
    
    # Ask if user wants to test the personality
    test = input(f"\n{Fore.YELLOW}Do you want to test this personality with a sample message? (y/n): {Style.RESET_ALL}").lower()
    if test == 'y':
        sample_message = input(f"\n{Fore.YELLOW}Enter a sample message to test with: {Style.RESET_ALL}")
        channel_name = "Test Channel"
        channel_bio = "A channel for testing personality settings"
        
        print(f"\n{Fore.CYAN}Generating sample response...{Style.RESET_ALL}")
        
        # Get first client for testing
        if clients:
            test_api_id = next(iter(clients.keys()))
            response = await generate_response(
                api_id=test_api_id,
                channel_name=channel_name,
                channel_bio=channel_bio,
                message_text=sample_message
            )
            if response:
                print(f"\n{Fore.GREEN}Sample response with {AI_PERSONALITY} personality, {AI_FORMALITY} formality:{Style.RESET_ALL}")
                print(f"{Fore.CYAN}'{response}'{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.RED}Failed to generate sample response. Check your API key.{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.RED}No active sessions to test with. Please create or load a session first.{Style.RESET_ALL}")

if __name__ == '__main__':
    try:
        # Display startup banner
        print(f"\n{Fore.CYAN + Style.BRIGHT}" + "="*60)
        print(f"{Fore.GREEN + Style.BRIGHT}        TELEGRAM AUTO-RESPONDER BOT{Style.RESET_ALL}")
        print(f"{Fore.CYAN + Style.BRIGHT}" + "="*60 + f"{Style.RESET_ALL}")
        
        # Create and run the event loop using the newer API
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        print(f"\n{Fore.YELLOW}Shutting down... Please wait.{Style.RESET_ALL}")
        # Get the current event loop for cleanup
        loop = asyncio.get_running_loop()
        for client in clients.values():
            loop.run_until_complete(client.disconnect())
        print(f"{Fore.GREEN}All sessions disconnected. Goodbye!{Style.RESET_ALL}")

