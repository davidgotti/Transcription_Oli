# core/diarization_handler.py
import logging
import torch
from pyannote.audio import Pipeline
# We'll need constants if we make status reporting more granular here,
# but for now, AudioProcessor handles the overall ProcessedAudioResult.
# from utils import constants

logger = logging.getLogger(__name__)

class DiarizationHandler:
    def __init__(self, hf_token=None, use_auth_token_flag=False, device=None, progress_callback=None):
        self.hf_token = hf_token
        self.use_auth_token_flag = use_auth_token_flag
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.progress_callback = progress_callback
        self.pipeline = None
        self._load_model()

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in DiarizationHandler progress_callback: {e}", exc_info=True)

    def _load_model(self):
        self._report_progress("Initializing diarization model...", 5) # Base progress
        logger.info(f"DiarizationHandler: Initializing pyannote.audio.Pipeline (use_auth_token: {self.use_auth_token_flag})")
        try:
            token_arg = self.hf_token if self.use_auth_token_flag and self.hf_token else self.use_auth_token_flag
            self.pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token_arg
            )
            self.pipeline.to(self.device)
            logger.info("DiarizationHandler: Pyannote diarization pipeline loaded successfully.")
            self._report_progress("Diarization model loaded.", 10) # Base progress
        except Exception as e:
            logger.exception("DiarizationHandler: Error loading Pyannote diarization pipeline.")
            self._report_progress("Error loading diarization model.", 5)
            self.pipeline = None

    def is_model_loaded(self) -> bool:
        return self.pipeline is not None

    def diarize(self, audio_path: str):
        if not self.is_model_loaded():
            logger.error("DiarizationHandler: Pipeline is not initialized. Skipping diarization.")
            self._report_progress("Diarization skipped (pipeline not loaded).", 30) # Progress within AudioProcessor's scale
            return None

        logger.info(f"DiarizationHandler: Starting diarization for {audio_path}...")
        # Note: AudioProcessor will handle the overall progress percentage updates (e.g., "Diarization starting... 25%")
        # This internal _report_progress is more for granular status if needed.
        try:
            diarization_result = self.pipeline(audio_path)
            logger.info("DiarizationHandler: Diarization complete.")
            self._report_progress("Diarization analysis complete.", 45) # Progress within AudioProcessor's scale
            return diarization_result
        except Exception as e:
            logger.exception(f"DiarizationHandler: Error during diarization for {audio_path}.")
            self._report_progress("Error during diarization analysis.", 30)
            return None