import os
import mimetypes
from typing import Tuple, Optional, Dict, List
from pyrogram.types import Message, Document, Video, Audio

try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

from __init__ import LOGGER

class MediaTypeDetector:
    """Enhanced media type detection with multiple validation methods"""
    
    # Comprehensive media type definitions
    MEDIA_TYPES = {
        'video': {
            'extensions': [
                'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'ts', 'm4v', 
                '3gp', 'ogv', 'mpg', 'mpeg', 'asf', 'rm', 'rmvb', 'vob', 'mts',
                'm2ts', 'divx', 'xvid', 'f4v', 'm1v', 'm2v', 'dat'
            ],
            'mime_patterns': ['video/'],
            'telegram_types': ['video']
        },
        'audio': {
            'extensions': [
                'mp3', 'aac', 'ac3', 'eac3', 'm4a', 'mka', 'thd', 'dts', 'flac', 
                'wav', 'ogg', 'wma', 'opus', 'ape', 'wv', 'tta', 'tak', 'ra',
                'amr', 'awb', 'au', 'snd', 'gsm', 'voc', 'aiff', 'aifc'
            ],
            'mime_patterns': ['audio/'],
            'telegram_types': ['audio']
        },
        'subtitle': {
            'extensions': [
                'srt', 'ass', 'ssa', 'vtt', 'sub', 'idx', 'mks', 'sup', 'pgs',
                'usf', 'jss', 'psb', 'rt', 'smi', 'stl', 'ttml', 'sbv', 'dfxp'
            ],
            'mime_patterns': ['text/plain', 'application/x-subrip', 'text/x-ssa'],
            'telegram_types': ['document']
        },
        'config': {
            'extensions': ['conf', 'config', 'ini', 'cfg', 'properties'],
            'mime_patterns': ['text/plain', 'text/x-config', 'application/x-ini'],
            'telegram_types': ['document']
        },
        'document': {
            'extensions': ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt'],
            'mime_patterns': ['application/pdf', 'application/msword', 'text/'],
            'telegram_types': ['document']
        }
    }

    @classmethod
    def get_file_extension(cls, filename: str) -> Optional[str]:
        """Extract file extension from filename"""
        if not filename or '.' not in filename:
            return None
        return filename.rsplit('.', 1)[-1].lower().strip()

    @classmethod
    def get_telegram_media_info(cls, message: Message) -> Tuple[Optional[str], Optional[object]]:
        """Get media type and object from Telegram message"""
        if message.video:
            return 'video', message.video
        elif message.audio:
            return 'audio', message.audio
        elif message.document:
            return 'document', message.document
        return None, None

    @classmethod
    def get_mime_type_from_telegram(cls, media) -> Optional[str]:
        """Extract MIME type from Telegram media object"""
        if hasattr(media, 'mime_type') and media.mime_type:
            return media.mime_type.lower()
        return None

    @classmethod
    def guess_mime_type_from_filename(cls, filename: str) -> Optional[str]:
        """Guess MIME type from filename using mimetypes module"""
        if not filename:
            return None
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type.lower() if mime_type else None

    @classmethod
    def detect_file_type_by_magic(cls, file_path: str) -> Optional[str]:
        """Detect file type using magic numbers (requires python-magic)"""
        if not HAS_MAGIC or not os.path.exists(file_path):
            return None
        
        try:
            mime_type = magic.from_file(file_path, mime=True)
            return mime_type.lower() if mime_type else None
        except Exception as e:
            LOGGER.warning(f"Magic detection failed for {file_path}: {e}")
            return None

    @classmethod
    def classify_by_mime_type(cls, mime_type: str) -> Optional[str]:
        """Classify media type based on MIME type"""
        if not mime_type:
            return None
        
        mime_type = mime_type.lower()
        
        for media_type, info in cls.MEDIA_TYPES.items():
            for pattern in info['mime_patterns']:
                if mime_type.startswith(pattern.lower()):
                    return media_type
        
        return 'unknown'

    @classmethod
    def classify_by_extension(cls, extension: str) -> Optional[str]:
        """Classify media type based on file extension"""
        if not extension:
            return None
        
        extension = extension.lower().strip()
        
        for media_type, info in cls.MEDIA_TYPES.items():
            if extension in info['extensions']:
                return media_type
        
        return 'unknown'

    @classmethod
    def detect_media_type(cls, message: Message, file_path: Optional[str] = None) -> Tuple[Optional[str], Dict]:
        """
        Comprehensive media type detection using multiple methods
        
        Returns:
            Tuple of (detected_type, detection_info)
        """
        detection_info = {
            'filename': None,
            'extension': None,
            'telegram_type': None,
            'mime_type_telegram': None,
            'mime_type_guessed': None,
            'mime_type_magic': None,
            'confidence': 'low'
        }
        
        # Get basic info from Telegram
        telegram_type, media = cls.get_telegram_media_info(message)
        detection_info['telegram_type'] = telegram_type
        
        if not media:
            return None, detection_info
        
        # Extract filename and extension
        filename = getattr(media, 'file_name', None)
        detection_info['filename'] = filename
        
        if filename:
            extension = cls.get_file_extension(filename)
            detection_info['extension'] = extension
        else:
            extension = None
        
        # Get MIME types from various sources
        mime_telegram = cls.get_mime_type_from_telegram(media)
        detection_info['mime_type_telegram'] = mime_telegram
        
        if filename:
            mime_guessed = cls.guess_mime_type_from_filename(filename)
            detection_info['mime_type_guessed'] = mime_guessed
        else:
            mime_guessed = None
        
        if file_path:
            mime_magic = cls.detect_file_type_by_magic(file_path)
            detection_info['mime_type_magic'] = mime_magic
        else:
            mime_magic = None
        
        # Detection priority order
        detection_methods = [
            ('magic', mime_magic, 'high'),
            ('telegram_mime', mime_telegram, 'high'),
            ('guessed_mime', mime_guessed, 'medium'),
            ('extension', extension, 'low'),
            ('telegram_type', telegram_type, 'low')
        ]
        
        detected_type = None
        confidence = 'low'
        
        for method_name, data, method_confidence in detection_methods:
            if not data:
                continue
            
            if method_name in ['magic', 'telegram_mime', 'guessed_mime']:
                result = cls.classify_by_mime_type(data)
            elif method_name == 'extension':
                result = cls.classify_by_extension(data)
            elif method_name == 'telegram_type':
                # Direct telegram type mapping
                if data == 'video':
                    result = 'video'
                elif data == 'audio':
                    result = 'audio'
                elif data == 'document':
                    # Need more info to classify documents
                    result = None
                else:
                    result = None
            else:
                result = None
            
            if result and result != 'unknown':
                detected_type = result
                confidence = method_confidence
                detection_info['confidence'] = confidence
                LOGGER.info(f"Detected {detected_type} using {method_name} with {confidence} confidence")
                break
        
        # Fallback classification
        if not detected_type or detected_type == 'unknown':
            if extension:
                detected_type = cls.classify_by_extension(extension)
                confidence = 'low'
            elif telegram_type:
                detected_type = telegram_type
                confidence = 'very_low'
        
        detection_info['confidence'] = confidence
        
        return detected_type, detection_info

    @classmethod
    def is_supported_format(cls, media_type: str, extension: str, merge_mode: int) -> Tuple[bool, str]:
        """
        Check if the detected media type and extension are supported for the given merge mode
        
        Args:
            media_type: Detected media type ('video', 'audio', 'subtitle', etc.)
            extension: File extension
            merge_mode: Current merge mode (1=video, 2=audio, 3=subtitle, 4=extract)
            
        Returns:
            Tuple of (is_supported, reason)
        """
        if not media_type or not extension:
            return False, "Could not determine file type"
        
        # Mode-specific validation
        if merge_mode == 1:  # Video merge mode
            if media_type != 'video':
                return False, f"Only video files are allowed in video merge mode. Detected: {media_type}"
            
            # Check if extension is in supported video formats
            if extension not in cls.MEDIA_TYPES['video']['extensions']:
                return False, f"Unsupported video format: {extension.upper()}"
            
        elif merge_mode == 2:  # Audio merge mode
            # First file must be video, subsequent files must be audio
            if media_type not in ['video', 'audio']:
                return False, f"Only video (first file) or audio files are allowed in audio merge mode. Detected: {media_type}"
                
        elif merge_mode == 3:  # Subtitle merge mode
            # First file must be video, subsequent files must be subtitles
            if media_type not in ['video', 'subtitle']:
                return False, f"Only video (first file) or subtitle files are allowed in subtitle merge mode. Detected: {media_type}"
                
        elif merge_mode == 4:  # Extract mode
            if media_type not in ['video', 'audio']:
                return False, f"Only video or audio files are allowed in extract mode. Detected: {media_type}"
        
        return True, "Supported format"

    @classmethod
    def validate_format_consistency(cls, current_extension: str, stored_format: Optional[str]) -> Tuple[bool, str]:
        """
        Validate format consistency within a merge session
        
        Args:
            current_extension: Extension of current file
            stored_format: Previously stored format for this user
            
        Returns:
            Tuple of (is_consistent, message)
        """
        if not stored_format:
            return True, "First file in session"
        
        if current_extension.lower() != stored_format.lower():
            return False, f"Format mismatch. Expected: {stored_format.upper()}, Got: {current_extension.upper()}"
        
        return True, "Format is consistent"


# Convenience function for backward compatibility
def detect_file_type(message: Message, file_path: Optional[str] = None) -> Tuple[Optional[str], Dict]:
    """Convenience function for file type detection"""
    return MediaTypeDetector.detect_media_type(message, file_path)