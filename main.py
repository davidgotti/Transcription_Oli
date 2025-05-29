# main.py
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import logging
import os
import datetime

# --- Project-specific imports ---
from utils import constants
from utils.logging_setup import setup_logging
from utils.config_manager import ConfigManager
from core.audio_processor import AudioProcessor
from ui.main_window import UI
# Corrected import for CorrectionWindow:
from ui.correction_window import CorrectionWindow

setup_logging()
logger = logging.getLogger(__name__)

class MainApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.config_manager = ConfigManager(constants.DEFAULT_CONFIG_FILE)
        self.audio_processor = None
        self.processing_thread = None
        self.audio_file_paths = [] # Changed to a list for multiple files
        self.correction_window_instance = None
        self.last_successful_audio_path = None # For correction window context
        self.last_successful_transcription_path = None # For correction window context

        self.error_display_queue = queue.Queue()
        self.root.after(200, self._poll_error_display_queue)

        self.ui_update_queue = queue.Queue()
        self.root.after(100, self._check_ui_update_queue)

        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_files, # Renamed for clarity
                     open_correction_window_callback=self.open_correction_window
                     )
        self.ui.set_save_token_callback(self.save_huggingface_token)

        self._load_and_display_saved_token()
        self._ensure_audio_processor_initialized(is_initial_setup=True, initial_model_key="large (recommended)")

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        logger.info("Application closing sequence initiated.")
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askyesno("Processing Active",
                                   "Audio processing is currently active. Exiting now may lead to incomplete results or errors. Are you sure you want to exit?",
                                   parent=self.root):
                logger.warning("User chose to exit while processing was active.")
                # Consider how to gracefully stop the thread if possible, though forceful exit is implied by user choice.
            else:
                logger.info("User cancelled exit due to active processing.")
                return

        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists():
            logger.info("Closing correction window as part of main app shutdown.")
            if hasattr(self.correction_window_instance, '_on_close') and callable(self.correction_window_instance._on_close):
                self.correction_window_instance._on_close()
            else:
                try:
                    self.correction_window_instance.window.destroy()
                except Exception as e:
                    logger.error(f"Error destroying correction window directly: {e}")

        logger.info("Destroying main application window.")
        self.root.destroy()

    def open_correction_window(self):
        logger.info("Attempting to open correction window.")
        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists():
            self.correction_window_instance.window.lift()
            self.correction_window_instance.window.focus_force()
            logger.info("Correction window already open, lifting to front and focusing.")
        else:
            include_timestamps_main = self.ui.include_timestamps_var.get()
            include_end_times_main = self.ui.include_end_times_var.get() if include_timestamps_main else False

            self.correction_window_instance = CorrectionWindow(
                self.root,
                initial_include_timestamps=include_timestamps_main,
                initial_include_end_times=include_end_times_main
            )
            logger.info(f"New correction window created with TS: {include_timestamps_main}, EndTS: {include_end_times_main}")

            if self.last_successful_audio_path and self.last_successful_transcription_path:
                logger.info(f"Populating correction window with last successful: Audio='{self.last_successful_audio_path}', Txt='{self.last_successful_transcription_path}'")
                if hasattr(self.correction_window_instance, 'ui'):
                    if hasattr(self.correction_window_instance.ui, 'transcription_file_path_var'):
                        self.correction_window_instance.ui.transcription_file_path_var.set(self.last_successful_transcription_path)
                    if hasattr(self.correction_window_instance.ui, 'audio_file_path_var'):
                        self.correction_window_instance.ui.audio_file_path_var.set(self.last_successful_audio_path)
                    # Automatically load these files in the correction window
                    if hasattr(self.correction_window_instance, 'callback_handler') and \
                       hasattr(self.correction_window_instance.callback_handler, 'load_files'):
                        self.correction_window_instance.callback_handler.load_files()
            else:
                logger.info("No last successful transcription/audio to auto-load into correction window.")


    def _load_and_display_saved_token(self):
        logger.info("Loading saved Hugging Face token...")
        token = self.config_manager.load_huggingface_token()
        self.ui.load_token_ui(token if token else "")

    def save_huggingface_token(self, token: str):
        token_to_save = token.strip() if token else ""
        logger.info(f"Saving Hugging Face token: {'Present' if token_to_save else 'Empty'}")
        self.config_manager.save_huggingface_token(token_to_save)
        self.config_manager.set_use_auth_token(bool(token_to_save))
        messagebox.showinfo("Token Saved", "Hugging Face token has been saved." if token_to_save else "Hugging Face token has been cleared.", parent=self.root)
        self._ensure_audio_processor_initialized(force_reinitialize=True)

    def select_audio_files(self): # Renamed and modified for multiple files
        logger.info("Opening file dialog to select audio file(s)...")
        # askopenfilenames returns a tuple of strings
        selected_paths = filedialog.askopenfilenames(
            defaultextension=".wav",
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")],
            parent=self.root
        )
        if selected_paths:
            self.audio_file_paths = list(selected_paths) # Store as a list
            self.ui.update_audio_file_entry_display(self.audio_file_paths)
            logger.info(f"{len(self.audio_file_paths)} audio file(s) selected.")
            self.last_successful_transcription_path = None # Reset context for correction window
            self.last_successful_audio_path = None
        else:
            # If selection is cancelled, keep existing selection or clear if desired
            # For now, let's keep existing if selection is cancelled, or clear if user selected then cancelled.
            # If selected_paths is empty tuple, it means cancel.
            # If self.audio_file_paths was already populated, we might want to leave it.
            # However, a common UX is that cancelling clears the selection. Let's try that.
            # self.audio_file_paths = []
            # self.ui.update_audio_file_entry_display(self.audio_file_paths)
            logger.info("No audio file selected or selection cancelled.")


    def _make_progress_callback(self):
        def callback(message: str, percentage: int = None):
            # This callback is for individual file processing by AudioProcessor
            if message:
                status_payload = {"type": constants.MSG_TYPE_STATUS, "text": message}
                self.ui_update_queue.put(status_payload)
            if percentage is not None:
                progress_payload = {"type": constants.MSG_TYPE_PROGRESS, "value": percentage}
                self.ui_update_queue.put(progress_payload)
        return callback

    def _map_ui_model_key_to_whisper_name(self, ui_model_key: str) -> str:
        mapping = {
            "tiny": "tiny", "base": "base", "small": "small", "medium": "medium",
            "large (recommended)": "large", "turbo": "small"
        }
        return mapping.get(ui_model_key, "large")

    def _ensure_audio_processor_initialized(self, force_reinitialize=False, is_initial_setup=False, initial_model_key=None):
        if not hasattr(self, 'ui') or not self.ui: # UI might not be fully ready
            logger.warning("_ensure_audio_processor_initialized called before UI is fully available. Deferring.")
            return False

        ui_selected_model_key = self.ui.model_var.get() if not initial_model_key else initial_model_key
        actual_whisper_model_name = self._map_ui_model_key_to_whisper_name(ui_selected_model_key)

        current_enable_diarization = self.ui.enable_diarization_var.get()
        current_include_timestamps = self.ui.include_timestamps_var.get()
        current_include_end_times = self.ui.include_end_times_var.get() if current_include_timestamps else False

        if self.audio_processor and not force_reinitialize:
            options_changed = (
                self.audio_processor.transcription_handler.model_name != actual_whisper_model_name or
                self.audio_processor.enable_diarization != current_enable_diarization or
                self.audio_processor.include_timestamps != current_include_timestamps or
                self.audio_processor.include_end_times != current_include_end_times
            )
            if not options_changed and self.audio_processor.are_models_loaded():
                logger.debug("Audio processor already initialized, models loaded, and options unchanged.")
                return True
            if options_changed: force_reinitialize = True
            elif not self.audio_processor.are_models_loaded(): force_reinitialize = True


        if force_reinitialize or not self.audio_processor:
            logger.info(f"Initializing/Re-initializing AudioProcessor. Model: '{actual_whisper_model_name}'. Initial Setup: {is_initial_setup}, ForceReinit: {force_reinitialize}")
            try:
                use_auth = self.config_manager.get_use_auth_token()
                hf_token = self.config_manager.load_huggingface_token() if use_auth else None
                processor_config = {
                    'huggingface': {'use_auth_token': 'yes' if use_auth else 'no', 'hf_token': hf_token},
                    'transcription': {'model_name': actual_whisper_model_name}
                }
                # Ensure the progress callback is always fresh for the AudioProcessor instance
                current_progress_callback = self._make_progress_callback()
                self.audio_processor = AudioProcessor(
                    config=processor_config, progress_callback=current_progress_callback,
                    enable_diarization=current_enable_diarization,
                    include_timestamps=current_include_timestamps,
                    include_end_times=current_include_end_times
                )
                if not self.audio_processor.are_models_loaded():
                    err_msg = "AudioProcessor models failed to load. Check logs for details (e.g., HuggingFace token issues or network)."
                    logger.error(err_msg)
                    if not is_initial_setup: self.error_display_queue.put(err_msg)
                    return False
                logger.info("AudioProcessor initialized/verified and models loaded.")
                return True
            except Exception as e:
                err_msg = f"Failed to initialize audio processing components: {e}"
                logger.exception(err_msg)
                if not is_initial_setup: self.error_display_queue.put(err_msg)
                return False
        return True


    def start_processing(self):
        logger.info("'Start Processing' button clicked.")
        if not self.audio_file_paths: # Check if the list is empty
            messagebox.showerror("Error", "Please select one or more valid audio files first.", parent=self.root); return
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.", parent=self.root); return

        # Ensure processor is initialized with current UI settings before starting any processing.
        # Pass force_reinitialize=True to make sure it picks up latest options if they changed since last run.
        if not self._ensure_audio_processor_initialized(force_reinitialize=True):
            logger.error("Start processing: Audio processor not ready or failed to re-initialize. Aborting."); return

        self.ui.disable_ui_for_processing()
        
        if len(self.audio_file_paths) == 1:
            # Single file processing
            self.ui.update_status_and_progress("Processing started...", 0)
            self.ui.update_output_text("Processing started...")
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_single, args=(self.audio_file_paths[0],), daemon=True)
            logger.info(f"Starting single file processing thread for: {self.audio_file_paths[0]} with model {self.audio_processor.transcription_handler.model_name}")
        else:
            # Batch file processing
            self.ui.update_status_and_progress(f"Batch processing started for {len(self.audio_file_paths)} files...", 0)
            self.ui.update_output_text(f"Batch processing started for {len(self.audio_file_paths)} files...")
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_batch, args=(list(self.audio_file_paths),), daemon=True) # Pass a copy
            logger.info(f"Starting batch processing thread for {len(self.audio_file_paths)} files with model {self.audio_processor.transcription_handler.model_name}")
        
        self.processing_thread.start()

    def _processing_thread_worker_single(self, audio_file_to_process):
        logger.info(f"Thread worker (single): Starting audio processing for: {audio_file_to_process}")
        status, msg, is_empty, segments_data = constants.STATUS_ERROR, "Unknown error during single file processing.", False, None
        try:
            if not self.audio_processor or not self.audio_processor.are_models_loaded():
                msg = "Critical error: Audio processor became unavailable before processing."
                logger.error(msg)
            else:
                result = self.audio_processor.process_audio(audio_file_to_process)
                status, msg, is_empty = result.status, result.message, result.status == constants.STATUS_EMPTY
                segments_data = result.data if result.status == constants.STATUS_SUCCESS else None
                if result.status == constants.STATUS_SUCCESS and not segments_data: # Should be caught by STATUS_EMPTY
                    status, is_empty, msg = constants.STATUS_EMPTY, True, result.message or "Successful but no segments generated."
        except Exception as e:
            logger.exception("Thread worker (single): Unhandled error during processing.")
            msg = f"Unexpected error processing {os.path.basename(audio_file_to_process)}: {e}"
        finally:
            logger.info(f"Thread worker (single): Finalizing for {os.path.basename(audio_file_to_process)} with status '{status}'.")
            self.ui_update_queue.put({
                "type": constants.MSG_TYPE_COMPLETED, # Standard completion message
                constants.KEY_FINAL_STATUS: status,
                constants.KEY_ERROR_MESSAGE: msg,
                constants.KEY_IS_EMPTY_RESULT: is_empty,
                "processed_segments": segments_data, # For single file, this is the actual data
                "original_audio_path": audio_file_to_process # Include for context
            })

    def _processing_thread_worker_batch(self, files_to_process_list):
        logger.info(f"Thread worker (batch): Starting processing for {len(files_to_process_list)} files.")
        all_results_for_batch = []
        total_files = len(files_to_process_list)

        for i, file_path in enumerate(files_to_process_list):
            base_filename = os.path.basename(file_path)
            logger.info(f"Batch: Processing file {i+1}/{total_files}: {base_filename}")
            self.ui_update_queue.put({
                "type": constants.MSG_TYPE_BATCH_FILE_START,
                constants.KEY_BATCH_FILENAME: base_filename,
                constants.KEY_BATCH_CURRENT_IDX: i + 1,
                constants.KEY_BATCH_TOTAL_FILES: total_files
            })

            file_status, file_msg, file_is_empty, file_segments_data = constants.STATUS_ERROR, f"Unknown error for {base_filename}", False, None
            try:
                if not self.audio_processor or not self.audio_processor.are_models_loaded():
                    file_msg = f"Audio processor unavailable for {base_filename}."
                    logger.error(file_msg)
                else:
                    # AudioProcessor's progress callback will update UI for current file
                    result_obj = self.audio_processor.process_audio(file_path)
                    file_status, file_msg = result_obj.status, result_obj.message
                    file_is_empty = result_obj.status == constants.STATUS_EMPTY
                    file_segments_data = result_obj.data if result_obj.status == constants.STATUS_SUCCESS else None
                    if result_obj.status == constants.STATUS_SUCCESS and not file_segments_data:
                         file_status, file_is_empty, file_msg = constants.STATUS_EMPTY, True, result_obj.message or "Successful but no segments."
            except Exception as e:
                logger.exception(f"Batch: Unhandled error processing {base_filename}")
                file_msg = f"Critical error during processing of {base_filename}: {e}"
            
            all_results_for_batch.append({
                "original_path": file_path,
                "status": file_status,
                "message": file_msg,
                "is_empty": file_is_empty,
                "segments_data": file_segments_data
            })
            # Optionally, send BATCH_FILE_END here if needed for UI updates between files

        logger.info("Batch processing of all files complete.")
        self.ui_update_queue.put({
            "type": constants.MSG_TYPE_BATCH_COMPLETED,
            constants.KEY_BATCH_ALL_RESULTS: all_results_for_batch
        })


    def _prompt_for_save_location_and_save_single(self, segments_to_save: list, original_audio_path: str):
        default_fn = "transcription.txt"
        try:
            name, _ = os.path.splitext(os.path.basename(original_audio_path))
            model_name = self.audio_processor.transcription_handler.model_name if self.audio_processor else "model"
            default_fn = f"{name}_{model_name}_transcription.txt"
        except Exception: pass

        chosen_path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text Files", "*.txt")],
            title="Save Transcription As", initialfile=default_fn, parent=self.root
        )
        if chosen_path:
            try:
                self.audio_processor.save_to_txt(chosen_path, segments_to_save)
                self.last_successful_transcription_path = chosen_path
                self.last_successful_audio_path = original_audio_path # Save context for correction
                self.ui.update_status_and_progress("Transcription saved!", 100)
                self.ui.display_processed_output(chosen_path, False) # Display the saved file
                messagebox.showinfo("Success", f"Transcription saved to {chosen_path}", parent=self.root)
            except Exception as e:
                err_msg = f"Could not save file: {e}"
                logger.exception(err_msg)
                self.ui.update_status_and_progress("Save failed.", 100) # Still 100% for processing
                self.ui.update_output_text(f"SAVE FAILED: {err_msg}\n\n{'\n'.join(segments_to_save or [])}")
                messagebox.showerror("Save Error", err_msg, parent=self.root)
        else:
            self.last_successful_transcription_path = None # Save was cancelled
            self.last_successful_audio_path = None
            self.ui.update_status_and_progress("Save cancelled by user.", 100)
            # Display content in UI even if not saved
            self.ui.update_output_text(f"File not saved. Transcription content:\n\n{'\n'.join(segments_to_save or [])}")
            messagebox.showwarning("Save Cancelled", "File not saved. Content shown in output area.", parent=self.root)


    def _prompt_for_batch_save_directory_and_save(self, all_processed_results: list):
        if not all_processed_results:
            messagebox.showinfo("Batch Process Complete", "No results to save from the batch.", parent=self.root)
            self.ui.update_status_and_progress("Batch complete. Nothing to save.", 100)
            self.ui.update_output_text("Batch processing finished. No results were generated or all failed.")
            return

        output_dir = filedialog.askdirectory(
            title="Select Directory to Save Batch Transcriptions",
            parent=self.root
        )

        if not output_dir:
            messagebox.showwarning("Batch Save Cancelled", "No directory selected. Batch transcriptions not saved.", parent=self.root)
            self.ui.update_status_and_progress("Batch complete. Save cancelled.", 100)
            # Display a summary of what would have been saved, or first/last result.
            summary_lines = ["Batch save cancelled. Transcriptions not saved to disk.\n"]
            for item in all_processed_results[:3]: # Show first few
                 summary_lines.append(f"{os.path.basename(item['original_path'])}: {item['status']} - {item['message'][:50]}...")
            if len(all_processed_results) > 3: summary_lines.append("...")
            self.ui.display_processed_output(is_batch_summary=True, batch_summary_message="\n".join(summary_lines))
            return

        # Optional: Create a subfolder like "batch_processing_YYYYMMDD_HHMMSS"
        # timestamp_folder_name = f"batch_transcripts_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # final_output_dir = os.path.join(output_dir, timestamp_folder_name)
        # os.makedirs(final_output_dir, exist_ok=True)
        # For now, using the user-selected directory directly as per "store all the files in which are now in a folder called batch processing"

        final_output_dir = output_dir # User selected the final folder.

        successful_saves = 0
        failed_saves = 0
        batch_summary_log = [f"Batch Processing Summary (Saved to: {final_output_dir}):"]

        for item in all_processed_results:
            original_file_path = item['original_path']
            base_filename = os.path.basename(original_file_path)

            if item['status'] == constants.STATUS_SUCCESS and item['segments_data']:
                transcript_filename_base, _ = os.path.splitext(base_filename)
                # Ensure model name is filesystem-friendly if used in filename
                model_name_suffix = self.audio_processor.transcription_handler.model_name.replace('.', '') if self.audio_processor else "model"
                output_filename = f"{transcript_filename_base}_{model_name_suffix}_transcript.txt" # Using original interpretation
                # output_filename = f"{transcript_filename_base}_transcript.txt" # Simpler version from prompt
                
                full_output_path = os.path.join(final_output_dir, output_filename)
                try:
                    self.audio_processor.save_to_txt(full_output_path, item['segments_data'])
                    logger.info(f"Batch save: Successfully saved {full_output_path}")
                    batch_summary_log.append(f"  SUCCESS: {base_filename} -> {output_filename}")
                    successful_saves += 1
                    # Update context for correction window to the last successfully saved file in batch
                    self.last_successful_audio_path = original_file_path
                    self.last_successful_transcription_path = full_output_path
                except Exception as e:
                    logger.exception(f"Batch save: Failed to save {full_output_path}")
                    batch_summary_log.append(f"  FAIL_SAVE: {base_filename} (Error: {e})")
                    failed_saves += 1
            else: # Error during processing or empty result for this file
                logger.warning(f"Batch save: Skipped saving for {base_filename} due to status: {item['status']} - {item['message']}")
                batch_summary_log.append(f"  SKIPPED ({item['status']}): {base_filename} - {item['message']}")
                failed_saves +=1 # Count non-successes as failures for summary purposes

        summary_message = f"Batch processing complete.\nSuccessfully saved: {successful_saves} file(s).\nFailed/Skipped: {failed_saves} file(s).\n\nLocation: {final_output_dir}"
        messagebox.showinfo("Batch Save Complete", summary_message, parent=self.root)
        self.ui.update_status_and_progress("Batch save complete.", 100)
        self.ui.display_processed_output(is_batch_summary=True, batch_summary_message=summary_message + "\n\n" + "\n".join(batch_summary_log))


    def _check_ui_update_queue(self):
        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                msg_type = payload.get("type")

                if msg_type == constants.MSG_TYPE_STATUS:
                    self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == constants.MSG_TYPE_PROGRESS:
                    self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == constants.MSG_TYPE_COMPLETED: # Single file completion
                    status = payload.get(constants.KEY_FINAL_STATUS)
                    err_msg = payload.get(constants.KEY_ERROR_MESSAGE)
                    is_empty = payload.get(constants.KEY_IS_EMPTY_RESULT)
                    segments = payload.get("processed_segments")
                    original_audio_path = payload.get("original_audio_path")

                    if status == constants.STATUS_SUCCESS and segments:
                        self._prompt_for_save_location_and_save_single(segments, original_audio_path)
                    elif status == constants.STATUS_EMPTY:
                        self.ui.update_status_and_progress(err_msg or "No speech detected.", 100)
                        self.ui.display_processed_output(processing_returned_empty=True) # Show generic empty message
                    elif status == constants.STATUS_ERROR:
                        self.ui.update_status_and_progress(f"Error: {err_msg[:100]}...", 0) # Keep progress at 0 for error
                        self.ui.update_output_text(f"Error processing {os.path.basename(original_audio_path)}:\n{err_msg}")
                        self.error_display_queue.put(f"Error processing {os.path.basename(original_audio_path)}:\n{err_msg}")
                    self.ui.enable_ui_after_processing()

                elif msg_type == constants.MSG_TYPE_BATCH_FILE_START:
                    filename = payload.get(constants.KEY_BATCH_FILENAME)
                    current_idx = payload.get(constants.KEY_BATCH_CURRENT_IDX)
                    total_files = payload.get(constants.KEY_BATCH_TOTAL_FILES)
                    # Update status for current file in batch, reset progress bar for this file
                    self.ui.update_status_and_progress(f"Batch: Processing {current_idx}/{total_files}: {filename}", 0)
                    self.ui.update_output_text(f"Batch: Now processing file {current_idx} of {total_files}: {filename}...")


                elif msg_type == constants.MSG_TYPE_BATCH_COMPLETED:
                    all_results = payload.get(constants.KEY_BATCH_ALL_RESULTS)
                    self.ui.update_status_and_progress("Batch processing finished. Awaiting save location...", 100) # Overall progress
                    self._prompt_for_batch_save_directory_and_save(all_results)
                    self.ui.enable_ui_after_processing()

                self.ui_update_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.exception("Error in _check_ui_update_queue.")
            self.error_display_queue.put(f"Critical UI update error: {e}")
            if hasattr(self, 'ui') and self.ui: # Ensure UI exists
                self.ui.enable_ui_after_processing() # Try to re-enable UI
        finally:
            if self.root.winfo_exists(): # Check if root window still exists
                self.root.after(100, self._check_ui_update_queue)


    def _poll_error_display_queue(self):
        try:
            while not self.error_display_queue.empty():
                error_message = self.error_display_queue.get_nowait()
                messagebox.showerror("Application Error/Warning", error_message, parent=self.root)
                self.error_display_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.exception("Error in _poll_error_display_queue.")
        finally:
            if self.root.winfo_exists(): # Check if root window still exists
                self.root.after(200, self._poll_error_display_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()