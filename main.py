# main.py
import os
import sys

# --- FINAL FIX for PyInstaller Distribution ---
# This "monkey patch" solves the 'tqdm' crash when running as a bundled .exe.
# The `openai-whisper` library uses `tqdm` to show download progress bars.
# In a GUI app without a console (`console=False` in the .spec), `tqdm` can't
# find a place to write and crashes with an AttributeError.
# This code detects if the app is running from a PyInstaller bundle
# (`sys.frozen` is True) and, if so, it disables tqdm's output.
if getattr(sys, 'frozen', False):
    from tqdm import tqdm
    from functools import partial
    # Replace the main tqdm class with a version where the output file is null
    tqdm = partial(tqdm, file=open(os.devnull, 'w'))
    # You could also completely disable it, but this is safer:
    # from unittest.mock import MagicMock
    # sys.modules['tqdm'] = MagicMock()

# --- FIX FOR VIRTUAL MACHINE FILE SYSTEM ISSUES ---
# Set a dedicated cache directory for the Whisper model.
cache_dir_path = "C:\\TranscriptionOli_Cache"
if sys.platform == "win32" and not os.path.exists(cache_dir_path):
    try:
        os.makedirs(cache_dir_path)
        os.environ['XDG_CACHE_HOME'] = cache_dir_path
    except OSError:
        # Fallback if C: drive is not writable, though unlikely.
        pass
# --------------------------------------------------

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import logging
<<<<<<< HEAD
import os
=======
import multiprocessing

# --- Add the bundled ffmpeg to the PATH ---
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    ffmpeg_path = os.path.join(bundle_dir, 'bin')
    os.environ["PATH"] += os.pathsep + ffmpeg_path
>>>>>>> 060be60b96e8a62acdf36f774b1c833055ad04de

# --- Project-specific imports ---
from utils import constants
from utils.logging_setup import setup_logging
from utils.config_manager import ConfigManager
from core.audio_processor import AudioProcessor
from ui.main_window import UI
from ui.correction_window import CorrectionWindow
from ui.launch_screen import LaunchScreen


setup_logging()
logger = logging.getLogger(__name__)

app_instance = None

class MainApp:
    def __init__(self, root_tk):
        self.root = root_tk
        self.config_manager = ConfigManager(constants.DEFAULT_CONFIG_FILE)
        logger.info(f"ConfigManager initialized with path: {constants.DEFAULT_CONFIG_FILE}")

        self.audio_processor = None
        self.processing_thread = None
        self.audio_file_paths = []
        self.correction_window_instance = None
        self.last_successful_audio_path = None
        self.last_successful_transcription_path = None

        self.error_display_queue = queue.Queue()
        self.ui_update_queue = queue.Queue()
        self.completion_queue = queue.Queue()
        
        self.ui = None
        self.launch_screen_ref = None
        self._completion_poller_id = None

    def _setup_main_ui_elements(self):
        logger.info("MainApp: Setting up main UI elements (without final geometry).")
        self.root.title("Audio Transcription and Diarization")

        style = ttk.Style(self.root)
        available_themes = style.theme_names()
        logger.info(f"Available themes: {available_themes}")
        try:
            if 'clam' in available_themes: style.theme_use('clam'); logger.info("Applied 'clam' theme.")
            elif 'alt' in available_themes: style.theme_use('alt'); logger.info("Applied 'alt' theme.")
            else: logger.info("No preferred built-in themes found, using default.")
        except tk.TclError as e: logger.error(f"Failed to apply a built-in ttk theme: {e}")
        
        try:
            theme_bg_color = style.lookup('TFrame', 'background')
            self.root.configure(background=theme_bg_color)
        except tk.TclError: logger.warning("Could not look up TFrame background for MainApp root.")

        self.root.after(200, self._poll_error_display_queue)
        self.root.after(100, self._check_ui_update_queue)

        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_file,
                     open_correction_window_callback=self.open_correction_window # Pass the new callback
                     )
        self.ui.set_save_token_callback(self.save_huggingface_token)
        self._load_and_display_saved_token()
        self._ensure_audio_processor_initialized(is_initial_setup=True)

    def open_correction_window(self):
        logger.info("Attempting to open correction window.")
        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists():
            self.correction_window_instance.window.lift()
            self.correction_window_instance.window.focus_force()
            logger.info("Correction window already open, lifting to front and focusing.")
        else:
            self.correction_window_instance = CorrectionWindow(self.root)
            logging.info("New correction window created.")
            # You might want to pass initial transcription/audio paths if available
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
            logging.info("Token loaded into UI.")
        else:
            logger.warning("_load_and_display_saved_token: UI not ready.")


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
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")],
            parent=self.root
        )
        if file_path:
            self.audio_file_path = file_path
            self.ui.audio_file_entry.delete(0, tk.END)
            self.ui.audio_file_entry.insert(0, file_path)
            logging.info(f"Audio file selected: {file_path}")
        else:
            logger.info("No audio file selected or selection cancelled.")


    def _make_progress_callback(self):
        # This 'callback' is executed by the worker thread.
        # It must NOT interact with Tkinter objects directly.
        # Its only job is to put data onto the thread-safe queue.
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
            # Ensure AudioProcessor is initialized only if it's needed for transcription processing
            # For the correction window, it's not directly used by MainApp.
            if not self.audio_processor or force_reinitialize:
                 self.audio_processor = AudioProcessor(processor_config, progress_callback=progress_cb)
                 logging.info(f"AudioProcessor instance {'re' if force_reinitialize else ''}created. "
                             f"Auth: {use_auth}, Token physically present: {bool(hf_token)}")


            if not self.audio_processor.are_models_loaded():
                error_msg = ("AudioProcessor essential models (Pyannote/Whisper) failed to load. "
                             "Please check console logs for details (e.g., token issues, network problems).")
                logging.error(error_msg)
                if not is_initial_setup: # Avoid error popup on initial startup if models fail then
                    self.error_display_queue.put(error_msg)
                return False # Indicate failure to initialize or load models
            logging.info("AudioProcessor initialized/verified and models are loaded.")
            return True
        except Exception as e:
            logging.exception("Critical error during AudioProcessor initialization/verification.")
            error_msg = f"Failed to initialize audio processing components: {str(e)}"
            if not is_initial_setup:
                 self.error_display_queue.put(error_msg)
            return False


    def start_processing(self):
        logger.info("'Start Processing' button clicked.")
        if not self.audio_file_paths:
            messagebox.showerror("Error", "Please select one or more valid audio files first.", parent=self.root); return
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.")
            logging.warning("Start processing: Processing already in progress.")
            return

        self.ui.disable_ui_for_processing()
        
        if len(self.audio_file_paths) == 1:
            self.ui.update_status_and_progress("Processing started...", 0)
            self.ui.update_output_text("Processing started...")
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_single, args=(self.audio_file_paths[0],), daemon=True)
            logger.info(f"Starting single file processing thread for: {self.audio_file_paths[0]} with model {self.audio_processor.transcription_handler.model_name}")
        else:
            self.ui.update_status_and_progress(f"Batch processing started for {len(self.audio_file_paths)} files...", 0)
            self.ui.update_output_text(f"Batch processing started for {len(self.audio_file_paths)} files...")
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_batch, args=(list(self.audio_file_paths),), daemon=True)
            logger.info(f"Starting batch processing thread for {len(self.audio_file_paths)} files with model {self.audio_processor.transcription_handler.model_name}")
        
        self.processing_thread.start()

    def _processing_thread_worker(self, current_audio_file):
        logging.info(f"Thread worker: Starting audio processing for: {current_audio_file}")
        final_status_for_queue = constants.STATUS_ERROR
        error_message_for_queue = "An unknown error occurred in the processing thread."
        is_empty_for_queue = False
        processed_segments_for_payload = None
        # self.last_saved_transcription_path = None # To potentially pass to correction window

        try:
            if not self.audio_processor or not self.audio_processor.transcription_handler.is_model_loaded():
                msg = "Critical error: Audio processor or transcription model became unavailable before processing."
                logger.error(msg)
            else:
                result = self.audio_processor.process_audio(current_audio_file)

                final_status_for_queue = result.status
                error_message_for_queue = result.message 
                is_empty_for_queue = result.status == constants.STATUS_EMPTY
                processed_segments_for_payload = result.data if result.status == constants.STATUS_SUCCESS else None

                if result.status == constants.STATUS_SUCCESS:
                    logging.info(f"Thread worker: Audio processing complete. Segments ready ({len(processed_segments_for_payload) if processed_segments_for_payload else 0} segments).")
                    if not processed_segments_for_payload: 
                        logging.warning("Thread worker: Processing reported success but returned no segments.")
                        final_status_for_queue = constants.STATUS_EMPTY 
                        is_empty_for_queue = True
                        error_message_for_queue = result.message or "Processing was successful but yielded no segments."
                elif result.status == constants.STATUS_EMPTY:
                    logging.warning(f"Thread worker: Audio processing resulted in empty output. Message: {result.message}")
                elif result.status == constants.STATUS_ERROR:
                    logging.error(f"Thread worker: Audio processing failed. Message: {result.message}")

        except Exception as e:
            logger.exception("Thread worker (single): Unhandled error during processing.")
            msg = f"Unexpected error processing {os.path.basename(audio_file_to_process)}: {e}"
        finally:
            logging.info(f"Thread worker: Finalizing with status '{final_status_for_queue}'.")
            completion_payload = {
                "type": constants.MSG_TYPE_COMPLETED,
                constants.KEY_FINAL_STATUS: final_status_for_queue,
                constants.KEY_ERROR_MESSAGE: error_message_for_queue if final_status_for_queue != constants.STATUS_SUCCESS or (final_status_for_queue == constants.STATUS_SUCCESS and processed_segments_for_payload is None) else None,
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
            parent=self.root 
        )
        if chosen_path:
            try:
                self.audio_processor.save_to_txt(chosen_output_path, segments_to_save) 
                logging.info(f"Output saved to: {chosen_output_path}")
                # self.last_saved_transcription_path = chosen_output_path # Store for correction window
                self.ui.update_status_and_progress("Transcription saved successfully!", 100)
                self.ui.display_processed_output(chosen_output_path, processing_returned_empty=False)
                messagebox.showinfo("Success", f"Transcription saved to {chosen_output_path}", parent=self.root)
            except Exception as e:
                logging.exception(f"Error saving file to {chosen_output_path}")
                error_message = f"Could not save file: {str(e)}"
                self.ui.update_status_and_progress("Processing complete, but save failed.", 100)
                text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
                self.ui.update_output_text(f"SAVE FAILED: {error_message}\n\n{text_to_display}")
                messagebox.showerror("Save Error", error_message, parent=self.root)
        else:
            logging.info("User cancelled save dialog.")
            # self.last_saved_transcription_path = None
            self.ui.update_status_and_progress("Processing successful, save cancelled by user.", 100)
            text_to_display = "\n".join(segments_to_save) if segments_to_save else "No content from processing."
            self.ui.update_output_text(f"File not saved (cancelled by user).\n\n{text_to_display}")
            messagebox.showwarning("Save Cancelled", "File was not saved. Content is displayed in the text area.", parent=self.root)


    def _check_ui_update_queue(self):
        if not (self.root and self.root.winfo_exists()):
            logger.info("_check_ui_update_queue: Root window no longer exists, stopping polling.")
            return

        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                
                if not (hasattr(self, 'ui') and self.ui and self.ui.root.winfo_exists()):
                    logger.warning("UI update queue: UI object or its root no longer exists. Skipping update for payload: %s", payload)
                    self.ui_update_queue.task_done()
                    continue

                msg_type = payload.get("type")

                if msg_type == constants.MSG_TYPE_STATUS:
                    self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == constants.MSG_TYPE_PROGRESS:
                    self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == constants.MSG_TYPE_COMPLETED:
                    final_status = payload.get(constants.KEY_FINAL_STATUS)
                    error_msg = payload.get(constants.KEY_ERROR_MESSAGE)
                    
                    if final_status == constants.STATUS_SUCCESS:
                        segments = payload.get("processed_segments")
                        if segments:
                            self._prompt_for_save_location_and_save(segments)
                        else:
                            logging.warning("MSG_TYPE_COMPLETED with STATUS_SUCCESS but no 'processed_segments' or segments are empty.")
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
                        self.ui.update_output_text(f"Processing Error: {final_err_text}\n(Check console for more details if available)")
                    
                    self.ui.enable_ui() 
                
                self.ui_update_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.exception("Error in _check_ui_update_queue processing a payload.")
            self.error_display_queue.put(f"Critical UI update error: {e}")
            if hasattr(self, 'ui') and self.ui and hasattr(self.ui, 'root') and self.ui.root.winfo_exists():
                try:
                    self.ui.enable_ui_after_processing()
                except Exception as e_enable:
                    logger.error(f"Error trying to re-enable UI after queue error: {e_enable}")
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(100, self._check_ui_update_queue)
            else:
                logger.info("_check_ui_update_queue: Root window destroyed, polling stopped.")

    def _poll_error_display_queue(self):
        try:
            while not self.error_display_queue.empty():
                error_message = self.error_display_queue.get_nowait()
                parent_window = self.root if self.root and self.root.winfo_exists() else None
                messagebox.showerror("Application Error/Warning", error_message, parent=parent_window)
                self.error_display_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.exception("Error in _poll_error_display_queue.")
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(200, self._poll_error_display_queue)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG) # Ensure root logger is configured for testing
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()