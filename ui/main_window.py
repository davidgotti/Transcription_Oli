# ui/main_window.py
import tkinter as tk
from tkinter import ttk, messagebox
import logging

# Import for tips
from utils.tips_data import get_tip # Assuming tips_data.py is in utils

logger = logging.getLogger(__name__)

class ToolTip:
    """
    Create a tooltip for a given widget with show/hide delays to prevent flickering.
    """
    def __init__(self, widget, text, wraplength=200, show_delay=500, hide_delay=100):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.show_delay = show_delay  # milliseconds
        self.hide_delay = hide_delay  # milliseconds
        self.tooltip_window = None
        self._show_after_id = None
        self._hide_after_id = None

        self._enter_binding = self.widget.bind("<Enter>", self.schedule_show_tooltip)
        self._leave_binding = self.widget.bind("<Leave>", self.schedule_hide_tooltip)
        # Also hide if the widget is destroyed (e.g., window closes)
        self._destroy_binding = self.widget.bind("<Destroy>", self.force_hide_tooltip)


    def schedule_show_tooltip(self, event=None):
        # If a hide is scheduled, cancel it because mouse re-entered
        if self._hide_after_id:
            self.widget.after_cancel(self._hide_after_id)
            self._hide_after_id = None
        
        # If a show is already scheduled, or tooltip is already visible, do nothing
        if self._show_after_id or self.tooltip_window:
            return
            
        # Schedule to show
        self._show_after_id = self.widget.after(self.show_delay, self._show_tooltip_actual)

    def _show_tooltip_actual(self):
        self._show_after_id = None # Clear the after ID as it has now run
        if self.tooltip_window or not self.text: # Do not show if already visible or no text
            return

        # Check if widget still exists
        try:
            if not self.widget.winfo_exists():
                return
        except tk.TclError: # Widget might have been destroyed
            return

        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 20

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(self.tooltip_window, text=self.text, justify=tk.LEFT,
                          background="#FFFFE0", relief="solid", borderwidth=1,
                          wraplength=self.wraplength, padding=(5,2))
        label.pack(ipadx=1)

    def schedule_hide_tooltip(self, event=None):
        # If a show is scheduled, cancel it because mouse left before it could show
        if self._show_after_id:
            self.widget.after_cancel(self._show_after_id)
            self._show_after_id = None
            
        # If a hide is already scheduled, or tooltip is not visible, do nothing
        if self._hide_after_id or not self.tooltip_window:
            return

        # Schedule to hide
        self._hide_after_id = self.widget.after(self.hide_delay, self._hide_tooltip_actual)

    def _hide_tooltip_actual(self):
        self._hide_after_id = None # Clear the after ID
        if self.tooltip_window:
            # Check if widget still exists before trying to access Toplevel parent
            try:
                if not self.widget.winfo_exists():
                    if self.tooltip_window.winfo_exists():
                        self.tooltip_window.destroy()
                    self.tooltip_window = None
                    return
            except tk.TclError:
                if self.tooltip_window and self.tooltip_window.winfo_exists():
                    self.tooltip_window.destroy()
                self.tooltip_window = None
                return

            if self.tooltip_window.winfo_exists():
                self.tooltip_window.destroy()
            self.tooltip_window = None
            
    def force_hide_tooltip(self, event=None):
        """Immediately hides the tooltip and cancels any pending actions. Used for <Destroy> or explicit unbind."""
        if self._show_after_id:
            self.widget.after_cancel(self._show_after_id)
            self._show_after_id = None
        if self._hide_after_id:
            self.widget.after_cancel(self._hide_after_id)
            self._hide_after_id = None
        if self.tooltip_window and self.tooltip_window.winfo_exists():
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def update_text(self, new_text):
        self.text = new_text
        # If tooltip is visible, hide it. It will re-appear with new text on next valid hover.
        if self.tooltip_window:
            self.force_hide_tooltip()

    def unbind(self):
        self.force_hide_tooltip() # Hide and cancel timers
        
        # Check if widget still exists before trying to unbind
        try:
            if self.widget.winfo_exists():
                if self._enter_binding:
                    self.widget.unbind("<Enter>", self._enter_binding)
                if self._leave_binding:
                    self.widget.unbind("<Leave>", self._leave_binding)
                if self._destroy_binding:
                    self.widget.unbind("<Destroy>", self._destroy_binding)
        except tk.TclError:
            # Widget might have already been destroyed
            pass
        finally:
            self._enter_binding = None
            self._leave_binding = None
            self._destroy_binding = None


class UI:
    def __init__(self, root, start_processing_callback, select_audio_file_callback,
                 open_correction_window_callback, config_manager_instance, initial_show_tips_state): # Added config_manager and initial state
        self.root = root
        self.config_manager = config_manager_instance # Store config_manager
        self.root.title("Audio Transcription and Diarization")

        self.start_processing_callback = start_processing_callback
        self.select_audio_file_callback = select_audio_file_callback
        self.open_correction_window_callback = open_correction_window_callback

        # --- Tips Feature ---
        self.show_tips_var = tk.BooleanVar(value=initial_show_tips_state)
        self.tips_widgets = {} # To store ToolTip instances: {widget_ref: ToolTip_instance}

        # Header frame for title and tips checkbox
        header_frame = ttk.Frame(root)
        header_frame.grid(row=0, column=0, columnspan=3, padx=5, pady=(5,0), sticky="ew")

        # App title or main label (optional, can be window title only)
        # app_title_label = ttk.Label(header_frame, text="Transcription & Diarization Tool", font=("Helvetica", 16, "bold"))
        # app_title_label.pack(side=tk.LEFT, padx=(5,0))

        header_frame.columnconfigure(0, weight=1) # Make the left cell (for title/spacer) expand

        self.tips_checkbox = ttk.Checkbutton(
            header_frame,
            text="Show Tips",
            variable=self.show_tips_var,
            command=self._on_toggle_tips
        )
        self.tips_checkbox.pack(side=tk.RIGHT, padx=5)
        self._add_tooltip_for_widget(self.tips_checkbox, "show_tips_checkbox_main")


        # --- Audio File Selection ---
        # Adjusted row to be 1 because header_frame is now row 0
        file_frame = ttk.LabelFrame(root, text="Audio File(s)", padding=(10,5))
        file_frame.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.audio_file_label = ttk.Label(file_frame, text="File Path(s):")
        self.audio_file_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.audio_file_entry = ttk.Entry(file_frame, width=50)
        self.audio_file_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.audio_file_entry.config(state=tk.DISABLED)

        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.select_audio_file_callback)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self._add_tooltip_for_widget(self.browse_button, "audio_file_browse")
        
        file_frame.columnconfigure(1, weight=1)

        # --- Processing Options Frame ---
        # Adjusted row to be 2
        self.options_outer_frame = ttk.LabelFrame(root, text="Processing Options", padding=(10, 5))
        self.options_outer_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=(5,0), sticky="ew")
        self.options_outer_frame.columnconfigure(0, weight=1)

        # --- Model Selection ---
        model_selection_frame = ttk.Frame(self.options_outer_frame)
        model_selection_frame.pack(fill=tk.X, pady=(0,5))

        self.model_label = ttk.Label(model_selection_frame, text="Transcription Model:")
        self.model_label.pack(side=tk.LEFT, padx=(0,5), pady=5)

        self.model_var = tk.StringVar()
        self.model_options = {
            "tiny": get_tip("main_window", "model_option_tiny") or "Tiny model",
            "base": get_tip("main_window", "model_option_base") or "Base model",
            "small": get_tip("main_window", "model_option_small") or "Small model",
            "medium": get_tip("main_window", "model_option_medium") or "Medium model",
            "large (recommended)": get_tip("main_window", "model_option_large") or "Large model",
            "turbo": get_tip("main_window", "model_option_turbo") or "Turbo model (uses 'small')"
        }
        
        self.model_dropdown = ttk.Combobox(model_selection_frame, textvariable=self.model_var,
                                           values=list(self.model_options.keys()), state="readonly", width=25)
        self.model_dropdown.set("large (recommended)")
        self.model_dropdown.pack(side=tk.LEFT, padx=5, pady=5)
        self.model_dropdown.bind("<<ComboboxSelected>>", self.show_model_description_label) # Changed from show_model_tooltip
        # General tooltip for the dropdown itself
        self._add_tooltip_for_widget(self.model_dropdown, "transcription_model_dropdown", wraplength=300)

        # This label shows description on selection, not hover for individual items.
        self.model_description_label = ttk.Label(model_selection_frame, text="", wraplength=300, foreground="grey")
        self.model_description_label.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
        self.show_model_description_label() # Initial call

        # --- Other Processing Options (Diarization, Timestamps, Auto Merge) ---
        self.checkbox_options_frame = ttk.Frame(self.options_outer_frame)
        self.checkbox_options_frame.pack(fill=tk.X, pady=(5,0))

        self.enable_diarization_var = tk.BooleanVar(value=False)
        self.diarization_checkbutton = ttk.Checkbutton(
            self.checkbox_options_frame,
            text="Enable Speaker Diarization",
            variable=self.enable_diarization_var,
            command=self._update_diarization_dependent_options
        )
        self.diarization_checkbutton.pack(side=tk.LEFT, padx=10, pady=5)
        self._add_tooltip_for_widget(self.diarization_checkbutton, "enable_diarization_checkbox")
        
        self.include_timestamps_var = tk.BooleanVar(value=True)
        self.timestamps_checkbutton = ttk.Checkbutton(
            self.checkbox_options_frame,
            text="Include Timestamps in Output",
            variable=self.include_timestamps_var,
            command=self._toggle_end_time_option
        )
        self.timestamps_checkbutton.pack(side=tk.LEFT, padx=10, pady=5)
        self._add_tooltip_for_widget(self.timestamps_checkbutton, "include_timestamps_checkbox")

        self.include_end_times_var = tk.BooleanVar(value=False)
        self.end_times_checkbutton = ttk.Checkbutton(
            self.checkbox_options_frame,
            text="Include End Times",
            variable=self.include_end_times_var,
            state=tk.DISABLED
        )
        self.end_times_checkbutton.pack(side=tk.LEFT, padx=(0,10), pady=5)
        self._add_tooltip_for_widget(self.end_times_checkbutton, "include_end_times_checkbox")
        self._toggle_end_time_option()

        self.auto_merge_var = tk.BooleanVar(value=False)
        self.auto_merge_checkbutton = ttk.Checkbutton(
            self.checkbox_options_frame,
            text="Automatically Merge Same Speakers",
            variable=self.auto_merge_var,
            state=tk.DISABLED
        )
        self.auto_merge_checkbutton.pack(side=tk.LEFT, padx=10, pady=5)
        self._add_tooltip_for_widget(self.auto_merge_checkbutton, "auto_merge_checkbox")

        # --- Hugging Face Token Input ---
        self.token_frame = ttk.LabelFrame(self.options_outer_frame, text="Hugging Face API Token", padding=(10, 5))
        # No .pack() or .grid() here yet

        self.token_required_label = ttk.Label(self.token_frame, text="(Required for Speaker Diarization)")
        self.token_required_label.grid(row=0, column=0, columnspan=3, padx=5, pady=(0,5), sticky="w")

        self.token_label = ttk.Label(self.token_frame, text="Token:")
        self.token_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        self.token_entry = ttk.Entry(self.token_frame, width=50)
        self.token_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self._add_tooltip_for_widget(self.token_entry, "huggingface_token_entry", wraplength=350)


        self.save_token_button = ttk.Button(self.token_frame, text="Save Token", command=self.save_token_ui)
        self.save_token_button.grid(row=1, column=2, padx=5, pady=5, sticky="w")
        self._add_tooltip_for_widget(self.save_token_button, "save_huggingface_token_button")
        
        self.token_frame.columnconfigure(1, weight=1)

        # --- Processing Button ---
        # Adjusted row to be 3
        self.process_button = ttk.Button(root, text="Start Processing", command=self.start_processing_callback)
        self.process_button.grid(row=3, column=0, columnspan=3, padx=5, pady=10, sticky="ew")
        self._add_tooltip_for_widget(self.process_button, "start_processing_button")

        # --- Progress Bar and Status Label ---
        # Adjusted row to be 4
        progress_status_frame = ttk.Frame(root)
        progress_status_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        self.status_label = ttk.Label(progress_status_frame, text="Status: Idle")
        self.status_label.pack(side=tk.TOP, fill=tk.X, expand=True)
        self._add_tooltip_for_widget(self.status_label, "status_label")

        self.progress_bar = ttk.Progressbar(progress_status_frame, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(side=tk.TOP, fill=tk.X, expand=True, pady=(5,0))
        self._add_tooltip_for_widget(self.progress_bar, "progress_bar")
        
        progress_status_frame.columnconfigure(0, weight=1)

        # --- Output Area ---
        # Adjusted row to be 5
        self.text_area_font = ('Helvetica', 12)
        output_frame = ttk.LabelFrame(root, text="Processed Output (Last File / Summary)", padding=(10,5))
        output_frame.grid(row=5, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")

        self.output_text_area = tk.Text(output_frame, height=15, width=70, wrap=tk.WORD,
                                        font=self.text_area_font,
                                        background="white",
                                        foreground="black",
                                        insertbackground="black")
        self.output_scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output_text_area.yview)
        self.output_text_area.configure(yscrollcommand=self.output_scrollbar.set)
        
        self.output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.output_text_area.config(state=tk.DISABLED)
        self._add_tooltip_for_widget(self.output_text_area, "output_text_area")
        
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        # --- Correction Window Button ---
        # Adjusted row to be 6
        self.correction_button = ttk.Button(root, text="Transcript Correction (Last Successful)", command=self.open_correction_window_callback)
        self.correction_button.grid(row=6, column=0, columnspan=3, padx=5, pady=10, sticky="ew")
        self._add_tooltip_for_widget(self.correction_button, "correction_window_button")

        root.columnconfigure(0, weight=1)
        root.rowconfigure(5, weight=1) # Output area gets resizing priority for height

        self.elements_to_disable_during_processing = [
            self.browse_button, self.process_button,
            self.token_entry, self.save_token_button, self.correction_button,
            self.diarization_checkbutton, self.timestamps_checkbutton,
            self.model_dropdown, self.end_times_checkbutton,
            self.auto_merge_checkbutton
        ]
        self.save_token_callback = None
        # self.model_hover_tooltip = None # Removed, model dropdown tooltip is now standard

        self._update_diarization_dependent_options()
        self._on_toggle_tips() # Apply initial tip state

    def _add_tooltip_for_widget(self, widget, tip_key: str, wraplength=250):
        """Adds a tooltip for a widget if tips are enabled."""
        if not widget: return
        tip_text = get_tip("main_window", tip_key)
        if tip_text:
            # If a tooltip already exists for this widget, update its text or unbind/rebind
            if widget in self.tips_widgets:
                self.tips_widgets[widget].unbind() # Remove old bindings
                del self.tips_widgets[widget]

            if self.show_tips_var.get():
                tooltip = ToolTip(widget, tip_text, wraplength=wraplength)
                self.tips_widgets[widget] = tooltip
        elif widget in self.tips_widgets: # No tip text found, but an old tooltip might exist
            self.tips_widgets[widget].unbind()
            del self.tips_widgets[widget]


    def _on_toggle_tips(self):
        """Handles the Show Tips checkbox action."""
        show = self.show_tips_var.get()
        self.config_manager.set_main_window_show_tips(show) # Save preference
        logger.info(f"Main window tips toggled: {'On' if show else 'Off'}")

        if show:
            # Re-initialize all tooltips as their state might have been cleared or not set
            self._setup_all_tooltips()
            self.show_model_description_label() # Ensure model description label is updated
        else:
            # Destroy all active tooltips
            for widget, tooltip_instance in list(self.tips_widgets.items()):
                tooltip_instance.unbind() # This also hides it
            self.tips_widgets.clear()
            # Clear model description label if tips are off and it was acting as a tip
            if hasattr(self, 'model_description_label'):
                 self.model_description_label.config(text="")


    def _setup_all_tooltips(self):
        """(Re)Initializes all tooltips based on current self.show_tips_var.get()."""
        # This method is called when tips are enabled.
        # It's a bit redundant with _add_tooltip_for_widget if called repeatedly,
        # but ensures all are fresh if needed.
        # For simplicity, _add_tooltip_for_widget will handle unbinding old ones.

        self._add_tooltip_for_widget(self.tips_checkbox, "show_tips_checkbox_main")
        self._add_tooltip_for_widget(self.browse_button, "audio_file_browse")
        self._add_tooltip_for_widget(self.model_dropdown, "transcription_model_dropdown", wraplength=300)
        self._add_tooltip_for_widget(self.diarization_checkbutton, "enable_diarization_checkbox")
        self._add_tooltip_for_widget(self.timestamps_checkbutton, "include_timestamps_checkbox")
        self._add_tooltip_for_widget(self.end_times_checkbutton, "include_end_times_checkbox")
        self._add_tooltip_for_widget(self.auto_merge_checkbutton, "auto_merge_checkbox")
        self._add_tooltip_for_widget(self.token_entry, "huggingface_token_entry", wraplength=350)
        self._add_tooltip_for_widget(self.save_token_button, "save_huggingface_token_button")
        self._add_tooltip_for_widget(self.process_button, "start_processing_button")
        self._add_tooltip_for_widget(self.status_label, "status_label")
        self._add_tooltip_for_widget(self.progress_bar, "progress_bar")
        self._add_tooltip_for_widget(self.output_text_area, "output_text_area")
        self._add_tooltip_for_widget(self.correction_button, "correction_window_button")
        # Add more calls here for other widgets that need tips

    def _update_diarization_dependent_options(self):
        diarization_enabled = self.enable_diarization_var.get()
        if diarization_enabled:
            self.token_frame.pack(fill=tk.X, pady=(5, 10), padx=5, after=self.checkbox_options_frame)
        else:
            self.token_frame.pack_forget()

        if diarization_enabled:
            self.auto_merge_checkbutton.config(state=tk.NORMAL)
        else:
            self.auto_merge_checkbutton.config(state=tk.DISABLED)
            self.auto_merge_var.set(False)

    def show_model_description_label(self, event=None): # Renamed from show_model_tooltip
        """Updates the dedicated label with the description of the selected model."""
        selected_model_key = self.model_var.get()
        description_text = self.model_options.get(selected_model_key, "Select a model to see details.")
        
        # Only show this description if tips are generally enabled, or always if preferred
        if self.show_tips_var.get(): # Or remove this condition to always show
            self.model_description_label.config(text=description_text)
        else:
            self.model_description_label.config(text="")


    # Removed show_model_tooltip_on_hover and hide_model_tooltip_on_hover
    # The general tooltip for model_dropdown is now handled by _add_tooltip_for_widget
    # and the description for the selected item is shown in model_description_label

    def _toggle_end_time_option(self):
        if self.include_timestamps_var.get():
            self.end_times_checkbutton.config(state=tk.NORMAL)
        else:
            self.end_times_checkbutton.config(state=tk.DISABLED)
            self.include_end_times_var.set(False)

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
        self.tips_checkbox.config(state=tk.DISABLED) # Disable tips checkbox during processing

    def enable_ui_after_processing(self):
        logger.debug("UI: Enabling UI elements after processing.")
        for element in self.elements_to_disable_during_processing:
            if hasattr(element, 'configure'):
                 element.configure(state=tk.NORMAL)
            elif hasattr(element, 'config'):
                 element.config(state=tk.NORMAL)
        self.tips_checkbox.config(state=tk.NORMAL) # Re-enable tips checkbox
        self._toggle_end_time_option()
        self._update_diarization_dependent_options()
        self._on_toggle_tips() # Re-apply tooltips if they are enabled

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

            if not output_file_path:
                msg_to_show = ("No output file path provided to display results. "
                               "Content might have been shown directly if save was cancelled or failed, or an error occurred before saving.")
                logger.warning(f"UI: {msg_to_show}")
                # Potentially show a default message in the text area if this path is taken.
                # self.update_output_text(msg_to_show) # Uncomment if desired to show this in UI
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