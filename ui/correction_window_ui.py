# ui/correction_window_ui.py
import tkinter as tk
from tkinter import ttk
import logging

logger = logging.getLogger(__name__)

class CorrectionWindowUI:
    def __init__(self, parent_tk_window,
                 browse_transcription_callback, browse_audio_callback,
                 load_files_callback, assign_speakers_callback, save_changes_callback,
                 toggle_play_pause_callback, seek_audio_callback, on_progress_bar_seek_callback,
                 jump_to_segment_start_callback,
                 text_area_double_click_callback, text_area_right_click_callback, text_area_left_click_edit_mode_callback,
                 on_speaker_click_callback, on_merge_click_callback):
        """
        Initializes and lays out the UI elements for the CorrectionWindow.
        Callbacks are passed in from the main CorrectionWindow class (via CorrectionCallbackHandler).
        """
        self.window = parent_tk_window # This is the Toplevel window instance

        # --- StringVars for Entry fields ---
        self.transcription_file_path_var = tk.StringVar()
        self.audio_file_path_var = tk.StringVar()
        self.audio_progress_var = tk.DoubleVar()

        # --- Colors and Styles ---
        self.text_area_bg_color = "#2E2E2E"
        self.text_area_fg_color = "white"
        self.editing_segment_bg_color = "#4A4A70" 
        self.timestamp_fg_color = "#AAAAAA"       
        self.active_highlight_bg = "yellow"       
        self.active_highlight_fg = "black"        

        # --- Main layout ---
        main_container_frame = ttk.Frame(self.window, padding="10")
        main_container_frame.pack(expand=True, fill=tk.BOTH)

        # --- Top Controls Frame (File Browse, Load, Assign, Save) ---
        top_controls_frame = ttk.Frame(main_container_frame)
        top_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 5))

        ttk.Label(top_controls_frame, text="Transcription File:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.transcription_entry = ttk.Entry(top_controls_frame, textvariable=self.transcription_file_path_var, width=40)
        self.transcription_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_transcription_button = ttk.Button(top_controls_frame, text="Browse...", command=browse_transcription_callback)
        self.browse_transcription_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(top_controls_frame, text="Audio File:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.audio_entry = ttk.Entry(top_controls_frame, textvariable=self.audio_file_path_var, width=40)
        self.audio_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_audio_button = ttk.Button(top_controls_frame, text="Browse...", command=browse_audio_callback)
        self.browse_audio_button.grid(row=1, column=2, padx=5, pady=5)

        self.load_files_button = ttk.Button(top_controls_frame, text="Load Files", command=load_files_callback)
        self.load_files_button.grid(row=0, column=3, rowspan=2, padx=(10,5), pady=5, sticky="nswe") 

        self.assign_speakers_button = ttk.Button(top_controls_frame, text="Assign Speakers", command=assign_speakers_callback, state=tk.DISABLED)
        self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5, sticky="ew")

        self.save_changes_button = ttk.Button(top_controls_frame, text="Save Changes", command=save_changes_callback, state=tk.DISABLED)
        self.save_changes_button.grid(row=1, column=4, padx=5, pady=5, sticky="ew")

        top_controls_frame.columnconfigure(1, weight=1) 
        top_controls_frame.columnconfigure(3, minsize=100)
        top_controls_frame.columnconfigure(4, minsize=120)

        # --- Audio Controls Frame ---
        audio_controls_frame = ttk.Frame(main_container_frame)
        audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,5))

        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=toggle_play_pause_callback, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=2)
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: seek_audio_callback(-5), state=tk.DISABLED)
        self.rewind_button.pack(side=tk.LEFT, padx=2)
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: seek_audio_callback(5), state=tk.DISABLED)
        self.forward_button.pack(side=tk.LEFT, padx=2)
        
        self.jump_to_segment_button = ttk.Button(audio_controls_frame, text="|< Jump to Seg Start (-1s)", command=jump_to_segment_start_callback)
        # This button will be packed/unpacked dynamically by CorrectionWindow logic
        
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=on_progress_bar_seek_callback, state=tk.DISABLED)
        self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000")
        self.current_time_label.pack(side=tk.LEFT, padx=5)

        # --- Transcription Text Area ---
        text_area_frame = ttk.Frame(main_container_frame)
        text_area_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        
        self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True, 
                                          background=self.text_area_bg_color, foreground=self.text_area_fg_color,
                                          insertbackground=self.text_area_fg_color) 
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview)
        self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._configure_text_tags()

        # Bind events that are handled by CorrectionCallbackHandler
        self.transcription_text.tag_bind("speaker_tag_style", "<Button-1>", on_speaker_click_callback)
        self.transcription_text.tag_bind("merge_tag_style", "<Button-1>", on_merge_click_callback)
        self.transcription_text.tag_bind("merge_tag_style", "<Enter>", lambda e: self.transcription_text.config(cursor="hand2"))
        self.transcription_text.tag_bind("merge_tag_style", "<Leave>", lambda e: self.transcription_text.config(cursor=""))

        self.transcription_text.bind("<Button-3>", text_area_right_click_callback)
        self.transcription_text.bind("<Double-1>", text_area_double_click_callback)
        self.transcription_text.bind("<Button-1>", text_area_left_click_edit_mode_callback) 

        self.transcription_text.config(state=tk.DISABLED) # Start as read-only

        # --- Context Menu (created by CorrectionWindow, but UI elements here) ---
        # The CorrectionWindow will create and manage the context_menu object itself,
        # as its commands will call methods in CorrectionCallbackHandler.

        logger.info("CorrectionWindowUI elements created.")

    def _configure_text_tags(self):
        """Configures all necessary tags for the transcription text area."""
        self.transcription_text.tag_configure("speaker_tag_style") 
        self.transcription_text.tag_configure("merge_tag_style", foreground="#7FFF00", underline=True, font=('TkDefaultFont', 9, 'bold'))
        self.transcription_text.tag_configure("timestamp_tag_style", foreground=self.timestamp_fg_color)
        self.transcription_text.tag_configure("no_timestamp_tag_style", foreground=self.timestamp_fg_color, font=('TkDefaultFont', 9, 'italic'))
        self.transcription_text.tag_configure("active_text_highlight", foreground=self.active_highlight_fg, background=self.active_highlight_bg)
        self.transcription_text.tag_configure("inactive_text_default", foreground=self.text_area_fg_color, background=self.text_area_bg_color)
        self.transcription_text.tag_configure("editing_active_segment_text", background=self.editing_segment_bg_color)
        logger.debug("Text area tags configured.")

    def set_play_pause_button_text(self, text: str):
        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
            self.play_pause_button.config(text=text)

    def update_time_labels_display(self, current_time_str: str, total_time_str: str):
        if hasattr(self, 'current_time_label') and self.current_time_label.winfo_exists():
            self.current_time_label.config(text=f"{current_time_str} / {total_time_str}")

    def update_audio_progress_bar_display(self, value: float, max_value: float | None = None):
        if hasattr(self, 'audio_progress_bar') and self.audio_progress_bar.winfo_exists():
            if max_value is not None:
                 self.audio_progress_bar.config(to=max_value)
            self.audio_progress_var.set(value)

    def set_widgets_state(self, widgets: list, state: str):
        """Sets the state (tk.NORMAL or tk.DISABLED) for a list of widgets."""
        for widget in widgets:
            if widget and hasattr(widget, 'winfo_exists') and widget.winfo_exists():
                widget.config(state=state)

    def get_transcription_file_path(self) -> str:
        return self.transcription_file_path_var.get()

    def get_audio_file_path(self) -> str:
        return self.audio_file_path_var.get()

