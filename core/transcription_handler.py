# core/transcription_handler.py
import logging
import torch
import whisper
# from utils import constants

logger = logging.getLogger(__name__)

class TranscriptionHandler:
    def __init__(self, model_name="large", device=None, progress_callback=None):
        self.model_name = model_name
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.progress_callback = progress_callback
        self.model = None
        self._load_model()

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in TranscriptionHandler progress_callback: {e}", exc_info=True)

    def _load_model(self):
        self._report_progress(f"Loading transcription model ({self.model_name})...", 15) # Base progress
        logger.info(f"TranscriptionHandler: Loading Whisper model ('{self.model_name}')...")
        try:
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info("TranscriptionHandler: Whisper model loaded successfully.")
            self._report_progress("Transcription model loaded.", 20) # Base progress
        except Exception as e:
            logger.exception(f"TranscriptionHandler: Error loading Whisper model ('{self.model_name}').")
            self._report_progress(f"Error loading transcription model.", 15)
            self.model = None

    def is_model_loaded(self) -> bool:
        return self.model is not None

    def transcribe(self, audio_path: str) -> dict:
        if not self.is_model_loaded():
            logger.error("TranscriptionHandler: Model is not initialized. Skipping transcription.")
            self._report_progress("Transcription skipped (model not loaded).", 55) # Progress within AudioProcessor's scale
            return {'text': '', 'segments': []}

        logger.info(f"TranscriptionHandler: Starting transcription for {audio_path}...")
        self._report_progress("Transcription analysis starting...", 55) # Progress within AudioProcessor's scale
        decoding_options_dict = {"fp16": False if self.device.type == "cpu" else True}
        try:
            result = self.model.transcribe(audio_path, **decoding_options_dict)
            logger.debug(f"TranscriptionHandler: Raw Whisper transcription result: {str(result)[:200]}...")
            if not result or 'segments' not in result:
                logger.warning("TranscriptionHandler: Whisper transcription result is missing 'segments'.")
                self._report_progress("Transcription malformed or no segments.", 70)
                return {'text': result.get('text', ''), 'segments': []}
            if not result['segments']:
                logger.info("TranscriptionHandler: Whisper transcription produced no segments (possibly no speech detected).")
                self._report_progress("No speech detected by Whisper.", 70)
            else:
                logger.info(f"TranscriptionHandler: Transcription complete. Found {len(result['segments'])} segments.")
                self._report_progress("Transcription analysis complete.", 70)
            return result
        except Exception as e:
            logger.exception(f"TranscriptionHandler: Error during Whisper transcription for {audio_path}.")
            self._report_progress("Error during transcription analysis.", 55)
            return {'text': '', 'segments': []}