# main.py
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import queue
import logging
import os

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
        self.audio_file_path = None
        self.correction_window_instance = None
        self.last_saved_transcription_path = None 

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
        self._ensure_audio_processor_initialized(is_initial_setup=True, initial_model_key="large (recommended)") 
        
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        logger.info("Application closing sequence initiated.")
        if self.processing_thread and self.processing_thread.is_alive():
            if messagebox.askyesno("Processing Active", 
                                   "Audio processing is currently active. Exiting now may lead to incomplete results or errors. Are you sure you want to exit?", 
                                   parent=self.root):
                logger.warning("User chose to exit while processing was active.")
            else:
                logger.info("User cancelled exit due to active processing.")
                return

        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists():
            logger.info("Closing correction window as part of main app shutdown.")
            # Assuming CorrectionWindow has an _on_close method to handle its cleanup
            if hasattr(self.correction_window_instance, '_on_close') and callable(self.correction_window_instance._on_close):
                self.correction_window_instance._on_close()
            else:
                logger.warning("CorrectionWindow instance does not have a callable _on_close method.")
                # Fallback to just destroying the window if _on_close is not available/callable
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
            
            if self.audio_file_path and self.last_saved_transcription_path:
               logger.info(f"Populating correction window with: Audio='{self.audio_file_path}', Txt='{self.last_saved_transcription_path}'")
               # Make sure the CorrectionWindow instance has these attributes and they are Tkinter StringVars or similar
               if hasattr(self.correction_window_instance, 'ui') and hasattr(self.correction_window_instance.ui, 'transcription_file_path_var'):
                   self.correction_window_instance.ui.transcription_file_path_var.set(self.last_saved_transcription_path)
               if hasattr(self.correction_window_instance, 'ui') and hasattr(self.correction_window_instance.ui, 'audio_file_path_var'):
                  self.correction_window_instance.ui.audio_file_path_var.set(self.audio_file_path)
               
               # The _load_files call should be made through the callback_handler if it's responsible
               if hasattr(self.correction_window_instance, 'callback_handler') and \
                  hasattr(self.correction_window_instance.callback_handler, 'load_files'):
                   self.correction_window_instance.callback_handler.load_files()
               elif hasattr(self.correction_window_instance, '_load_files_core_logic'): # Fallback if direct method exists
                   self.correction_window_instance._load_files_core_logic(self.last_saved_transcription_path, self.audio_file_path)


    def _load_and_display_saved_token(self):
        logger.info("Loading saved Hugging Face token...")
        token = self.config_manager.load_huggingface_token()
        if token:
            self.ui.load_token_ui(token)
        else:
            logger.info("No saved Hugging Face token found.")
            self.ui.load_token_ui("")

    def save_huggingface_token(self, token: str):
        token_to_save = token.strip() if token else ""
        logger.info(f"Saving Hugging Face token: {'Present' if token_to_save else 'Empty'}")
        self.config_manager.save_huggingface_token(token_to_save)
        self.config_manager.set_use_auth_token(bool(token_to_save))
        messagebox.showinfo("Token Saved", "Hugging Face token has been saved." if token_to_save else "Hugging Face token has been cleared.", parent=self.root)
        logger.info("Token saved/cleared. Configuration updated.")
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
            self.last_saved_transcription_path = None 
        else:
            logger.info("No audio file selected.")

    def _make_progress_callback(self):
        def callback(message: str, percentage: int = None):
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
        if not hasattr(self, 'ui') or not self.ui:
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
            logger.info(f"Initializing/Re-initializing AudioProcessor. Model: '{actual_whisper_model_name}'. Initial: {is_initial_setup}")
            try:
                use_auth = self.config_manager.get_use_auth_token()
                hf_token = self.config_manager.load_huggingface_token() if use_auth else None
                processor_config = {
                    'huggingface': {'use_auth_token': 'yes' if use_auth else 'no', 'hf_token': hf_token},
                    'transcription': {'model_name': actual_whisper_model_name}
                }
                self.audio_processor = AudioProcessor(
                    config=processor_config, progress_callback=self._make_progress_callback(),
                    enable_diarization=current_enable_diarization,
                    include_timestamps=current_include_timestamps,
                    include_end_times=current_include_end_times
                )
                if not self.audio_processor.are_models_loaded():
                    err_msg = "AudioProcessor models failed to load. Check logs."
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
        if not self.audio_file_path or not os.path.exists(self.audio_file_path):
            messagebox.showerror("Error", "Please select a valid audio file first.", parent=self.root); return
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already in progress.", parent=self.root); return

        if not self._ensure_audio_processor_initialized(force_reinitialize=True): 
            logger.error("Start processing: Audio processor not ready. Aborting."); return

        self.ui.disable_ui_for_processing()
        self.ui.update_status_and_progress("Processing started...", 0)
        self.ui.update_output_text("Processing started...")

        self.processing_thread = threading.Thread(target=self._processing_thread_worker, args=(self.audio_file_path,), daemon=True)
        logger.info(f"Starting processing thread for: {self.audio_file_path} with model {self.audio_processor.transcription_handler.model_name}")
        self.processing_thread.start()

    def _processing_thread_worker(self, current_audio_file_for_thread):
        logger.info(f"Thread worker: Starting audio processing for: {current_audio_file_for_thread}")
        status, msg, is_empty, segments_data = constants.STATUS_ERROR, "Unknown error.", False, None
        try:
            if not self.audio_processor or not self.audio_processor.are_models_loaded():
                msg = "Critical error: Audio processor became unavailable."
            else:
                result = self.audio_processor.process_audio(current_audio_file_for_thread)
                status, msg, is_empty = result.status, result.message, result.status == constants.STATUS_EMPTY
                segments_data = result.data if result.status == constants.STATUS_SUCCESS else None
                if result.status == constants.STATUS_SUCCESS and not segments_data:
                    status, is_empty, msg = constants.STATUS_EMPTY, True, result.message or "Successful but no segments."
        except Exception as e: logger.exception("Thread worker: Unhandled error."); msg = f"Unexpected error: {e}"
        finally:
            logger.info(f"Thread worker: Finalizing with status '{status}'.")
            self.ui_update_queue.put({
                "type": constants.MSG_TYPE_COMPLETED, constants.KEY_FINAL_STATUS: status,
                constants.KEY_ERROR_MESSAGE: msg, constants.KEY_IS_EMPTY_RESULT: is_empty,
                "processed_segments": segments_data if segments_data else None
            })

    def _prompt_for_save_location_and_save(self, segments_to_save: list):
        default_fn = "transcription.txt"
        if self.audio_file_path:
            try:
                name, _ = os.path.splitext(os.path.basename(self.audio_file_path))
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
                self.last_saved_transcription_path = chosen_path
                self.ui.update_status_and_progress("Transcription saved!", 100)
                self.ui.display_processed_output(chosen_path, False)
                messagebox.showinfo("Success", f"Transcription saved to {chosen_path}", parent=self.root)
            except Exception as e:
                err_msg = f"Could not save file: {e}"
                logger.exception(err_msg)
                self.ui.update_status_and_progress("Save failed.", 100)
                self.ui.update_output_text(f"SAVE FAILED: {err_msg}\n\n{'\n'.join(segments_to_save or [])}")
                messagebox.showerror("Save Error", err_msg, parent=self.root)
        else:
            self.last_saved_transcription_path = None
            self.ui.update_status_and_progress("Save cancelled.", 100)
            self.ui.update_output_text(f"File not saved.\n\n{'\n'.join(segments_to_save or [])}")
            messagebox.showwarning("Save Cancelled", "File not saved.", parent=self.root)

    def _check_ui_update_queue(self):
        try:
            while not self.ui_update_queue.empty():
                payload = self.ui_update_queue.get_nowait()
                msg_type = payload.get("type")
                if msg_type == constants.MSG_TYPE_STATUS: self.ui.update_status_and_progress(status_text=payload.get("text"))
                elif msg_type == constants.MSG_TYPE_PROGRESS: self.ui.update_status_and_progress(progress_value=payload.get("value"))
                elif msg_type == constants.MSG_TYPE_COMPLETED:
                    status, err_msg, is_empty = payload.get(constants.KEY_FINAL_STATUS), payload.get(constants.KEY_ERROR_MESSAGE), payload.get(constants.KEY_IS_EMPTY_RESULT)
                    if status == constants.STATUS_SUCCESS:
                        segments = payload.get("processed_segments")
                        if segments: self._prompt_for_save_location_and_save(segments)
                        else: self.ui.update_status_and_progress(err_msg or "No content.", 100); self.ui.update_output_text(err_msg or "No content.")
                    elif status == constants.STATUS_EMPTY:
                        self.ui.update_status_and_progress(err_msg or "No speech.", 100); self.ui.display_processed_output(None, True)
                    elif status == constants.STATUS_ERROR:
                        self.ui.update_status_and_progress(f"Error: {err_msg[:100]}...", 0); self.error_display_queue.put(err_msg); self.ui.update_output_text(f"Error: {err_msg}")
                    self.ui.enable_ui_after_processing()
                self.ui_update_queue.task_done()
        except queue.Empty: pass
        except Exception as e:
            logger.exception("Error in _check_ui_update_queue."); self.error_display_queue.put(f"UI update error: {e}")
            if hasattr(self, 'ui'): self.ui.enable_ui_after_processing() 
        finally:
            if self.root.winfo_exists(): self.root.after(100, self._check_ui_update_queue)

    def _poll_error_display_queue(self):
        try:
            while not self.error_display_queue.empty():
                messagebox.showerror("Application Error/Warning", self.error_display_queue.get_nowait(), parent=self.root)
        except queue.Empty: pass
        except Exception as e: logger.exception("Error in _poll_error_display_queue.")
        finally:
            if self.root.winfo_exists(): self.root.after(200, self._poll_error_display_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()
