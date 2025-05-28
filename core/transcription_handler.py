# core/transcription_handler.py
import logging
import torch
import whisper
import time # For timing the transcription process

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
                # Avoid crashing the handler if the callback itself fails
                logger.error(f"Error in TranscriptionHandler's progress_callback: {e}", exc_info=True)

    def _load_model(self):
        self._report_progress(f"Transcription model ({self.model_name}): Initializing...", 15) # Overall progress
        logger.info(f"TranscriptionHandler: Loading Whisper model ('{self.model_name}') on device '{self.device}'...")
        try:
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"TranscriptionHandler: Whisper model '{self.model_name}' loaded successfully.")
            self._report_progress(f"Transcription model ({self.model_name}): Loaded.", 20) # Overall progress
        except Exception as e:
            logger.exception(f"TranscriptionHandler: Error loading Whisper model ('{self.model_name}').")
            self._report_progress(f"Transcription model ({self.model_name}): Load Error ({str(e)[:50]}...).", 15)
            self.model = None

    def is_model_loaded(self) -> bool:
        return self.model is not None

    def transcribe(self, audio_path: str) -> dict: # Returns dict like {'text': str, 'segments': list}
        if not self.is_model_loaded():
            logger.error("TranscriptionHandler: Model is not initialized. Skipping transcription.")
            self._report_progress("Transcription: Skipped (model not loaded).", 55) # Example progress
            return {'text': '', 'segments': []}

        logger.info(f"TranscriptionHandler: Starting transcription for {audio_path} using model '{self.model_name}'...")
        self._report_progress("Transcription: Analysis starting...", 55) # Example progress
        
        # fp16 is only for CUDA devices. Set to False for CPU.
        decoding_options_dict = {"fp16": self.device.type == "cuda"}
        logger.debug(f"Transcription decoding options: {decoding_options_dict}")

        start_time = time.time()
        try:
            # The `transcribe` method of whisper.model.Whisper can take various arguments.
            # For simplicity, we're using basic options.
            # `language` can be specified if known, otherwise Whisper auto-detects.
            # `verbose=False` (default) or `True` for more console output from Whisper.
            result = self.model.transcribe(audio_path, **decoding_options_dict, verbose=None) # verbose=None uses default
            
            duration = time.time() - start_time
            logger.info(f"TranscriptionHandler: Transcription analysis for '{audio_path}' took {duration:.2f} seconds.")
            
            # Validate result structure
            if not isinstance(result, dict) or 'segments' not in result or 'text' not in result:
                logger.warning(f"TranscriptionHandler: Whisper transcription result for '{audio_path}' has unexpected structure: {type(result)}")
                self._report_progress("Transcription: Malformed result or no segments.", 70)
                return {'text': str(result.get('text','')) if isinstance(result, dict) else '', 'segments': []} # Attempt to salvage text if possible

            if not result['segments']: # No speech detected or no segments produced
                logger.info(f"TranscriptionHandler: Whisper transcription produced no segments for '{audio_path}' (possibly no speech detected). Full text: '{result.get('text','')}'")
                self._report_progress("Transcription: No speech segments detected.", 70)
            else:
                num_segments = len(result['segments'])
                logger.info(f"TranscriptionHandler: Transcription complete for '{audio_path}'. Found {num_segments} segment(s).")
                self._report_progress(f"Transcription: Analysis complete ({num_segments} segment(s)).", 70)
            
            return result # Expected: {'text': '...', 'segments': [{'id':..., 'start':..., 'end':..., 'text':...}, ...], 'language': '...'}
        
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"TranscriptionHandler: Error during Whisper transcription for {audio_path} after {duration:.2f} seconds.")
            self._report_progress(f"Transcription: Error during analysis ({str(e)[:50]}...).", 55)
            return {'text': '', 'segments': []} # Return empty on error