# audio_processor.py

import whisper
import torch
from pyannote.audio import Pipeline
import logging
import os

logger = logging.getLogger(__name__) # Use module-level logger

class AudioProcessor:
    # Ensure 'progress_callback=None' is added here
    def __init__(self, config: dict, progress_callback=None): # <--- THIS IS THE CRITICAL CHANGE
        huggingface_config = config.get('huggingface', {})
        self.use_auth_token = str(huggingface_config.get('use_auth_token', 'no')).lower() == 'yes'
        self.hf_token = huggingface_config.get('hf_token') if self.use_auth_token else None

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {self.device}")

        self.diarization_pipeline = None
        self.transcription_model = None
        
        self.progress_callback = progress_callback # Store the callback

        self._load_models()

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                # Log error in the callback, but don't let it crash the processing
                logger.error(f"Error in progress_callback itself: {e}", exc_info=True)
    
    def _load_models(self):
        """Loads the diarization and transcription models."""
        # Load Diarization Model
        self._report_progress("Initializing diarization model...", 5)
        logger.info(f"Initializing pyannote.audio.Pipeline (use_auth_token: {self.use_auth_token})")
        try:
            token_arg = self.hf_token if self.use_auth_token and self.hf_token else self.use_auth_token
            self.diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token_arg
            )
            self.diarization_pipeline.to(self.device)
            logger.info("Pyannote diarization pipeline loaded successfully.")
            self._report_progress("Diarization model loaded.", 10)
        except Exception as e:
            logger.exception("Error loading Pyannote diarization pipeline.")
            self._report_progress("Error loading diarization model.", 5) # Update status
            self.diarization_pipeline = None

        # Load Transcription Model
        model_name = "large" # Or consider making this configurable
        self._report_progress(f"Loading transcription model ({model_name})...", 15)
        logger.info(f"Loading Whisper model ('{model_name}')...")
        try:
            self.transcription_model = whisper.load_model(model_name, device=self.device)
            logger.info("Whisper model loaded successfully.")
            self._report_progress("Transcription model loaded.", 20)
        except Exception as e:
            logger.exception(f"Error loading Whisper model ('{model_name}').")
            self._report_progress(f"Error loading transcription model.", 15) # Update status
            self.transcription_model = None

    def are_models_loaded(self) -> bool:
        """Checks if both essential models are loaded."""
        return self.diarization_pipeline is not None and self.transcription_model is not None

    def process_audio(self, audio_path: str) -> list:
        logger.info(f"Starting audio processing for file: {audio_path}")
        if not self.are_models_loaded():
            logger.error("Cannot process audio: one or more models are not loaded.")
            self._report_progress("Error: Models not loaded", 0)
            return ["Error: Models not loaded for processing."]

        all_aligned_segments = []
        try:
            # Stage 1: Diarization
            self._report_progress("Diarization starting...", 25)
            diarization_result = self._diarize_audio(audio_path)
            if diarization_result is None:
                self._report_progress("Diarization failed.", 50) # Some progress even if failed
                return ["Error: Diarization process failed."] # Specific error message
            self._report_progress("Diarization complete. Transcription starting...", 50)

            # Stage 2: Transcription
            transcription_result = self._transcribe_audio(audio_path)
            if not transcription_result or 'segments' not in transcription_result or not transcription_result['segments']:
                logger.error("Transcription failed or returned no segments.")
                self._report_progress("Transcription failed or no speech.", 75)
                # More specific message for no speech vs failure
                msg = "No speech detected during transcription." if not transcription_result.get('segments') else "Error: Transcription process failed."
                return [msg]
            self._report_progress("Transcription complete. Aligning outputs...", 75)

            # Stage 3: Alignment
            all_aligned_segments = self._align_outputs(diarization_result, transcription_result)
            if not all_aligned_segments or (isinstance(all_aligned_segments, list) and all_aligned_segments and "Error:" in all_aligned_segments[0]):
                 self._report_progress("Alignment failed or produced no output.", 90)
                 return all_aligned_segments # Propagate error/note from alignment
            self._report_progress("Processing complete.", 100)
            return all_aligned_segments

        except Exception as e:
            logger.exception(f"Unhandled exception during process_audio for {audio_path}")
            self._report_progress(f"Critical Error: {str(e)}", 0)
            return [f"Critical error during processing: {str(e)}"]


    def _diarize_audio(self, audio_path: str):
        if self.diarization_pipeline is None:
            logger.error("Diarization pipeline is not initialized. Skipping diarization.")
            self._report_progress("Diarization skipped (pipeline not loaded).", 30) # Example progress
            return None
        logger.info("Starting diarization (pipeline call)...")
        try:
            diarization_result = self.diarization_pipeline(audio_path)
            logger.info("Diarization complete.")
            self._report_progress("Diarization analysis complete.", 45) # Example progress
            return diarization_result
        except Exception as e:
            logger.exception(f"Error during diarization for {audio_path}.")
            self._report_progress("Error during diarization analysis.", 30)
            return None

    def _transcribe_audio(self, audio_path: str) -> dict:
        if self.transcription_model is None:
            logger.error("Transcription model is not initialized. Skipping transcription.")
            self._report_progress("Transcription skipped (model not loaded).", 55) # Example progress
            return {'text': '', 'segments': []}

        logger.info("Starting transcription (Whisper model call)...")
        self._report_progress("Transcription analysis starting...", 55) # Example progress
        decoding_options_dict = {"fp16": False if self.device.type == "cpu" else True}
        try:
            result = self.transcription_model.transcribe(audio_path, **decoding_options_dict)
            logger.debug(f"Raw Whisper transcription result: {str(result)[:200]}...")
            if not result or 'segments' not in result:
                logger.warning("Whisper transcription result is missing 'segments'.")
                self._report_progress("Transcription malformed or no segments.", 70)
                return {'text': result.get('text', ''), 'segments': []}
            if not result['segments']:
                logger.info("Whisper transcription produced no segments (possibly no speech detected).")
                self._report_progress("No speech detected by Whisper.", 70)
            else:
                 logger.info(f"Transcription complete. Found {len(result['segments'])} segments.")
                 self._report_progress("Transcription analysis complete.", 70)
            return result
        except Exception as e:
            logger.exception(f"Error during Whisper transcription for {audio_path}.")
            self._report_progress("Error during transcription analysis.", 55)
            return {'text': '', 'segments': []}

    def _align_outputs(self, diarization_result, transcription_result: dict) -> list:
        if not transcription_result or not transcription_result.get('segments'):
            logger.warning("Alignment skipped: Transcription segments are missing.")
            self._report_progress("Alignment skipped (no transcription).", 80)
            return ["Error: Transcription data unavailable for alignment."]
        
        self._report_progress("Aligning speakers with text...", 85)

        transcription_segments = transcription_result['segments']
        aligned_output = []

        diar_segments_for_lookup = []
        if diarization_result:
            try:
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
        elif not transcription_segments:
             self._report_progress("No transcription segments to align.", 95)
             return ["No transcription segments to align."]

        logger.info("Alignment complete.")
        self._report_progress("Alignment complete.", 95)
        return aligned_output

    def _format_time(self, seconds: float) -> str:
        if seconds is None: return "00:00.000"
        sec = int(seconds)
        ms = int((seconds - sec) * 1000)
        return f"{sec // 60:02d}:{sec % 60:02d}.{ms:03d}"

    def save_to_txt(self, output_path: str, segments: list):
        logger.info(f"Saving processed output to: {output_path}")
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                if segments:
                    for segment_str in segments:
                        f.write(segment_str + '\n')
                    logger.info("Output saved successfully.")
                    self._report_progress("Output saved.", 99) # Assuming save is quick
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