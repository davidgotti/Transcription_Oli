# ui/main_window.py
import tkinter as tk
from tkinter import ttk
import logging

logger = logging.getLogger(__name__)

class UI:
    def __init__(self, root, start_processing_callback, select_audio_file_callback, open_correction_window_callback):
        self.root = root
        self.root.title("Audio Transcription and Diarization")

        self.start_processing_callback = start_processing_callback
        self.select_audio_file_callback = select_audio_file_callback
        self.open_correction_window_callback = open_correction_window_callback

        # --- Hugging Face Token Input ---
        token_frame = ttk.LabelFrame(root, text="Hugging Face API Token (Optional)", padding=(10, 5))
        token_frame.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        
        self.token_label = ttk.Label(token_frame, text="Token:")
        self.token_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.token_entry = ttk.Entry(token_frame, width=50)
        self.token_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.save_token_button = ttk.Button(token_frame, text="Save Token", command=self.save_token_ui)
        self.save_token_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        token_frame.columnconfigure(1, weight=1) # Allow token entry to expand

        # --- Audio File Selection ---
        file_frame = ttk.LabelFrame(root, text="Audio File", padding=(10,5))
        file_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.audio_file_label = ttk.Label(file_frame, text="File Path:")
        self.audio_file_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.audio_file_entry = ttk.Entry(file_frame, width=50)
        self.audio_file_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.select_audio_file_callback)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        file_frame.columnconfigure(1, weight=1) # Allow audio file entry to expand

        # --- Processing Options Frame ---
        options_frame = ttk.LabelFrame(root, text="Processing Options", padding=(10, 5))
        options_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=(5,0), sticky="ew")

        self.enable_diarization_var = tk.BooleanVar(value=True) # Default to True
        self.diarization_checkbutton = ttk.Checkbutton(options_frame, text="Enable Speaker Diarization", variable=self.enable_diarization_var)
        self.diarization_checkbutton.pack(side=tk.LEFT, padx=10, pady=5) # pack for horizontal layout
        
        self.include_timestamps_var = tk.BooleanVar(value=True) # Default to True
        self.timestamps_checkbutton = ttk.Checkbutton(options_frame, text="Include Timestamps in Output", variable=self.include_timestamps_var)
        self.timestamps_checkbutton.pack(side=tk.LEFT, padx=10, pady=5) # pack for horizontal layout

        # --- Processing Button ---
        self.process_button = ttk.Button(root, text="Start Processing", command=self.start_processing_callback)
        self.process_button.grid(row=3, column=0, columnspan=3, padx=5, pady=10, sticky="ew")

        # --- Progress Bar and Status Label ---
        progress_status_frame = ttk.Frame(root) # Frame to group status and progress bar
        progress_status_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.status_label = ttk.Label(progress_status_frame, text="Status: Idle")
        self.status_label.pack(side=tk.TOP, fill=tk.X, expand=True) # Use pack for simpler layout within this frame

        self.progress_bar = ttk.Progressbar(progress_status_frame, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(5,0))
        
        progress_status_frame.columnconfigure(0, weight=1)


        # --- Output Area ---
        output_frame = ttk.LabelFrame(root, text="Processed Output", padding=(10,5))
        output_frame.grid(row=5, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")

        self.output_text_area = tk.Text(output_frame, height=15, width=70, wrap=tk.WORD) # wrap=tk.WORD
        self.output_scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output_text_area.yview)
        self.output_text_area.configure(yscrollcommand=self.output_scrollbar.set)
        
        self.output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_text_area.config(state=tk.DISABLED)
        
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)


        # --- Correction Window Button ---
        # Changed text as per item 3
        self.correction_button = ttk.Button(root, text="Transcript Correction", command=self.open_correction_window_callback)
        self.correction_button.grid(row=6, column=0, columnspan=3, padx=5, pady=10, sticky="ew")

        # --- Configure grid weights for main window resizing ---
        root.columnconfigure(0, weight=1) # Allow the single column of frames to expand
        # root.columnconfigure(1, weight=1) # Not needed if all frames span 3 columns
        # root.columnconfigure(2, weight=1) # Not needed
        root.rowconfigure(5, weight=1) # Allow output_frame (containing text area) to expand vertically

        self.elements_to_disable_during_processing = [
            self.browse_button, self.process_button, self.audio_file_entry,
            self.token_entry, self.save_token_button, self.correction_button,
            self.diarization_checkbutton, self.timestamps_checkbutton
        ]
        self.save_token_callback = None

    def update_status_and_progress(self, status_text=None, progress_value=None):
        if status_text is not None:
            self.status_label.config(text=f"Status: {status_text}")
            logger.debug(f"UI Status Updated: {status_text}")
        if progress_value is not None:
            self.progress_bar['value'] = progress_value
            logger.debug(f"UI Progress Updated: {progress_value}%")
        self.root.update_idletasks() # Ensure UI updates are drawn

    def set_save_token_callback(self, callback):
        self.save_token_callback = callback

    def save_token_ui(self):
        if self.save_token_callback:
            token = self.token_entry.get()
            self.save_token_callback(token)
            logger.info("Save token UI action triggered.")

    def load_token_ui(self, token):
        self.token_entry.delete(0, tk.END)
        if token: # Ensure token is not None before inserting
            self.token_entry.insert(0, token)
        logger.info(f"Token loaded into UI: {'Present' if token else 'Empty/None'}")


    def disable_ui_for_processing(self):
        logger.debug("UI: Disabling UI elements for processing.")
        for element in self.elements_to_disable_during_processing:
            if hasattr(element, 'configure'): # Check if it's a standard widget
                 element.configure(state=tk.DISABLED)
            elif hasattr(element, 'config'): # Check for older Tkinter way
                 element.config(state=tk.DISABLED)


    def enable_ui_after_processing(self):
        logger.debug("UI: Enabling UI elements after processing.")
        for element in self.elements_to_disable_during_processing:
            if hasattr(element, 'configure'):
                 element.configure(state=tk.NORMAL)
            elif hasattr(element, 'config'):
                 element.config(state=tk.NORMAL)


    def update_output_text(self, text_content: str):
        self.output_text_area.config(state=tk.NORMAL)
        self.output_text_area.delete("1.0", tk.END)
        self.output_text_area.insert(tk.END, text_content)
        self.output_text_area.config(state=tk.DISABLED)
        logger.debug(f"Output text area updated with content (first 100 chars): '{text_content[:100]}...'")

    def display_processed_output(self, output_file_path: str = None, processing_returned_empty: bool = False):
        logger.info(f"UI: Displaying results. Path: '{output_file_path}', Empty: {processing_returned_empty}")
        try:
            if processing_returned_empty:
                self.update_output_text("No speech was detected or transcribed from the audio file, or the processing yielded no usable segments.")
                logger.info("UI: Displayed 'no speech/segments' message.")
                return

            if not output_file_path:
                msg_to_show = "Error: No output file path provided to display results, though processing was not marked as empty."
                logger.error(f"UI: {msg_to_show}")
                self.update_output_text(msg_to_show)
                return

            with open(output_file_path, 'r', encoding='utf-8') as f:
                output_text = f.read()

            if output_text.strip():
                self.update_output_text(output_text)
                logger.info(f"UI: Results from '{output_file_path}' displayed successfully.")
            else: 
                self.update_output_text(f"Processing complete, but the output file ('{output_file_path}') was unexpectedly empty.")
                logger.warning(f"UI: Output file '{output_file_path}' was empty, though processing_returned_empty was False.")

        except FileNotFoundError:
            logger.error(f"UI: Output file '{output_file_path}' not found for display.")
            msg_to_show = (f"Error: Output file '{output_file_path}' not found. "
                           "The save step might have failed or the path is incorrect. "
                           "Content might have been shown directly if save was cancelled or failed.")
            self.update_output_text(msg_to_show)
        except Exception as e:
            logger.exception("UI: An unexpected error occurred during display_processed_output.")
            err_msg = f"An error occurred while trying to display results from '{output_file_path}': {str(e)}"
            self.update_output_text(err_msg)