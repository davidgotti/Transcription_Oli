# ui/main_window.py
import tkinter as tk
from tkinter import ttk, messagebox
import logging

logger = logging.getLogger(__name__)

class ToolTip:
    """
    Create a tooltip for a given widget.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(self.tooltip_window, text=self.text, background="#FFFFE0", relief="solid", borderwidth=1, padding=(5,2))
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
        self.tooltip_window = None

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
        
        token_frame.columnconfigure(1, weight=1)

        # --- Audio File Selection ---
        file_frame = ttk.LabelFrame(root, text="Audio File(s)", padding=(10,5))
        file_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.audio_file_label = ttk.Label(file_frame, text="File Path(s):")
        self.audio_file_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.audio_file_entry = ttk.Entry(file_frame, width=50)
        self.audio_file_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.audio_file_entry.config(state=tk.DISABLED) # Display only

        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.select_audio_file_callback)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        file_frame.columnconfigure(1, weight=1)

        # --- Processing Options Frame ---
        options_outer_frame = ttk.LabelFrame(root, text="Processing Options", padding=(10, 5))
        options_outer_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=(5,0), sticky="ew")
        options_outer_frame.columnconfigure(0, weight=1) # Allow inner frame to expand

        # --- Model Selection ---
        model_selection_frame = ttk.Frame(options_outer_frame)
        model_selection_frame.pack(fill=tk.X, pady=(0,5)) # Use pack for this sub-frame

        self.model_label = ttk.Label(model_selection_frame, text="Transcription Model:")
        self.model_label.pack(side=tk.LEFT, padx=(0,5), pady=5)

        self.model_var = tk.StringVar()
        self.model_options = {
            "tiny": "Tiny: Fastest, lowest accuracy, ~39M params. Good for quick tests.",
            "base": "Base: Faster, better accuracy than tiny, ~74M params.",
            "small": "Small: Balanced speed and accuracy, ~244M params.",
            "medium": "Medium: Slower, good accuracy, ~769M params.",
            "large (recommended)": "Large (v3): Slowest, highest accuracy, ~1550M params. Recommended for best results.",
            "turbo": "Turbo (uses 'small'): A faster option, currently maps to 'small' model for broader compatibility."
        }
        
        self.model_dropdown = ttk.Combobox(model_selection_frame, textvariable=self.model_var, 
                                           values=list(self.model_options.keys()), state="readonly", width=25)
        self.model_dropdown.set("large (recommended)") # Default selection
        self.model_dropdown.pack(side=tk.LEFT, padx=5, pady=5)
        self.model_dropdown.bind("<<ComboboxSelected>>", self.show_model_tooltip)
        self.model_dropdown.bind("<Enter>", self.show_model_tooltip_on_hover)
        self.model_dropdown.bind("<Leave>", self.hide_model_tooltip_on_hover)
        
        self.model_tooltip_label = ttk.Label(model_selection_frame, text="", wraplength=300, foreground="grey")
        self.model_tooltip_label.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
        self.show_model_tooltip() # Show initial tooltip

        # --- Other Processing Options (Diarization, Timestamps) ---
        checkbox_options_frame = ttk.Frame(options_outer_frame)
        checkbox_options_frame.pack(fill=tk.X, pady=(5,0))

        self.enable_diarization_var = tk.BooleanVar(value=True)
        self.diarization_checkbutton = ttk.Checkbutton(checkbox_options_frame, text="Enable Speaker Diarization", variable=self.enable_diarization_var)
        self.diarization_checkbutton.pack(side=tk.LEFT, padx=10, pady=5)
        
        self.include_timestamps_var = tk.BooleanVar(value=True)
        self.timestamps_checkbutton = ttk.Checkbutton(checkbox_options_frame, text="Include Timestamps in Output", 
                                                      variable=self.include_timestamps_var, command=self._toggle_end_time_option)
        self.timestamps_checkbutton.pack(side=tk.LEFT, padx=10, pady=5)

        self.include_end_times_var = tk.BooleanVar(value=False) # Default to False (start time only if timestamps active)
        self.end_times_checkbutton = ttk.Checkbutton(checkbox_options_frame, text="Include End Times", 
                                                     variable=self.include_end_times_var, state=tk.DISABLED)
        self.end_times_checkbutton.pack(side=tk.LEFT, padx=(0,10), pady=5)
        self._toggle_end_time_option() # Set initial state

        # --- Processing Button ---
        self.process_button = ttk.Button(root, text="Start Processing", command=self.start_processing_callback)
        self.process_button.grid(row=3, column=0, columnspan=3, padx=5, pady=10, sticky="ew")

        # --- Progress Bar and Status Label ---
        progress_status_frame = ttk.Frame(root)
        progress_status_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.status_label = ttk.Label(progress_status_frame, text="Status: Idle")
        self.status_label.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.progress_bar = ttk.Progressbar(progress_status_frame, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(5,0))
        
        progress_status_frame.columnconfigure(0, weight=1)


        # --- Output Area ---
        self.text_area_font = ('Helvetica', 12)
        output_frame = ttk.LabelFrame(root, text="Processed Output (Last File / Summary)", padding=(10,5)) #
        output_frame.grid(row=5, column=0, columnspan=3, padx=5, pady=5, sticky="nsew") #

        self.output_text_area = tk.Text(output_frame, height=15, width=70, wrap=tk.WORD,
                                        font=self.text_area_font,
                                        background="white",       # <--- ADD THIS LINE
                                        foreground="black",       # <--- ADD THIS LINE
                                        insertbackground="black") # <--- ADD THIS (Cursor color)
        self.output_scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output_text_area.yview) #
        self.output_text_area.configure(yscrollcommand=self.output_scrollbar.set) #
        
        self.output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y) #
        self.output_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True) #
        self.output_text_area.config(state=tk.DISABLED) #
        
        output_frame.columnconfigure(0, weight=1) #
        output_frame.rowconfigure(0, weight=1) #

        # --- Correction Window Button ---
        self.correction_button = ttk.Button(root, text="Transcript Correction (Last Successful)", command=self.open_correction_window_callback)
        self.correction_button.grid(row=6, column=0, columnspan=3, padx=5, pady=10, sticky="ew")

        root.columnconfigure(0, weight=1)
        root.rowconfigure(5, weight=1)

        self.elements_to_disable_during_processing = [
            self.browse_button, self.process_button, # audio_file_entry is already disabled for direct input
            self.token_entry, self.save_token_button, self.correction_button,
            self.diarization_checkbutton, self.timestamps_checkbutton,
            self.model_dropdown, self.end_times_checkbutton
        ]
        self.save_token_callback = None
        self.model_hover_tooltip = None # For hover tooltip on combobox itself

    def show_model_tooltip(self, event=None):
        selected_model_key = self.model_var.get()
        tooltip_text = self.model_options.get(selected_model_key, "Select a model to see details.")
        self.model_tooltip_label.config(text=tooltip_text)

    def show_model_tooltip_on_hover(self, event=None):
        # This tooltip is for when hovering over the Combobox itself
        selected_model_key = self.model_var.get()
        tooltip_text = self.model_options.get(selected_model_key, "Select a model.")
        
        # Simple delay to avoid flickering if mouse moves quickly over options
        if hasattr(self, '_tooltip_after_id'):
            self.root.after_cancel(self._tooltip_after_id)

        self._tooltip_after_id = self.root.after(500, lambda: self._display_hover_tooltip(tooltip_text))
        
    def _display_hover_tooltip(self, tooltip_text):
        if self.model_hover_tooltip:
            self.model_hover_tooltip.hide_tooltip()
        self.model_hover_tooltip = ToolTip(self.model_dropdown, tooltip_text)
        self.model_hover_tooltip.show_tooltip()


    def hide_model_tooltip_on_hover(self, event=None):
        if hasattr(self, '_tooltip_after_id'):
            self.root.after_cancel(self._tooltip_after_id)
            delattr(self, '_tooltip_after_id')
        if self.model_hover_tooltip:
            self.model_hover_tooltip.hide_tooltip()
            self.model_hover_tooltip = None

    def _toggle_end_time_option(self):
        if self.include_timestamps_var.get():
            self.end_times_checkbutton.config(state=tk.NORMAL)
        else:
            self.end_times_checkbutton.config(state=tk.DISABLED)
            self.include_end_times_var.set(False) # Uncheck if parent is unchecked

    def update_status_and_progress(self, status_text=None, progress_value=None):
        if status_text is not None:
            self.status_label.config(text=f"Status: {status_text}")
            logger.debug(f"UI Status Updated: {status_text}")
        if progress_value is not None:
            self.progress_bar['value'] = progress_value
            logger.debug(f"UI Progress Updated: {progress_value}%")
        self.root.update_idletasks()

    def set_save_token_callback(self, callback):
        self.save_token_callback = callback

    def save_token_ui(self):
        if self.save_token_callback:
            token = self.token_entry.get()
            self.save_token_callback(token)
            logger.info("Save token UI action triggered.")

    def load_token_ui(self, token):
        self.token_entry.delete(0, tk.END)
        if token:
            self.token_entry.insert(0, token)
        logger.info(f"Token loaded into UI: {'Present' if token else 'Empty/None'}")

    def disable_ui_for_processing(self):
        logger.debug("UI: Disabling UI elements for processing.")
        for element in self.elements_to_disable_during_processing:
            if hasattr(element, 'configure'):
                 element.configure(state=tk.DISABLED)
            elif hasattr(element, 'config'):
                 element.config(state=tk.DISABLED)
        # self.audio_file_entry is already disabled, no need to touch it here.

    def enable_ui_after_processing(self):
        logger.debug("UI: Enabling UI elements after processing.")
        for element in self.elements_to_disable_during_processing:
            if hasattr(element, 'configure'):
                 element.configure(state=tk.NORMAL)
            elif hasattr(element, 'config'):
                 element.config(state=tk.NORMAL)
        # Special handling for end_times_checkbutton based on timestamps_checkbutton state
        self._toggle_end_time_option()
        # self.audio_file_entry remains disabled for direct input.

    def update_audio_file_entry_display(self, file_paths: list):
        self.audio_file_entry.config(state=tk.NORMAL)
        self.audio_file_entry.delete(0, tk.END)
        if not file_paths:
            self.audio_file_entry.insert(0, "")
        elif len(file_paths) == 1:
            self.audio_file_entry.insert(0, file_paths[0])
        else:
            self.audio_file_entry.insert(0, f"{len(file_paths)} files selected")
        self.audio_file_entry.config(state=tk.DISABLED)


    def update_output_text(self, text_content: str):
        self.output_text_area.config(state=tk.NORMAL)
        self.output_text_area.delete("1.0", tk.END)
        self.output_text_area.insert(tk.END, text_content)
        self.output_text_area.config(state=tk.DISABLED)
        logger.debug(f"Output text area updated with content (first 100 chars): '{text_content[:100]}...'")

    def display_processed_output(self, output_file_path: str = None, processing_returned_empty: bool = False, is_batch_summary: bool = False, batch_summary_message: str = ""):
        logger.info(f"UI: Displaying results. Path: '{output_file_path}', Empty: {processing_returned_empty}, BatchSummary: {is_batch_summary}")
        try:
            if is_batch_summary:
                self.update_output_text(batch_summary_message)
                logger.info("UI: Displayed batch summary message.")
                return

            if processing_returned_empty:
                self.update_output_text("No speech was detected or transcribed from the audio file, or the processing yielded no usable segments.")
                logger.info("UI: Displayed 'no speech/segments' message.")
                return

            if not output_file_path: # Should only happen for single file error before save or cancelled save
                msg_to_show = ("No output file path provided to display results. "
                               "Content might have been shown directly if save was cancelled or failed, or an error occurred before saving.")
                logger.warning(f"UI: {msg_to_show}")
                # self.update_output_text(msg_to_show) # Avoid overwriting potentially direct error text
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
                           "The save step might have failed or the path is incorrect. ")
            self.update_output_text(msg_to_show)
        except Exception as e:
            logger.exception("UI: An unexpected error occurred during display_processed_output.")
            err_msg = f"An error occurred while trying to display results from '{output_file_path}': {str(e)}"
            self.update_output_text(err_msg)