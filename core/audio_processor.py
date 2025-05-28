# core/audio_processor.py
import logging
import torch
import os
import time # For processing time logging

from utils import constants # Ensure constants is imported
from .diarization_handler import DiarizationHandler
from .transcription_handler import TranscriptionHandler

logger = logging.getLogger(__name__)

class ProcessedAudioResult:
    def __init__(self, status, data=None, message=None):
        self.status = status 
        self.data = data     
        self.message = message 

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

        self.diarization_handler = DiarizationHandler(
            hf_token=hf_token_val,
            use_auth_token_flag=use_auth_token_flag,
            device=self.device,
            progress_callback=self.progress_callback 
        )
        
        whisper_model_name = config.get('transcription', {}).get('model_name', 'large')
        self.transcription_handler = TranscriptionHandler(
            model_name=whisper_model_name,
            device=self.device,
            progress_callback=self.progress_callback
        )

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in AudioProcessor's direct progress_callback: {e}", exc_info=True)

    def are_models_loaded(self) -> bool:
        dia_loaded = self.diarization_handler.is_model_loaded()
        trans_loaded = self.transcription_handler.is_model_loaded()
        if not dia_loaded and self.enable_diarization: 
            logger.warning("AudioProcessor: Diarization is enabled, but its model is not loaded.")
        elif not dia_loaded and not self.enable_diarization:
            logger.info("AudioProcessor: Diarization is disabled, model load status not critical for it.")
            dia_loaded = True 
            
        if not trans_loaded:
            logger.warning("AudioProcessor: Transcription model not loaded.")
        
        return dia_loaded and trans_loaded

    def process_audio(self, audio_path: str) -> ProcessedAudioResult:
        overall_start_time = time.time()
        logger.info(f"AudioProcessor: Starting audio processing for file: {audio_path}. Diarization: {'Enabled' if self.enable_diarization else 'Disabled'}, Timestamps: {'Included' if self.include_timestamps else 'Excluded'}")

        if not self.are_models_loaded():
            logger.error("AudioProcessor: Cannot process audio: one or more required models are not loaded.")
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Essential models not loaded. Check logs for details.")

        diarization_result_obj = None
        try:
            if self.enable_diarization:
                self._report_progress("Diarization starting...", 25)
                diarization_result_obj = self.diarization_handler.diarize(audio_path)
                if diarization_result_obj is None:
                    return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Diarization process failed. Check logs.")
            else:
                logger.info("AudioProcessor: Diarization is disabled by user option.")
                self._report_progress("Diarization skipped (disabled). Transcription starting...", 25)

            transcription_start_progress = 50 if self.enable_diarization else 25 
            self._report_progress("Transcription starting...", transcription_start_progress)
            transcription_output_dict = self.transcription_handler.transcribe(audio_path)

            if not transcription_output_dict or 'segments' not in transcription_output_dict:
                logger.error("AudioProcessor: Transcription failed or returned invalid structure.")
                return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Transcription process failed or returned invalid data.")
            if not transcription_output_dict['segments']:
                 logger.info("AudioProcessor: Transcription produced no segments (no speech detected).")
                 return ProcessedAudioResult(status=constants.STATUS_EMPTY, message="No speech detected during transcription.")

            alignment_start_progress = 75 
            self._report_progress("Aligning speakers with text...", alignment_start_progress)
            align_start_time = time.time()
            aligned_segments = self._align_outputs(diarization_result_obj, transcription_output_dict)
            align_duration = time.time() - align_start_time
            logger.info(f"AudioProcessor: Alignment completed in {align_duration:.2f} seconds.")
            
            if not aligned_segments:
                self._report_progress("Alignment produced no output.", 95)
                return ProcessedAudioResult(status=constants.STATUS_EMPTY,
                                            message="Alignment produced no formatted lines from transcription.")
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
            self._report_progress(f"Critical Error: {str(e)[:100]}...", 0)
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message=f"Critical error during processing: {str(e)}")


    def _align_outputs(self, diarization_annotation, transcription_result_dict: dict) -> list:
        if not transcription_result_dict or not transcription_result_dict.get('segments'):
            logger.warning("Alignment skipped: Transcription segments are missing.")
            return ["Error: Transcription data unavailable for alignment."]

        transcription_segments = transcription_result_dict['segments']
        aligned_output = []
        
        diar_turns_with_labels = []
        # Only prepare diarization turns if diarization is enabled AND annotation object exists
        if self.enable_diarization and diarization_annotation:
            try:
                for turn, _, speaker_label_from_diar in diarization_annotation.itertracks(yield_label=True):
                    diar_turns_with_labels.append({'start': turn.start, 'end': turn.end, 'speaker': speaker_label_from_diar})
                logger.info(f"Prepared {len(diar_turns_with_labels)} diarization turns for lookup.")
            except Exception as e:
                logger.warning(f"Could not process diarization tracks for lookup: {e}. Proceeding without speaker assignment from diarization.")
                diar_turns_with_labels = []
        elif not self.enable_diarization:
            logger.info("Diarization is disabled. Speaker information will not be included from diarization.")
        else: # Diarization enabled but diarization_annotation is None (e.g., diarization failed)
            logger.info("No diarization results provided for alignment. Speaker information will be 'SPEAKER_UNKNOWN' if diarization was attempted.")

        logger.info(f"Aligning {len(transcription_segments)} transcription segments. Timestamps: {self.include_timestamps}, Diarization: {self.enable_diarization}")

        for t_seg in transcription_segments:
            start_time = t_seg['start'] 
            end_time = t_seg['end']     
            text = t_seg['text'].strip()
            
            assigned_speaker_label = "SPEAKER_UNKNOWN" # Default if diarization is enabled but fails to match

            if self.enable_diarization and diar_turns_with_labels:
                best_overlap_duration = 0
                for d_turn in diar_turns_with_labels:
                    overlap_start = max(start_time, d_turn['start'])
                    overlap_end = min(end_time, d_turn['end'])
                    current_overlap = overlap_end - overlap_start
                    
                    if current_overlap > best_overlap_duration:
                        best_overlap_duration = current_overlap
                        assigned_speaker_label = d_turn['speaker']
            
            formatted_line_parts = []
            # 1. Add Timestamps if enabled
            if self.include_timestamps:
                formatted_time_start = self._format_time(start_time)
                formatted_time_end = self._format_time(end_time)
                formatted_line_parts.append(f"[{formatted_time_start} - {formatted_time_end}]")
            
            # 2. Add Speaker if diarization is enabled
            if self.enable_diarization:
                # `assigned_speaker_label` will be from diarization if successful, or "SPEAKER_UNKNOWN"
                # If diarization was enabled but diar_turns_with_labels is empty (e.g. diarization failed early),
                # it will also use "SPEAKER_UNKNOWN".
                formatted_line_parts.append(f"{assigned_speaker_label}:")
            
            # 3. Add Text
            formatted_line_parts.append(text)
            
            # Join parts with space, but handle cases where some parts are missing to avoid extra spaces.
            # e.g., if only text, no leading/trailing space.
            # if only TS and text: "[TS] text"
            # if only Speaker and text: "Speaker: text"
            # if TS, Speaker, text: "[TS] Speaker: text"
            
            final_line = ""
            if self.include_timestamps and self.enable_diarization:
                final_line = f"{formatted_line_parts[0]} {formatted_line_parts[1]} {formatted_line_parts[2]}"
            elif self.include_timestamps: # Diarization disabled
                final_line = f"{formatted_line_parts[0]} {formatted_line_parts[1]}" # TS, Text
            elif self.enable_diarization: # Timestamps disabled
                final_line = f"{formatted_line_parts[0]} {formatted_line_parts[1]}" # Speaker, Text
            else: # Both disabled
                final_line = formatted_line_parts[0] # Just Text

            aligned_output.append(final_line)

        if not aligned_output and transcription_segments:
            logger.warning("Alignment produced no output lines despite having transcription segments.")
            return ["Note: Transcription was processed, but alignment step yielded no formatted lines."]
        elif not transcription_segments:
            return ["Error: No transcription segments were provided to align."]

        logger.info(f"Alignment generated {len(aligned_output)} lines.")
        return aligned_output

    def _format_time(self, seconds: float) -> str:
        if seconds is None or not isinstance(seconds, (int, float)): 
            logger.warning(f"Invalid time value received for formatting: {seconds}. Defaulting to 00:00.000")
            seconds = 0.0
        
        seconds = max(0, seconds)

        sec_int = int(seconds)
        milliseconds = int((seconds - sec_int) * 1000)
        minutes = sec_int // 60
        sec_rem = sec_int % 60
        return f"{minutes:02d}:{sec_rem:02d}.{milliseconds:03d}"

    def save_to_txt(self, output_path: str, segments_data: list):
        logger.info(f"Saving processed output to: {output_path}")
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                if segments_data:
                    for segment_str_line in segments_data:
                        f.write(segment_str_line + '\n')
                    logger.info("Output saved successfully.")
                else:
                    logger.warning("No segments provided to save_to_txt.")
                    f.write("No transcription results found or an error occurred during processing.\n")
        except IOError as e:
            logger.exception(f"IOError saving to text file {output_path}.")
            raise 
        except Exception as e:
            logger.exception(f"Unexpected error saving to text file {output_path}.")
            raise