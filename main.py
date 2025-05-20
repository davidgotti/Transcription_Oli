# main.py
import threading
import time # Keep for potential future use, not strictly needed by this version's logic
import tkinter as tk
from tkinter import filedialog, messagebox, ttk # Added ttk for Progressbar
import queue
import logging

# Assuming these are your existing, potentially refactored, modules
from config_manager import ConfigManager
from audio_processor import AudioProcessor
from ui import UI

OUTPUT_TEXT_FILE = "processed_output.txt"

# --- Message types for the queue --- # <--- THESE ARE MODULE LEVEL
MSG_TYPE_STATUS = "STATUS_UPDATE"
MSG_TYPE_PROGRESS = "PROGRESS_PERCENT"
MSG_TYPE_COMPLETED = "PROCESSING_COMPLETED"

# --- Payload keys for MSG_TYPE_COMPLETED --- # <--- THESE ARE MODULE LEVEL
KEY_FINAL_STATUS = "final_status"
KEY_ERROR_MESSAGE = "error_message"
KEY_IS_EMPTY_RESULT = "is_empty_result"

# For the specific error in your log:
# We also need the actual status values that are used
MSG_PROCESSING_SUCCESS = "SUCCESS"
MSG_PROCESSING_EMPTY = "EMPTY"
MSG_PROCESSING_ERROR = "ERROR"

# --- Specific status values for KEY_FINAL_STATUS ---
STATUS_SUCCESS = "SUCCESS"
STATUS_EMPTY = "EMPTY"
STATUS_ERROR = "ERROR"

class MainApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.config_manager = ConfigManager('config.ini')
        self.audio_processor = None
        self.processing_thread = None
        self.audio_file_path = None
        self.output_text_file = OUTPUT_TEXT_FILE

        # Queue for general errors to be displayed by messagebox
        self.error_display_queue = queue.Queue()
        self.root.after(200, self._poll_error_display_queue) # Poll every 200ms

        # Unified queue for progress updates and final completion signals from the worker thread
        self.ui_update_queue = queue.Queue()
        self.root.after(100, self._check_ui_update_queue) # Poll every 100ms for UI updates

        # Initialize UI, passing necessary callbacks
        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_file)
        self.ui.set_save_token_callback(self.save_huggingface_token)

        self._load_and_display_saved_token()
        # Attempt initial audio processor load.
        # Errors during this initial, non-user-initiated load will be logged
        # but won't show a popup, to avoid interrupting app startup.
        self._ensure_audio_processor_initialized(is_initial_setup=True)

    def _load_and_display_saved_token(self):
        logging.info("Loading saved Hugging Face token...")
        token = self.config_manager.load_huggingface_token()
        if token:
            self.ui.load_token_ui(token)
            logging.info("Token loaded into UI.")
        else:
            logging.info("No saved token found.")

    def save_huggingface_token(self, token: str):
        logging.info(f"Saving Hugging Face token: {'present' if token else 'empty'}")
        self.config_manager.save_huggingface_token(token)
        self.config_manager.set_use_auth_token(bool(token))
        messagebox.showinfo("Token Saved", "Hugging Face token has been saved.")
        logging.info("Token saved. Configuration updated.")
        # Re-initialize audio processor as token status affects model loading
        self._ensure_audio_processor_initialized(force_reinitialize=True)

    def select_audio_file(self):
        logging.info("Opening file dialog to select audio file...")
        file_path = filedialog.askopenfilename(
            defaultextension=".wav",
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a")]
        )
        if file_path:
            self.audio_file_path = file_path
            self.ui.audio_file_entry.delete(0, tk.END)
            self.ui.audio_file_entry.insert(0, file_path)
            logging.info(f"Audio file selected: {file_path}")
        else:
            logging.info("No audio file selected.")

    def _make_progress_callback(self):
        """Creates a callback function for AudioProcessor to report progress."""
        def callback(message: str, percentage: int = None):
            # This callback will be executed by the AudioProcessor (likely in the worker thread)
            # It puts messages onto a queue that the main Tkinter thread polls.
            if message: # Ensure message is not None or empty before putting
                status_payload = {"type": MSG_TYPE_STATUS, "text": message}
                self.ui_update_queue.put(status_payload)
            if percentage is not None:
                progress_payload = {"type": MSG_TYPE_PROGRESS, "value": percentage}
                self.ui_update_queue.put(progress_payload)
        return callback

    def _ensure_audio_processor_initialized(self, force_reinitialize=False, is_initial_setup=False):
        if self.audio_processor and not force_reinitialize:
            if self.audio_processor.are_models_loaded():
                logging.debug("Audio processor already initialized and models loaded.")
                return True
            logging.warning("Audio processor exists but models not loaded. Re-initializing.")

        logging.info(f"Ensuring AudioProcessor is initialized. Force: {force_reinitialize}, Initial: {is_initial_setup}")
        try:
            use_auth = self.config_manager.get_use_auth_token()
            hf_token = self.config_manager.load_huggingface_token() if use_auth else None

            if use_auth and not hf_token:
                logging.warning("'Use auth token' is enabled, but no Hugging Face token is found. "
                                "Loading restricted models from Pyannote might fail.")

            processor_config = {
                'huggingface': {
                    'use_auth_token': 'yes' if use_auth else 'no',
                    'hf_token': hf_token
                }
            }

            # Create or re-create AudioProcessor instance
            progress_cb = self._make_progress_callback()
            self.audio_processor = AudioProcessor(processor_config, progress_callback=progress_cb)
            logging.info(f"AudioProcessor instance {'re' if force_reinitialize else ''}created. "
                         f"Auth: {use_auth}, Token physically present: {bool(hf_token)}")

            if not self.audio_processor.are_models_loaded():
                error_msg = ("AudioProcessor essential models (Pyannote/Whisper) failed to load. "
                             "Please check console logs for details (e.g., token issues, network problems).")
                logging.error(error_msg)
                # Only show popup if not initial setup, to avoid error on app start if models fail silently
                if not is_initial_setup:
                    self.error_display_queue.put(error_msg)
                return False

            logging.info("AudioProcessor initialized/verified and models are loaded.")
            return True
        except Exception as e:
            logging.exception("Critical error during AudioProcessor initialization/verification.")
            error_msg = f"Failed to initialize audio processing components: {str(e)}"
            if not is_initial_setup: # Avoid popup on initial silent load failure
                self.error_display_queue.put(error_msg)
            return False

    def start_processing(self):
        logging.info("'Start Processing' button clicked.")
        if not self.audio_file_path:
            messagebox.showerror("Error", "Please select an audio file first.")
            logging.warning("Start processing: No audio file selected.")
            return

        # Ensure audio processor is ready (this will attempt initialization if needed)
        if not self._ensure_audio_processor_initialized():
            logging.error("Start processing: Audio processor is not ready. Aborting.")
            # _ensure_audio_processor_initialized should have queued an error message for display
            self.ui.enable_ui() # Make sure UI is enabled if we can't proceed
            return

        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.")
            logging.warning("Start processing: Processing already in progress.")
            return

        self.ui.disable_ui()
        self.ui.update_status_and_progress("Processing started...", 0) # Initial UI feedback
        self.ui.update_output_text("Processing started...\nThis may take a few moments depending on the audio length.")

        self.processing_thread = threading.Thread(
            target=self._processing_thread_worker,
            args=(self.audio_file_path,),
            daemon=True # Allows main program to exit even if thread is running
        )
        logging.info(f"Starting audio processing thread for: {self.audio_file_path}")
        self.processing_thread.start()

    def _processing_thread_worker(self, current_audio_file):
        logging.info(f"Thread worker: Starting audio processing for: {current_audio_file}")
        final_status_for_queue = STATUS_ERROR # Use defined constant
        error_message_for_queue = "An unknown error occurred in the processing thread."
        is_empty_for_queue = False

        try:
            if not self.audio_processor or not self.audio_processor.are_models_loaded():
                logging.error("Thread worker: Audio processor or its models are not ready at thread start.")
                error_message_for_queue = "Critical error: Audio processor or models became unavailable."
                # final_status_for_queue remains STATUS_ERROR
            else:
                processed_segments = self.audio_processor.process_audio(current_audio_file)

                if isinstance(processed_segments, list) and processed_segments:
                    is_special_message = (len(processed_segments) == 1 and
                                          isinstance(processed_segments[0], str) and
                                          ("Error:" in processed_segments[0] or
                                           "No " in processed_segments[0] or
                                           "failed" in processed_segments[0].lower() ))

                    if is_special_message:
                        if "No " in processed_segments[0] or "no speech" in processed_segments[0].lower():
                            final_status_for_queue = STATUS_EMPTY # Use defined constant
                            is_empty_for_queue = True
                            error_message_for_queue = processed_segments[0]
                        else:
                            final_status_for_queue = STATUS_ERROR # Use defined constant
                            error_message_for_queue = processed_segments[0]
                    else:
                        self.audio_processor.save_to_txt(self.output_text_file, processed_segments)
                        logging.info("Thread worker: Audio processing complete and output saved.")
                        final_status_for_queue = STATUS_SUCCESS # Use defined constant
                        is_empty_for_queue = False
                else:
                    logging.warning("Thread worker: Audio processing returned no segments or an empty list.")
                    final_status_for_queue = STATUS_EMPTY # Use defined constant
                    is_empty_for_queue = True
                    error_message_for_queue = "No speech was detected or transcribed from the audio."

        except Exception as e:
            logging.exception("Thread worker: Unhandled error during audio processing.")
            error_message_for_queue = f"Unexpected error in processing thread: {str(e)}"
            # final_status_for_queue remains STATUS_ERROR
        finally:
            logging.info(f"Thread worker: Finalizing with status '{final_status_for_queue}'.")
            completion_payload = {
                "type": MSG_TYPE_COMPLETED, # This one is fine
                KEY_FINAL_STATUS: final_status_for_queue,
                KEY_ERROR_MESSAGE: error_message_for_queue if final_status_for_queue != STATUS_SUCCESS else None, # Use defined constant
                KEY_IS_EMPTY_RESULT: is_empty_for_queue
            }
            self.ui_update_queue.put(completion_payload)
            logging.info("Thread worker: Completion message put on ui_update_queue.")

    def _check_ui_update_queue(self):
        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                logging.debug(f"Main thread received from ui_update_queue: {payload}")
                msg_type = payload.get("type")

                if msg_type == MSG_TYPE_STATUS:
                    self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == MSG_TYPE_PROGRESS:
                    self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == MSG_TYPE_COMPLETED:
                    final_status = payload.get(KEY_FINAL_STATUS)
                    error_msg = payload.get(KEY_ERROR_MESSAGE)
                    is_empty = payload.get(KEY_IS_EMPTY_RESULT, False)

                    if final_status == STATUS_SUCCESS: # Use defined constant
                        self.ui.update_status_and_progress("Processing successful!", 100)
                        self.display_results_in_ui(processing_returned_empty=False)
                    elif final_status == STATUS_EMPTY: # Use defined constant
                        empty_message = error_msg or "No speech detected or transcribed."
                        self.ui.update_status_and_progress(empty_message, 100)
                        self.display_results_in_ui(processing_returned_empty=True)
                    elif final_status == STATUS_ERROR: # Use defined constant
                        final_err_text = error_msg or "An unspecified error occurred during processing."
                        self.ui.update_status_and_progress(f"Error: {final_err_text[:100]}...", 0)
                        self.error_display_queue.put(final_err_text)
                        self.ui.update_output_text(f"Processing Error: {final_err_text}\n(Check console for details)")
                    
                    self.ui.enable_ui()
                
                self.ui_update_queue.task_done()

        except queue.Empty:
            pass
        except Exception as e:
            logging.exception("Error processing message from ui_update_queue.")
            self.error_display_queue.put(f"Internal error handling UI update: {str(e)}")
            if hasattr(self, 'ui'): self.ui.enable_ui()
        finally:
            self.root.after(100, self._check_ui_update_queue)

    def display_results_in_ui(self, processing_returned_empty=False):
        logging.info(f"Displaying results. processing_returned_empty: {processing_returned_empty}")
        try:
            if processing_returned_empty:
                self.ui.update_output_text("No speech was detected or transcribed from the audio file.")
                logging.info("Displayed 'no speech detected' message.")
                return

            # This part only runs if processing_returned_empty is False
            with open(self.output_text_file, 'r', encoding='utf-8') as f:
                output_text = f.read()

            if output_text.strip():
                self.ui.update_output_text(output_text)
                logging.info("Results displayed in UI.")
            else: # File is empty, but we didn't expect it to be (not flagged as empty result initially)
                self.ui.update_output_text("Processing complete, but the output file was unexpectedly empty.")
                logging.warning("Output file was empty, though processing_returned_empty was False.")

        except FileNotFoundError:
            logging.error(f"Output file '{self.output_text_file}' not found for display.")
            # This implies processing was "successful" enough to try displaying results, but file missing.
            msg_to_show = f"Error: Output file '{self.output_text_file}' not found. Save step might have failed."
            self.ui.update_output_text(msg_to_show)
            self.error_display_queue.put(msg_to_show)
        except Exception as e:
            logging.exception("Error during display_results_in_ui.")
            err_msg = f"Error displaying results: {str(e)}"
            self.error_display_queue.put(err_msg)
            self.ui.update_output_text(err_msg) # Also update text area for visibility

    def _poll_error_display_queue(self):
        try:
            while not self.error_display_queue.empty():
                error_message = self.error_display_queue.get_nowait()
                logging.info(f"Displaying error from error_display_queue: {error_message}")
                messagebox.showerror("Application Error/Warning", error_message)
                # UI enabling is now primarily handled by _check_ui_update_queue upon task completion/error
                # but as a failsafe:
                if hasattr(self, 'ui'): self.ui.enable_ui()
        except queue.Empty:
            pass
        except Exception as e:
            logging.exception("Critical error within _poll_error_display_queue itself.")
        finally:
            self.root.after(200, self._poll_error_display_queue) # Reschedule polling

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG, # DEBUG for development, INFO for release
        format='%(asctime)s %(levelname)-8s [%(threadName)s] [%(filename)s:%(lineno)d] %(funcName)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Example: To see more detailed logs from specific libraries if needed
    # logging.getLogger('httpx').setLevel(logging.WARNING) # httpx can be very verbose
    # logging.getLogger('pyannote').setLevel(logging.INFO) # Or DEBUG if needed
    # logging.getLogger('whisper').setLevel(logging.INFO)

    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()