# core/transcription_handler.py
import logging
import torch
import whisper
import time 

logger = logging.getLogger(__name__)

class TranscriptionHandler:
    def __init__(self, model_name="large", device=None, progress_callback=None):
        # Ensure model_name is a valid Whisper model string (e.g., "tiny", "base", "small", "medium", "large")
        # The mapping from UI selection like "large (recommended)" to "large" happens in MainApp.
        self.model_name = model_name
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.progress_callback = progress_callback
        self.model = None
        self._load_model() # Load model during initialization

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in TranscriptionHandler's progress_callback: {e}", exc_info=True)

    def _load_model(self):
        # Progress reporting: Using a generic "Transcription model" since specific name is already in message
        self._report_progress(f"Transcription model ({self.model_name}): Initializing...", 15) 
        logger.info(f"TranscriptionHandler: Loading Whisper model ('{self.model_name}') on device '{self.device}'...")
        try:
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"TranscriptionHandler: Whisper model '{self.model_name}' loaded successfully.")
            self._report_progress(f"Transcription model ({self.model_name}): Loaded.", 20)
        except Exception as e:
            logger.exception(f"TranscriptionHandler: Error loading Whisper model ('{self.model_name}').")
            self._report_progress(f"Transcription model ({self.model_name}): Load Error ({str(e)[:50]}...).", 15)
            self.model = None # Ensure model is None if loading fails

    def is_model_loaded(self) -> bool:
        return self.model is not None

    def transcribe(self, audio_path: str) -> dict:
        if not self.is_model_loaded():
            logger.error("TranscriptionHandler: Model not initialized. Skipping transcription.")
            self._report_progress("Transcription: Skipped (model not loaded).", 55)
            return {'text': '', 'segments': []}

        logger.info(f"TranscriptionHandler: Starting transcription for {audio_path} using model '{self.model_name}'...")
        self._report_progress(f"Transcription ({self.model_name}): Analysis starting...", 55)
        
        decoding_options_dict = {"fp16": self.device.type == "cuda"}
        logger.debug(f"Transcription decoding options: {decoding_options_dict}")

        start_time = time.time()
        try:
            result = self.model.transcribe(audio_path, **decoding_options_dict, verbose=None)
            duration = time.time() - start_time
            logger.info(f"TranscriptionHandler: Analysis for '{audio_path}' took {duration:.2f}s.")
            
            if not isinstance(result, dict) or 'segments' not in result or 'text' not in result:
                logger.warning(f"Whisper result for '{audio_path}' has unexpected structure: {type(result)}")
                self._report_progress("Transcription: Malformed result.", 70)
                return {'text': str(result.get('text','')) if isinstance(result, dict) else '', 'segments': []}

            if not result['segments']:
                logger.info(f"Whisper produced no segments for '{audio_path}'. Text: '{result.get('text','')}'")
                self._report_progress("Transcription: No speech segments detected.", 70)
            else:
                num_segments = len(result['segments'])
                logger.info(f"Transcription complete for '{audio_path}'. Found {num_segments} segment(s).")
                self._report_progress(f"Transcription: Analysis complete ({num_segments} segment(s)).", 70)
            
            return result
        
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"Error during Whisper transcription for {audio_path} after {duration:.2f}s.")
            self._report_progress(f"Transcription: Error ({str(e)[:50]}...).", 55)
            return {'text': '', 'segments': []}
