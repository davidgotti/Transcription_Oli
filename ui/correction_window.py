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
        self.audio_player_update_queue = None # Will hold the queue from AudioPlayer instance

        self.segments = []
        self.speaker_map = {}
        self.unique_speaker_labels = set()

        self.currently_highlighted_text_seg_id = None # For playback highlighting
        self.edit_mode_active = False
        self.editing_segment_id = None
        self.editing_segment_text_start_index = None
        self.editing_segment_text_end_index = None
        self.right_clicked_segment_id = None

        self.segment_pattern = re.compile(r"\[(\d{2}:\d{2}\.\d{3}) - (\d{2}:\d{2}\.\d{3})\] (SPEAKER_\d+|SPEAKER_UNKNOWN):\s*(.*)")

        # --- Main layout ---
        main_container_frame = ttk.Frame(self.window, padding="10")
        main_container_frame.pack(expand=True, fill=tk.BOTH)

        # --- Top Controls Frame (File Browse, Load, Assign, Save) ---
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
        self.load_files_button.grid(row=0, column=3, padx=(10,5), pady=5, sticky="ew") # Corrected layout

        self.assign_speakers_button = ttk.Button(top_controls_frame, text="Assign Speakers", command=self._open_assign_speakers_dialog, state=tk.DISABLED)
        self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5, sticky="ew")

        self.save_changes_button = ttk.Button(top_controls_frame, text="Save Changes", command=self._save_changes, state=tk.DISABLED)
        self.save_changes_button.grid(row=1, column=4, padx=5, pady=5, sticky="ew")

        top_controls_frame.columnconfigure(1, weight=1) # Allow entry fields to expand
        top_controls_frame.columnconfigure(3, minsize=100)
        top_controls_frame.columnconfigure(4, minsize=120)


        # --- Audio Controls Frame ---
        audio_controls_frame = ttk.Frame(main_container_frame)
        audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,5))

        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=self._toggle_play_pause, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=2)
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: self._seek_audio(-5), state=tk.DISABLED)
        self.rewind_button.pack(side=tk.LEFT, padx=2)
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: self._seek_audio(5), state=tk.DISABLED)
        self.forward_button.pack(side=tk.LEFT, padx=2)

        self.jump_to_segment_button = ttk.Button(audio_controls_frame, text="|< Jump to Seg Start (-1s)", command=self._jump_to_segment_start_action)
        # This button is packed/unpacked dynamically in _enter_edit_mode and _exit_edit_mode

        self.audio_progress_var = tk.DoubleVar()
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=self._on_progress_bar_seek, state=tk.DISABLED)
        self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000")
        self.current_time_label.pack(side=tk.LEFT, padx=5)

        # --- Transcription Text Area ---
        text_area_frame = ttk.Frame(main_container_frame)
        text_area_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self.text_area_bg_color = "#2E2E2E"
        self.text_area_fg_color = "white"
        self.editing_segment_bg_color = "#4A4A70" # A distinct color for the text part being edited

        self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True, background=self.text_area_bg_color, foreground=self.text_area_fg_color, insertbackground=self.text_area_fg_color)
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview)
        self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- Text Area Tag Configurations ---
        self.transcription_text.tag_configure("speaker_tag_style") # Default, no special styling
        self.transcription_text.tag_configure("merge_tag_style", foreground="lightgreen", underline=True, font=('TkDefaultFont', 9, 'bold'))
        self.transcription_text.tag_configure("timestamp_tag_style", foreground="gray")
        self.transcription_text.tag_configure("active_text_highlight", foreground="black", background="yellow") # For playback highlight
        self.transcription_text.tag_configure("inactive_text_default", foreground=self.text_area_fg_color, background=self.text_area_bg_color)
        self.transcription_text.tag_configure("editing_active_segment_text", background=self.editing_segment_bg_color) # For text being edited

        # --- Text Area Bindings ---
        self.transcription_text.tag_bind("speaker_tag_style", "<Button-1>", self._on_speaker_click)
        self.transcription_text.tag_bind("merge_tag_style", "<Button-1>", self._on_merge_click)
        self.transcription_text.tag_bind("merge_tag_style", "<Enter>", lambda e, ts=self: ts.transcription_text.config(cursor="hand2"))
        self.transcription_text.tag_bind("merge_tag_style", "<Leave>", lambda e, ts=self: ts.transcription_text.config(cursor=""))

        self.context_menu = tk.Menu(self.transcription_text, tearoff=0)
        self.context_menu.add_command(label="Edit Segment Text", command=self._edit_segment_text_action_from_menu)
        self.context_menu.add_command(label="Remove Segment", command=self._remove_segment_action)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Change Speaker for this Segment", command=self._change_segment_speaker_action_menu)

        self.transcription_text.bind("<Button-3>", self._show_context_menu)
        self.transcription_text.bind("<Double-1>", self._double_click_edit_action)
        self.transcription_text.bind("<Button-1>", self._handle_click_during_edit_mode) # For exiting edit mode

        self.transcription_text.config(state=tk.DISABLED) # Start disabled

        # --- Window Close and Save Binding ---
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda e: self._save_changes()) # Ctrl+S to save

        # --- Start Audio Player Queue Poller ---
        self.window.after(100, self._poll_audio_player_queue)


    def _time_str_to_seconds(self, time_str: str) -> float:
        try:
            m, s_ms = time_str.split(':')
            s, ms = s_ms.split('.')
            return int(m) * 60 + int(s) + int(ms) / 1000.0
        except ValueError:
            logger.error(f"Invalid time string format encountered: {time_str}")
            raise # Re-raise to be caught by parser
    
    def _seconds_to_time_str(self, total_seconds: float) -> str:
        if not isinstance(total_seconds, (int, float)) or total_seconds < 0: 
            total_seconds = 0 # Handle None or negative by defaulting to 0
        m, s_rem = divmod(int(total_seconds), 60)
        ms = int((total_seconds - int(total_seconds)) * 1000)
        return f"{m:02d}:{s_rem:02d}.{ms:03d}"

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
        if self.audio_player: # Attempt to clean up
            self.audio_player.stop_resources() # Ensure resources are stopped.
            self.audio_player = None
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
        
        try:
            # Stop and clear previous audio player first
            if self.audio_player:
                self.audio_player.stop_resources()
                self.audio_player = None
            if self.audio_player_update_queue: # Clear old queue if any
                while not self.audio_player_update_queue.empty():
                    try: self.audio_player_update_queue.get_nowait()
                    except queue.Empty: break
                self.audio_player_update_queue = None


            self.segments = [] 
            self.speaker_map = {} # Reset speaker map
            self.unique_speaker_labels = set() # Reset unique labels
            
            with open(txt_p, 'r', encoding='utf-8') as f: 
                lines = f.readlines()
            
            if not self._parse_transcription_text_to_segments(lines):
                self._disable_audio_controls() 
                return # Parsing failed, error shown by parser

            self._render_segments_to_text_area() # Render new segments
            
            # Instantiate new AudioPlayer
            logger.info(f"Loading audio file: {aud_p}")
            self.audio_player = AudioPlayer(aud_p, on_error_callback=self._handle_audio_player_error)
            
            if not self.audio_player.is_ready():
                logger.error("Audio player failed to initialize after file selection.")
                # Error should have been handled by callback or player's init via its queue
                # self._disable_audio_controls() is called in _handle_audio_player_error
                return 

            self.audio_player_update_queue = self.audio_player.get_update_queue()
            
            # Initial state based on player being ready (some updates also come via 'initialized' queue message)
            if self.audio_player.frame_rate > 0:
                self.audio_progress_bar.config(to=self.audio_player.total_frames / self.audio_player.frame_rate)
                self._update_audio_progress_bar(self.audio_player.current_frame / self.audio_player.frame_rate)
            else: # Fallback if frame rate is bad (should be caught by player init)
                self.audio_progress_bar.config(to=100)
                self._update_audio_progress_bar(0)

            self._update_time_labels(self.audio_player.current_frame) 


            for btn in [self.play_pause_button, self.rewind_button, self.forward_button]: btn.config(state=tk.NORMAL)
            self.save_changes_button.config(state=tk.NORMAL) 
            self.play_pause_button.config(text="Play")
            self.audio_progress_bar.config(state=tk.NORMAL)
            self.assign_speakers_button.config(state=tk.NORMAL if self.unique_speaker_labels else tk.DISABLED)
            self.load_files_button.config(text="Reload Files") # Change text after initial load
            logger.info("Files loaded successfully.")
            
        except Exception as e:
            logger.exception("Error during _load_files operation.")
            messagebox.showerror("Load Error", f"An unexpected error occurred: {e}", parent=self.window)
            self.transcription_text.config(state=tk.DISABLED); self._disable_audio_controls()


    def _parse_transcription_text_to_segments(self, text_lines: list[str]) -> bool:
        self.segments.clear() # Ensure segments list is empty before parsing
        self.unique_speaker_labels.clear()
        malformed_count = 0
        id_counter = 0
        
        for i, line_content in enumerate(l.strip() for l in text_lines if l.strip()):
            match = self.segment_pattern.match(line_content)
            if not match:
                logger.warning(f"Line {i+1} does not match segment pattern: '{line_content}'")
                malformed_count += 1
                continue
            
            start_time_str, end_time_str, speaker_raw, text_content = match.groups()
            
            try:
                text_tag_id = f"text_content_{id_counter}" # Unique tag for the text part of this segment
                segment = {
                    "id": f"seg_{id_counter}",
                    "start_time": self._time_str_to_seconds(start_time_str),
                    "end_time": self._time_str_to_seconds(end_time_str),
                    "speaker_raw": speaker_raw.strip(),
                    "text": text_content.strip(),
                    "original_line_num": i + 1,
                    "text_tag_id": text_tag_id 
                }
                if segment["start_time"] >= segment["end_time"]:
                    logger.warning(f"Line {i+1} has start time >= end time: {line_content}")
                    malformed_count +=1; continue

                self.segments.append(segment)
                self.unique_speaker_labels.add(segment['speaker_raw'])
                id_counter += 1
            except ValueError: # Raised by _time_str_to_seconds if format is bad
                logger.warning(f"Line {i+1} has invalid time format: '{line_content}'.")
                malformed_count += 1
        
        if malformed_count > 0:
            messagebox.showwarning("Parsing Issues", f"{malformed_count} line(s) in the transcription file could not be parsed correctly. They have been skipped.", parent=self.window)
        
        if not self.segments and any(l.strip() for l in text_lines): # If file had content but nothing was parsed
            messagebox.showerror("Parsing Failed", "No valid segments could be parsed from the transcription file. Please check its format against the expected pattern.", parent=self.window)
            return False
        elif not self.segments: # File was empty or only whitespace
            logger.info("Transcription file was empty or contained no parsable segment lines.")
            # No error message here, might be intentional
            
        return True


    def _render_segments_to_text_area(self):
        if self.edit_mode_active: # Should not happen if logic is correct, but as safeguard
            self._exit_edit_mode(save_changes=False) 

        current_state = self.transcription_text.cget("state")
        self.transcription_text.config(state=tk.NORMAL)
        self.transcription_text.delete("1.0", tk.END)
        self.currently_highlighted_text_seg_id = None # Reset playback highlight
        
        if not self.segments:
            self.transcription_text.insert(tk.END, "No transcription data loaded or all lines were unparsable.\nPlease load a valid transcription and audio file.")
            self.transcription_text.config(state=tk.DISABLED)
            return
        
        for idx, seg in enumerate(self.segments):
            # Ensure all necessary keys are in the segment dictionary
            required_keys = ["id", "start_time", "end_time", "speaker_raw", "text", "text_tag_id"]
            if not all(key in seg for key in required_keys):
                logger.warning(f"Segment at index {idx} is malformed, skipping rendering: {seg.get('id', 'Unknown ID')}")
                continue
            
            line_start_index = self.transcription_text.index(tk.END + "-1c linestart") # Start of the line being inserted
            
            display_speaker = self.speaker_map.get(seg['speaker_raw'], seg['speaker_raw'])
            
            # Prefix for merged segments (the "+" sign)
            prefix_text, merge_tag_tuple = "  ", () # Default: two spaces, no merge tag
            if idx > 0 and self.segments[idx-1].get("speaker_raw") == seg["speaker_raw"]:
                prefix_text, merge_tag_tuple = "+ ", ("merge_tag_style", seg['id']) # Apply merge style and base segment ID
            self.transcription_text.insert(tk.END, prefix_text, merge_tag_tuple)
            
            # Timestamp
            timestamp_str = f"[{self._seconds_to_time_str(seg['start_time'])} - {self._seconds_to_time_str(seg['end_time'])}] "
            self.transcription_text.insert(tk.END, timestamp_str, ("timestamp_tag_style", seg['id']))
            
            # Speaker
            speaker_tag_start = self.transcription_text.index(tk.END)
            self.transcription_text.insert(tk.END, display_speaker, ("speaker_tag_style", seg['id']))
            speaker_tag_end = self.transcription_text.index(tk.END)
            self.transcription_text.tag_add(f"speaker_{seg['id']}", speaker_tag_start, speaker_tag_end) # More specific tag for speaker part

            self.transcription_text.insert(tk.END, ": ")
            
            # Text content (this is the part that will be editable)
            text_content_start_index = self.transcription_text.index(tk.END)
            # Apply inactive_text_default and the unique text_tag_id (e.g., "text_content_0")
            self.transcription_text.insert(tk.END, seg['text'], ("inactive_text_default", seg["text_tag_id"]))
            text_content_end_index = self.transcription_text.index(tk.END)
            
            self.transcription_text.insert(tk.END, "\n")
            line_end_index = self.transcription_text.index(tk.END + "-1c lineend") # End of the inserted line
            
            # Apply base segment ID tag to the whole line for context menu and double click
            self.transcription_text.tag_add(seg['id'], line_start_index, line_end_index)
            
        self.transcription_text.config(state=tk.DISABLED)


    def _toggle_ui_for_edit_mode(self, disable: bool):
        new_state = tk.DISABLED if disable else tk.NORMAL
        
        # Buttons in top_controls_frame
        self.browse_transcription_button.config(state=new_state)
        self.browse_audio_button.config(state=new_state)
        self.load_files_button.config(state=new_state)
        self.assign_speakers_button.config(state=new_state if not disable and self.unique_speaker_labels else tk.DISABLED)
        self.save_changes_button.config(state=new_state)

        # Context Menu items
        # For context menu, state depends on whether a segment is right-clicked,
        # but if we are disabling UI, all should be disabled regardless.
        is_segment_selected_for_context = bool(self.right_clicked_segment_id) and not disable

        if disable: # Entering edit mode
            self.context_menu.entryconfig("Edit Segment Text", state=tk.DISABLED)
            self.context_menu.entryconfig("Remove Segment", state=tk.DISABLED)
            self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.DISABLED)
        else: # Exiting edit mode, restore context menu states based on selection
            self.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if is_segment_selected_for_context else tk.DISABLED)
            self.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if is_segment_selected_for_context else tk.DISABLED)
            self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if is_segment_selected_for_context else tk.DISABLED)


    def _enter_edit_mode(self, segment_id_to_edit: str):
        if self.edit_mode_active and self.editing_segment_id == segment_id_to_edit:
            logger.debug(f"Already editing segment {segment_id_to_edit}.")
            return 
        if self.edit_mode_active: 
            logger.debug(f"Exiting current edit for {self.editing_segment_id} to edit {segment_id_to_edit}.")
            self._exit_edit_mode(save_changes=True) # Save current before starting new

        target_segment = next((s for s in self.segments if s["id"] == segment_id_to_edit), None)
        if not target_segment:
            logger.warning(f"Attempted to edit non-existent segment ID: {segment_id_to_edit}")
            return

        self.edit_mode_active = True
        self.editing_segment_id = segment_id_to_edit
        
        self.transcription_text.config(state=tk.NORMAL) # Enable text area for editing
        self._toggle_ui_for_edit_mode(disable=True) # Disable other UI elements
        
        text_content_tag_id = target_segment["text_tag_id"] # e.g. "text_content_0"
        try:
            ranges = self.transcription_text.tag_ranges(text_content_tag_id)
            if ranges:
                self.editing_segment_text_start_index = ranges[0]
                self.editing_segment_text_end_index = ranges[1] # This end index might change during edit

                # Apply editing highlight
                self.transcription_text.tag_remove("inactive_text_default", self.editing_segment_text_start_index, self.editing_segment_text_end_index)
                self.transcription_text.tag_add("editing_active_segment_text", self.editing_segment_text_start_index, self.editing_segment_text_end_index)
                
                self.transcription_text.focus_set()
                self.transcription_text.mark_set(tk.INSERT, self.editing_segment_text_start_index)
                self.transcription_text.see(self.editing_segment_text_start_index)
            else:
                logger.error(f"Could not find text tag ranges for '{text_content_tag_id}' to start editing.")
                self._exit_edit_mode(save_changes=False); return # Exit if tag not found

        except tk.TclError:
            logger.exception(f"TclError applying editing tag for '{text_content_tag_id}'")
            self._exit_edit_mode(save_changes=False); return

        self.jump_to_segment_button.pack(side=tk.LEFT, padx=(5,0), before=self.audio_progress_bar) # Show the button
        logger.info(f"Entered edit mode for segment: {self.editing_segment_id} (text tag: {text_content_tag_id})")


    def _exit_edit_mode(self, save_changes: bool = True):
        if not self.edit_mode_active or not self.editing_segment_id:
            return

        logger.info(f"Exiting edit mode for segment: {self.editing_segment_id}. Save: {save_changes}")
        
        original_segment = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)

        if original_segment:
            text_content_tag_id = original_segment["text_tag_id"]
            try:
                # Attempt to remove editing highlight using the specific text_content_tag_id
                # The ranges might have changed if text length was altered.
                current_ranges = self.transcription_text.tag_ranges(text_content_tag_id)
                if current_ranges:
                    self.transcription_text.tag_remove("editing_active_segment_text", current_ranges[0], current_ranges[1])
                    # Re-apply default inactive tag to be safe, though full re-render will do this too.
                    # self.transcription_text.tag_add("inactive_text_default", current_ranges[0], current_ranges[1])

                if save_changes and current_ranges:
                    modified_text = self.transcription_text.get(current_ranges[0], current_ranges[1]).strip()
                    if original_segment["text"] != modified_text:
                        original_segment["text"] = modified_text
                        logger.info(f"Segment {self.editing_segment_id} updated text to: '{modified_text[:50]}...'")
                    else:
                        logger.info(f"Segment {self.editing_segment_id} text unchanged.")
            except tk.TclError:
                logger.warning(f"TclError handling tags for {text_content_tag_id} on exit.")
            except Exception as e:
                logger.exception(f"Error retrieving or updating segment text for {self.editing_segment_id}")
        
        self.jump_to_segment_button.pack_forget() # Hide button
        self.transcription_text.config(state=tk.DISABLED) # Disable text area again
        self._toggle_ui_for_edit_mode(disable=False) # Re-enable other UI
        
        # Clear editing state variables
        self.edit_mode_active = False
        self.editing_segment_id = None
        self.editing_segment_text_start_index = None
        self.editing_segment_text_end_index = None
        
        if save_changes and original_segment : # Only re-render if changes might have occurred and need saving/display
             self._render_segments_to_text_area() # Re-render to reflect changes and reset all tags correctly


    def _handle_click_during_edit_mode(self, event):
        if not self.edit_mode_active or not self.editing_segment_id:
            return # Do nothing if not in edit mode

        clicked_index_str = self.transcription_text.index(f"@{event.x},{event.y}")
        
        # Check if the click is within the bounds of the currently edited segment's text_content_tag
        editing_seg = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)
        if not editing_seg:
            self._exit_edit_mode(save_changes=False); return # Should not happen

        text_content_tag_id = editing_seg["text_tag_id"]
        try:
            tag_ranges = self.transcription_text.tag_ranges(text_content_tag_id)
            if tag_ranges:
                start_idx, end_idx = tag_ranges[0], tag_ranges[1]
                # Check if clicked_index is between start_idx and end_idx (inclusive for start, exclusive for end)
                if self.transcription_text.compare(clicked_index_str, ">=", start_idx) and \
                   self.transcription_text.compare(clicked_index_str, "<", end_idx):
                    return # Click is inside the editable text, let default Tkinter text bindings handle cursor placement
            
            # If not returned by now, click was outside the current segment's text part
            logger.debug("Clicked outside editable text area during edit mode. Saving and exiting.")
            self._exit_edit_mode(save_changes=True)
            # return "break" # May not be needed since we disable text area after exit

        except tk.TclError: # Tag might not be found
            logger.warning(f"TclError checking click for tag {text_content_tag_id}, exiting edit mode.")
            self._exit_edit_mode(save_changes=False)
        except Exception as e:
            logger.exception(f"Error in _handle_click_during_edit_mode: {e}")
            self._exit_edit_mode(save_changes=False)


    def _double_click_edit_action(self, event):
        if self.edit_mode_active: 
            # If already editing, let the default double-click behavior (e.g., word selection) happen.
            # However, we need to ensure it doesn't trigger exiting edit mode if the click is within the segment.
            # The _handle_click_during_edit_mode should correctly identify if the click is inside.
            return 

        text_index = self.transcription_text.index(f"@{event.x},{event.y}")
        segment_id = self._get_segment_id_from_text_index(text_index) 
        if segment_id:
            logger.info(f"Double-clicked on segment: {segment_id}. Entering edit mode.")
            self._enter_edit_mode(segment_id)
            return "break" # Prevent default double-click behavior if we initiated edit mode


    def _edit_segment_text_action_from_menu(self):
        if not self.right_clicked_segment_id: return # No segment was right-clicked
        
        # If already editing this segment, do nothing.
        if self.edit_mode_active and self.editing_segment_id == self.right_clicked_segment_id:
            return 
        # If editing another segment, exit that first (saving changes)
        elif self.edit_mode_active:
             self._exit_edit_mode(save_changes=True)

        logger.info(f"Context menu 'Edit Segment Text' for: {self.right_clicked_segment_id}")
        self._enter_edit_mode(self.right_clicked_segment_id)
        self.right_clicked_segment_id = None # Clear after use


    def _jump_to_segment_start_action(self):
        if not self.edit_mode_active or not self.editing_segment_id:
            logger.warning("Jump to segment start called but not in edit mode or no segment selected.")
            return
        
        segment = next((s for s in self.segments if s["id"] == self.editing_segment_id), None)
        if not segment or not self.audio_player or not self.audio_player.is_ready():
            logger.warning("Cannot jump: Segment data missing or audio player not ready.")
            return

        target_time_secs = max(0, segment["start_time"] - 1.0) # Go to start - 1 second
        
        if self.audio_player.frame_rate > 0:
            target_frame = int(target_time_secs * self.audio_player.frame_rate)
            self.audio_player.set_pos_frames(target_frame) # Player will handle thread signaling
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
        dialog.grab_set() # Make dialog modal

        entries = {}
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)
        main_frame.rowconfigure(1, weight=1) 
        main_frame.columnconfigure(0, weight=1)

        ttk.Label(main_frame, text="Assign custom names to raw speaker labels:").grid(row=0, column=0, pady=(0,10), sticky="w")
        
        # Scrollable frame for speaker entries
        content_frame = ttk.Frame(main_frame)
        content_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        content_frame.rowconfigure(0, weight=1)
        content_frame.columnconfigure(0, weight=1)

        canvas = tk.Canvas(content_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas) # Frame to hold the actual speaker entries

        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=inner_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        for i, raw_label in enumerate(sorted(list(self.unique_speaker_labels))):
            ttk.Label(inner_frame, text=f"{raw_label}:").grid(row=i, column=0, padx=5, pady=3, sticky="w")
            entry = ttk.Entry(inner_frame, width=30)
            entry.insert(0, self.speaker_map.get(raw_label, "")) # Pre-fill if already mapped
            entry.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
            entries[raw_label] = entry
        
        inner_frame.columnconfigure(1, weight=1) # Allow entry fields to expand
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=2, column=0, sticky="ew", pady=(10,0))
        btn_frame.columnconfigure(0, weight=1) # Push buttons to the right
        
        def on_save_dialog():
            for raw_label, entry_widget in entries.items():
                custom_name = entry_widget.get().strip()
                if custom_name: 
                    self.speaker_map[raw_label] = custom_name 
                elif raw_label in self.speaker_map: # If field cleared, remove mapping
                    del self.speaker_map[raw_label] 
            logger.info(f"Speaker names updated: {self.speaker_map}")
            self._render_segments_to_text_area() # Re-render main text area with new names
            dialog.destroy()

        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0,5))
        ttk.Button(btn_frame, text="Save", command=on_save_dialog).pack(side=tk.RIGHT, padx=5) 
        
        dialog.update_idletasks()
        min_width = 350
        num_speakers = len(self.unique_speaker_labels)
        estimated_height = num_speakers * 30 if num_speakers > 0 else 30 
        buttons_height = 100 
        min_height = max(150, min(400, estimated_height + buttons_height)) # Min 150, Max 400
        
        dialog.minsize(min_width, min_height)
        dialog.update_idletasks() # Ensure dimensions are calculated
        
        # Center dialog on parent window
        parent_x, parent_y = self.window.winfo_x(), self.window.winfo_y()
        parent_width, parent_height = self.window.winfo_width(), self.window.winfo_height()
        dialog_width, dialog_height = dialog.winfo_width(), dialog.winfo_height()
        
        center_x = parent_x + (parent_width // 2) - (dialog_width // 2)
        center_y = parent_y + (parent_height // 2) - (dialog_height // 2)
        dialog.geometry(f"+{center_x}+{center_y}")
        
        dialog.lift() # Bring to front
        if entries: # Focus first entry field if available
            list(entries.values())[0].focus_set()
        dialog.wait_window() # Wait for dialog to close


    def _get_segment_id_from_text_index(self, text_index_str: str) -> str | None:
        # This should return the base segment ID for the line, e.g., "seg_0"
        tags_at_index = self.transcription_text.tag_names(text_index_str)
        for tag in tags_at_index:
            if tag.startswith("seg_") and tag.count('_') == 1: # e.g., "seg_0", "seg_12"
                parts = tag.split('_')
                if len(parts) == 2 and parts[0] == 'seg' and parts[1].isdigit():
                    return tag # Found a base segment ID tag
        return None


    def _show_context_menu(self, event):
        if self.edit_mode_active: 
            # If editing, a right click might be for system copy/paste within the text.
            # To allow that, don't show custom menu and don't return "break".
            # However, for simplicity now, we block custom menu.
            return "break" 

        text_index = self.transcription_text.index(f"@{event.x},{event.y}")
        self.right_clicked_segment_id = self._get_segment_id_from_text_index(text_index)
        
        is_segment_sel = bool(self.right_clicked_segment_id)
        self.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        
        if is_segment_sel: 
            logger.info(f"Context menu shown for segment: {self.right_clicked_segment_id} at text index {text_index}")
        else: 
            logger.info(f"Context menu shown over non-segment area (index {text_index}).")
            
        self.context_menu.tk_popup(event.x_root, event.y_root)
        return "break" # Prevent default right-click text widget menu if our menu is shown


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
        self.right_clicked_segment_id = None # Clear after action


    def _change_segment_speaker_action_menu(self): 
        if self.edit_mode_active or not self.right_clicked_segment_id: return
        
        segment_to_change = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not segment_to_change: 
            logger.warning(f"Attempted to change speaker for non-existent segment ID: {self.right_clicked_segment_id}")
            return
        
        # Build list of speaker choices: (raw_label, display_name)
        speaker_choices = {} 
        for raw_label, custom_name in self.speaker_map.items(): 
            speaker_choices[raw_label] = custom_name if custom_name else raw_label 
        for raw_label in self.unique_speaker_labels: 
            if raw_label not in speaker_choices: 
                speaker_choices[raw_label] = raw_label 
        if "SPEAKER_UNKNOWN" not in speaker_choices and "SPEAKER_UNKNOWN" in self.unique_speaker_labels:
            speaker_choices["SPEAKER_UNKNOWN"] = "SPEAKER_UNKNOWN" # Default if not mapped
        elif "SPEAKER_UNKNOWN" not in self.unique_speaker_labels: # Ensure it's an option even if not in unique_speaker_labels
            pass # Don't add if not in unique and not mapped.

        # Add option to set to a generic "Unknown Speaker" if not already present by that exact name
        generic_unknown_raw = "SPEAKER_UNKNOWN" # Predefined raw label
        if generic_unknown_raw not in speaker_choices:
             speaker_choices[generic_unknown_raw] = "Unknown Speaker" # Display name


        if not speaker_choices: 
            messagebox.showinfo("Change Speaker", "No speaker labels (including 'Unknown') are available to choose from.", parent=self.window)
            self.right_clicked_segment_id = None
            return
        
        # Sort by display name for the menu
        sorted_choices_for_menu = sorted(speaker_choices.items(), key=lambda item: item[1]) 

        speaker_menu = tk.Menu(self.window, tearoff=0)
        def set_speaker_for_segment(chosen_raw_label):
            logger.info(f"Changing speaker for segment {segment_to_change['id']} from '{segment_to_change['speaker_raw']}' to '{chosen_raw_label}'")
            segment_to_change['speaker_raw'] = chosen_raw_label
            self._render_segments_to_text_area()
            self.right_clicked_segment_id = None # Clear after action

        for raw_label, display_name in sorted_choices_for_menu: 
            speaker_menu.add_command(label=display_name, command=lambda rl=raw_label: set_speaker_for_segment(rl))
        
        try: # Attempt to show menu at mouse pointer
            x_coord, y_coord = self.window.winfo_pointerx(), self.window.winfo_pointery()
            speaker_menu.tk_popup(x_coord, y_coord)
        except tk.TclError: # Fallback if pointer info fails (e.g., during rapid context switches)
            logger.warning("Could not get pointer coordinates for speaker menu, using fallback position.")
            speaker_menu.tk_popup(self.window.winfo_rootx() + 150, self.window.winfo_rooty() + 150)
        # self.right_clicked_segment_id = None # Cleared by set_speaker_for_segment


    def _on_speaker_click(self, event): 
        if self.edit_mode_active: return "break" # No action if editing text
        # This is a left-click on a speaker label. Currently no action defined.
        clicked_index = self.transcription_text.index(f"@{event.x},{event.y}")
        seg_id = self._get_segment_id_from_text_index(clicked_index)
        logger.info(f"Speaker label left-clicked on segment {seg_id} at index {clicked_index}. No direct action implemented.")
        return "break" # Prevent any other text widget bindings for this click if needed


    def _on_merge_click(self, event):
        if self.edit_mode_active: 
            messagebox.showwarning("Action Blocked", "Please exit text edit mode before merging segments.", parent=self.window)
            return "break"
        
        clicked_index_str = self.transcription_text.index(f"@{event.x},{event.y}")
        tags_at_click = self.transcription_text.tag_names(clicked_index_str)
        
        # Check if the click was on a "merge_tag_style"
        if "merge_tag_style" not in tags_at_click:
            return # Not a merge symbol click

        # Get the segment ID associated with the merge symbol
        segment_id_of_merge_symbol = self._get_segment_id_from_text_index(clicked_index_str)
        if not segment_id_of_merge_symbol: return "break"

        current_segment_index = next((i for i, s in enumerate(self.segments) if s["id"] == segment_id_of_merge_symbol), -1)

        if current_segment_index <= 0: # Cannot merge first segment or if index not found
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

        # Perform the merge
        previous_segment["end_time"] = current_segment["end_time"] # Previous segment now extends to end of current
        
        # Join text, ensuring a space if needed
        separator = " " 
        if not previous_segment["text"] or not current_segment["text"] or \
           previous_segment["text"].endswith(" ") or current_segment["text"].startswith(" "):
            separator = ""
        previous_segment["text"] += separator + current_segment["text"]
        
        logger.info(f"Merged segment {current_segment['id']} into {previous_segment['id']}.")
        self.segments.pop(current_segment_index) # Remove the current segment
        self._render_segments_to_text_area() # Re-render to show changes
        return "break"


    def _poll_audio_player_queue(self):
        if self.audio_player_update_queue:
            try:
                while not self.audio_player_update_queue.empty():
                    message = self.audio_player_update_queue.get_nowait()
                    msg_type = message[0]
                    # logger.debug(f"Audio queue message: {message}")

                    if msg_type == 'initialized':
                        current_frame, total_frames, frame_rate = message[1], message[2], message[3]
                        if frame_rate > 0:
                            self.audio_progress_bar.config(to=total_frames / frame_rate)
                            self._update_audio_progress_bar(current_frame / frame_rate)
                        else: # Should be caught by player init
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
                        self.play_pause_button.config(text="Pause")
                        logger.info(f"Audio playback {msg_type} via queue.")

                    elif msg_type == 'paused':
                        self.play_pause_button.config(text="Play")
                        logger.info("Audio playback paused via queue.")

                    elif msg_type == 'finished':
                        self.play_pause_button.config(text="Play")
                        if self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                            end_pos_secs = self.audio_player.total_frames / self.audio_player.frame_rate
                            self._update_audio_progress_bar(end_pos_secs)
                            self._update_time_labels(self.audio_player.total_frames)
                        logger.info("Audio playback finished via queue.")
                    
                    elif msg_type == 'stopped': 
                        self.play_pause_button.config(text="Play")
                        # Progress bar and time labels should reflect rewind (current_frame=0)
                        # which is handled by player's rewind -> progress message
                        logger.info("Audio playback stopped by user action via queue.")

                    elif msg_type == 'error':
                        error_message = message[1]
                        self._handle_audio_player_error(error_message)

                    self.audio_player_update_queue.task_done()
            except queue.Empty:
                pass 
            except Exception as e:
                logger.exception("Error processing audio player queue.")
        
        if self.window.winfo_exists(): 
            self.window.after(50, self._poll_audio_player_queue)


    def _toggle_play_pause(self):
        if not self.audio_player or not self.audio_player.is_ready(): 
            logger.warning("Audio player not ready for toggle.")
            if self.audio_file_path.get() and os.path.exists(self.audio_file_path.get()):
                 messagebox.showinfo("Audio Not Ready", "Audio player is not ready. Try (re)loading files or check for errors in console.", parent=self.window)
            else:
                 messagebox.showinfo("No Audio", "Please load an audio file first.", parent=self.window)
            return

        if self.audio_player.playing: # If it's playing (not paused)
            self.audio_player.pause()
        else: # Either fully stopped, finished, or paused
            self.audio_player.play() # Handles resume from pause or play from start/stop


    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.is_ready(): return
        
        if self.audio_player.frame_rate <= 0: 
            logger.warning("Cannot seek, audio player frame rate is invalid.")
            return

        current_pos_secs = self.audio_player.current_frame / self.audio_player.frame_rate
        target_time_secs = current_pos_secs + delta_seconds
        
        target_frame = int(target_time_secs * self.audio_player.frame_rate)
        self.audio_player.set_pos_frames(target_frame) # Player sends progress update via queue


    def _on_progress_bar_seek(self, value_str: str): # Value from scale is a string
        if not self.audio_player or not self.audio_player.is_ready(): return 
        
        if self.audio_player.frame_rate <= 0:
            logger.warning("Cannot seek via progress bar, audio player frame rate is invalid.")
            return
            
        seek_time_secs = float(value_str)
        target_frame = int(seek_time_secs * self.audio_player.frame_rate)
        self.audio_player.set_pos_frames(target_frame) # Player sends progress update via queue


    def _update_time_labels(self, current_player_frame: int | None = None):
        if not self.audio_player or not self.audio_player.is_ready(): 
            self.current_time_label.config(text="00:00.000 / 00:00.000")
            return
        
        rate = self.audio_player.frame_rate
        if rate <= 0: 
            self.current_time_label.config(text="Error: No Rate / Error: No Rate")
            return

        # Use provided frame if available (from queue), else player's internal current_frame
        frame_for_current_time = current_player_frame if current_player_frame is not None else self.audio_player.current_frame

        current_s = frame_for_current_time / rate
        total_s = self.audio_player.total_frames / rate 
        self.current_time_label.config(text=f"{self._seconds_to_time_str(current_s)} / {self._seconds_to_time_str(total_s)}")


    def _update_audio_progress_bar(self, current_playback_seconds: float):
        if self.audio_player and self.audio_player.is_ready(): 
            # Ensure value is within the scale's range (0 to max_seconds)
            max_seconds = self.audio_progress_bar.cget("to")
            safe_seconds = max(0, min(current_playback_seconds, max_seconds))
            self.audio_progress_var.set(safe_seconds)


    def _highlight_current_segment(self, current_playback_seconds: float):
        if self.edit_mode_active: # Don't apply playback highlighting if in text edit mode
            return

        newly_highlighted_segment_id = None
        for segment in self.segments:
            if "start_time" in segment and "end_time" in segment and \
               segment["start_time"] <= current_playback_seconds < segment["end_time"]:
                newly_highlighted_segment_id = segment['id']
                break
        
        # If the highlighted segment changes or becomes None
        if self.currently_highlighted_text_seg_id != newly_highlighted_segment_id:
            # Remove old highlight if it exists
            if self.currently_highlighted_text_seg_id:
                old_seg_data = next((s for s in self.segments if s["id"] == self.currently_highlighted_text_seg_id), None)
                if old_seg_data:
                    text_tag_to_deactivate = old_seg_data["text_tag_id"]
                    try:
                        ranges = self.transcription_text.tag_ranges(text_tag_to_deactivate)
                        if ranges:
                            self.transcription_text.tag_remove("active_text_highlight", ranges[0], ranges[1])
                            self.transcription_text.tag_add("inactive_text_default", ranges[0], ranges[1])
                    except tk.TclError: pass # Tag might not exist or ranges empty
            
            # Add new highlight if a new segment is active
            if newly_highlighted_segment_id:
                new_seg_data = next((s for s in self.segments if s["id"] == newly_highlighted_segment_id), None)
                if new_seg_data:
                    text_tag_to_activate = new_seg_data["text_tag_id"]
                    try:
                        ranges = self.transcription_text.tag_ranges(text_tag_to_activate)
                        if ranges:
                            self.transcription_text.tag_remove("inactive_text_default", ranges[0], ranges[1])
                            self.transcription_text.tag_add("active_text_highlight", ranges[0], ranges[1])
                    except tk.TclError: pass
            
            self.currently_highlighted_text_seg_id = newly_highlighted_segment_id
    
    def _save_changes(self):
        if self.edit_mode_active:
            messagebox.showwarning("Save Blocked", "Please finish editing the current segment (e.g., click outside it) before saving all changes.", parent=self.window)
            return

        if not self.segments:
             messagebox.showinfo("Nothing to Save", "No transcription data loaded to save.", parent=self.window)
             return

        content_lines = []
        for s in self.segments:
            # Ensure all parts are present for formatting
            if not all(k in s for k in ["start_time", "end_time", "speaker_raw", "text"]):
                logger.warning(f"Segment {s.get('id','Unknown ID')} is malformed and will be skipped during save.")
                continue
            
            speaker_to_save = self.speaker_map.get(s['speaker_raw'], s['speaker_raw'])
            line = (f"[{self._seconds_to_time_str(s['start_time'])} - {self._seconds_to_time_str(s['end_time'])}] "
                    f"{speaker_to_save}: {s['text']}")
            content_lines.append(line)
            
        if not content_lines:
            messagebox.showwarning("Nothing to Save", "All segments were malformed or data was missing. Nothing was saved.", parent=self.window)
            return
            
        content_to_save = "\n".join(content_lines) + "\n" # Add trailing newline

        initial_filename = "corrected_transcription.txt"
        if self.transcription_file_path.get(): # Try to base it on original transcription filename
            try:
                base = os.path.basename(self.transcription_file_path.get())
                name_part, ext_part = os.path.splitext(base)
                initial_filename = f"{name_part}_corrected{ext_part if ext_part else '.txt'}"
            except Exception: pass # If path parsing fails, use default

        save_path = filedialog.asksaveasfilename(
            initialfile=initial_filename, 
            defaultextension=".txt", 
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")], 
            parent=self.window,
            title="Save Corrected Transcription As"
        )
        
        if not save_path: # User cancelled
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
        for btn in [self.play_pause_button, self.rewind_button, self.forward_button]: 
            btn.config(state=tk.DISABLED)
        self.audio_progress_bar.config(state=tk.DISABLED)
        self.audio_progress_var.set(0) # Reset progress var
        self.jump_to_segment_button.pack_forget() # Ensure it's hidden if it was visible


    def _on_close(self):
        if self.edit_mode_active:
            if messagebox.askyesno("Unsaved Edit", "You are currently editing a segment. Are you sure you want to exit without saving this specific change?", parent=self.window, icon=messagebox.WARNING):
                self._exit_edit_mode(save_changes=False) # Exit edit mode without saving current segment
            else:
                return # Don't close, user wants to continue editing or save

        # Safely stop audio player resources
        if self.audio_player: 
            logger.debug("Closing CorrectionWindow: Stopping audio player resources.")
            self.audio_player.stop_resources() 
        self.audio_player = None # Clear reference
        self.audio_player_update_queue = None # Clear queue reference

        logger.debug("Destroying CorrectionWindow.")
        self.window.destroy()