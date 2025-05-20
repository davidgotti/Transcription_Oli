# logging_setup.py
import logging
import constants # Assuming constants.py is in the same directory

def setup_logging():
    """Configures the root logger for the application."""
    logging.basicConfig(
        level=constants.ACTIVE_LOG_LEVEL,
        format=constants.LOG_FORMAT,
        datefmt=constants.LOG_DATE_FORMAT
    )
    # Example: To set different levels for noisy libraries
    # logging.getLogger('httpx').setLevel(logging.WARNING)
    # logging.getLogger('pyannote').setLevel(logging.INFO)
    # logging.getLogger('whisper').setLevel(logging.INFO)
    logging.info("Logging configured.")

if __name__ == '__main__':
    # This allows you to test the logging setup independently if needed
    setup_logging()
    logging.debug("This is a debug message.")
    logging.info("This is an info message.")
    logging.warning("This is a warning message.")
    logging.error("This is an error message.")