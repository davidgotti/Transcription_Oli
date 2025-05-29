# main.py
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import queue # Ensure queue is imported
import logging
import os
import datetime

# ... (other imports: constants, setup_logging, ConfigManager, etc.)
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
    def __init__(self, root_tk_param):
        global app_instance
        app_instance = self
        self.root = root_tk_param

        self.config_manager = ConfigManager(constants.DEFAULT_CONFIG_FILE) #
        self.audio_processor = None #
        self.processing_thread = None #
        self.audio_file_paths = [] #
        self.correction_window_instance = None #
        self.last_successful_audio_path = None #
        self.last_successful_transcription_path = None #

        self.error_display_queue = queue.Queue() #
        self.ui_update_queue = queue.Queue() #
        self.completion_queue = queue.Queue() # <<< NEW: Queue for startup completion signal
        
        self.ui = None
        self.launch_screen_ref = None
        self._completion_poller_id = None # To stop the completion poller

    def _setup_main_ui_elements(self): #
        """Sets up the main application UI elements.
           Does NOT set final geometry or zoomed state yet."""
        logger.info("MainApp: Setting up main UI elements (without final geometry).") #
        self.root.title("Audio Transcription and Diarization") #

        style = ttk.Style(self.root) #
        available_themes = style.theme_names() #
        logger.info(f"Available themes: {available_themes}") #
        try:
            if 'clam' in available_themes: style.theme_use('clam'); logger.info("Applied 'clam' theme.") #
            elif 'alt' in available_themes: style.theme_use('alt'); logger.info("Applied 'alt' theme.") #
            else: logger.info("No preferred built-in themes found, using default.") #
        except tk.TclError as e: logger.error(f"Failed to apply a built-in ttk theme: {e}") #
        
        try:
            theme_bg_color = style.lookup('TFrame', 'background') #
            self.root.configure(background=theme_bg_color) #
        except tk.TclError: logger.warning("Could not look up TFrame background for MainApp root.") #

        self.root.after(200, self._poll_error_display_queue) #
        self.root.after(100, self._check_ui_update_queue) #

        self.ui = UI(self.root,
                     start_processing_callback=self.start_processing,
                     select_audio_file_callback=self.select_audio_files,
                     open_correction_window_callback=self.open_correction_window) #
        self.ui.set_save_token_callback(self.save_huggingface_token) #
        self._load_and_display_saved_token() #
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing) #
        logger.info("MainApp: Basic UI framework setup complete (final geometry/state pending).") #

    def _load_models_in_background(self): #
        logger.info("MainApp: Starting model loading in background thread.") #
        success = False
        error_for_finalize = None
        try:
            success = self._ensure_audio_processor_initialized(
                is_initial_setup=True, initial_model_key="large (recommended)"
            ) #
            logger.info(f"Model loading thread: _ensure_audio_processor_initialized returned {success}") #
            # --- MODIFIED: Put result on completion_queue ---
            self.completion_queue.put((success, error_for_finalize))
            logger.info(f"Model loading thread: Put success={success} on completion_queue.")
        except Exception as e:
            logger.error(f"Exception in model loading thread: {e}", exc_info=True) #
            error_for_finalize = str(e)
            success = False
             # --- MODIFIED: Put result on completion_queue ---
            self.completion_queue.put((success, error_for_finalize))
            logger.info(f"Model loading thread: Put success={success} (due to exception) on completion_queue.")

    def _finalize_startup_on_main_thread(self, models_loaded_ok, error_msg=None): #
        # This method's detailed logging should remain.
        logger.critical(f"--- CRITICAL: ENTERING _finalize_startup_on_main_thread. models_loaded_ok={models_loaded_ok}, error_msg='{error_msg}' ---") #

        if self.launch_screen_ref and self.launch_screen_ref.winfo_exists(): #
            logger.info("Launch screen exists, attempting to close.") #
            try:
                self.launch_screen_ref.attributes('-topmost', False) #
                self.launch_screen_ref.close() #
                logger.info("Launch screen closed.") #
            except Exception as e:
                logger.error(f"Error closing launch screen: {e}", exc_info=True) #
            self.launch_screen_ref = None #
        elif self.launch_screen_ref: #
            logger.warning("Launch screen reference exists but winfo_exists() is false.") #
        else:
            logger.warning("Launch screen reference is None at finalize time.") #

        if models_loaded_ok: #
            if self.root and self.root.winfo_exists(): #
                logger.info("Models loaded OK. Preparing to show main window.") #
                try:
                    logger.info("Applying final geometry/zoom state...") #
                    self.root.state('zoomed') #
                except tk.TclError:
                    logger.warning("Failed to set 'zoomed' state, using geometry fallback.") #
                    screen_width = self.root.winfo_screenwidth() #
                    screen_height = self.root.winfo_screenheight() #
                    self.root.geometry(f"{screen_width}x{screen_height}+0+0") #
                
                logger.info("Deiconifying main window...") #
                self.root.deiconify() #
                logger.info("Lifting main window...") #
                self.root.lift() #
                logger.info("Forcing focus to main window...") #
                self.root.focus_force() #
                self.root.update_idletasks() #
                logger.info("MainApp: Application fully initialized and displayed.") #
            else:
                logger.error("Root window does not exist at finalization after successful model load!") #
        else:
            logger.error(f"Model loading failed. Error: {error_msg}") #
            full_error_message = f"Failed to initialize application models: {error_msg or 'Unknown error'}.\nPlease check logs and setup." #
            msg_parent = self.root if self.root and self.root.winfo_exists() else None #
            if msg_parent: #
                messagebox.showerror("Application Error", full_error_message, parent=msg_parent) #
            else: 
                logger.critical(f"Cannot show messagebox (no parent): {full_error_message}") #

            if self.root and self.root.winfo_exists(): #
                logger.info("Destroying root window due to model loading failure.") #
                self.root.destroy() #
        logger.info(f"--- EXITING _finalize_startup_on_main_thread ---") #

    # +++ NEW METHOD to poll the completion queue +++
    def _check_completion_queue(self):
        try:
            while not self.completion_queue.empty():
                success, err_msg = self.completion_queue.get_nowait()
                logger.info(f"MainThread: Got completion signal from queue. Success: {success}, Error: {err_msg}")
                self._finalize_startup_on_main_thread(success, err_msg)
                # Stop polling this queue once the completion signal is processed
                if self._completion_poller_id:
                    self.root.after_cancel(self._completion_poller_id)
                    self._completion_poller_id = None
                return # Exit after processing the first completion message
            
            # If queue is empty, reschedule the poller IF it's still active
            if self.root and self.root.winfo_exists() and self._completion_poller_id:
                 self._completion_poller_id = self.root.after(100, self._check_completion_queue)

        except queue.Empty:
            # If queue is empty, reschedule the poller IF it's still active
            if self.root and self.root.winfo_exists() and self._completion_poller_id:
                 self._completion_poller_id = self.root.after(100, self._check_completion_queue)
        except Exception as e:
            logger.error(f"Error in _check_completion_queue: {e}", exc_info=True)
            # Keep polling if an unexpected error occurs, or decide to stop
            if self.root and self.root.winfo_exists() and self._completion_poller_id:
                 self._completion_poller_id = self.root.after(100, self._check_completion_queue)


    def start_initialization_sequence(self, launch_screen): #
        self.launch_screen_ref = launch_screen #
        self._setup_main_ui_elements() #

        if self.launch_screen_ref and hasattr(self.launch_screen_ref, 'loading_label_text'): #
            self.launch_screen_ref.loading_label_text.set("Loading models, please wait...") #
            if self.launch_screen_ref.winfo_exists(): #
                 self.launch_screen_ref.update_idletasks() #
        
        # +++ START POLLING THE COMPLETION QUEUE +++
        if self.root and self.root.winfo_exists():
            self._completion_poller_id = self.root.after(100, self._check_completion_queue)

        model_loader_thread = threading.Thread(
            target=self._load_models_in_background,
            daemon=True
        ) #
        model_loader_thread.start() #

    # ... (rest of MainApp methods: _on_closing, _ensure_audio_processor_initialized, etc.) ...
    # Make sure all your other MainApp methods are pasted here correctly indented.
    # I'll just show the _ensure_audio_processor_initialized for context if needed.
    def _on_closing(self): #
        logger.info("Application closing sequence initiated.") #
        if self.processing_thread and self.processing_thread.is_alive(): #
            if messagebox.askyesno("Processing Active",
                                   "Audio processing is currently active. Exiting now may lead to incomplete results or errors. Are you sure you want to exit?",
                                   parent=self.root): #
                logger.warning("User chose to exit while processing was active.") #
            else:
                logger.info("User cancelled exit due to active processing.") #
                return #

        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists(): #
            logger.info("Closing correction window as part of main app shutdown.") #
            if hasattr(self.correction_window_instance, '_on_close') and callable(self.correction_window_instance._on_close): #
                self.correction_window_instance._on_close() #
            else:
                try:
                    self.correction_window_instance.window.destroy() #
                except Exception as e:
                    logger.error(f"Error destroying correction window directly: {e}") #

        logger.info("Destroying main application window.") #
        if self.root and self.root.winfo_exists(): # Check before destroying
            self.root.destroy() #

    def open_correction_window(self): #
        logger.info("Attempting to open correction window.") #
        if self.correction_window_instance and hasattr(self.correction_window_instance, 'window') and self.correction_window_instance.window.winfo_exists(): #
            self.correction_window_instance.window.lift() #
            self.correction_window_instance.window.focus_force() #
            logger.info("Correction window already open, lifting to front and focusing.") #
        else:
            include_timestamps_main = self.ui.include_timestamps_var.get() #
            include_end_times_main = self.ui.include_end_times_var.get() if include_timestamps_main else False #

            self.correction_window_instance = CorrectionWindow(
                self.root,
                initial_include_timestamps=include_timestamps_main,
                initial_include_end_times=include_end_times_main
            ) #
            logger.info(f"New correction window created with TS: {include_timestamps_main}, EndTS: {include_end_times_main}") #

            if self.last_successful_audio_path and self.last_successful_transcription_path: #
                logger.info(f"Populating correction window with last successful: Audio='{self.last_successful_audio_path}', Txt='{self.last_successful_transcription_path}'") #
                if hasattr(self.correction_window_instance, 'ui'): #
                    if hasattr(self.correction_window_instance.ui, 'transcription_file_path_var'): #
                        self.correction_window_instance.ui.transcription_file_path_var.set(self.last_successful_transcription_path) #
                    if hasattr(self.correction_window_instance.ui, 'audio_file_path_var'): #
                        self.correction_window_instance.ui.audio_file_path_var.set(self.last_successful_audio_path) #
                    if hasattr(self.correction_window_instance, 'callback_handler') and \
                       hasattr(self.correction_window_instance.callback_handler, 'load_files'): #
                        self.correction_window_instance.callback_handler.load_files() #
            else:
                logger.info("No last successful transcription/audio to auto-load into correction window.") #


    def _load_and_display_saved_token(self): #
        logger.info("Loading saved Hugging Face token...") #
        token = self.config_manager.load_huggingface_token() #
        self.ui.load_token_ui(token if token else "") #

    def save_huggingface_token(self, token: str): #
        token_to_save = token.strip() if token else "" #
        logger.info(f"Saving Hugging Face token: {'Present' if token_to_save else 'Empty'}") #
        self.config_manager.save_huggingface_token(token_to_save) #
        self.config_manager.set_use_auth_token(bool(token_to_save)) #
        messagebox.showinfo("Token Saved", "Hugging Face token has been saved." if token_to_save else "Hugging Face token has been cleared.", parent=self.root) #
        if self.audio_processor: 
             self._ensure_audio_processor_initialized(force_reinitialize=True) #


    def select_audio_files(self): #
        logger.info("Opening file dialog to select audio file(s)...") #
        selected_paths = filedialog.askopenfilenames(
            defaultextension=".wav",
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")],
            parent=self.root
        ) #
        if selected_paths: #
            self.audio_file_paths = list(selected_paths) #
            self.ui.update_audio_file_entry_display(self.audio_file_paths) #
            logger.info(f"{len(self.audio_file_paths)} audio file(s) selected.") #
            self.last_successful_transcription_path = None #
            self.last_successful_audio_path = None #
        else:
            logger.info("No audio file selected or selection cancelled.") #


    def _make_progress_callback(self): #
        def callback(message: str, percentage: int = None): #
            if self.root and self.root.winfo_exists(): 
                if message: #
                    status_payload = {"type": constants.MSG_TYPE_STATUS, "text": message} #
                    self.ui_update_queue.put(status_payload) #
                if percentage is not None: #
                    progress_payload = {"type": constants.MSG_TYPE_PROGRESS, "value": percentage} #
                    self.ui_update_queue.put(progress_payload) #
        return callback #

    def _map_ui_model_key_to_whisper_name(self, ui_model_key: str) -> str: #
        mapping = {
            "tiny": "tiny", "base": "base", "small": "small", "medium": "medium",
            "large (recommended)": "large", "turbo": "small"
        } #
        return mapping.get(ui_model_key, "large") #

    def _ensure_audio_processor_initialized(self, force_reinitialize=False, is_initial_setup=False, initial_model_key=None): #
        ui_model_key_to_use = initial_model_key # [main.py]
        if hasattr(self, 'ui') and self.ui and self.ui.model_var.get(): # [main.py]
             if not initial_model_key or not is_initial_setup : # [main.py]
                ui_model_key_to_use = self.ui.model_var.get() # [main.py]
        
        if not ui_model_key_to_use: # [main.py]
            logger.warning("Model key not determined for audio processor, defaulting to 'large (recommended)'.") # [main.py]
            ui_model_key_to_use = "large (recommended)" # [main.py]

        actual_whisper_model_name = self._map_ui_model_key_to_whisper_name(ui_model_key_to_use) # [main.py]
        
        current_enable_diarization = self.ui.enable_diarization_var.get() if hasattr(self, 'ui') and self.ui else True # [main.py]
        current_include_timestamps = self.ui.include_timestamps_var.get() if hasattr(self, 'ui') and self.ui else True # [main.py]
        current_include_end_times = self.ui.include_end_times_var.get() if hasattr(self, 'ui') and self.ui and current_include_timestamps else False # [main.py]

        if self.audio_processor and not force_reinitialize: # [main.py]
            options_changed = (
                self.audio_processor.transcription_handler.model_name != actual_whisper_model_name or
                self.audio_processor.enable_diarization != current_enable_diarization or
                self.audio_processor.include_timestamps != current_include_timestamps or
                self.audio_processor.include_end_times != current_include_end_times
            ) # [main.py]
            if not options_changed and self.audio_processor.are_models_loaded(): # [main.py]
                logger.debug("Audio processor already initialized, models loaded, and options unchanged.") # [main.py]
                return True # [main.py]
            if options_changed: force_reinitialize = True # [main.py]
            elif not self.audio_processor.are_models_loaded(): force_reinitialize = True # [main.py]

        if force_reinitialize or not self.audio_processor: # [main.py]
            logger.info(f"Initializing/Re-initializing AudioProcessor. Model: '{actual_whisper_model_name}'. Initial Setup: {is_initial_setup}, ForceReinit: {force_reinitialize}") # [main.py]
            current_progress_callback = self._make_progress_callback() # [main.py]
            try:
                use_auth = self.config_manager.get_use_auth_token() # [main.py]
                hf_token = self.config_manager.load_huggingface_token() if use_auth else None # [main.py]
                processor_config = {
                    'huggingface': {'use_auth_token': 'yes' if use_auth else 'no', 'hf_token': hf_token},
                    'transcription': {'model_name': actual_whisper_model_name}
                } # [main.py]
                self.audio_processor = AudioProcessor(
                    config=processor_config, progress_callback=current_progress_callback,
                    enable_diarization=current_enable_diarization,
                    include_timestamps=current_include_timestamps,
                    include_end_times=current_include_end_times
                ) # [main.py]
                if not self.audio_processor.are_models_loaded(): # [main.py]
                    err_msg = "AudioProcessor models failed to load. Check logs (e.g., HuggingFace token/network)." # [main.py]
                    logger.error(err_msg) # [main.py]
                    raise RuntimeError(err_msg) # [main.py]
                logger.info("AudioProcessor initialized/verified and models loaded.") # [main.py]
                return True # [main.py]
            except Exception as e: 
                err_msg = f"Failed to initialize audio processing components: {e}" # [main.py]
                logger.exception(err_msg) # [main.py]
                raise # [main.py]
        return True # [main.py]

    def start_processing(self): # [main.py]
        logger.info("'Start Processing' button clicked.") # [main.py]
        if not self.audio_file_paths: # [main.py]
            messagebox.showerror("Error", "Please select one or more valid audio files first.", parent=self.root); return # [main.py]
        if self.processing_thread and self.processing_thread.is_alive(): # [main.py]
            messagebox.showwarning("Busy", "Processing is already in progress.", parent=self.root); return # [main.py]
        try:
            if not self._ensure_audio_processor_initialized(force_reinitialize=True): # [main.py]
                logger.error("Start processing: Audio processor not ready or failed to re-initialize. Aborting."); return # [main.py]
        except Exception as e:
             logger.error(f"Failed to ensure audio processor initialized for processing: {e}") # [main.py]
             messagebox.showerror("Error", f"Could not initialize audio processor: {e}", parent=self.root) # [main.py]
             return # [main.py]

        self.ui.disable_ui_for_processing() # [main.py]
        
        if len(self.audio_file_paths) == 1: # [main.py]
            self.ui.update_status_and_progress("Processing started...", 0) # [main.py]
            self.ui.update_output_text("Processing started...") # [main.py]
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_single, args=(self.audio_file_paths[0],), daemon=True) # [main.py]
            logger.info(f"Starting single file processing thread for: {self.audio_file_paths[0]} with model {self.audio_processor.transcription_handler.model_name}") # [main.py]
        else:
            self.ui.update_status_and_progress(f"Batch processing started for {len(self.audio_file_paths)} files...", 0) #
            self.ui.update_output_text(f"Batch processing started for {len(self.audio_file_paths)} files...") #
            self.processing_thread = threading.Thread(target=self._processing_thread_worker_batch, args=(list(self.audio_file_paths),), daemon=True) #
            logger.info(f"Starting batch processing thread for {len(self.audio_file_paths)} files with model {self.audio_processor.transcription_handler.model_name}") #
        
        self.processing_thread.start() # [main.py]

    def _processing_thread_worker_single(self, audio_file_to_process): # [main.py]
        logger.info(f"Thread worker (single): Starting audio processing for: {audio_file_to_process}") # [main.py]
        status, msg, is_empty, segments_data = constants.STATUS_ERROR, "Unknown error during single file processing.", False, None # [main.py]
        try:
            if not self.audio_processor or not self.audio_processor.are_models_loaded(): # [main.py]
                msg = "Critical error: Audio processor became unavailable before processing." # [main.py]
                logger.error(msg) # [main.py]
            else:
                result = self.audio_processor.process_audio(audio_file_to_process) # [main.py]
                status, msg, is_empty = result.status, result.message, result.status == constants.STATUS_EMPTY # [main.py]
                segments_data = result.data if result.status == constants.STATUS_SUCCESS else None # [main.py]
                if result.status == constants.STATUS_SUCCESS and not segments_data: # [main.py]
                    status, is_empty, msg = constants.STATUS_EMPTY, True, result.message or "Successful but no segments generated." # [main.py]
        except Exception as e:
            logger.exception("Thread worker (single): Unhandled error during processing.") # [main.py]
            msg = f"Unexpected error processing {os.path.basename(audio_file_to_process)}: {e}" # [main.py]
        finally:
            logger.info(f"Thread worker (single): Finalizing for {os.path.basename(audio_file_to_process)} with status '{status}'.") # [main.py]
            if self.root and self.root.winfo_exists(): 
                self.ui_update_queue.put({
                    "type": constants.MSG_TYPE_COMPLETED, 
                    constants.KEY_FINAL_STATUS: status,
                    constants.KEY_ERROR_MESSAGE: msg,
                    constants.KEY_IS_EMPTY_RESULT: is_empty,
                    "processed_segments": segments_data, 
                    "original_audio_path": audio_file_to_process 
                }) # [main.py]

    def _processing_thread_worker_batch(self, files_to_process_list): # [main.py]
        logger.info(f"Thread worker (batch): Starting processing for {len(files_to_process_list)} files.") # [main.py]
        all_results_for_batch = [] # [main.py]
        total_files = len(files_to_process_list) # [main.py]

        for i, file_path in enumerate(files_to_process_list): # [main.py]
            base_filename = os.path.basename(file_path) # [main.py]
            logger.info(f"Batch: Processing file {i+1}/{total_files}: {base_filename}") # [main.py]
            if self.root and self.root.winfo_exists():
                self.ui_update_queue.put({
                    "type": constants.MSG_TYPE_BATCH_FILE_START,
                    constants.KEY_BATCH_FILENAME: base_filename,
                    constants.KEY_BATCH_CURRENT_IDX: i + 1,
                    constants.KEY_BATCH_TOTAL_FILES: total_files
                }) # [main.py]

            file_status, file_msg, file_is_empty, file_segments_data = constants.STATUS_ERROR, f"Unknown error for {base_filename}", False, None # [main.py]
            try:
                if not self.audio_processor or not self.audio_processor.are_models_loaded(): # [main.py]
                    file_msg = f"Audio processor unavailable for {base_filename}." # [main.py]
                    logger.error(file_msg) # [main.py]
                else:
                    result_obj = self.audio_processor.process_audio(file_path) # [main.py]
                    file_status, file_msg = result_obj.status, result_obj.message # [main.py]
                    file_is_empty = result_obj.status == constants.STATUS_EMPTY # [main.py]
                    file_segments_data = result_obj.data if result_obj.status == constants.STATUS_SUCCESS else None # [main.py]
                    if result_obj.status == constants.STATUS_SUCCESS and not file_segments_data: # [main.py]
                         file_status, file_is_empty, file_msg = constants.STATUS_EMPTY, True, result_obj.message or "Successful but no segments." # [main.py]
            except Exception as e:
                logger.exception(f"Batch: Unhandled error processing {base_filename}") # [main.py]
                file_msg = f"Critical error during processing of {base_filename}: {e}" # [main.py]
            
            all_results_for_batch.append({
                "original_path": file_path,
                "status": file_status,
                "message": file_msg,
                "is_empty": file_is_empty,
                "segments_data": file_segments_data
            }) # [main.py]

        logger.info("Batch processing of all files complete.") # [main.py]
        if self.root and self.root.winfo_exists():
            self.ui_update_queue.put({
                "type": constants.MSG_TYPE_BATCH_COMPLETED,
                constants.KEY_BATCH_ALL_RESULTS: all_results_for_batch
            }) # [main.py]


    def _prompt_for_save_location_and_save_single(self, segments_to_save: list, original_audio_path: str): # [main.py]
        default_fn = "transcription.txt" # [main.py]
        try:
            name, _ = os.path.splitext(os.path.basename(original_audio_path)) # [main.py]
            model_name = self.audio_processor.transcription_handler.model_name if self.audio_processor else "model" # [main.py]
            default_fn = f"{name}_{model_name}_transcription.txt" # [main.py]
        except Exception: pass # [main.py]

        chosen_path = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text Files", "*.txt")],
            title="Save Transcription As", initialfile=default_fn, parent=self.root
        ) # [main.py]
        if chosen_path: # [main.py]
            try:
                self.audio_processor.save_to_txt(chosen_path, segments_to_save) # [main.py]
                self.last_successful_transcription_path = chosen_path # [main.py]
                self.last_successful_audio_path = original_audio_path # [main.py]
                self.ui.update_status_and_progress("Transcription saved!", 100) # [main.py]
                self.ui.display_processed_output(chosen_path, False) # [main.py]
                messagebox.showinfo("Success", f"Transcription saved to {chosen_path}", parent=self.root) # [main.py]
            except Exception as e:
                err_msg = f"Could not save file: {e}" # [main.py]
                logger.exception(err_msg) # [main.py]
                self.ui.update_status_and_progress("Save failed.", 100) # [main.py]
                self.ui.update_output_text(f"SAVE FAILED: {err_msg}\n\n{'\n'.join(segments_to_save or [])}") # [main.py]
                messagebox.showerror("Save Error", err_msg, parent=self.root) # [main.py]
        else:
            self.last_successful_transcription_path = None # [main.py]
            self.last_successful_audio_path = None # [main.py]
            self.ui.update_status_and_progress("Save cancelled by user.", 100) # [main.py]
            self.ui.update_output_text(f"File not saved. Transcription content:\n\n{'\n'.join(segments_to_save or [])}") # [main.py]
            messagebox.showwarning("Save Cancelled", "File not saved. Content shown in output area.", parent=self.root) # [main.py]


    def _prompt_for_batch_save_directory_and_save(self, all_processed_results: list): # [main.py]
        if not all_processed_results: # [main.py]
            messagebox.showinfo("Batch Process Complete", "No results to save from the batch.", parent=self.root) # [main.py]
            self.ui.update_status_and_progress("Batch complete. Nothing to save.", 100) # [main.py]
            self.ui.update_output_text("Batch processing finished. No results were generated or all failed.") # [main.py]
            return # [main.py]

        output_dir = filedialog.askdirectory(
            title="Select Directory to Save Batch Transcriptions",
            parent=self.root
        ) # [main.py]

        if not output_dir: # [main.py]
            messagebox.showwarning("Batch Save Cancelled", "No directory selected. Batch transcriptions not saved.", parent=self.root) # [main.py]
            self.ui.update_status_and_progress("Batch complete. Save cancelled.", 100) # [main.py]
            summary_lines = ["Batch save cancelled. Transcriptions not saved to disk.\n"] # [main.py]
            for item in all_processed_results[:3]: # [main.py]
                 summary_lines.append(f"{os.path.basename(item['original_path'])}: {item['status']} - {item['message'][:50]}...") # [main.py]
            if len(all_processed_results) > 3: summary_lines.append("...") # [main.py]
            self.ui.display_processed_output(is_batch_summary=True, batch_summary_message="\n".join(summary_lines)) # [main.py]
            return # [main.py]

        final_output_dir = output_dir # [main.py]

        successful_saves = 0 # [main.py]
        failed_saves = 0 # [main.py]
        batch_summary_log = [f"Batch Processing Summary (Saved to: {final_output_dir}):"] # [main.py]

        for item in all_processed_results: # [main.py]
            original_file_path = item['original_path'] # [main.py]
            base_filename = os.path.basename(original_file_path) # [main.py]

            if item['status'] == constants.STATUS_SUCCESS and item['segments_data']: # [main.py]
                transcript_filename_base, _ = os.path.splitext(base_filename) # [main.py]
                model_name_suffix = self.audio_processor.transcription_handler.model_name.replace('.', '') if self.audio_processor else "model" # [main.py]
                output_filename = f"{transcript_filename_base}_{model_name_suffix}_transcript.txt" # [main.py]
                
                full_output_path = os.path.join(final_output_dir, output_filename) # [main.py]
                try:
                    self.audio_processor.save_to_txt(full_output_path, item['segments_data']) # [main.py]
                    logger.info(f"Batch save: Successfully saved {full_output_path}") # [main.py]
                    batch_summary_log.append(f"  SUCCESS: {base_filename} -> {output_filename}") # [main.py]
                    successful_saves += 1 # [main.py]
                    self.last_successful_audio_path = original_file_path # [main.py]
                    self.last_successful_transcription_path = full_output_path # [main.py]
                except Exception as e:
                    logger.exception(f"Batch save: Failed to save {full_output_path}") # [main.py]
                    batch_summary_log.append(f"  FAIL_SAVE: {base_filename} (Error: {e})") # [main.py]
                    failed_saves += 1 # [main.py]
            else: 
                logger.warning(f"Batch save: Skipped saving for {base_filename} due to status: {item['status']} - {item['message']}") # [main.py]
                batch_summary_log.append(f"  SKIPPED ({item['status']}): {base_filename} - {item['message']}") # [main.py]
                failed_saves +=1 # [main.py]

        summary_message = f"Batch processing complete.\nSuccessfully saved: {successful_saves} file(s).\nFailed/Skipped: {failed_saves} file(s).\n\nLocation: {final_output_dir}" # [main.py]
        messagebox.showinfo("Batch Save Complete", summary_message, parent=self.root) # [main.py]
        self.ui.update_status_and_progress("Batch save complete.", 100) # [main.py]
        self.ui.display_processed_output(is_batch_summary=True, batch_summary_message=summary_message + "\n\n" + "\n".join(batch_summary_log)) # [main.py]


    def _check_ui_update_queue(self): # [main.py]
        try:
            while not self.ui_update_queue.empty(): # [main.py]
                payload = self.ui_update_queue.get_nowait() # [main.py]
                msg_type = payload.get("type") # [main.py]

                if msg_type == constants.MSG_TYPE_STATUS: # [main.py]
                    self.ui.update_status_and_progress(status_text=payload.get("text")) # [main.py]
                elif msg_type == constants.MSG_TYPE_PROGRESS: # [main.py]
                    self.ui.update_status_and_progress(progress_value=payload.get("value")) # [main.py]
                elif msg_type == constants.MSG_TYPE_COMPLETED: # [main.py]
                    status = payload.get(constants.KEY_FINAL_STATUS) # [main.py]
                    err_msg = payload.get(constants.KEY_ERROR_MESSAGE) # [main.py]
                    is_empty = payload.get(constants.KEY_IS_EMPTY_RESULT) # [main.py]
                    segments = payload.get("processed_segments") # [main.py]
                    original_audio_path = payload.get("original_audio_path") # [main.py]

                    if status == constants.STATUS_SUCCESS and segments: # [main.py]
                        self._prompt_for_save_location_and_save_single(segments, original_audio_path) # [main.py]
                    elif status == constants.STATUS_EMPTY: # [main.py]
                        self.ui.update_status_and_progress(err_msg or "No speech detected.", 100) # [main.py]
                        self.ui.display_processed_output(processing_returned_empty=True) # [main.py]
                    elif status == constants.STATUS_ERROR: # [main.py]
                        self.ui.update_status_and_progress(f"Error: {err_msg[:100]}...", 0) # [main.py]
                        self.ui.update_output_text(f"Error processing {os.path.basename(original_audio_path)}:\n{err_msg}") # [main.py]
                        self.error_display_queue.put(f"Error processing {os.path.basename(original_audio_path)}:\n{err_msg}") # [main.py]
                    self.ui.enable_ui_after_processing() # [main.py]

                elif msg_type == constants.MSG_TYPE_BATCH_FILE_START: # [main.py]
                    filename = payload.get(constants.KEY_BATCH_FILENAME) # [main.py]
                    current_idx = payload.get(constants.KEY_BATCH_CURRENT_IDX) # [main.py]
                    total_files = payload.get(constants.KEY_BATCH_TOTAL_FILES) # [main.py]
                    self.ui.update_status_and_progress(f"Batch: Processing {current_idx}/{total_files}: {filename}", 0) # [main.py]
                    self.ui.update_output_text(f"Batch: Now processing file {current_idx} of {total_files}: {filename}...") # [main.py]


                elif msg_type == constants.MSG_TYPE_BATCH_COMPLETED: # [main.py]
                    all_results = payload.get(constants.KEY_BATCH_ALL_RESULTS) # [main.py]
                    self.ui.update_status_and_progress("Batch processing finished. Awaiting save location...", 100) # [main.py]
                    self._prompt_for_batch_save_directory_and_save(all_results) # [main.py]
                    self.ui.enable_ui_after_processing() # [main.py]

                self.ui_update_queue.task_done() # [main.py]
        except queue.Empty: # [main.py]
            pass # [main.py]
        except Exception as e:
            logger.exception("Error in _check_ui_update_queue.") # [main.py]
            self.error_display_queue.put(f"Critical UI update error: {e}") # [main.py]
            if hasattr(self, 'ui') and self.ui and self.ui.root.winfo_exists() : # Check UI and its root # [main.py]
                self.ui.enable_ui_after_processing() # [main.py]
        finally:
            if self.root and self.root.winfo_exists(): # [main.py]
                self.root.after(100, self._check_ui_update_queue) # [main.py]


    def _poll_error_display_queue(self): # [main.py]
        try:
            while not self.error_display_queue.empty(): # [main.py]
                error_message = self.error_display_queue.get_nowait() # [main.py]
                parent_window = self.root if self.root and self.root.winfo_exists() else None # [main.py]
                messagebox.showerror("Application Error/Warning", error_message, parent=parent_window) # [main.py]
                self.error_display_queue.task_done() # [main.py]
        except queue.Empty: # [main.py]
            pass # [main.py]
        except Exception as e:
            logger.exception("Error in _poll_error_display_queue.") # [main.py]
        finally:
            if self.root and self.root.winfo_exists(): # [main.py]
                self.root.after(200, self._poll_error_display_queue) # [main.py]


if __name__ == "__main__":
    main_app_root = tk.Tk()

    main_app_root.geometry("1x1-10000-10000") # [main.py]
    main_app_root.title("Transcription Oli Loader") # [main.py]

    style_for_root = ttk.Style(main_app_root) # [main.py]
    try:
        if 'clam' in style_for_root.theme_names(): style_for_root.theme_use('clam') # [main.py]
        elif 'alt' in style_for_root.theme_names(): style_for_root.theme_use('alt') # [main.py]
        theme_bg = style_for_root.lookup('TFrame', 'background') # [main.py]
        main_app_root.configure(background=theme_bg) # [main.py]
    except tk.TclError as e:
        logger.warning(f"Could not apply early theme/bg for root: {e}") # [main.py]
    
    main_app_root.withdraw() # [main.py]
    main_app_root.update_idletasks() # [main.py]

    launch_screen = LaunchScreen(main_app_root) # [main.py]

    main_app_root.update_idletasks() # [main.py]

    app = MainApp(main_app_root) 
    main_app_root.after(150, lambda: app.start_initialization_sequence(launch_screen)) 

    main_app_root.mainloop() #
