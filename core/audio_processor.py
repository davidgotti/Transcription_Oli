# core/audio_processor.py
import logging
import torch
import os
import time # For processing time logging

from utils import constants
from .diarization_handler import DiarizationHandler
from .transcription_handler import TranscriptionHandler

logger = logging.getLogger(__name__)

class ProcessedAudioResult:
    def __init__(self, status, data=None, message=None):
        self.status = status # e.g., constants.STATUS_SUCCESS, constants.STATUS_ERROR, constants.STATUS_EMPTY
        self.data = data     # Typically the list of aligned segment strings for success
        self.message = message # Error message or informational message

class AudioProcessor:
    def __init__(self, config: dict, progress_callback=None, enable_diarization=True, include_timestamps=True):
        huggingface_config = config.get('huggingface', {})
        use_auth_token_flag = str(huggingface_config.get('use_auth_token', 'no')).lower() == 'yes'
        hf_token_val = huggingface_config.get('hf_token') if use_auth_token_flag else None

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"AudioProcessor: Using device: {self.device}")

        self.progress_callback = progress_callback
        self.enable_diarization = enable_diarization
        self.include_timestamps = include_timestamps
        logger.info(f"AudioProcessor initialized with Diarization: {self.enable_diarization}, Timestamps: {self.include_timestamps}")


        # Instantiate handlers
        # The progress_callback passed to handlers will be the one from MainApp,
        # which queues updates for the UI thread.
        self.diarization_handler = DiarizationHandler(
            hf_token=hf_token_val,
            use_auth_token_flag=use_auth_token_flag,
            device=self.device,
            progress_callback=self.progress_callback 
        )
        
        whisper_model_name = config.get('transcription', {}).get('model_name', 'large') # Default to 'large'
        self.transcription_handler = TranscriptionHandler(
            model_name=whisper_model_name,
            device=self.device,
            progress_callback=self.progress_callback
        )
        # Models are loaded during handler initialization.

    def _report_progress(self, message: str, percentage: int = None):
        """Helper for AudioProcessor's own progress messages if needed directly,
           though most progress comes from handlers now."""
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in AudioProcessor's direct progress_callback: {e}", exc_info=True)

    def are_models_loaded(self) -> bool:
        dia_loaded = self.diarization_handler.is_model_loaded()
        trans_loaded = self.transcription_handler.is_model_loaded()
        if not dia_loaded and self.enable_diarization: # Only warn if diarization is enabled but model failed
            logger.warning("AudioProcessor: Diarization is enabled, but its model is not loaded.")
        elif not dia_loaded and not self.enable_diarization:
            logger.info("AudioProcessor: Diarization is disabled, model load status not critical for it.")
            dia_loaded = True # Effectively, diarization part is "ready" if disabled
            
        if not trans_loaded:
            logger.warning("AudioProcessor: Transcription model not loaded.")
        
        return dia_loaded and trans_loaded

    def process_audio(self, audio_path: str) -> ProcessedAudioResult:
        overall_start_time = time.time()
        logger.info(f"AudioProcessor: Starting audio processing for file: {audio_path}. Diarization: {'Enabled' if self.enable_diarization else 'Disabled'}, Timestamps: {'Included' if self.include_timestamps else 'Excluded'}")

        if not self.are_models_loaded(): # This now considers if diarization is enabled
            logger.error("AudioProcessor: Cannot process audio: one or more required models are not loaded.")
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Essential models not loaded. Check logs for details.")

        diarization_result_obj = None # Stores the actual pyannote.Annotation object
        try:
            # Stage 1: Diarization (Conditional)
            if self.enable_diarization:
                self._report_progress("Diarization starting...", 25) # Overall progress
                # DiarizationHandler will log its own timing and detailed progress via its callback
                diarization_result_obj = self.diarization_handler.diarize(audio_path)
                if diarization_result_obj is None: # Handler indicates failure
                    # _report_progress("Diarization failed.", 50) # Progress handled by handler
                    return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Diarization process failed. Check logs.")
                # _report_progress("Diarization complete. Transcription starting...", 50) # Progress handled by handler
            else:
                logger.info("AudioProcessor: Diarization is disabled by user option.")
                self._report_progress("Diarization skipped (disabled). Transcription starting...", 25) # Adjust progress if skipping a phase

            # Stage 2: Transcription
            # TranscriptionHandler will log its own timing and detailed progress
            # Adjust starting percentage if diarization was skipped
            transcription_start_progress = 50 if self.enable_diarization else 25 
            self._report_progress("Transcription starting...", transcription_start_progress) # Overall progress
            transcription_output_dict = self.transcription_handler.transcribe(audio_path)

            if not transcription_output_dict or 'segments' not in transcription_output_dict:
                logger.error("AudioProcessor: Transcription failed or returned invalid structure.")
                # _report_progress("Transcription failed or no speech.", 75) # Progress handled by handler
                return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Transcription process failed or returned invalid data.")
            if not transcription_output_dict['segments']: # No actual speech segments
                 logger.info("AudioProcessor: Transcription produced no segments (no speech detected).")
                 # _report_progress("No speech detected.", 75) # Progress handled by handler
                 return ProcessedAudioResult(status=constants.STATUS_EMPTY, message="No speech detected during transcription.")
            # _report_progress("Transcription complete. Aligning outputs...", 75) # Progress handled by handler

            # Stage 3: Alignment
            alignment_start_progress = 75 # Assuming transcription was successful
            self._report_progress("Aligning speakers with text...", alignment_start_progress)
            align_start_time = time.time()
            aligned_segments = self._align_outputs(diarization_result_obj, transcription_output_dict)
            align_duration = time.time() - align_start_time
            logger.info(f"AudioProcessor: Alignment completed in {align_duration:.2f} seconds.")
            
            if not aligned_segments:
                self._report_progress("Alignment produced no output.", 95)
                return ProcessedAudioResult(status=constants.STATUS_EMPTY,
                                            message="Alignment produced no formatted lines from transcription.")
            # Check for internal error/note messages from _align_outputs
            if isinstance(aligned_segments, list) and aligned_segments and \
                 ("Error:" in aligned_segments[0] or "Note:" in aligned_segments[0]):
                self._report_progress("Alignment reported an issue.", 95)
                status_for_alignment_issue = constants.STATUS_ERROR if "Error:" in aligned_segments[0] else constants.STATUS_EMPTY
                return ProcessedAudioResult(status=status_for_alignment_issue, message=aligned_segments[0])

            overall_duration = time.time() - overall_start_time
            logger.info(f"Total audio processing for {audio_path} completed in {overall_duration:.2f} seconds.")
            self._report_progress("Processing complete.", 100)
            return ProcessedAudioResult(status=constants.STATUS_SUCCESS, data=aligned_segments)

        except Exception as e:
            logger.exception(f"AudioProcessor: Unhandled exception during process_audio for {audio_path}")
            overall_duration = time.time() - overall_start_time
            logger.error(f"Audio processing for {audio_path} failed after {overall_duration:.2f} seconds due to an exception.")
            self._report_progress(f"Critical Error: {str(e)[:100]}...", 0) # Show limited error in status
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message=f"Critical error during processing: {str(e)}")


    def _align_outputs(self, diarization_annotation, transcription_result_dict: dict) -> list:
        # diarization_annotation is the pyannote.Annotation object or None
        # transcription_result_dict is the dictionary from Whisper
        
        if not transcription_result_dict or not transcription_result_dict.get('segments'):
            logger.warning("Alignment skipped: Transcription segments are missing.")
            # self._report_progress("Alignment skipped (no transcription).", 80) # Progress handled by caller
            return ["Error: Transcription data unavailable for alignment."]

        # self._report_progress("Aligning speakers with text...", 85) # Progress handled by caller
        transcription_segments = transcription_result_dict['segments']
        aligned_output = []
        
        diar_turns_with_labels = []
        if self.enable_diarization and diarization_annotation:
            try:
                # Convert pyannote.Annotation to a list of (Segment, track_id, speaker_label)
                # This is how pyannote's tutorial shows iteration.
                for turn, _, speaker_label_from_diar in diarization_annotation.itertracks(yield_label=True):
                    diar_turns_with_labels.append({'start': turn.start, 'end': turn.end, 'speaker': speaker_label_from_diar})
                logger.info(f"Prepared {len(diar_turns_with_labels)} diarization turns for lookup.")
            except Exception as e:
                logger.warning(f"Could not process diarization tracks for lookup: {e}. Proceeding without speaker assignment from diarization.")
                # self._report_progress("Warning: Could not use diarization data for speaker assignment.", 85) # Progress handled by caller
                diar_turns_with_labels = [] # Ensure it's empty if processing failed
        elif not self.enable_diarization:
            logger.info("Diarization disabled, speakers will be 'SPEAKER_UNKNOWN' or based on Whisper if it provides them (it doesn't by default).")
        else: # Diarization enabled but diarization_annotation is None (e.g., diarization failed)
            logger.info("No diarization results provided for alignment. Speakers will be 'SPEAKER_UNKNOWN'.")
            # self._report_progress("No diarization data, speakers will be unknown.", 85) # Progress handled by caller

        logger.info(f"Aligning {len(transcription_segments)} transcription segments.")

        for t_seg in transcription_segments:
            start_time = t_seg['start'] # Whisper segment start
            end_time = t_seg['end']     # Whisper segment end
            text = t_seg['text'].strip()
            
            # Default speaker if diarization is off or fails to find a match
            assigned_speaker_label = "SPEAKER_UNKNOWN" 

            if self.enable_diarization and diar_turns_with_labels:
                best_overlap_duration = 0
                # Find the diarization turn that has the maximum overlap with the Whisper segment
                for d_turn in diar_turns_with_labels:
                    # Calculate overlap: max(0, min(end1, end2) - max(start1, start2))
                    overlap_start = max(start_time, d_turn['start'])
                    overlap_end = min(end_time, d_turn['end'])
                    current_overlap = overlap_end - overlap_start
                    
                    if current_overlap > best_overlap_duration:
                        best_overlap_duration = current_overlap
                        assigned_speaker_label = d_turn['speaker']
            
            # Format the output line
            formatted_line_parts = []
            if self.include_timestamps:
                formatted_time_start = self._format_time(start_time)
                formatted_time_end = self._format_time(end_time)
                formatted_line_parts.append(f"[{formatted_time_start} - {formatted_time_end}]")
            
            # Add speaker label, even if it's UNKNOWN
            formatted_line_parts.append(f"{assigned_speaker_label}:")
            formatted_line_parts.append(text)
            
            aligned_output.append(" ".join(formatted_line_parts))

        if not aligned_output and transcription_segments: # Should not happen if formatting is correct
            logger.warning("Alignment produced no output lines despite having transcription segments.")
            # self._report_progress("Alignment produced no output.", 95) # Progress handled by caller
            return ["Note: Transcription was processed, but alignment step yielded no formatted lines."]
        elif not transcription_segments: # This case should be caught by the caller
            # self._report_progress("No transcription segments to align.", 95) # Progress handled by caller
            return ["Error: No transcription segments were provided to align."] # Should be an error from transcription

        logger.info(f"Alignment generated {len(aligned_output)} lines.")
        # self._report_progress("Alignment complete.", 95) # Progress handled by caller
        return aligned_output

    def _format_time(self, seconds: float) -> str:
        if seconds is None or not isinstance(seconds, (int, float)): 
            logger.warning(f"Invalid time value received for formatting: {seconds}. Defaulting to 00:00.000")
            seconds = 0.0
        
        # Ensure seconds is not negative, which can happen with model outputs sometimes
        seconds = max(0, seconds)

        sec_int = int(seconds)
        milliseconds = int((seconds - sec_int) * 1000)
        minutes = sec_int // 60
        sec_rem = sec_int % 60
        return f"{minutes:02d}:{sec_rem:02d}.{milliseconds:03d}"

    def save_to_txt(self, output_path: str, segments_data: list):
        # segments_data is the list of already formatted strings from _align_outputs
        logger.info(f"Saving processed output to: {output_path}")
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                if segments_data:
                    for segment_str_line in segments_data:
                        f.write(segment_str_line + '\n')
                    logger.info("Output saved successfully.")
                    # self._report_progress("Output saved.", 99) # Progress handled by caller (MainApp)
                else:
                    logger.warning("No segments provided to save_to_txt.")
                    # self._report_progress("No segments to save.", 99) # Progress handled by caller
                    f.write("No transcription results found or an error occurred during processing.\n")
        except IOError as e:
            logger.exception(f"IOError saving to text file {output_path}.")
            # self._report_progress("Error saving output file.", 99) # Progress handled by caller
            # Re-raise or handle appropriately if MainApp needs to know about save failure specifically
            raise 
        except Exception as e:
            logger.exception(f"Unexpected error saving to text file {output_path}.")
            # self._report_progress("Error saving output file.", 99) # Progress handled by caller
            raise