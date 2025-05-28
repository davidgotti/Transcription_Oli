# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
import re
import queue # Required for checking queue.Empty

logger = logging.getLogger(__name__)

from .audio_player import AudioPlayer

class CorrectionWindow:
    def __init__(self, parent_root):
        self.parent_root = parent_root
        self.window = tk.Toplevel(parent_root)
        self.window.title("Transcription Correction Tool")
        self.window.geometry("800x600")

        self.transcription_file_path = tk.StringVar()
        self.audio_file_path = tk.StringVar()
        self.audio_player = None
        self.audio_player_update_queue = None 

        self.segments = []
        self.speaker_map = {} 
        self.unique_speaker_labels = set() 

        self.currently_highlighted_text_seg_id = None 
        self.edit_mode_active = False
        self.editing_segment_id = None
        self.editing_segment_text_start_index = None
        self.right_clicked_segment_id = None

        self.segment_pattern_with_ts = re.compile(
            r"\[(\d{2}:\d{2}\.\d{3})\s*-\s*(\d{2}:\d{2}\.\d{3})\]\s*([^:]+?):\s*(.*)"
        )
        self.segment_pattern_no_ts = re.compile(
            r"^\s*([^:]+?):\s*(.*)" # Speaker: Text
        )

        # --- Main layout ---
        logger.debug("CorrectionWindow __init__: Creating main_container_frame.")
        main_container_frame = ttk.Frame(self.window, padding="10")
        main_container_frame.pack(expand=True, fill=tk.BOTH)

        # --- Top Controls Frame (File Browse, Load, Assign, Save) ---
        logger.debug("CorrectionWindow __init__: Creating top_controls_frame.")
        top_controls_frame = ttk.Frame(main_container_frame)
        top_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 5))

        ttk.Label(top_controls_frame, text="Transcription File:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.transcription_entry = ttk.Entry(top_controls_frame, textvariable=self.transcription_file_path, width=40)
        self.transcription_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_transcription_button = ttk.Button(top_controls_frame, text="Browse...", command=self._browse_transcription_file)
        self.browse_transcription_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(top_controls_frame, text="Audio File:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.audio_entry = ttk.Entry(top_controls_frame, textvariable=self.audio_file_path, width=40)
        self.audio_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_audio_button = ttk.Button(top_controls_frame, text="Browse...", command=self._browse_audio_file)
        self.browse_audio_button.grid(row=1, column=2, padx=5, pady=5)

        self.load_files_button = ttk.Button(top_controls_frame, text="Load Files", command=self._load_files)
        self.load_files_button.grid(row=0, column=3, rowspan=2, padx=(10,5), pady=5, sticky="nswe") 

        self.assign_speakers_button = ttk.Button(top_controls_frame, text="Assign Speakers", command=self._open_assign_speakers_dialog, state=tk.DISABLED)
        self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5, sticky="ew")

        self.save_changes_button = ttk.Button(top_controls_frame, text="Save Changes", command=self._save_changes, state=tk.DISABLED)
        self.save_changes_button.grid(row=1, column=4, padx=5, pady=5, sticky="ew")

        top_controls_frame.columnconfigure(1, weight=1) 
        top_controls_frame.columnconfigure(3, minsize=100)
        top_controls_frame.columnconfigure(4, minsize=120)


        # --- Audio Controls Frame ---
        logger.debug("CorrectionWindow __init__: Creating audio_controls_frame.")
        audio_controls_frame = ttk.Frame(main_container_frame)
        audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,5))

        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=self._toggle_play_pause, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=2)
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: self._seek_audio(-5), state=tk.DISABLED)
        self.rewind_button.pack(side=tk.LEFT, padx=2)
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: self._seek_audio(5), state=tk.DISABLED)
        self.forward_button.pack(side=tk.LEFT, padx=2)

        self.jump_to_segment_button = ttk.Button(audio_controls_frame, text="|< Jump to Seg Start (-1s)", command=self._jump_to_segment_start_action)
        
        self.audio_progress_var = tk.DoubleVar()
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=self._on_progress_bar_seek, state=tk.DISABLED)
        self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000")
        self.current_time_label.pack(side=tk.LEFT, padx=5)

        # --- Transcription Text Area ---
        logger.debug("CorrectionWindow __init__: Creating text_area_frame.")
        text_area_frame = ttk.Frame(main_container_frame)
        text_area_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        
        # Explicitly set desired dark theme colors
        self.text_area_bg_color = "#2E2E2E"  # Dark Gray
        self.text_area_fg_color = "white"    # White
        logger.debug(f"CorrectionWindow __init__: Using hardcoded text area colors: BG='{self.text_area_bg_color}', FG='{self.text_area_fg_color}'")

        self.editing_segment_bg_color = "#4A4A70" # Darker purple for editing
        self.timestamp_fg_color = "#AAAAAA"       # Lighter gray for timestamps
        self.active_highlight_bg = "yellow"       # Keep yellow for active segment highlight
        self.active_highlight_fg = "black"        # Black text on yellow highlight for contrast

        self.transcription_text = None 
        try:
            logger.debug(f"CorrectionWindow __init__: Attempting to create self.transcription_text widget with BG='{self.text_area_bg_color}', FG='{self.text_area_fg_color}'.")
            self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True, 
                                              background=self.text_area_bg_color, foreground=self.text_area_fg_color,
                                              insertbackground=self.text_area_fg_color) # Cursor color same as text
            logger.info("CorrectionWindow __init__: self.transcription_text widget CREATED successfully.")
        except Exception as e_text_widget:
            logger.critical(f"CorrectionWindow __init__: CRITICAL ERROR creating self.transcription_text widget: {e_text_widget}", exc_info=True)
            messagebox.showerror("UI Initialization Error", 
                                 f"Failed to create the main text area component.\nError: {e_text_widget}\n\nThe correction window may not function correctly.",
                                 parent=self.window if hasattr(self, 'window') else parent_root)
            return 

        if self.transcription_text is None:
            logger.critical("CorrectionWindow __init__: self.transcription_text is None after creation attempt. Window will likely be unusable.")
            return


        logger.debug("CorrectionWindow __init__: Configuring scrollbar for transcription_text.")
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview)
        self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        logger.debug("CorrectionWindow __init__: Configuring text area tags.")
        self.transcription_text.tag_configure("speaker_tag_style") # Default, no special style needed if text fg is white
        self.transcription_text.tag_configure("merge_tag_style", foreground="#7FFF00", underline=True, font=('TkDefaultFont', 9, 'bold')) # Chartreuse for merge
        self.transcription_text.tag_configure("timestamp_tag_style", foreground=self.timestamp_fg_color)
        self.transcription_text.tag_configure("no_timestamp_tag_style", foreground=self.timestamp_fg_color, font=('TkDefaultFont', 9, 'italic')) # Italic for placeholder
        self.transcription_text.tag_configure("active_text_highlight", foreground=self.active_highlight_fg, background=self.active_highlight_bg) 
        self.transcription_text.tag_configure("inactive_text_default", foreground=self.text_area_fg_color, background=self.text_area_bg_color)
        self.transcription_text.tag_configure("editing_active_segment_text", background=self.editing_segment_bg_color) 

        logger.debug("CorrectionWindow __init__: Binding text area events.")
        self.transcription_text.tag_bind("speaker_tag_style", "<Button-1>", self._on_speaker_click)
        self.transcription_text.tag_bind("merge_tag_style", "<Button-1>", self._on_merge_click)
        self.transcription_text.tag_bind("merge_tag_style", "<Enter>", lambda e, ts=self: ts.transcription_text.config(cursor="hand2"))
        self.transcription_text.tag_bind("merge_tag_style", "<Leave>", lambda e, ts=self: ts.transcription_text.config(cursor=""))

        self.context_menu = tk.Menu(self.transcription_text, tearoff=0)
        self.context_menu.add_command(label="Edit Segment Text", command=self._edit_segment_text_action_from_menu)
        # Add "Set Timestamps" to context menu, initially disabled
        self.context_menu.add_command(label="Set/Edit Timestamps", command=self._set_segment_timestamps_action_menu, state=tk.DISABLED)
        self.context_menu.add_command(label="Remove Segment", command=self._remove_segment_action)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Change Speaker for this Segment", command=self._change_segment_speaker_action_menu)


        self.transcription_text.bind("<Button-3>", self._show_context_menu)
        self.transcription_text.bind("<Double-1>", self._double_click_edit_action)
        self.transcription_text.bind("<Button-1>", self._handle_click_during_edit_mode) 

        self.transcription_text.config(state=tk.DISABLED) 

        logger.debug("CorrectionWindow __init__: Setting up window close protocol and bindings.")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda e: self._save_changes()) 

        logger.debug("CorrectionWindow __init__: Starting audio player queue poller.")
        self.window.after(100, self._poll_audio_player_queue)
        logger.info("CorrectionWindow __init__: Initialization complete.")


    def _time_str_to_seconds(self, time_str: str) -> float | None: # Can return None if parsing fails
        if not time_str or not isinstance(time_str, str): return None
        try:
            m_part, s_ms_part = time_str.split(':')
            s_part, ms_part = s_ms_part.split('.')
            return int(m_part) * 60 + int(s_part) + int(ms_part) / 1000.0
        except ValueError:
            logger.error(f"Invalid time string format encountered: {time_str}")
            return None # Return None on parsing error
    
    def _seconds_to_time_str(self, total_seconds: float | None) -> str:
        if total_seconds is None:
            return "--:--.---" # Placeholder for None times
        if not isinstance(total_seconds, (int, float)) or total_seconds < 0: 
            logger.warning(f"Invalid total_seconds value for formatting: {total_seconds}. Defaulting to 0.")
            total_seconds = 0.0
        
        total_seconds_abs = abs(total_seconds) 
        m, s_rem_float = divmod(total_seconds_abs, 60)
        s_rem_int = int(s_rem_float)
        ms = int((s_rem_float - s_rem_int) * 1000)
        
        sign = "-" if total_seconds < 0 else "" 
        return f"{sign}{int(m):02d}:{s_rem_int:02d}.{ms:03d}"


    def _browse_transcription_file(self):
        if self.edit_mode_active: return
        fp = filedialog.askopenfilename(title="Select Transcription File", filetypes=[("Text files", "*.txt"), ("All files", "*.*")], parent=self.window)
        if fp:
            self.transcription_file_path.set(fp)
            logger.info(f"Transcription file selected: {fp}")

    def _browse_audio_file(self):
        if self.edit_mode_active: return
        fp = filedialog.askopenfilename(title="Select Audio File", filetypes=[("Audio files", "*.wav *.mp3 *.flac *.m4a"), ("All files", "*.*")], parent=self.window)
        if fp:
            self.audio_file_path.set(fp)
            logger.info(f"Audio file selected: {fp}")
            
    def _handle_audio_player_error(self, error_message):
        logger.error(f"AudioPlayer reported error: {error_message}")
        messagebox.showerror("Audio Player Error", error_message, parent=self.window)
        self._disable_audio_controls()
        if self.audio_player: 
            self.audio_player.stop_resources() 
            self.audio_player = None
        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
            self.play_pause_button.config(text="Play")


    def _load_files(self):
        if self.edit_mode_active:
            messagebox.showwarning("Action Blocked", "Please exit text edit mode before loading new files.", parent=self.window)
            return

        txt_p = self.transcription_file_path.get()
        aud_p = self.audio_file_path.get()

        if not (txt_p and os.path.exists(txt_p)):
            messagebox.showerror("File Error", "Please select a valid transcription file.", parent=self.window)
            return
        if not (aud_p and os.path.exists(aud_p)):
            messagebox.showerror("File Error", "Please select a valid audio file.", parent=self.window)
            return
        
        if not hasattr(self, 'transcription_text') or self.transcription_text is None:
            logger.error("_load_files: self.transcription_text is not initialized. Aborting load.")
            messagebox.showerror("UI Error", "Cannot load files: Text display area is not ready.", parent=self.window)
            return

        try:
            if self.audio_player:
                self.audio_player.stop_resources()
                self.audio_player = None
            if self.audio_player_update_queue: 
                while not self.audio_player_update_queue.empty():
                    try: self.audio_player_update_queue.get_nowait()
                    except queue.Empty: break
                self.audio_player_update_queue = None

            self.segments = [] 
            self.speaker_map = {} 
            self.unique_speaker_labels = set() 
            
            with open(txt_p, 'r', encoding='utf-8') as f: 
                lines = f.readlines()
            
            parsing_successful = self._parse_transcription_text_to_segments(lines)
            
            if not parsing_successful and not self.segments : 
                 messagebox.showerror("Load Error", "Failed to parse any valid segments from the transcription file. Please check the file format and logs.", parent=self.window)
                 self._disable_audio_controls()
                 return 
            
            self._render_segments_to_text_area() 
            
            logger.info(f"Loading audio file: {aud_p}")
            self.audio_player = AudioPlayer(aud_p, on_error_callback=self._handle_audio_player_error)
            
            if not self.audio_player.is_ready():
                logger.error("Audio player failed to initialize after file selection.")
                return 

            self.audio_player_update_queue = self.audio_player.get_update_queue()
            
            if self.audio_player.frame_rate > 0:
                self.audio_progress_bar.config(to=self.audio_player.total_frames / self.audio_player.frame_rate)
                self._update_audio_progress_bar(self.audio_player.current_frame / self.audio_player.frame_rate)
            else: 
                self.audio_progress_bar.config(to=100) 
                self._update_audio_progress_bar(0)
            self._update_time_labels(self.audio_player.current_frame) 

            for btn in [self.play_pause_button, self.rewind_button, self.forward_button]: btn.config(state=tk.NORMAL)
            self.save_changes_button.config(state=tk.NORMAL) 
            self.play_pause_button.config(text="Play")
            self.audio_progress_bar.config(state=tk.NORMAL)
            self.assign_speakers_button.config(state=tk.NORMAL if self.unique_speaker_labels else tk.DISABLED)
            self.load_files_button.config(text="Reload Files") 
            logger.info("Files loaded successfully into Correction Window.")
            
        except Exception as e: 
            logger.exception("Error during _load_files operation in CorrectionWindow.")
            messagebox.showerror("Load Error", f"An unexpected error occurred during file loading: {e}", parent=self.window)
            if hasattr(self, 'transcription_text') and self.transcription_text is not None:
                 self.transcription_text.config(state=tk.DISABLED)
            self._disable_audio_controls()


    def _parse_transcription_text_to_segments(self, text_lines: list[str]) -> bool:
        self.segments.clear()
        self.unique_speaker_labels.clear()
        malformed_count = 0
        id_counter = 0
        
        for i, line_content_raw in enumerate(text_lines):
            line_content = line_content_raw.strip()
            if not line_content: continue 

            match_with_ts = self.segment_pattern_with_ts.match(line_content)
            
            start_time_s, end_time_s = 0.0, 0.0 # Default for lines without valid TS
            speaker_raw, text_content = None, None
            has_timestamps_in_line = False

            if match_with_ts:
                start_time_str, end_time_str, speaker_raw_match, text_content_match = match_with_ts.groups()
                parsed_start_s = self._time_str_to_seconds(start_time_str)
                parsed_end_s = self._time_str_to_seconds(end_time_str)

                if parsed_start_s is not None and parsed_end_s is not None and parsed_start_s < parsed_end_s:
                    start_time_s = parsed_start_s
                    end_time_s = parsed_end_s
                    speaker_raw = speaker_raw_match
                    text_content = text_content_match
                    has_timestamps_in_line = True
                    logger.debug(f"Line {i+1} parsed WITH valid timestamps: Start={start_time_s:.3f}, End={end_time_s:.3f}, Spk='{speaker_raw}', Txt='{text_content[:20]}...'")
                else:
                    logger.warning(f"Line {i+1} matched timestamp pattern but times were invalid/malformed: '{start_time_str}', '{end_time_str}'. Treating as no-timestamp line.")
                    # Fall through to no-timestamp parsing logic
            
            if not has_timestamps_in_line: # Try parsing as no-timestamp line
                match_no_ts = self.segment_pattern_no_ts.match(line_content)
                if match_no_ts:
                    speaker_raw, text_content = match_no_ts.groups()
                    has_timestamps_in_line = False # Explicitly false
                    # start_time_s and end_time_s remain 0.0 as default
                    logger.warning(f"Line {i+1} parsed WITHOUT timestamps. Speaker='{speaker_raw}', Text='{text_content[:30]}...'. Times set to 0.0.")
                else:
                    logger.warning(f"Line {i+1} does not match any segment pattern: '{line_content}'")
                    malformed_count += 1
                    continue
            
            try:
                if speaker_raw is None or text_content is None:
                    logger.error(f"Critical parsing error: speaker_raw or text_content is None for line {i+1}. Line: '{line_content}'")
                    malformed_count += 1
                    continue

                text_tag_id = f"text_content_{id_counter}"
                segment = {
                    "id": f"seg_{id_counter}",
                    "start_time": start_time_s, # Use parsed or default 0.0
                    "end_time": end_time_s,     # Use parsed or default 0.0
                    "speaker_raw": speaker_raw.strip(),
                    "text": text_content.strip(),
                    "original_line_num": i + 1,
                    "text_tag_id": text_tag_id,
                    "has_timestamps": has_timestamps_in_line 
                }
                
                self.segments.append(segment)
                self.unique_speaker_labels.add(segment['speaker_raw'])
                id_counter += 1
            except Exception as ex: # Catch any other unexpected error during segment creation
                 logger.exception(f"Unexpected error creating segment object on line {i+1}: '{line_content}'")
                 malformed_count += 1
        
        if not self.segments and any(l.strip() for l in text_lines): 
            logger.error("Parsing failed: No valid segments could be parsed from the transcription file although it contained text.")
            return False 
        
        if malformed_count > 0 and self.segments: 
             messagebox.showwarning("Parsing Issues", f"{malformed_count} line(s) in the transcription file could not be parsed correctly and were skipped. Check logs for details.", parent=self.window)
        
        return True 


    def _render_segments_to_text_area(self):
        if self.edit_mode_active: 
            self._exit_edit_mode(save_changes=False) 

        if not hasattr(self, 'transcription_text') or self.transcription_text is None:
            logger.critical("CRITICAL: _render_segments_to_text_area called but self.transcription_text is not defined or is None!")
            messagebox.showerror("Internal UI Error", "Text area component is missing. Cannot render segments.", parent=self.window)
            return

        self.transcription_text.config(state=tk.NORMAL)
        self.transcription_text.delete("1.0", tk.END)
        self.currently_highlighted_text_seg_id = None 
        
        if not self.segments:
            self.transcription_text.insert(tk.END, "No transcription data loaded or all lines were unparsable.\nPlease load a valid transcription and audio file.")
            self.transcription_text.config(state=tk.DISABLED)
            return
        
        for idx, seg in enumerate(self.segments):
            required_keys = ["id", "start_time", "end_time", "speaker_raw", "text", "text_tag_id", "has_timestamps"]
            if not all(key in seg for key in required_keys):
                logger.warning(f"Segment at index {idx} is malformed (missing keys), skipping rendering: {seg.get('id', 'Unknown ID')}")
                continue
            
            line_start_index = self.transcription_text.index(tk.END + "-1c linestart") 
            display_speaker = self.speaker_map.get(seg['speaker_raw'], seg['speaker_raw'])
            
            prefix_text, merge_tag_tuple = "  ", () 
            if idx > 0 and self.segments[idx-1].get("speaker_raw") == seg["speaker_raw"]:
                prefix_text, merge_tag_tuple = "+ ", ("merge_tag_style", seg['id']) 
            self.transcription_text.insert(tk.END, prefix_text, merge_tag_tuple)
            
            if seg.get("has_timestamps", False):
                timestamp_str = f"[{self._seconds_to_time_str(seg['start_time'])} - {self._seconds_to_time_str(seg['end_time'])}] "
                self.transcription_text.insert(tk.END, timestamp_str, ("timestamp_tag_style", seg['id']))
            else:
                self.transcription_text.insert(tk.END, "[No Timestamps] ", ("no_timestamp_tag_style", seg['id']))

            
            speaker_tag_start = self.transcription_text.index(tk.END)
            self.transcription_text.insert(tk.END, display_speaker, ("speaker_tag_style", seg['id']))
            speaker_tag_end = self.transcription_text.index(tk.END)
            self.transcription_text.tag_add(f"speaker_{seg['id']}", speaker_tag_start, speaker_tag_end)

            self.transcription_text.insert(tk.END, ": ")
            
            text_content_start_index = self.transcription_text.index(tk.END)
            self.transcription_text.insert(tk.END, seg['text'], ("inactive_text_default", seg["text_tag_id"]))
            
            self.transcription_text.insert(tk.END, "\n")
            line_end_index = self.transcription_text.index(tk.END + "-1c lineend") 
            
            self.transcription_text.tag_add(seg['id'], line_start_index, line_end_index)
            
        self.transcription_text.config(state=tk.DISABLED)


    def _toggle_ui_for_edit_mode(self, disable: bool):
        new_state = tk.DISABLED if disable else tk.NORMAL
        
        self.browse_transcription_button.config(state=new_state)
        self.browse_audio_button.config(state=new_state)
        self.load_files_button.config(state=new_state)
        self.assign_speakers_button.config(state=new_state if not disable and self.unique_speaker_labels else tk.DISABLED)
        self.save_changes_button.config(state=new_state)

        is_segment_sel = bool(self.right_clicked_segment_id) and not disable
        segment_has_ts = False
        if is_segment_sel:
            clicked_seg = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
            if clicked_seg:
                segment_has_ts = clicked_seg.get("has_timestamps", False)


        if disable: 
            self.context_menu.entryconfig("Edit Segment Text", state=tk.DISABLED)
            self.context_menu.entryconfig("Set/Edit Timestamps", state=tk.DISABLED)
            self.context_menu.entryconfig("Remove Segment", state=tk.DISABLED)
            self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.DISABLED)
        else: 
            self.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
            # Enable "Set/Edit Timestamps" only if a segment is selected (regardless of whether it currently has timestamps)
            self.context_menu.entryconfig("Set/Edit Timestamps", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
            self.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
            self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)


    def _enter_edit_mode(self, segment_id_to_edit: str):
        if self.edit_mode_active and self.editing_segment_id == segment_id_to_edit:
            return 
        if self.edit_mode_active: 
            self._exit_edit_mode(save_changes=True) 

        target_segment = next((s for s in self.segments if s["id"] == segment_id_to_edit), None)
        if not target_segment:
            logger.warning(f"Attempted to edit non-existent segment ID: {segment_id_to_edit}")
            return

        self.edit_mode_active = True
        self.editing_segment_id = segment_id_to_edit
        
        self.transcription_text.config(state=tk.NORMAL) 
        self._toggle_ui_for_edit_mode(disable=True) 
        
        text_content_tag_id = target_segment["text_tag_id"] 
        try:
            ranges = self.transcription_text.tag_ranges(text_content_tag_id)
            if ranges:
                self.editing_segment_text_start_index = ranges[0]
                
                self.transcription_text.tag_remove("inactive_text_default", self.editing_segment_text_start_index, ranges[1]) 
                self.transcription_text.tag_add("editing_active_segment_text", self.editing_segment_text_start_index, ranges[1]) 
                
                self.transcription_text.focus_set()
                self.transcription_text.mark_set(tk.INSERT, self.editing_segment_text_start_index)
                self.transcription_text.see(self.editing_segment_text_start_index)
            else:
                logger.error(f"Could not find text tag ranges for '{text_content_tag_id}' to start editing.")
                self._exit_edit_mode(save_changes=False); return 

        except tk.TclError:
            logger.exception(f"TclError applying editing tag for '{text_content_tag_id}'")
            self._exit_edit_mode(save_changes=False); return

        if target_segment.get("has_timestamps", False): 
            self.jump_to_segment_button.pack(side=tk.LEFT, padx=(5,0), before=self.audio_progress_bar)
        else:
            self.jump_to_segment_button.pack_forget()

        logger.info(f"Entered edit mode for segment: {self.editing_segment_id} (text tag: {text_content_tag_id})")


    def _exit_edit_mode(self, save_changes: bool = True):
        if not self.edit_mode_active or not self.editing_segment_id:
            return

        logger.info(f"Exiting edit mode for segment: {self.editing_segment_id}. Save: {save_changes}")
        
        original_segment = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)
        text_updated_needs_rerender = False

        if original_segment:
            text_content_tag_id = original_segment["text_tag_id"]
            try:
                current_ranges = self.transcription_text.tag_ranges(text_content_tag_id)
                if current_ranges:
                    self.transcription_text.tag_remove("editing_active_segment_text", current_ranges[0], current_ranges[1])
                    self.transcription_text.tag_add("inactive_text_default", current_ranges[0], current_ranges[1])

                    if save_changes:
                        modified_text = self.transcription_text.get(current_ranges[0], current_ranges[1]).strip()
                        if original_segment["text"] != modified_text:
                            original_segment["text"] = modified_text
                            text_updated_needs_rerender = True 
                            logger.info(f"Segment {self.editing_segment_id} updated text to: '{modified_text[:50]}...'")
                        else:
                            logger.info(f"Segment {self.editing_segment_id} text unchanged.")
                else: 
                    logger.warning(f"Could not find ranges for tag {text_content_tag_id} on exiting edit mode.")

            except tk.TclError:
                logger.warning(f"TclError handling tags for {text_content_tag_id} on exit.")
            except Exception as e:
                logger.exception(f"Error retrieving or updating segment text for {self.editing_segment_id}")
        
        self.jump_to_segment_button.pack_forget() 
        self.transcription_text.config(state=tk.DISABLED) 
        self._toggle_ui_for_edit_mode(disable=False) 
        
        self.edit_mode_active = False
        self.editing_segment_id = None
        self.editing_segment_text_start_index = None
        
        if text_updated_needs_rerender : 
             self._render_segments_to_text_area() 


    def _handle_click_during_edit_mode(self, event):
        if not self.edit_mode_active or not self.editing_segment_id:
            return 

        clicked_index_str = self.transcription_text.index(f"@{event.x},{event.y}")
        
        editing_seg = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)
        if not editing_seg:
            self._exit_edit_mode(save_changes=False); return 

        text_content_tag_id = editing_seg["text_tag_id"]
        try:
            tag_ranges = self.transcription_text.tag_ranges(text_content_tag_id)
            if tag_ranges:
                start_idx, end_idx = tag_ranges[0], tag_ranges[1]
                if self.transcription_text.compare(clicked_index_str, ">=", start_idx) and \
                   self.transcription_text.compare(clicked_index_str, "<", end_idx):
                    return 
            
            logger.debug("Clicked outside editable text area during edit mode. Saving and exiting.")
            self._exit_edit_mode(save_changes=True)

        except tk.TclError: 
            logger.warning(f"TclError checking click for tag {text_content_tag_id}, exiting edit mode.")
            self._exit_edit_mode(save_changes=False)
        except Exception as e:
            logger.exception(f"Error in _handle_click_during_edit_mode: {e}")
            self._exit_edit_mode(save_changes=False)


    def _double_click_edit_action(self, event):
        if self.edit_mode_active: 
            return 

        text_index = self.transcription_text.index(f"@{event.x},{event.y}")
        segment_id = self._get_segment_id_from_text_index(text_index) 
        if segment_id:
            logger.info(f"Double-clicked on segment: {segment_id}. Entering edit mode.")
            self._enter_edit_mode(segment_id)
            return "break" 


    def _edit_segment_text_action_from_menu(self):
        if not self.right_clicked_segment_id: return 
        
        if self.edit_mode_active and self.editing_segment_id == self.right_clicked_segment_id:
            return 
        elif self.edit_mode_active:
             self._exit_edit_mode(save_changes=True)

        logger.info(f"Context menu 'Edit Segment Text' for: {self.right_clicked_segment_id}")
        self._enter_edit_mode(self.right_clicked_segment_id)
        self.right_clicked_segment_id = None 


    def _set_segment_timestamps_action_menu(self):
        if not self.right_clicked_segment_id:
            logger.warning("Set Timestamps called but no segment was right-clicked.")
            return
        
        segment = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not segment:
            logger.warning(f"Set Timestamps: Could not find segment with ID {self.right_clicked_segment_id}")
            self.right_clicked_segment_id = None
            return

        logger.info(f"Context menu 'Set/Edit Timestamps' for segment: {segment['id']}")

        dialog = tk.Toplevel(self.window)
        dialog.title(f"Set Timestamps for Segment {segment['id']}")
        dialog.transient(self.window)
        dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(main_frame, text=f"Segment Text (first 50 chars):").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,5))
        ttk.Label(main_frame, text=f"'{segment['text'][:50]}...'").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0,10))
        
        ttk.Label(main_frame, text="Start Time (MM:SS.mmm):").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        start_time_var = tk.StringVar(value=self._seconds_to_time_str(segment['start_time']) if segment.get("has_timestamps") else "00:00.000")
        start_time_entry = ttk.Entry(main_frame, textvariable=start_time_var, width=12)
        start_time_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(main_frame, text="End Time (MM:SS.mmm):").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        end_time_var = tk.StringVar(value=self._seconds_to_time_str(segment['end_time']) if segment.get("has_timestamps") else "00:00.000")
        end_time_entry = ttk.Entry(main_frame, textvariable=end_time_var, width=12)
        end_time_entry.grid(row=3, column=1, sticky="ew", padx=5, pady=2)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(10,0))

        def on_ok():
            start_str = start_time_var.get()
            end_str = end_time_var.get()
            
            new_start_s = self._time_str_to_seconds(start_str)
            new_end_s = self._time_str_to_seconds(end_str)

            if new_start_s is None or new_end_s is None:
                messagebox.showerror("Invalid Time Format", "Please enter times in MM:SS.mmm format (e.g., 01:23.456).", parent=dialog)
                return
            if new_start_s >= new_end_s:
                messagebox.showerror("Invalid Time Range", "Start time must be less than end time.", parent=dialog)
                return
            
            segment['start_time'] = new_start_s
            segment['end_time'] = new_end_s
            segment['has_timestamps'] = True # Mark as having (now valid) timestamps
            logger.info(f"Timestamps updated for segment {segment['id']}: Start={new_start_s:.3f}, End={new_end_s:.3f}")
            self._render_segments_to_text_area()
            dialog.destroy()

        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        start_time_entry.focus_set()
        start_time_entry.selection_range(0, tk.END)

        # Center dialog
        dialog.update_idletasks()
        parent_x = self.window.winfo_rootx()
        parent_y = self.window.winfo_rooty()
        parent_width = self.window.winfo_width()
        parent_height = self.window.winfo_height()
        dialog_width = dialog.winfo_width()
        dialog_height = dialog.winfo_height()
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        dialog.geometry(f"+{x}+{y}")

        self.right_clicked_segment_id = None # Clear after use
        dialog.wait_window()


    def _jump_to_segment_start_action(self):
        if not self.edit_mode_active or not self.editing_segment_id:
            logger.warning("Jump to segment start called but not in edit mode or no segment selected.")
            return
        
        segment = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)
        if not segment or not self.audio_player or not self.audio_player.is_ready():
            logger.warning("Cannot jump: Segment data missing or audio player not ready.")
            return
        
        if not segment.get("has_timestamps", False):
            logger.warning(f"Cannot jump: Segment {self.editing_segment_id} has no real timestamps.")
            messagebox.showwarning("Playback Warning", "Cannot jump to segment start as this segment was loaded without original timestamps.", parent=self.window)
            return

        target_time_secs = max(0, segment["start_time"] - 1.0) 
        
        if self.audio_player.frame_rate > 0:
            target_frame = int(target_time_secs * self.audio_player.frame_rate)
            self.audio_player.set_pos_frames(target_frame) 
            logger.info(f"Jump requested to {target_time_secs:.3f}s for segment {self.editing_segment_id}")
        else:
            logger.warning("Cannot jump, audio player frame rate is invalid or player not fully ready.")


    def _open_assign_speakers_dialog(self):
        if self.edit_mode_active: 
            messagebox.showwarning("Action Blocked", "Please exit text edit mode first.", parent=self.window)
            return
        
        if not self.unique_speaker_labels: 
            messagebox.showinfo("Assign Speakers", "No speaker labels found in the loaded transcription to assign.", parent=self.window)
            return

        dialog = tk.Toplevel(self.window)
        dialog.title("Assign Speaker Names")
        dialog.transient(self.window)
        dialog.grab_set() 

        entries = {}
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)
        
        ttk.Label(main_frame, text="Assign custom names to raw speaker labels:").pack(anchor="w", pady=(0,10))
        
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas) 

        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"), width=e.width))
        canvas.create_window((0,0), window=inner_frame, anchor="nw") 
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def _on_mousewheel_dialog(event): 
            scroll_val = -1*(event.delta // 120) 
            canvas.yview_scroll(scroll_val, "units")
        
        dialog.bind_all("<MouseWheel>", _on_mousewheel_dialog) 


        for i, raw_label in enumerate(sorted(list(self.unique_speaker_labels))):
            row_frame = ttk.Frame(inner_frame) 
            row_frame.pack(fill=tk.X, expand=True)
            ttk.Label(row_frame, text=f"{raw_label}:", width=20).pack(side=tk.LEFT, padx=5, pady=3) 
            entry = ttk.Entry(row_frame) 
            entry.insert(0, self.speaker_map.get(raw_label, "")) 
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=3)
            entries[raw_label] = entry
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10,0))
        
        def on_save_dialog():
            for raw_label, entry_widget in entries.items():
                custom_name = entry_widget.get().strip()
                if custom_name: 
                    self.speaker_map[raw_label] = custom_name 
                elif raw_label in self.speaker_map: 
                    del self.speaker_map[raw_label] 
            logger.info(f"Speaker names updated: {self.speaker_map}")
            self._render_segments_to_text_area() 
            dialog.unbind_all("<MouseWheel>") 
            dialog.destroy()
        
        def on_cancel_dialog():
            dialog.unbind_all("<MouseWheel>")
            dialog.destroy()

        ttk.Button(btn_frame, text="Save", command=on_save_dialog).pack(side=tk.RIGHT, padx=5) 
        ttk.Button(btn_frame, text="Cancel", command=on_cancel_dialog).pack(side=tk.RIGHT) 
        
        dialog.update_idletasks() 
        
        min_width = 400
        num_speakers = len(self.unique_speaker_labels)
        header_height = 50 
        entry_row_height = 35 
        buttons_height = 50
        padding_height = 20
        
        estimated_content_height = num_speakers * entry_row_height if num_speakers > 0 else entry_row_height
        desired_height = header_height + estimated_content_height + buttons_height + padding_height
        
        max_dialog_height = int(self.window.winfo_height() * 0.8)
        dialog_height = max(200, min(int(desired_height), max_dialog_height))
        dialog_width = min_width

        dialog.minsize(min_width, 200) 
        dialog.geometry(f"{dialog_width}x{dialog_height}")
        
        parent_x = self.window.winfo_rootx() 
        parent_y = self.window.winfo_rooty()
        parent_width = self.window.winfo_width()
        parent_height = self.window.winfo_height()
        
        dialog.update_idletasks() 
        d_width = dialog.winfo_width()
        d_height = dialog.winfo_height()

        center_x = parent_x + (parent_width // 2) - (d_width // 2)
        center_y = parent_y + (parent_height // 2) - (d_height // 2)
        dialog.geometry(f"+{max(0,center_x)}+{max(0,center_y)}")
        
        dialog.lift() 
        if entries: 
            list(entries.values())[0].focus_set()
        dialog.wait_window() 


    def _get_segment_id_from_text_index(self, text_index_str: str) -> str | None:
        tags_at_index = self.transcription_text.tag_names(text_index_str)
        for tag in tags_at_index:
            if tag.startswith("seg_") and tag.count('_') == 1: 
                parts = tag.split('_')
                if len(parts) == 2 and parts[0] == 'seg' and parts[1].isdigit():
                    return tag 
        return None


    def _show_context_menu(self, event):
        if self.edit_mode_active: 
            return "break" 

        text_index = self.transcription_text.index(f"@{event.x},{event.y}")
        self.right_clicked_segment_id = self._get_segment_id_from_text_index(text_index)
        
        is_segment_sel = bool(self.right_clicked_segment_id)
        self.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.context_menu.entryconfig("Set/Edit Timestamps", state=tk.NORMAL if is_segment_sel else tk.DISABLED) # Enable if segment selected
        self.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        
        if is_segment_sel: 
            logger.info(f"Context menu shown for segment: {self.right_clicked_segment_id} at text index {text_index}")
        else: 
            logger.info(f"Context menu shown over non-segment area (index {text_index}).")
            
        self.context_menu.tk_popup(event.x_root, event.y_root)
        return "break" 


    def _remove_segment_action(self):
        if self.edit_mode_active or not self.right_clicked_segment_id: return
        
        segment_to_remove = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not segment_to_remove: 
            logger.warning(f"Attempted to remove non-existent segment ID: {self.right_clicked_segment_id}")
            return

        confirm = messagebox.askyesno("Confirm Remove", 
                                     f"Are you sure you want to remove this segment?\n'{segment_to_remove['text'][:70]}...'", 
                                     parent=self.window)
        if confirm:
            self.segments = [s for s in self.segments if s["id"] != self.right_clicked_segment_id]
            self._render_segments_to_text_area() 
            logger.info(f"Segment {self.right_clicked_segment_id} removed.")
        self.right_clicked_segment_id = None 


    def _change_segment_speaker_action_menu(self): 
        if self.edit_mode_active or not self.right_clicked_segment_id: return
        
        segment_to_change = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not segment_to_change: 
            logger.warning(f"Attempted to change speaker for non-existent segment ID: {self.right_clicked_segment_id}")
            return
        
        speaker_choices = {} 
        for raw_label, custom_name in self.speaker_map.items(): 
            speaker_choices[raw_label] = custom_name if custom_name else raw_label 
        for raw_label in self.unique_speaker_labels: 
            if raw_label not in speaker_choices: 
                speaker_choices[raw_label] = raw_label 
        
        generic_unknown_raw = "SPEAKER_UNKNOWN" 
        if generic_unknown_raw not in speaker_choices:
             speaker_choices[generic_unknown_raw] = "Unknown Speaker (set)" 


        if not speaker_choices: 
            messagebox.showinfo("Change Speaker", "No speaker labels (including 'Unknown') are available to choose from.", parent=self.window)
            self.right_clicked_segment_id = None
            return
        
        sorted_choices_for_menu = sorted(speaker_choices.items(), key=lambda item: item[1]) 

        speaker_menu = tk.Menu(self.window, tearoff=0)
        def set_speaker_for_segment(chosen_raw_label):
            logger.info(f"Changing speaker for segment {segment_to_change['id']} from '{segment_to_change['speaker_raw']}' to '{chosen_raw_label}'")
            segment_to_change['speaker_raw'] = chosen_raw_label
            self._render_segments_to_text_area()
            self.right_clicked_segment_id = None 

        for raw_label, display_name in sorted_choices_for_menu: 
            speaker_menu.add_command(label=display_name, command=lambda rl=raw_label: set_speaker_for_segment(rl))
        
        try: 
            x_coord, y_coord = self.window.winfo_pointerx(), self.window.winfo_pointery()
            speaker_menu.tk_popup(x_coord, y_coord)
        except tk.TclError: 
            logger.warning("Could not get pointer coordinates for speaker menu, using fallback position.")
            x_root = self.window.winfo_rootx()
            y_root = self.window.winfo_rooty()
            speaker_menu.tk_popup(x_root + 100, y_root + 100)


    def _on_speaker_click(self, event): 
        if self.edit_mode_active: return "break" 
        clicked_index = self.transcription_text.index(f"@{event.x},{event.y}")
        seg_id = self._get_segment_id_from_text_index(clicked_index)
        logger.info(f"Speaker label left-clicked on segment {seg_id} at index {clicked_index}. No direct action implemented.")
        return "break" 


    def _on_merge_click(self, event):
        if self.edit_mode_active: 
            messagebox.showwarning("Action Blocked", "Please exit text edit mode before merging segments.", parent=self.window)
            return "break"
        
        clicked_index_str = self.transcription_text.index(f"@{event.x},{event.y}")
        tags_at_click = self.transcription_text.tag_names(clicked_index_str)
        
        if "merge_tag_style" not in tags_at_click:
            return 

        segment_id_of_merge_symbol = self._get_segment_id_from_text_index(clicked_index_str)
        if not segment_id_of_merge_symbol: return "break"

        current_segment_index = next((i for i, s in enumerate(self.segments) if s["id"] == segment_id_of_merge_symbol), -1)

        if current_segment_index <= 0: 
            messagebox.showwarning("Merge Error", "Cannot merge the first segment or an error occurred finding the segment.", parent=self.window)
            return "break"
            
        current_segment = self.segments[current_segment_index]
        previous_segment = self.segments[current_segment_index - 1]

        if previous_segment["speaker_raw"] != current_segment["speaker_raw"]:
            messagebox.showwarning("Merge Error", "Cannot merge segments from different speakers.", parent=self.window)
            return "break"
        
        confirm_merge = messagebox.askyesno("Confirm Merge", 
                                           f"Merge segment:\n'{current_segment['text'][:70]}...'\n\nwith previous segment:\n'{previous_segment['text'][:70]}...'?",
                                           parent=self.window)
        if not confirm_merge: return "break"

        # Preserve start time of the previous segment
        # End time becomes the end time of the current segment being merged
        previous_segment["end_time"] = current_segment["end_time"] 
        
        separator = " " 
        if not previous_segment["text"] or not current_segment["text"] or \
           previous_segment["text"].endswith(" ") or current_segment["text"].startswith(" "):
            separator = ""
        previous_segment["text"] += separator + current_segment["text"]
        
        # If the current segment had real timestamps and the previous one didn't,
        # the merged segment now effectively has the previous one's start and current one's end.
        # The `has_timestamps` flag should reflect if the *resulting* segment has meaningful start/end.
        # If previous had timestamps, it keeps them. If current had them and previous didn't, it's a bit mixed.
        # For simplicity, if *either* had timestamps, we can consider the merged one to have them,
        # though the start time is from the previous and end time from current.
        if current_segment.get("has_timestamps", False) or previous_segment.get("has_timestamps", False):
             previous_segment["has_timestamps"] = True
        else:
             previous_segment["has_timestamps"] = False # Both were dummy/no TS
        
        logger.info(f"Merged segment {current_segment['id']} into {previous_segment['id']}.")
        self.segments.pop(current_segment_index) 
        self._render_segments_to_text_area() 
        return "break"


    def _poll_audio_player_queue(self):
        if self.audio_player_update_queue:
            try:
                while not self.audio_player_update_queue.empty():
                    message = self.audio_player_update_queue.get_nowait()
                    msg_type = message[0]

                    if msg_type == 'initialized':
                        current_frame, total_frames, frame_rate = message[1], message[2], message[3]
                        if frame_rate > 0:
                            self.audio_progress_bar.config(to=total_frames / frame_rate)
                            self._update_audio_progress_bar(current_frame / frame_rate)
                        else: 
                            self.audio_progress_bar.config(to=100) 
                            self._update_audio_progress_bar(0)
                        self._update_time_labels(current_frame)

                    elif msg_type == 'progress':
                        current_frame = message[1]
                        if self.audio_player and self.audio_player.is_ready():
                            self._update_time_labels(current_frame)
                            if self.audio_player.frame_rate > 0:
                                current_secs = current_frame / self.audio_player.frame_rate
                                self._update_audio_progress_bar(current_secs)
                                if not self.edit_mode_active: 
                                     self._highlight_current_segment(current_secs)
                    
                    elif msg_type == 'started' or msg_type == 'resumed':
                        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
                            self.play_pause_button.config(text="Pause")
                    elif msg_type == 'paused':
                        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
                            self.play_pause_button.config(text="Play")
                    elif msg_type == 'finished':
                        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
                            self.play_pause_button.config(text="Play")
                        if self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                            end_pos_secs = self.audio_player.total_frames / self.audio_player.frame_rate
                            self._update_audio_progress_bar(end_pos_secs)
                            self._update_time_labels(self.audio_player.total_frames)
                    elif msg_type == 'stopped': 
                        if hasattr(self, 'play_pause_button') and self.play_pause_button.winfo_exists():
                            self.play_pause_button.config(text="Play")
                    elif msg_type == 'error':
                        error_message = message[1]
                        self._handle_audio_player_error(error_message)
                    self.audio_player_update_queue.task_done()
            except queue.Empty:
                pass 
            except Exception as e:
                logger.exception("Error processing audio player queue.")
        
        if hasattr(self, 'window') and self.window.winfo_exists(): 
            self.window.after(50, self._poll_audio_player_queue)


    def _toggle_play_pause(self):
        if not self.audio_player or not self.audio_player.is_ready(): 
            if self.audio_file_path.get() and os.path.exists(self.audio_file_path.get()):
                 messagebox.showinfo("Audio Not Ready", "Audio player is not ready. Try (re)loading files or check for errors in console.", parent=self.window)
            else:
                 messagebox.showinfo("No Audio", "Please load an audio file first.", parent=self.window)
            return

        if self.audio_player.playing: 
            self.audio_player.pause()
        else: 
            self.audio_player.play() 


    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.is_ready(): return
        if self.audio_player.frame_rate <= 0: return

        current_pos_secs = self.audio_player.current_frame / self.audio_player.frame_rate
        target_time_secs = current_pos_secs + delta_seconds
        target_frame = int(target_time_secs * self.audio_player.frame_rate)
        self.audio_player.set_pos_frames(target_frame) 


    def _on_progress_bar_seek(self, value_str: str): 
        if not self.audio_player or not self.audio_player.is_ready(): return 
        if self.audio_player.frame_rate <= 0: return
            
        seek_time_secs = float(value_str)
        target_frame = int(seek_time_secs * self.audio_player.frame_rate)
        self.audio_player.set_pos_frames(target_frame) 


    def _update_time_labels(self, current_player_frame: int | None = None):
        if not self.audio_player or not self.audio_player.is_ready(): 
            if hasattr(self, 'current_time_label') and self.current_time_label.winfo_exists():
                self.current_time_label.config(text="00:00.000 / 00:00.000")
            return
        
        rate = self.audio_player.frame_rate
        if rate <= 0: 
            if hasattr(self, 'current_time_label') and self.current_time_label.winfo_exists():
                self.current_time_label.config(text="Rate Error / Rate Error")
            return

        frame_for_current_time = current_player_frame if current_player_frame is not None else self.audio_player.current_frame
        current_s = frame_for_current_time / rate
        total_s = self.audio_player.total_frames / rate 
        if hasattr(self, 'current_time_label') and self.current_time_label.winfo_exists():
            self.current_time_label.config(text=f"{self._seconds_to_time_str(current_s)} / {self._seconds_to_time_str(total_s)}")


    def _update_audio_progress_bar(self, current_playback_seconds: float):
        if self.audio_player and self.audio_player.is_ready():
            if hasattr(self, 'audio_progress_bar') and self.audio_progress_bar.winfo_exists():
                max_seconds = self.audio_progress_bar.cget("to")
                if not isinstance(max_seconds, (int, float)): max_seconds = 0.0
                safe_seconds = max(0, min(current_playback_seconds, max_seconds ))
                if hasattr(self, 'audio_progress_var'):
                    self.audio_progress_var.set(safe_seconds)


    def _highlight_current_segment(self, current_playback_seconds: float):
        if self.edit_mode_active: return
        if not hasattr(self, 'transcription_text') or self.transcription_text is None: return


        newly_highlighted_segment_id = None
        active_segment_has_real_timestamps = False

        for segment in self.segments:
            if segment.get("has_timestamps", False) and \
               "start_time" in segment and "end_time" in segment and \
               segment["start_time"] <= current_playback_seconds < segment["end_time"]:
                newly_highlighted_segment_id = segment['id']
                active_segment_has_real_timestamps = True 
                break 
        
        if self.currently_highlighted_text_seg_id != newly_highlighted_segment_id:
            if self.currently_highlighted_text_seg_id:
                old_seg_data = next((s for s in self.segments if s["id"] == self.currently_highlighted_text_seg_id), None)
                if old_seg_data:
                    text_tag_to_deactivate = old_seg_data["text_tag_id"]
                    try:
                        ranges = self.transcription_text.tag_ranges(text_tag_to_deactivate)
                        if ranges:
                            self.transcription_text.tag_remove("active_text_highlight", ranges[0], ranges[1])
                            self.transcription_text.tag_add("inactive_text_default", ranges[0], ranges[1])
                    except tk.TclError: pass 
            
            if newly_highlighted_segment_id and active_segment_has_real_timestamps:
                new_seg_data = next((s for s in self.segments if s["id"] == newly_highlighted_segment_id), None)
                if new_seg_data:
                    text_tag_to_activate = new_seg_data["text_tag_id"]
                    try:
                        ranges = self.transcription_text.tag_ranges(text_tag_to_activate)
                        if ranges:
                            self.transcription_text.tag_remove("inactive_text_default", ranges[0], ranges[1])
                            self.transcription_text.tag_add("active_text_highlight", ranges[0], ranges[1])
                            self.transcription_text.see(ranges[0]) 
                    except tk.TclError: pass
            
            self.currently_highlighted_text_seg_id = newly_highlighted_segment_id if active_segment_has_real_timestamps else None
    
    def _save_changes(self):
        if self.edit_mode_active:
            messagebox.showwarning("Save Blocked", "Please finish editing the current segment (e.g., click outside it) before saving all changes.", parent=self.window)
            return

        if not self.segments:
             messagebox.showinfo("Nothing to Save", "No transcription data loaded to save.", parent=self.window)
             return

        content_lines = []
        for s in self.segments:
            if not all(k in s for k in ["start_time", "end_time", "speaker_raw", "text", "has_timestamps"]):
                logger.warning(f"Segment {s.get('id','Unknown ID')} is malformed and will be skipped during save.")
                continue
            
            speaker_to_save = self.speaker_map.get(s['speaker_raw'], s['speaker_raw'])
            
            line_parts = []
            if s.get("has_timestamps", False): 
                line_parts.append(f"[{self._seconds_to_time_str(s['start_time'])} - {self._seconds_to_time_str(s['end_time'])}]")
            
            line_parts.append(f"{speaker_to_save}:")
            line_parts.append(s['text'])
            content_lines.append(" ".join(line_parts))
            
        if not content_lines: 
            messagebox.showwarning("Nothing to Save", "No valid segments found to save after formatting.", parent=self.window)
            return
            
        content_to_save = "\n".join(content_lines) + "\n" 

        initial_filename = "corrected_transcription.txt"
        if self.transcription_file_path.get(): 
            try:
                base = os.path.basename(self.transcription_file_path.get())
                name_part, ext_part = os.path.splitext(base)
                initial_filename = f"{name_part}_corrected{ext_part if ext_part else '.txt'}"
            except Exception: pass 

        save_path = filedialog.asksaveasfilename(
            initialfile=initial_filename, 
            defaultextension=".txt", 
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")], 
            parent=self.window,
            title="Save Corrected Transcription As"
        )
        
        if not save_path: 
            logger.info("Save operation cancelled by user.")
            return
        
        try:
            with open(save_path, 'w', encoding='utf-8') as f: 
                f.write(content_to_save)
            messagebox.showinfo("Saved Successfully", f"Corrected transcription saved to:\n{save_path}", parent=self.window)
            logger.info(f"Changes saved to {save_path}")
        except IOError as e: 
            messagebox.showerror("Save Error", f"Could not save file: {e}", parent=self.window)
            logger.exception(f"IOError during _save_changes to {save_path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"An unexpected error occurred during save: {e}", parent=self.window)
            logger.exception(f"Unexpected error during _save_changes to {save_path}")


    def _disable_audio_controls(self):
        widgets_to_disable = [
            getattr(self, 'play_pause_button', None), 
            getattr(self, 'rewind_button', None), 
            getattr(self, 'forward_button', None),
            getattr(self, 'audio_progress_bar', None)
        ]
        for widget in widgets_to_disable:
            if widget and hasattr(widget, 'winfo_exists') and widget.winfo_exists():
                 widget.config(state=tk.DISABLED)

        if hasattr(self, 'audio_progress_var'): self.audio_progress_var.set(0) 
        
        jump_button = getattr(self, 'jump_to_segment_button', None)
        if jump_button and hasattr(jump_button, 'winfo_exists') and jump_button.winfo_exists():
            jump_button.pack_forget()


    def _on_close(self):
        logger.info("CorrectionWindow: Close requested.")
        if self.edit_mode_active:
            if messagebox.askyesno("Unsaved Edit", "You are currently editing a segment. Exiting now will discard this specific change. Are you sure?", parent=self.window, icon=messagebox.WARNING):
                self._exit_edit_mode(save_changes=False) 
            else:
                logger.info("CorrectionWindow: Close cancelled by user due to active edit.")
                return 

        if self.audio_player: 
            logger.debug("CorrectionWindow: Stopping audio player resources on close.")
            self.audio_player.stop_resources() 
        self.audio_player = None 
        self.audio_player_update_queue = None 

        try: 
            if hasattr(self, 'window') and self.window.winfo_exists():
                 self.window.unbind_all("<MouseWheel>")
        except tk.TclError:
            logger.debug("TclError during unbind_all on close, window might be gone.")
            pass 

        logger.debug("CorrectionWindow: Destroying window.")
        if hasattr(self, 'window') and self.window.winfo_exists():
            self.window.destroy()

