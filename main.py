# main.py
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import logging
import os

# --- Project-specific imports ---
from utils import constants
from utils.logging_setup import setup_logging # This will now configure file logging too
from utils.config_manager import ConfigManager
from core.audio_processor import AudioProcessor 
from ui.main_window import UI
from ui.correction_window import CorrectionWindow

# Call setup_logging() at the module level to ensure it's configured once
setup_logging()
logger = logging.getLogger(__name__) # Get logger for this module

class MainApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.config_manager = ConfigManager(constants.DEFAULT_CONFIG_FILE)
        self.audio_processor = None
        self.processing_thread = None
        self.audio_file_path = None
        self.correction_window_instance = None

        self.error_display_queue = queue.Queue()
        self.root.after(200, self._poll_error_display_queue)

        self.ui_update_queue = queue.Queue()
        self.root.after(100, self._check_ui_update_queue)

        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_file,
                     open_correction_window_callback=self.open_correction_window
                     )
        self.ui.set_save_token_callback(self.save_huggingface_token)

        self._load_and_display_saved_token()
        # Initialize AudioProcessor after UI is ready so options can be read
        self._ensure_audio_processor_initialized(is_initial_setup=True) 
        
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)


    def _on_closing(self):
        logger.info("Application closing sequence initiated.")
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askyesno("Processing Active", 
                                   "Audio processing is currently active. Exiting now may lead to incomplete results or errors. Are you sure you want to exit?", 
                                   parent=self.root):
                logger.warning("User chose to exit while processing was active. Attempting to stop thread (thread is daemon, will exit with main).")
                # Daemon threads will exit when main program exits. If you need graceful shutdown of thread,
                # you'd need to implement signaling (e.g., an event) for the thread to stop itself.
            else:
                logger.info("User cancelled exit due to active processing.")
                return # Don't close

        if self.correction_window_instance and self.correction_window_instance.window.winfo_exists():
            logger.info("Closing correction window as part of main app shutdown.")
            self.correction_window_instance._on_close() # Trigger its close handler

        logger.info("Destroying main application window.")
        self.root.destroy()


    def open_correction_window(self):
        logger.info("Attempting to open correction window.")
        if self.correction_window_instance and self.correction_window_instance.window.winfo_exists():
            self.correction_window_instance.window.lift()
            self.correction_window_instance.window.focus_force()
            logger.info("Correction window already open, lifting to front and focusing.")
        else:
            self.correction_window_instance = CorrectionWindow(self.root)
            logger.info("New correction window created.")
            # Optionally pass initial transcription/audio paths if available
            # e.g., if a file was just processed:
            # if self.audio_file_path and hasattr(self, 'last_saved_transcription_path'):
            #    self.correction_window_instance.transcription_file_path.set(self.last_saved_transcription_path)
            #    self.correction_window_instance.audio_file_path.set(self.audio_file_path)
            #    self.correction_window_instance._load_files() # Optionally auto-load

    def _load_and_display_saved_token(self):
        logger.info("Loading saved Hugging Face token...")
        token = self.config_manager.load_huggingface_token()
        if token:
            self.ui.load_token_ui(token)
            # logger.info("Token loaded into UI.") # Logged by UI method
        else:
            logger.info("No saved Hugging Face token found.")
            self.ui.load_token_ui("") # Ensure field is cleared if no token

    def save_huggingface_token(self, token: str):
        token_to_save = token.strip() if token else ""
        logger.info(f"Saving Hugging Face token: {'Present' if token_to_save else 'Empty'}")
        self.config_manager.save_huggingface_token(token_to_save)
        self.config_manager.set_use_auth_token(bool(token_to_save))
        messagebox.showinfo("Token Saved", "Hugging Face token has been saved." if token_to_save else "Hugging Face token has been cleared.", parent=self.root)
        logger.info("Token saved/cleared. Configuration updated.")
        # Re-initialize or update audio_processor with new token status
        self._ensure_audio_processor_initialized(force_reinitialize=True)

    def select_audio_file(self):
        logger.info("Opening file dialog to select audio file...")
        file_path = filedialog.askopenfilename(
            defaultextension=".wav",
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")],
            parent=self.root
        )
        if file_path:
            self.audio_file_path = file_path
            self.ui.audio_file_entry.delete(0, tk.END)
            self.ui.audio_file_entry.insert(0, file_path)
            logger.info(f"Audio file selected: {file_path}")
        else:
            logger.info("No audio file selected.")

    def _make_progress_callback(self):
        def callback(message: str, percentage: int = None):
            # This callback is executed by the worker thread.
            # It needs to put updates onto a queue for the main thread to process.
            if message:
                status_payload = {"type": constants.MSG_TYPE_STATUS, "text": message}
                self.ui_update_queue.put(status_payload)
            if percentage is not None:
                progress_payload = {"type": constants.MSG_TYPE_PROGRESS, "value": percentage}
                self.ui_update_queue.put(progress_payload)
        return callback

    def _ensure_audio_processor_initialized(self, force_reinitialize=False, is_initial_setup=False):
        # Check if UI is available, especially during initial setup
        if not hasattr(self, 'ui') or not self.ui:
            logger.warning("_ensure_audio_processor_initialized called before UI is fully available. Deferring.")
            return False # Cannot proceed without UI for options

        if self.audio_processor and not force_reinitialize:
            if self.audio_processor.are_models_loaded():
                # Also update options if they changed without full reinitialization
                current_enable_diarization = self.ui.enable_diarization_var.get()
                current_include_timestamps = self.ui.include_timestamps_var.get()
                if (self.audio_processor.enable_diarization != current_enable_diarization or
                    self.audio_processor.include_timestamps != current_include_timestamps):
                    self.audio_processor.enable_diarization = current_enable_diarization
                    self.audio_processor.include_timestamps = current_include_timestamps
                    logger.info(f"AudioProcessor options updated: Diarization={current_enable_diarization}, Timestamps={current_include_timestamps}")
                logger.debug("Audio processor already initialized and models loaded. Options checked/updated.")
                return True
            logger.warning("Audio processor exists but models not loaded. Re-initializing.")

        logger.info(f"Ensuring AudioProcessor is initialized. Force: {force_reinitialize}, Initial: {is_initial_setup}")
        try:
            use_auth = self.config_manager.get_use_auth_token()
            hf_token = self.config_manager.load_huggingface_token() if use_auth else None

            if use_auth and not hf_token:
                logging.warning("'Use auth token' is enabled, but no Hugging Face token is found. "
                                "Loading restricted models from Pyannote might fail.")

            # Get options from UI
            enable_diarization = self.ui.enable_diarization_var.get()
            include_timestamps = self.ui.include_timestamps_var.get()
            
            logger.info(f"AudioProcessor config: Diarization={enable_diarization}, Timestamps={include_timestamps}, UseAuth={use_auth}, HFTokenPresent={bool(hf_token)}")


            processor_config = { # This config is mainly for HuggingFace token, actual options passed directly
                'huggingface': {
                    'use_auth_token': 'yes' if use_auth else 'no',
                    'hf_token': hf_token
                }
            }
            progress_cb = self._make_progress_callback()
            
            # Create or re-create the AudioProcessor instance
            self.audio_processor = AudioProcessor(
                config=processor_config, 
                progress_callback=progress_cb,
                enable_diarization=enable_diarization,
                include_timestamps=include_timestamps
            )
            logger.info(f"AudioProcessor instance {'re' if force_reinitialize or (not is_initial_setup and self.audio_processor) else ''}created/updated. ")

            if not self.audio_processor.are_models_loaded():
                error_msg = ("AudioProcessor essential models (Pyannote/Whisper) failed to load. "
                             "Please check console and log file for details (e.g., token issues, network problems).")
                logger.error(error_msg)
                if not is_initial_setup:
                    self.error_display_queue.put(error_msg)
                return False
            logger.info("AudioProcessor initialized/verified and models are loaded.")
            return True
        except Exception as e:
            logger.exception("Critical error during AudioProcessor initialization/verification.")
            error_msg = f"Failed to initialize audio processing components: {str(e)}"
            if not is_initial_setup:
                 self.error_display_queue.put(error_msg)
            return False

    def start_processing(self):
        logger.info("'Start Processing' button clicked.")
        if not self.audio_file_path or not os.path.exists(self.audio_file_path):
            messagebox.showerror("Error", "Please select a valid audio file first.", parent=self.root)
            logger.warning(f"Start processing: No audio file selected or path invalid: {self.audio_file_path}")
            return

        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.", parent=self.root)
            logger.warning("Start processing: Processing already in progress.")
            return

        # Ensure processor is initialized WITH LATEST UI OPTIONS before processing
        if not self._ensure_audio_processor_initialized(force_reinitialize=False):
            logger.error("Start processing: Audio processor is not ready. Aborting.")
            # Error message should have been queued by _ensure_audio_processor_initialized
            return

        self.ui.disable_ui_for_processing()
        self.ui.update_status_and_progress("Processing started...", 0)
        self.ui.update_output_text("Processing started...\nThis may take a few moments depending on the audio length and selected options.")

        self.processing_thread = threading.Thread(
            target=self._processing_thread_worker,
            args=(self.audio_file_path,), # Pass current audio file path
            daemon=True # Daemon threads exit when main program exits
        )
        logger.info(f"Starting audio processing thread for: {self.audio_file_path}")
        self.processing_thread.start()

    def _processing_thread_worker(self, current_audio_file_for_thread):
        # This method runs in a separate thread.
        # It should not directly interact with Tkinter UI elements.
        # All UI updates should be done via the ui_update_queue.
        logger.info(f"Thread worker: Starting audio processing for: {current_audio_file_for_thread}")
        final_status_for_queue = constants.STATUS_ERROR
        error_message_for_queue = "An unknown error occurred in the processing thread."
        is_empty_for_queue = False
        processed_segments_for_payload = None
        # self.last_saved_transcription_path = None # For correction window, if needed later

        try:
            # The audio_processor instance should already be configured by start_processing
            if not self.audio_processor or not self.audio_processor.are_models_loaded():
                logger.error("Thread worker: Audio processor or its models are not ready at thread start.")
                error_message_for_queue = "Critical error: Audio processor or models became unavailable."
                # No direct UI interaction here
            else:
                # process_audio will use the options (diarization, timestamps) set on self.audio_processor
                result = self.audio_processor.process_audio(current_audio_file_for_thread)

                final_status_for_queue = result.status
                error_message_for_queue = result.message 
                is_empty_for_queue = result.status == constants.STATUS_EMPTY
                processed_segments_for_payload = result.data if result.status == constants.STATUS_SUCCESS else None

                if result.status == constants.STATUS_SUCCESS:
                    logger.info(f"Thread worker: Audio processing complete. Segments ready ({len(processed_segments_for_payload) if processed_segments_for_payload else 0} segments).")
                    if not processed_segments_for_payload: 
                        logger.warning("Thread worker: Processing reported success but returned no segments.")
                        final_status_for_queue = constants.STATUS_EMPTY 
                        is_empty_for_queue = True
                        error_message_for_queue = result.message or "Processing was successful but yielded no segments."
                elif result.status == constants.STATUS_EMPTY:
                    logger.warning(f"Thread worker: Audio processing resulted in empty output. Message: {result.message}")
                elif result.status == constants.STATUS_ERROR:
                    logger.error(f"Thread worker: Audio processing failed. Message: {result.message}")

        except Exception as e:
            logger.exception("Thread worker: Unhandled error during audio processing.")
            error_message_for_queue = f"Unexpected error in processing thread: {str(e)}"
            final_status_for_queue = constants.STATUS_ERROR 
            is_empty_for_queue = False 
            processed_segments_for_payload = None
        finally:
            logger.info(f"Thread worker: Finalizing with status '{final_status_for_queue}'.")
            completion_payload = {
                "type": constants.MSG_TYPE_COMPLETED,
                constants.KEY_FINAL_STATUS: final_status_for_queue,
                constants.KEY_ERROR_MESSAGE: error_message_for_queue if final_status_for_queue != constants.STATUS_SUCCESS or (final_status_for_queue == constants.STATUS_SUCCESS and not processed_segments_for_payload) else None,
                constants.KEY_IS_EMPTY_RESULT: is_empty_for_queue
            }
            if final_status_for_queue == constants.STATUS_SUCCESS and processed_segments_for_payload:
                completion_payload["processed_segments"] = processed_segments_for_payload

            self.ui_update_queue.put(completion_payload)
            logger.info("Thread worker: Completion message put on ui_update_queue.")


    def _prompt_for_save_location_and_save(self, segments_to_save: list):
        # This method is called from the main thread (_check_ui_update_queue)
        logger.info("Prompting user for save location.")
        default_filename = "transcription.txt"
        if self.audio_file_path:
            try:
                base = os.path.basename(self.audio_file_path)
                name_without_ext = os.path.splitext(base)[0]
                default_filename = f"{name_without_ext}_transcription.txt"
            except Exception as e:
                logger.warning(f"Could not generate default filename from audio path: {e}")

        chosen_output_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            title="Save Transcription As",
            initialfile=default_filename,
            parent=self.root 
        )

        if chosen_output_path:
            try:
                # audio_processor.save_to_txt should handle the include_timestamps option internally
                # based on how it was initialized or updated.
                self.audio_processor.save_to_txt(chosen_output_path, segments_to_save) 
                logger.info(f"Output saved to: {chosen_output_path}")
                # self.last_saved_transcription_path = chosen_output_path # For correction window
                self.ui.update_status_and_progress("Transcription saved successfully!", 100)
                self.ui.display_processed_output(chosen_output_path, processing_returned_empty=False)
                messagebox.showinfo("Success", f"Transcription saved to {chosen_output_path}", parent=self.root)
            except Exception as e:
                logger.exception(f"Error saving file to {chosen_output_path}")
                error_message = f"Could not save file: {str(e)}"
                self.ui.update_status_and_progress("Processing complete, but save failed.", 100)
                text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
                self.ui.update_output_text(f"SAVE FAILED: {error_message}\n\n{text_to_display}")
                messagebox.showerror("Save Error", error_message, parent=self.root)
        else:
            logger.info("User cancelled save dialog.")
            # self.last_saved_transcription_path = None
            self.ui.update_status_and_progress("Processing successful, save cancelled by user.", 100)
            text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
            self.ui.update_output_text(f"File not saved (cancelled by user).\n\n{text_to_display}")
            messagebox.showwarning("Save Cancelled", "File was not saved. Content is displayed in the text area.", parent=self.root)


    def _check_ui_update_queue(self):
        # This method runs in the main Tkinter thread.
        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                logger.debug(f"Main thread received from ui_update_queue: {payload.get('type')}")
                msg_type = payload.get("type")

                if msg_type == constants.MSG_TYPE_STATUS:
                    self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == constants.MSG_TYPE_PROGRESS:
                    self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == constants.MSG_TYPE_COMPLETED:
                    final_status = payload.get(constants.KEY_FINAL_STATUS)
                    error_msg = payload.get(constants.KEY_ERROR_MESSAGE)
                    is_empty = payload.get(constants.KEY_IS_EMPTY_RESULT)
                    
                    if final_status == constants.STATUS_SUCCESS:
                        segments = payload.get("processed_segments")
                        if segments: # Successfully processed and got segments
                            self._prompt_for_save_location_and_save(segments)
                        else: # Success status but no segments (should ideally be STATUS_EMPTY)
                            logger.warning("MSG_TYPE_COMPLETED with STATUS_SUCCESS but no 'processed_segments' or segments are empty.")
                            no_content_msg = error_msg or "Processing completed, but no textual content was generated."
                            self.ui.update_status_and_progress(no_content_msg, 100)
                            self.ui.update_output_text(no_content_msg)
                    elif final_status == constants.STATUS_EMPTY:
                        empty_message = error_msg or "No speech detected or transcribed."
                        self.ui.update_status_and_progress(empty_message, 100)
                        self.ui.display_processed_output(output_file_path=None, processing_returned_empty=True)
                    elif final_status == constants.STATUS_ERROR:
                        final_err_text = error_msg or "An unspecified error occurred during processing."
                        self.ui.update_status_and_progress(f"Error: {final_err_text[:100]}...", 0) 
                        self.error_display_queue.put(final_err_text) 
                        self.ui.update_output_text(f"Processing Error: {final_err_text}\n(Check log file for more details if available)")
                    
                    self.ui.enable_ui_after_processing() # Enable UI regardless of outcome
                
                self.ui_update_queue.task_done()

        except queue.Empty:
            pass # No messages in queue, normal
        except Exception as e:
            logger.exception("Error processing message from ui_update_queue.")
            self.error_display_queue.put(f"Internal error handling UI update: {str(e)}")
            if hasattr(self, 'ui'): self.ui.enable_ui_after_processing() 
        finally:
            if self.root.winfo_exists(): # Check if root window still exists
                 self.root.after(100, self._check_ui_update_queue)

    def _poll_error_display_queue(self):
        # This method runs in the main Tkinter thread.
        try:
            while not self.error_display_queue.empty():
                error_message = self.error_display_queue.get_nowait()
                logger.info(f"Displaying error from error_display_queue: {error_message}")
                messagebox.showerror("Application Error/Warning", error_message, parent=self.root)
                # No need to enable UI here, _check_ui_update_queue handles it on MSG_TYPE_COMPLETED
        except queue.Empty:
            pass # No errors in queue, normal
        except Exception as e:
            logger.exception("Critical error within _poll_error_display_queue itself.")
        finally:
            if self.root.winfo_exists(): # Check if root window still exists
                self.root.after(200, self._poll_error_display_queue)

if __name__ == "__main__":
    # BasicConfig is okay for __main__ but setup_logging() should handle the main app logging.
    # logging.basicConfig(level=logging.DEBUG) 
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()