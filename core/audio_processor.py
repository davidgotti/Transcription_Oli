# core/audio_processor.py
import logging
import torch # Keep for device default if not passed explicitly
import os # Keep if used elsewhere or for future use
# No longer directly use whisper or pyannote.audio.Pipeline here
# import whisper
# from pyannote.audio import Pipeline

from utils import constants # Ensure this is present
from .diarization_handler import DiarizationHandler # New import
from .transcription_handler import TranscriptionHandler # New import

logger = logging.getLogger(__name__)

# ProcessedAudioResult class definition (can stay here or be moved)
class ProcessedAudioResult:
    def __init__(self, status, data=None, message=None):
        self.status = status
        self.data = data
        self.message = message

class AudioProcessor:
    def __init__(self, config: dict, progress_callback=None):
        huggingface_config = config.get('huggingface', {})
        use_auth_token_flag = str(huggingface_config.get('use_auth_token', 'no')).lower() == 'yes'
        hf_token_val = huggingface_config.get('hf_token') if use_auth_token_flag else None

        # General device configuration
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"AudioProcessor: Using device: {self.device}")

        self.progress_callback = progress_callback

        # Instantiate handlers
        self.diarization_handler = DiarizationHandler(
            hf_token=hf_token_val,
            use_auth_token_flag=use_auth_token_flag,
            device=self.device,
            progress_callback=self._make_scoped_progress_callback("Diarization") # or pass self.progress_callback directly
        )
        # You might want to make whisper model name configurable via `config` dict
        whisper_model_name = config.get('transcription', {}).get('model_name', 'large')
        self.transcription_handler = TranscriptionHandler(
            model_name=whisper_model_name,
            device=self.device,
            progress_callback=self._make_scoped_progress_callback("Transcription") # or pass self.progress_callback directly
        )

        # Note: _load_models in handlers is called during their __init__.
        # If you prefer explicit loading:
        # self.diarization_handler._load_model()
        # self.transcription_handler._load_model()
        # The _report_progress in AudioProcessor's _load_models was for overall status;
        # handlers now manage their own initial loading progress.

    def _make_scoped_progress_callback(self, scope_name: str):
        """Helper to prepend a scope to progress messages if desired, or just pass through."""
        if not self.progress_callback:
            return None
        def scoped_callback(message: str, percentage: int = None):
            # self.progress_callback(f"[{scope_name}] {message}", percentage) # Example of scoping
            self.progress_callback(message, percentage) # Current behavior passes through
        return scoped_callback

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in AudioProcessor progress_callback: {e}", exc_info=True)

    # _load_models is effectively handled by handlers' __init__
    # def _load_models(self):
    #     pass # Models are loaded by handlers

    def are_models_loaded(self) -> bool:
        # Check if both handlers have successfully loaded their models
        dia_loaded = self.diarization_handler.is_model_loaded()
        trans_loaded = self.transcription_handler.is_model_loaded()
        if not dia_loaded:
            logger.warning("AudioProcessor: Diarization model not loaded.")
        if not trans_loaded:
            logger.warning("AudioProcessor: Transcription model not loaded.")
        return dia_loaded and trans_loaded

    def process_audio(self, audio_path: str) -> ProcessedAudioResult:
        logger.info(f"AudioProcessor: Starting audio processing for file: {audio_path}")
        if not self.are_models_loaded():
            logger.error("AudioProcessor: Cannot process audio: one or more models are not loaded.")
            # Individual handlers would have reported their specific loading errors via progress_callback
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Essential models not loaded. Check logs/status for details.")

        try:
            # Stage 1: Diarization
            self._report_progress("Diarization starting...", 25)
            diarization_result = self.diarization_handler.diarize(audio_path) # Delegate
            if diarization_result is None: # Handler indicates failure
                self._report_progress("Diarization failed.", 50) # Update overall progress
                return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Diarization process failed.")
            self._report_progress("Diarization complete. Transcription starting...", 50)

            # Stage 2: Transcription
            # self._report_progress("Transcription starting...", 50) # Done by handler's internal progress
            transcription_output_dict = self.transcription_handler.transcribe(audio_path) # Delegate

            if not transcription_output_dict or 'segments' not in transcription_output_dict or not transcription_output_dict['segments']:
                logger.error("AudioProcessor: Transcription failed or returned no segments.")
                self._report_progress("Transcription failed or no speech.", 75) # Overall
                msg = "No speech detected during transcription." if not transcription_output_dict.get('segments') else "Transcription process failed."
                status_to_return = constants.STATUS_EMPTY if "No speech detected" in msg else constants.STATUS_ERROR
                return ProcessedAudioResult(status=status_to_return, message=msg)
            self._report_progress("Transcription complete. Aligning outputs...", 75)

            # Stage 3: Alignment (remains in AudioProcessor)
            aligned_segments = self._align_outputs(diarization_result, transcription_output_dict)

            # Handling alignment_output as before
            if not aligned_segments:
                self._report_progress("Alignment produced no output.", 90)
                return ProcessedAudioResult(status=constants.STATUS_EMPTY,
                                            message="Alignment produced no formatted lines from transcription.")
            elif isinstance(aligned_segments, list) and aligned_segments and \
                 ("Error:" in aligned_segments[0] or "Note:" in aligned_segments[0]):
                self._report_progress("Alignment reported an issue.", 90)
                status_for_alignment_issue = constants.STATUS_ERROR if "Error:" in aligned_segments[0] else constants.STATUS_EMPTY
                return ProcessedAudioResult(status=status_for_alignment_issue, message=aligned_segments[0])

            self._report_progress("Processing complete.", 100)
            return ProcessedAudioResult(status=constants.STATUS_SUCCESS, data=aligned_segments)

        except Exception as e:
            logger.exception(f"AudioProcessor: Unhandled exception during process_audio for {audio_path}")
            self._report_progress(f"Critical Error: {str(e)}", 0)
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message=f"Critical error during processing: {str(e)}")

    # _diarize_audio method is now effectively replaced by diarization_handler.diarize()
    # def _diarize_audio(self, audio_path: str): ...

    # _transcribe_audio method is now effectively replaced by transcription_handler.transcribe()
    # def _transcribe_audio(self, audio_path: str) -> dict: ...

    # _align_outputs method remains here as it uses results from both.
    def _align_outputs(self, diarization_result, transcription_result: dict) -> list:
        if not transcription_result or not transcription_result.get('segments'):
            logger.warning("Alignment skipped: Transcription segments are missing.")
            self._report_progress("Alignment skipped (no transcription).", 80)
            return ["Error: Transcription data unavailable for alignment."] # Keep as list for this internal method for now

        self._report_progress("Aligning speakers with text...", 85)
        transcription_segments = transcription_result['segments']
        aligned_output = []
        diar_segments_for_lookup = []

        if diarization_result:
            try:
                # Ensure diarization_result is the expected Annotation object
                diar_segments_for_lookup = list(diarization_result.itertracks(yield_label=True))
            except Exception as e:
                logger.warning(f"Could not process diarization tracks for lookup: {e}")
                self._report_progress("Warning: Could not use diarization data.", 85)
        else:
            logger.info("No diarization results provided for alignment. Speakers will be 'Unknown'.")
            self._report_progress("No diarization data, speakers will be unknown.", 85)

        logger.info(f"Aligning {len(transcription_segments)} transcription segments "
                    f"with {len(diar_segments_for_lookup)} diarization tracks.")

        for t_seg in transcription_segments:
            start_time = t_seg['start']
            end_time = t_seg['end']
            text = t_seg['text'].strip()
            speaker_label = "SPEAKER_UNKNOWN" 

            if diar_segments_for_lookup:
                best_overlap = 0
                for d_turn, _, label in diar_segments_for_lookup:
                    overlap_start = max(start_time, d_turn.start)
                    overlap_end = min(end_time, d_turn.end)
                    overlap_duration = overlap_end - overlap_start
                    if overlap_duration > best_overlap:
                        best_overlap = overlap_duration
                        speaker_label = label

            formatted_time_start = self._format_time(start_time)
            formatted_time_end = self._format_time(end_time)
            aligned_output.append(
                f"[{formatted_time_start} - {formatted_time_end}] {speaker_label}: {text}"
            )

        if not aligned_output and transcription_segments:
            logger.warning("Alignment produced no output despite having transcription segments.")
            self._report_progress("Alignment produced no output.", 95)
            return ["Note: Transcription was processed, but alignment step yielded no formatted lines."]
        elif not transcription_segments: # Should have been caught earlier by transcription_handler
            self._report_progress("No transcription segments to align.", 95)
            return ["No transcription segments to align."]

        logger.info("Alignment complete.")
        self._report_progress("Alignment complete.", 95)
        return aligned_output

    def _format_time(self, seconds: float) -> str: # Stays here
        if seconds is None: return "00:00.000"
        sec = int(seconds)
        ms = int((seconds - sec) * 1000)
        return f"{sec // 60:02d}:{sec % 60:02d}.{ms:03d}"

    def save_to_txt(self, output_path: str, segments: list): # Stays here
        logger.info(f"Saving processed output to: {output_path}")
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                if segments:
                    for segment_str in segments:
                        f.write(segment_str + '\n')
                    logger.info("Output saved successfully.")
                    self._report_progress("Output saved.", 99)
                else:
                    logger.warning("No segments provided to save.")
                    self._report_progress("No segments to save.", 99)
                    f.write("No transcription results found or an error occurred during processing.\n")
        except IOError as e:
            logger.exception(f"IOError saving to text file {output_path}.")
            self._report_progress("Error saving output file.", 99)
        except Exception as e:
            logger.exception(f"Unexpected error saving to text file {output_path}.")
            self._report_progress("Error saving output file.", 99)