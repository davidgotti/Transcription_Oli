# main.py
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import logging
import os # <--- ADD THIS IMPORT

# --- Project-specific imports ---
from utils import constants
from utils.logging_setup import setup_logging
from utils.config_manager import ConfigManager
from core.audio_processor import AudioProcessor
from ui.main_window import UI

setup_logging()

class MainApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.config_manager = ConfigManager(constants.DEFAULT_CONFIG_FILE)
        self.audio_processor = None
        self.processing_thread = None
        self.audio_file_path = None
        # self.output_text_file = constants.DEFAULT_OUTPUT_TEXT_FILE # This is no longer the primary save path

        self.error_display_queue = queue.Queue()
        self.root.after(200, self._poll_error_display_queue)

        self.ui_update_queue = queue.Queue()
        self.root.after(100, self._check_ui_update_queue)

        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_file)
        self.ui.set_save_token_callback(self.save_huggingface_token)

        self._load_and_display_saved_token()
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
        def callback(message: str, percentage: int = None):
            if message:
                status_payload = {"type": constants.MSG_TYPE_STATUS, "text": message}
                self.ui_update_queue.put(status_payload)
            if percentage is not None:
                progress_payload = {"type": constants.MSG_TYPE_PROGRESS, "value": percentage}
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
            progress_cb = self._make_progress_callback()
            self.audio_processor = AudioProcessor(processor_config, progress_callback=progress_cb)
            logging.info(f"AudioProcessor instance {'re' if force_reinitialize else ''}created. "
                         f"Auth: {use_auth}, Token physically present: {bool(hf_token)}")

            if not self.audio_processor.are_models_loaded():
                error_msg = ("AudioProcessor essential models (Pyannote/Whisper) failed to load. "
                             "Please check console logs for details (e.g., token issues, network problems).")
                logging.error(error_msg)
                if not is_initial_setup:
                    self.error_display_queue.put(error_msg)
                return False
            logging.info("AudioProcessor initialized/verified and models are loaded.")
            return True
        except Exception as e:
            logging.exception("Critical error during AudioProcessor initialization/verification.")
            error_msg = f"Failed to initialize audio processing components: {str(e)}"
            if not is_initial_setup:
                self.error_display_queue.put(error_msg)
            return False

    def start_processing(self):
        logging.info("'Start Processing' button clicked.")
        if not self.audio_file_path:
            messagebox.showerror("Error", "Please select an audio file first.")
            logging.warning("Start processing: No audio file selected.")
            return

        if not self._ensure_audio_processor_initialized():
            logging.error("Start processing: Audio processor is not ready. Aborting.")
            self.ui.enable_ui() # Ensure UI is enabled if we abort early
            return

        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.")
            logging.warning("Start processing: Processing already in progress.")
            return

        self.ui.disable_ui()
        self.ui.update_status_and_progress("Processing started...", 0)
        self.ui.update_output_text("Processing started...\nThis may take a few moments depending on the audio length.")

        self.processing_thread = threading.Thread(
            target=self._processing_thread_worker,
            args=(self.audio_file_path,),
            daemon=True
        )
        logging.info(f"Starting audio processing thread for: {self.audio_file_path}")
        self.processing_thread.start()

    def _processing_thread_worker(self, current_audio_file):
        logging.info(f"Thread worker: Starting audio processing for: {current_audio_file}")
        final_status_for_queue = constants.STATUS_ERROR
        error_message_for_queue = "An unknown error occurred in the processing thread."
        is_empty_for_queue = False
        processed_segments_for_payload = None # Initialize

        try:
            if not self.audio_processor or not self.audio_processor.are_models_loaded():
                logging.error("Thread worker: Audio processor or its models are not ready at thread start.")
                error_message_for_queue = "Critical error: Audio processor or models became unavailable."
            else:
                processed_segments = self.audio_processor.process_audio(current_audio_file)

                if isinstance(processed_segments, list) and processed_segments:
                    is_special_message = (len(processed_segments) == 1 and
                                          isinstance(processed_segments[0], str) and
                                          ("Error:" in processed_segments[0] or
                                           "No " in processed_segments[0] or # "No speech detected", "No transcription segments"
                                           "failed" in processed_segments[0].lower() or
                                           "Note:" in processed_segments[0] )) # "Note: Alignment produced no output"


                    if is_special_message:
                        # Check for conditions that should be treated as "empty" vs "error"
                        if "No " in processed_segments[0] or \
                           "no speech" in processed_segments[0].lower() or \
                           "no segments to align" in processed_segments[0].lower() or \
                           ( "Note:" in processed_segments[0] and "yielded no formatted lines" in processed_segments[0]): # Alignment note
                            final_status_for_queue = constants.STATUS_EMPTY
                            is_empty_for_queue = True
                            error_message_for_queue = processed_segments[0] # This is the message to display
                        else: # Treat other messages like "Error:" or "failed" as errors
                            final_status_for_queue = constants.STATUS_ERROR
                            error_message_for_queue = processed_segments[0]
                    else:
                        # This is the successful case with actual segments
                        final_status_for_queue = constants.STATUS_SUCCESS
                        is_empty_for_queue = False
                        processed_segments_for_payload = processed_segments # Store for payload
                        # Saving is now handled by the main thread after user input
                        logging.info("Thread worker: Audio processing complete. Segments ready.")
                else: # Empty list or None returned
                    logging.warning("Thread worker: Audio processing returned no segments or an empty list.")
                    final_status_for_queue = constants.STATUS_EMPTY
                    is_empty_for_queue = True
                    error_message_for_queue = "No speech was detected or transcribed from the audio."

        except Exception as e:
            logging.exception("Thread worker: Unhandled error during audio processing.")
            error_message_for_queue = f"Unexpected error in processing thread: {str(e)}"
            final_status_for_queue = constants.STATUS_ERROR # Ensure it's error status
        finally:
            logging.info(f"Thread worker: Finalizing with status '{final_status_for_queue}'.")
            completion_payload = {
                "type": constants.MSG_TYPE_COMPLETED,
                constants.KEY_FINAL_STATUS: final_status_for_queue,
                constants.KEY_ERROR_MESSAGE: error_message_for_queue if final_status_for_queue != constants.STATUS_SUCCESS else None,
                constants.KEY_IS_EMPTY_RESULT: is_empty_for_queue
            }
            if final_status_for_queue == constants.STATUS_SUCCESS and processed_segments_for_payload:
                completion_payload["processed_segments"] = processed_segments_for_payload
            
            self.ui_update_queue.put(completion_payload)
            logging.info("Thread worker: Completion message put on ui_update_queue.")

    def _prompt_for_save_location_and_save(self, segments_to_save: list):
        logging.info("Prompting user for save location.")
        default_filename = "transcription.txt"
        if self.audio_file_path:
            try:
                base = os.path.basename(self.audio_file_path)
                name_without_ext = os.path.splitext(base)[0]
                default_filename = f"{name_without_ext}_transcription.txt"
            except Exception as e:
                logging.warning(f"Could not generate default filename from audio path: {e}")

        chosen_output_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            title="Save Transcription As",
            initialfile=default_filename,
            parent=self.root # Ensure dialog is modal to the main window
        )

        if chosen_output_path:
            try:
                # The AudioProcessor.save_to_txt already reports progress if callback is used there.
                # Here, we are interested in the success of this specific save operation.
                self.audio_processor.save_to_txt(chosen_output_path, segments_to_save) # This might use its own progress reporting
                logging.info(f"Output saved to: {chosen_output_path}")
                self.ui.update_status_and_progress("Transcription saved successfully!", 100)
                self.ui.display_processed_output(chosen_output_path, processing_returned_empty=False)
                messagebox.showinfo("Success", f"Transcription saved to {chosen_output_path}", parent=self.root)
            except Exception as e:
                logging.exception(f"Error saving file to {chosen_output_path}")
                error_message = f"Could not save file: {str(e)}"
                self.ui.update_status_and_progress("Processing complete, but save failed.", 100) # Still 100% for processing
                text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
                self.ui.update_output_text(f"SAVE FAILED: {error_message}\n\n{text_to_display}")
                messagebox.showerror("Save Error", error_message, parent=self.root)
        else:
            logging.info("User cancelled save dialog.")
            self.ui.update_status_and_progress("Processing successful, save cancelled by user.", 100)
            text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
            self.ui.update_output_text(f"File not saved (cancelled by user).\n\n{text_to_display}")
            messagebox.showwarning("Save Cancelled", "File was not saved. Content is displayed in the text area.", parent=self.root)


    def _check_ui_update_queue(self):
        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                logging.debug(f"Main thread received from ui_update_queue: {payload}")
                msg_type = payload.get("type")

                if msg_type == constants.MSG_TYPE_STATUS:
                    self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == constants.MSG_TYPE_PROGRESS:
                    self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == constants.MSG_TYPE_COMPLETED:
                    final_status = payload.get(constants.KEY_FINAL_STATUS)
                    error_msg = payload.get(constants.KEY_ERROR_MESSAGE)
                    # is_empty = payload.get(constants.KEY_IS_EMPTY_RESULT, False) # Not directly used here now

                    if final_status == constants.STATUS_SUCCESS:
                        segments = payload.get("processed_segments")
                        if segments:
                            # Prompt for save location and handle UI updates related to save
                            self._prompt_for_save_location_and_save(segments)
                        else:
                            # Successful processing but no segments (e.g. alignment yielded nothing from valid transcription)
                            logging.warning("MSG_TYPE_COMPLETED with STATUS_SUCCESS but no 'processed_segments' in payload or segments are empty.")
                            no_content_msg = error_msg or "Processing completed, but no textual content was generated to display or save."
                            self.ui.update_status_and_progress(no_content_msg, 100)
                            self.ui.update_output_text(no_content_msg)
                    elif final_status == constants.STATUS_EMPTY:
                        empty_message = error_msg or "No speech detected or transcribed."
                        self.ui.update_status_and_progress(empty_message, 100)
                        # Pass None for path, True for empty. ui.py handles display.
                        self.ui.display_processed_output(output_file_path=None, processing_returned_empty=True)
                    elif final_status == constants.STATUS_ERROR:
                        final_err_text = error_msg or "An unspecified error occurred during processing."
                        self.ui.update_status_and_progress(f"Error: {final_err_text[:100]}...", 0) # Reset progress on error
                        self.error_display_queue.put(final_err_text) # For messagebox
                        self.ui.update_output_text(f"Processing Error: {final_err_text}\n(Check console for more details if available)")
                    
                    self.ui.enable_ui() # Enable UI after handling any completion status
                
                self.ui_update_queue.task_done()

        except queue.Empty:
            pass
        except Exception as e:
            logging.exception("Error processing message from ui_update_queue.")
            self.error_display_queue.put(f"Internal error handling UI update: {str(e)}")
            if hasattr(self, 'ui'): self.ui.enable_ui() # Fallback
        finally:
            self.root.after(100, self._check_ui_update_queue)

    def _poll_error_display_queue(self):
        try:
            while not self.error_display_queue.empty():
                error_message = self.error_display_queue.get_nowait()
                logging.info(f"Displaying error from error_display_queue: {error_message}")
                messagebox.showerror("Application Error/Warning", error_message, parent=self.root)
                if hasattr(self, 'ui'): self.ui.enable_ui() # Ensure UI is enabled
        except queue.Empty:
            pass
        except Exception as e:
            logging.exception("Critical error within _poll_error_display_queue itself.")
        finally:
            self.root.after(200, self._poll_error_display_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()