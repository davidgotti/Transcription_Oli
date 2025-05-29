# utils/logging_setup.py
import logging
import os # Added for log directory
from utils import constants # Assuming constants.py is in the same directory

# Define a log file name and path (e.g., in the project root or a dedicated logs folder)
LOG_DIRECTORY = "logs" # You can change this to a full path if needed
if not os.path.exists(LOG_DIRECTORY):
    try:
        os.makedirs(LOG_DIRECTORY)
    except OSError as e:
        # Fallback if logs directory can't be created (e.g. permissions)
        # This will log to the current working directory if LOG_DIRECTORY fails.
        print(f"Warning: Could not create log directory '{LOG_DIRECTORY}'. Logging to current directory. Error: {e}")
        LOG_DIRECTORY = "." 

LOG_FILE_PATH = os.path.join(LOG_DIRECTORY, "transcription_app.log")

def setup_logging():
    """Configures the root logger for the application."""
    
    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(constants.ACTIVE_LOG_LEVEL) # Set level for root logger

    # Clear existing handlers (if any, to avoid duplicate logs on re-runs in some environments)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(constants.LOG_FORMAT, datefmt=constants.LOG_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    # Optionally set a different level for console, e.g., logging.INFO
    # console_handler.setLevel(logging.INFO) 
    logger.addHandler(console_handler)

    # File Handler
    try:
        # Changed mode from 'a' (append) to 'w' (write) to reset log on each run
        file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w', encoding='utf-8') # 'w' for write, utf-8 for encoding
        file_formatter = logging.Formatter(constants.LOG_FORMAT, datefmt=constants.LOG_DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        # File handler can log at a more verbose level, e.g., DEBUG
        # file_handler.setLevel(logging.DEBUG) 
        logger.addHandler(file_handler)
        initial_log_message = "Logging configured. Console and File handlers active. Log file reset for this session."
    except IOError as e:
        # If file handler fails (e.g., permissions), log to console about it
        logger.addHandler(console_handler) # Ensure console handler is still there
        initial_log_message = f"Logging configured. Console handler active. FILE LOGGING FAILED for {LOG_FILE_PATH}: {e}"

    # Example: To set different levels for noisy libraries
    # logging.getLogger('httpx').setLevel(logging.WARNING)
    # logging.getLogger('pyannote').setLevel(logging.INFO) 
    # logging.getLogger('whisper').setLevel(logging.INFO)
    
    # Use the root logger for the initial message
    logging.info(initial_log_message)

if __name__ == '__main__':
    # This allows you to test the logging setup independently if needed
    setup_logging()
    logging.debug("This is a debug message for both console and file (if file logging is working).")
    logging.info("This is an info message for both console and file (if file logging is working).")
    logging.warning("This is a warning message.")
    logging.error("This is an error message.")
    logging.critical("This is a critical message.")