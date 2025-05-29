# core/audio_processor.py
import logging
import torch
import os
import time 

from utils import constants
from .diarization_handler import DiarizationHandler
from .transcription_handler import TranscriptionHandler

logger = logging.getLogger(__name__)

class ProcessedAudioResult:
    def __init__(self, status, data=None, message=None):
        self.status = status 
        self.data = data     
        self.message = message 

class AudioProcessor:
    def __init__(self, config: dict, progress_callback=None, 
                 enable_diarization=True, include_timestamps=True, include_end_times=False): # Added include_end_times
        huggingface_config = config.get('huggingface', {})
        use_auth_token_flag = str(huggingface_config.get('use_auth_token', 'no')).lower() == 'yes'
        hf_token_val = huggingface_config.get('hf_token') if use_auth_token_flag else None

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"AudioProcessor: Using device: {self.device}")

        self.progress_callback = progress_callback
        self.enable_diarization = enable_diarization
        self.include_timestamps = include_timestamps
        self.include_end_times = include_end_times # Store the new option
        
        logger.info(f"AudioProcessor initialized with Diarization: {self.enable_diarization}, "
                    f"Timestamps: {self.include_timestamps}, Include End Times: {self.include_end_times}")

        self.diarization_handler = DiarizationHandler(
            hf_token=hf_token_val,
            use_auth_token_flag=use_auth_token_flag,
            device=self.device,
            progress_callback=self.progress_callback 
        )
        
        # Model name for transcription is now passed via config in MainApp
        whisper_model_name = config.get('transcription', {}).get('model_name', 'large') # Default to 'large'
        self.transcription_handler = TranscriptionHandler(
            model_name=whisper_model_name, # Use the passed model name
            device=self.device,
            progress_callback=self.progress_callback
        )

    def _report_progress(self, message: str, percentage: int = None):
        if self.progress_callback:
            try:
                self.progress_callback(message, percentage)
            except Exception as e:
                logger.error(f"Error in AudioProcessor's progress_callback: {e}", exc_info=True)

    def are_models_loaded(self) -> bool:
        dia_loaded = True # Assume true if diarization is disabled
        if self.enable_diarization: # Only check if enabled
            dia_loaded = self.diarization_handler.is_model_loaded()
            if not dia_loaded:
                logger.warning("AudioProcessor: Diarization is enabled, but its model is not loaded.")
        else: # Diarization disabled
             logger.info("AudioProcessor: Diarization is disabled, model load status not critical for it.")
            
        trans_loaded = self.transcription_handler.is_model_loaded()
        if not trans_loaded:
            logger.warning("AudioProcessor: Transcription model not loaded.")
        
        return dia_loaded and trans_loaded

    def process_audio(self, audio_path: str) -> ProcessedAudioResult:
        overall_start_time = time.time()
        logger.info(f"AudioProcessor: Processing file: {audio_path}. Diar: {self.enable_diarization}, "
                    f"TS: {self.include_timestamps}, EndTS: {self.include_end_times}, Model: {self.transcription_handler.model_name}")

        if not self.are_models_loaded():
            logger.error("AudioProcessor: Cannot process audio: models not loaded.")
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Essential models not loaded.")

        diarization_result_obj = None
        try:
            if self.enable_diarization:
                self._report_progress("Diarization starting...", 25)
                diarization_result_obj = self.diarization_handler.diarize(audio_path)
                if diarization_result_obj is None and self.diarization_handler.is_model_loaded(): # Check if model was loaded but diarization failed
                    logger.warning("Diarization process completed but returned no result (e.g. no speakers found or error during diarization itself).")
                    # Continue to transcription, but alignment will use 'SPEAKER_UNKNOWN'
            else:
                logger.info("AudioProcessor: Diarization disabled.")
                self._report_progress("Diarization skipped. Transcription starting...", 25)

            transcription_start_progress = 50 if self.enable_diarization else 25 
            self._report_progress(f"Transcription ({self.transcription_handler.model_name}) starting...", transcription_start_progress)
            transcription_output_dict = self.transcription_handler.transcribe(audio_path)

            if not transcription_output_dict or 'segments' not in transcription_output_dict:
                return ProcessedAudioResult(status=constants.STATUS_ERROR, message="Transcription failed or returned invalid data.")
            if not transcription_output_dict['segments']:
                 return ProcessedAudioResult(status=constants.STATUS_EMPTY, message="No speech detected during transcription.")

            alignment_start_progress = 75 
            self._report_progress("Aligning outputs...", alignment_start_progress)
            aligned_segments = self._align_outputs(diarization_result_obj, transcription_output_dict)
            
            if not aligned_segments:
                return ProcessedAudioResult(status=constants.STATUS_EMPTY, message="Alignment produced no formatted lines.")
            if isinstance(aligned_segments, list) and aligned_segments and ("Error:" in aligned_segments[0] or "Note:" in aligned_segments[0]):
                status = constants.STATUS_ERROR if "Error:" in aligned_segments[0] else constants.STATUS_EMPTY
                return ProcessedAudioResult(status=status, message=aligned_segments[0])

            logger.info(f"Total audio processing for {audio_path} completed in {time.time() - overall_start_time:.2f}s.")
            self._report_progress("Processing complete.", 100)
            return ProcessedAudioResult(status=constants.STATUS_SUCCESS, data=aligned_segments)

        except Exception as e:
            logger.exception(f"AudioProcessor: Unhandled exception during process_audio for {audio_path}")
            self._report_progress(f"Critical Error: {str(e)[:100]}...", 0)
            return ProcessedAudioResult(status=constants.STATUS_ERROR, message=f"Critical error: {str(e)}")

    def _align_outputs(self, diarization_annotation, transcription_result_dict: dict) -> list:
        if not transcription_result_dict or not transcription_result_dict.get('segments'):
            return ["Error: Transcription data unavailable for alignment."]

        transcription_segments = transcription_result_dict['segments']
        aligned_output = []
        
        diar_turns = []
        if self.enable_diarization and diarization_annotation and diarization_annotation.labels():
            try:
                for turn, _, speaker_label in diarization_annotation.itertracks(yield_label=True):
                    diar_turns.append({'start': turn.start, 'end': turn.end, 'speaker': speaker_label})
                logger.info(f"Prepared {len(diar_turns)} diarization turns.")
            except Exception as e:
                logger.warning(f"Could not process diarization tracks: {e}. Proceeding without diarization-based speaker assignment.")
                diar_turns = [] # Ensure it's empty if processing failed
        elif not self.enable_diarization:
            logger.info("Diarization disabled for alignment.")
        elif self.enable_diarization and (not diarization_annotation or not diarization_annotation.labels()):
             logger.info("Diarization enabled, but no diarization tracks/labels found. Speakers will be UNKNOWN.")


        for t_seg in transcription_segments:
            start_time = t_seg['start'] 
            end_time = t_seg['end']     
            text = t_seg['text'].strip()
            
            assigned_speaker = "SPEAKER_UNKNOWN" 
            if self.enable_diarization and diar_turns:
                best_overlap = 0
                for d_turn in diar_turns:
                    overlap = max(0, min(end_time, d_turn['end']) - max(start_time, d_turn['start']))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        assigned_speaker = d_turn['speaker']
            
            line_parts = []
            if self.include_timestamps:
                ts_start_str = self._format_time(start_time)
                if self.include_end_times: # New condition
                    ts_end_str = self._format_time(end_time)
                    line_parts.append(f"[{ts_start_str} - {ts_end_str}]")
                else: # Only start time
                    line_parts.append(f"[{ts_start_str}]")
            
            if self.enable_diarization:
                line_parts.append(f"{assigned_speaker}:")
            
            line_parts.append(text)
            
            aligned_output.append(" ".join(filter(None, line_parts))) # filter(None,...) removes empty strings if any part was conditional

        if not aligned_output and transcription_segments:
            return ["Note: Transcription processed, but alignment yielded no lines."]
        elif not transcription_segments:
            return ["Error: No transcription segments to align."]
        return aligned_output

    def _format_time(self, seconds: float) -> str:
        if seconds is None or not isinstance(seconds, (int, float)): 
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
                    for segment_line in segments_data:
                        f.write(segment_line + '\n')
                else:
                    f.write("No transcription results or error during processing.\n")
            logger.info("Output saved successfully.")
        except IOError as e:
            logger.exception(f"IOError saving to {output_path}.")
            raise
