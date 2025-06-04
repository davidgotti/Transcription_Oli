# utils/constants.py
import logging
import os  # <<< ADD THIS IMPORT

# --- User-specific Application Data Directory ---
# It's good practice to define this once and use it for logs, configs, etc.
APP_NAME = "TranscriptionOli"  # Or your preferred application name

# For macOS, ~/Library/Application Support/YourAppName is standard
# os.path.expanduser("~") gets the user's home directory
APP_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_NAME)

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
DEFAULT_OUTPUT_TEXT_FILE = "processed_output.txt" # For transcription output, user chooses actual save path
DEFAULT_CONFIG_FILE = os.path.join(APP_USER_DATA_DIR, 'config.ini')  # <<< CORRECTED TO FULL PATH

# --- Special Labels ---
NO_SPEAKER_LABEL = "SPEAKER_NONE_INTERNAL"

# --- Logging Configuration ---
# Ensure LOG_DIRECTORY in logging_setup.py also uses APP_USER_DATA_DIR
# e.g., LOG_DIRECTORY = os.path.join(APP_USER_DATA_DIR, 'logs')
LOG_LEVEL_DEBUG = logging.DEBUG
LOG_LEVEL_INFO = logging.INFO
ACTIVE_LOG_LEVEL = LOG_LEVEL_DEBUG
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