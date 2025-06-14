# utils/constants.py
<<<<<<< HEAD
=======
import os
import sys
>>>>>>> ad2357cfa3db78e5a6649cfa66120c79cbc04232
import logging
import os

# --- User-specific Application Data Directory ---
APP_NAME = "TranscriptionOli"  
APP_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)

# --- User-specific Application Data Directory ---
APP_NAME = "TranscriptionOli"

def get_app_data_dir():
    """Returns the appropriate user-specific data directory for the OS."""
    if sys.platform == "win32":
        # Windows
        return os.path.join(os.environ['APPDATA'], APP_NAME)
    elif sys.platform == "darwin":
        # macOS
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)
    else:
        # Linux and other Unix-like systems
        return os.path.join(os.path.expanduser("~"), ".config", APP_NAME)

APP_USER_DATA_DIR = get_app_data_dir()


# --- Message types for the queue ---
MSG_TYPE_STATUS = "STATUS_UPDATE"
MSG_TYPE_PROGRESS = "PROGRESS_PERCENT"
MSG_TYPE_COMPLETED = "PROCESSING_COMPLETED"

# --- Payload keys for MSG_TYPE_COMPLETED ---
KEY_FINAL_STATUS = "final_status"
KEY_ERROR_MESSAGE = "error_message"
KEY_IS_EMPTY_RESULT = "is_empty_result"

# --- Specific status values for KEY_FINAL_STATUS ---
STATUS_SUCCESS = "SUCCESS"
STATUS_EMPTY = "EMPTY"
STATUS_ERROR = "ERROR"

# --- Default output file name ---
DEFAULT_OUTPUT_TEXT_FILE = "processed_output.txt" 
DEFAULT_CONFIG_FILE = os.path.join(APP_USER_DATA_DIR, 'config.ini')

# --- Special Labels ---
NO_SPEAKER_LABEL = "SPEAKER_NONE_INTERNAL" # Used by SegmentManager and AudioProcessor
EMPTY_SEGMENT_PLACEHOLDER = "[Double-click to edit text]" # NEW: For empty text in CorrectionWindow

# --- Logging Configuration ---
LOG_LEVEL_DEBUG = logging.DEBUG
LOG_LEVEL_INFO = logging.INFO
ACTIVE_LOG_LEVEL = LOG_LEVEL_DEBUG # Or LOG_LEVEL_INFO for less verbosity
LOG_FORMAT = '%(asctime)s %(levelname)-8s [%(threadName)s] [%(filename)s:%(lineno)d] %(funcName)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# --- Message types for batch processing ---
MSG_TYPE_BATCH_FILE_START = "BATCH_FILE_START"
MSG_TYPE_BATCH_COMPLETED = "BATCH_PROCESSING_COMPLETED"

# --- Payload keys for BATCH messages ---
KEY_BATCH_FILENAME = "filename"
KEY_BATCH_CURRENT_IDX = "current_idx"
KEY_BATCH_TOTAL_FILES = "total_files"
KEY_BATCH_ALL_RESULTS = "all_results"