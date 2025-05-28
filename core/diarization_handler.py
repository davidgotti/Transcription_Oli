# core/diarization_handler.py
import logging
import torch
from pyannote.audio import Pipeline
import time # For timing the diarization process

logger = logging.getLogger(__name__)

class DiarizationHandler:
    def __init__(self, hf_token=None, use_auth_token_flag=False, device=None, progress_callback=None):
        self.hf_token = hf_token
        self.use_auth_token_flag = use_auth_token_flag # This is True/False
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.progress_callback = progress_callback
        self.pipeline = None
        self._load_model()

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                # Avoid crashing the handler if the callback itself fails
                logger.error(f"Error in DiarizationHandler's progress_callback: {e}", exc_info=True)

    def _load_model(self):
        self._report_progress("Diarization model: Initializing...", 5) # Overall progress step
        logger.info(f"DiarizationHandler: Initializing pyannote.audio.Pipeline (use_auth_token_flag: {self.use_auth_token_flag}, hf_token_present: {bool(self.hf_token)})")
        
        # Determine the token argument for from_pretrained
        # If use_auth_token_flag is True, pass the actual token.
        # If False, pyannote will try to use cached models or download public ones.
        # Passing `None` or `False` when a private model is needed without a token will fail.
        # Pyannote's `use_auth_token` expects the token string or a boolean.
        token_for_pipeline = self.hf_token if self.use_auth_token_flag and self.hf_token else self.use_auth_token_flag

        try:
            self.pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", # Using a specific, potentially gated model
                use_auth_token=token_for_pipeline
            )
            self.pipeline.to(self.device)
            logger.info("DiarizationHandler: Pyannote diarization pipeline loaded successfully.")
            self._report_progress("Diarization model: Loaded.", 10) # Overall progress step
        except Exception as e:
            logger.exception("DiarizationHandler: Error loading Pyannote diarization pipeline.")
            error_detail = str(e)
            if "401 Client Error" in error_detail or "requires you to be authenticated" in error_detail:
                 logger.error("Authentication error with Hugging Face. Ensure token is correct and has access to pyannote/speaker-diarization-3.1.")
                 self._report_progress("Diarization model: Auth Error. Check token/access.", 5)
            elif "OfflineModeException" in error_detail:
                 logger.error("Pyannote offline mode error. Check network connection or model cache.")
                 self._report_progress("Diarization model: Offline/Network Error.", 5)
            else:
                 self._report_progress(f"Diarization model: Load Error ({error_detail[:50]}...).", 5)
            self.pipeline = None


    def is_model_loaded(self) -> bool:
        return self.pipeline is not None

    def diarize(self, audio_path: str): # Returns pyannote.Annotation object or None
        if not self.is_model_loaded():
            logger.error("DiarizationHandler: Pipeline is not initialized. Skipping diarization.")
            self._report_progress("Diarization: Skipped (pipeline not loaded).", 30) # Example progress update
            return None

        logger.info(f"DiarizationHandler: Starting diarization for {audio_path}...")
        self._report_progress("Diarization: Analysis starting...", 30) # Example progress update
        
        start_time = time.time()
        try:
            # Pyannote pipeline can take a file path directly.
            # It handles loading the audio.
            diarization_annotation_result = self.pipeline(audio_path)
            duration = time.time() - start_time
            logger.info(f"DiarizationHandler: Diarization analysis for '{audio_path}' took {duration:.2f} seconds.")
            
            if not diarization_annotation_result.labels(): # Check if any speaker labels were found
                logger.info("DiarizationHandler: Diarization complete but no speaker segments found (possibly no speech or single speaker not clearly segmented).")
                self._report_progress("Diarization: No speaker segments detected.", 45)
            else:
                num_speakers = len(diarization_annotation_result.labels())
                logger.info(f"DiarizationHandler: Diarization complete. Found {num_speakers} speaker(s).")
                self._report_progress(f"Diarization: Analysis complete ({num_speakers} speaker(s)).", 45)
            return diarization_annotation_result
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"DiarizationHandler: Error during diarization for {audio_path} after {duration:.2f} seconds.")
            self._report_progress(f"Diarization: Error during analysis ({str(e)[:50]}...).", 30)
            return None