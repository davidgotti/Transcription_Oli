# utils/constants.py
import logging

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
DEFAULT_CONFIG_FILE = 'config.ini'

# --- Special Labels ---
# Used internally in CorrectionWindow for segments parsed without explicit speaker info
NO_SPEAKER_LABEL = "SPEAKER_NONE_INTERNAL"

# --- Logging Configuration ---
LOG_LEVEL_DEBUG = logging.DEBUG
LOG_LEVEL_INFO = logging.INFO
# Set the desired log level for the application
ACTIVE_LOG_LEVEL = LOG_LEVEL_DEBUG # Or LOG_LEVEL_INFO for release

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