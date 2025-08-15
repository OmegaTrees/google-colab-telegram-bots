import os
from typing import Tuple, Optional, Dict, Any
from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardMarkup

from __init__ import LOGGER, queueDB, formatDB, replyDB
from helpers.file_type_detector import MediaTypeDetector
from helpers.utils import UserSettings

class EnhancedFileHandler:
    """Enhanced file handling with improved type detection and validation"""
    
    @staticmethod
    async def validate_file_for_mode(
        message: Message, 
        user_settings: UserSettings, 
        file_path: Optional[str] = None
    ) -> Tuple[bool, str, Dict]:
        """
        Comprehensive file validation for different merge modes
        
        Returns:
            Tuple of (is_valid, error_message, detection_info)
        """
        user_id = user_settings.user_id
        merge_mode = user_settings.merge_mode
        
        # Detect file type
        detected_type, detection_info = MediaTypeDetector.detect_media_type(message, file_path)
        
        if not detected_type:
            return False, "Could not determine file type. Please check the file and try again.", detection_info
        
        # Get file extension
        media = message.video or message.document or message.audio
        if not media or not media.file_name:
            return False, "File name not found.", detection_info
        
        extension = MediaTypeDetector.get_file_extension(media.file_name)
        if not extension:
            return False, "Could not determine file extension.", detection_info
        
        # Check if format is supported
        is_supported, support_reason = MediaTypeDetector.is_supported_format(
            detected_type, extension, merge_mode
        )
        
        if not is_supported:
            return False, support_reason, detection_info
        
        # Mode-specific validation
        queue = queueDB.get(user_id, {})
        video_count = len(queue.get('videos', []))
        
        if merge_mode == 1:  # Video merge mode
            # Check format consistency
            stored_format = formatDB.get(user_id)
            is_consistent, consistency_message = MediaTypeDetector.validate_format_consistency(
                extension, stored_format
            )
            
            if not is_consistent:
                return False, consistency_message, detection_info
                
        elif merge_mode == 2:  # Audio merge mode
            if video_count == 0:
                # First file must be video
                if detected_type != 'video':
                    return False, "First file must be a video in audio merge mode.", detection_info
            else:
                # Subsequent files must be audio
                if detected_type != 'audio':
                    return False, "Additional files must be audio in audio merge mode.", detection_info
                    
        elif merge_mode == 3:  # Subtitle merge mode
            if video_count == 0:
                # First file must be video
                if detected_type != 'video':
                    return False, "First file must be a video in subtitle merge mode.", detection_info
            else:
                # Subsequent files must be subtitles
                if detected_type != 'subtitle':
                    return False, "Additional files must be subtitles in subtitle merge mode.", detection_info
        
        return True, "File validation passed", detection_info
    
    @staticmethod
    async def process_config_file(client: Client, message: Message) -> bool:
        """
        Process configuration files (rclone config)
        
        Returns:
            bool: True if config file was processed, False otherwise
        """
        media = message.video or message.document or message.audio
        if not media or not media.file_name:
            return False
        
        extension = MediaTypeDetector.get_file_extension(media.file_name)
        
        if extension == 'conf':
            from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            await message.reply_text(
                text="**💾 Config file found, Do you want to save it?**",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Yes", callback_data="rclone_save"),
                        InlineKeyboardButton("❌ No", callback_data="rclone_discard"),
                    ]
                ]),
                quote=True,
            )
            return True
        
        return False
    
    @staticmethod
    def get_detailed_file_info(message: Message, detection_info: Dict) -> str:
        """Generate detailed file information for logging/debugging"""
        media = message.video or message.document or message.audio
        
        info_lines = [
            "📋 **File Analysis Report**",
            f"**Filename:** `{media.file_name if media else 'N/A'}`",
            f"**Size:** `{media.file_size if media else 'N/A'} bytes`",
            f"**Telegram Type:** `{detection_info.get('telegram_type', 'N/A')}`",
            f"**Extension:** `{detection_info.get('extension', 'N/A')}`",
            f"**MIME (Telegram):** `{detection_info.get('mime_type_telegram', 'N/A')}`",
            f"**MIME (Guessed):** `{detection_info.get('mime_type_guessed', 'N/A')}`",
            f"**Confidence:** `{detection_info.get('confidence', 'N/A')}`"
        ]
        
        if detection_info.get('mime_type_magic'):
            info_lines.append(f"**MIME (Magic):** `{detection_info['mime_type_magic']}`")
        
        return "\n".join(info_lines)

    @staticmethod
    async def handle_file_with_enhanced_detection(
        client: Client, 
        message: Message, 
        user_settings: UserSettings
    ) -> Tuple[bool, Optional[str]]:
        """
        Main file handling function with enhanced detection
        
        Returns:
            Tuple of (success, error_message)
        """
        user_id = user_settings.user_id
        
        # Check if config file
        if await EnhancedFileHandler.process_config_file(client, message):
            return True, None
        
        # Validate file
        is_valid, error_message, detection_info = await EnhancedFileHandler.validate_file_for_mode(
            message, user_settings
        )
        
        if not is_valid:
            # Log detailed information for debugging
            LOGGER.warning(f"File validation failed for user {user_id}: {error_message}")
            LOGGER.debug(f"Detection info: {detection_info}")
            
            # Send user-friendly error message
            await message.reply_text(
                f"❌ **File Validation Failed**\n\n{error_message}\n\n"
                f"💡 **Tip:** Make sure you're sending the correct file type for your current merge mode.",
                quote=True
            )
            return False, error_message
        
        # Log successful detection
        media = message.video or message.document or message.audio
        LOGGER.info(
            f"File accepted for user {user_id}: {media.file_name if media else 'Unknown'} "
            f"(Type: {detection_info.get('detected_type', 'Unknown')}, "
            f"Confidence: {detection_info.get('confidence', 'Unknown')})"
        )
        
        return True, None