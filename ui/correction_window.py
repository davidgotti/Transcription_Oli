# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
import re 

logger = logging.getLogger(__name__)

# Assuming AudioPlayer is in the same directory or project structure allows this import
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
        self.segments = [] 
        self.speaker_map = {} # Stores raw_label -> custom_name
        self.unique_speaker_labels = set()

        self.segment_pattern = re.compile(
            r"\[(\d{2}:\d{2}\.\d{3}) - (\d{2}:\d{2}\.\d{3})\] (SPEAKER_\d+|SPEAKER_UNKNOWN):\s*(.*)"
        )

        top_pane = ttk.Frame(self.window, padding="10")
        top_pane.pack(fill=tk.X, side=tk.TOP)
        middle_pane = ttk.Frame(self.window, padding="10")
        middle_pane.pack(fill=tk.BOTH, expand=True)

        ttk.Label(top_pane, text="Transcription File:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.transcription_entry = ttk.Entry(top_pane, textvariable=self.transcription_file_path, width=50)
        self.transcription_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_transcription_button = ttk.Button(top_pane, text="Browse...", command=self._browse_transcription_file)
        self.browse_transcription_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(top_pane, text="Audio File:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.audio_entry = ttk.Entry(top_pane, textvariable=self.audio_file_path, width=50)
        self.audio_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_audio_button = ttk.Button(top_pane, text="Browse...", command=self._browse_audio_file)
        self.browse_audio_button.grid(row=1, column=2, padx=5, pady=5)

        self.load_files_button = ttk.Button(top_pane, text="Load Files", command=self._load_files)
        self.load_files_button.grid(row=0, column=3, rowspan=2, padx=10, pady=5, sticky="ns")
        
        self.assign_speakers_button = ttk.Button(top_pane, text="Assign Speakers", command=self._open_assign_speakers_dialog, state=tk.DISABLED)
        self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5)

        self.save_changes_button = ttk.Button(top_pane, text="Save Changes", command=self._save_changes, state=tk.DISABLED)
        self.save_changes_button.grid(row=1, column=4, padx=5, pady=5)
        top_pane.columnconfigure(1, weight=1)

        audio_controls_frame = ttk.Frame(middle_pane)
        audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,10))

        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=self._toggle_play_pause, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=2)
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: self._seek_audio(-5), state=tk.DISABLED)
        self.rewind_button.pack(side=tk.LEFT, padx=2)
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: self._seek_audio(5), state=tk.DISABLED)
        self.forward_button.pack(side=tk.LEFT, padx=2)

        self.audio_progress_var = tk.DoubleVar()
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=self._on_progress_bar_seek, state=tk.DISABLED)
        self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000")
        self.current_time_label.pack(side=tk.LEFT, padx=5)

        text_area_frame = ttk.Frame(middle_pane)
        text_area_frame.pack(fill=tk.BOTH, expand=True)

        self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True)
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview)
        self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.transcription_text.config(state=tk.DISABLED)

        self.transcription_text.tag_configure("speaker_tag", foreground="blue", underline=True)
        self.transcription_text.tag_configure("merge_tag", foreground="green", underline=True)
        self.transcription_text.tag_configure("timestamp_tag", foreground="gray")
        self.transcription_text.tag_configure("highlighted_segment", background="yellow")

        self.transcription_text.tag_bind("speaker_tag", "<Button-1>", self._on_speaker_click)
        self.transcription_text.tag_bind("merge_tag", "<Button-1>", self._on_merge_click)
        self.transcription_text.tag_bind("speaker_tag", "<Enter>", lambda e: self.transcription_text.config(cursor="hand2"))
        self.transcription_text.tag_bind("speaker_tag", "<Leave>", lambda e: self.transcription_text.config(cursor=""))
        self.transcription_text.tag_bind("merge_tag", "<Enter>", lambda e: self.transcription_text.config(cursor="hand2"))
        self.transcription_text.tag_bind("merge_tag", "<Leave>", lambda e: self.transcription_text.config(cursor=""))

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda event: self._save_changes())
        self._update_audio_progress_loop()

    def _time_str_to_seconds(self, time_str: str) -> float:
        minutes, seconds_ms = time_str.split(':')
        seconds, ms = seconds_ms.split('.')
        return int(minutes) * 60 + int(seconds) + int(ms) / 1000.0

    def _seconds_to_time_str(self, total_seconds: float) -> str:
        if total_seconds is None or not isinstance(total_seconds, (int, float)): return "00:00.000"
        total_seconds = max(0, total_seconds)
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        ms = int((total_seconds - minutes * 60 - seconds) * 1000)
        return f"{minutes:02d}:{seconds:02d}.{ms:03d}"

    def _browse_transcription_file(self):
        file_path = filedialog.askopenfilename(title="Select Transcription File", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if file_path: self.transcription_file_path.set(file_path)

    def _browse_audio_file(self):
        file_path = filedialog.askopenfilename(title="Select Audio File", filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")])
        if file_path: self.audio_file_path.set(file_path)

    def _load_files(self):
        txt_path, audio_path = self.transcription_file_path.get(), self.audio_file_path.get()
        if not (txt_path and os.path.exists(txt_path) and audio_path and os.path.exists(audio_path)):
            messagebox.showerror("Error", "Please select valid transcription and audio files.", parent=self.window)
            return
        try:
            with open(txt_path, 'r', encoding='utf-8') as f: raw_text_lines = f.readlines()
            if not self._parse_transcription_text_to_segments(raw_text_lines): return
            self._render_segments_to_text_area()
            logger.info(f"Parsed {len(self.segments)} segments. Unique speakers: {self.unique_speaker_labels}")
            if self.audio_player: self.audio_player.stop()
            self.audio_player = AudioPlayer(audio_path, self.window)
            self.audio_progress_bar.config(to=self.audio_player.wf.getnframes() / self.audio_player.wf.getframerate())
            self._update_time_labels()
            for btn in [self.play_pause_button, self.rewind_button, self.forward_button, self.save_changes_button]: btn.config(state=tk.NORMAL)
            self.play_pause_button.config(text="Play")
            self.audio_progress_bar.config(state=tk.NORMAL)
            self.assign_speakers_button.config(state=tk.NORMAL if self.unique_speaker_labels else tk.DISABLED)
            self.transcription_text.config(state=tk.NORMAL)
            messagebox.showinfo("Success", "Files loaded and transcription parsed.", parent=self.window)
        except Exception as e:
            logger.exception("Error loading files")
            messagebox.showerror("Error", f"Failed to load files: {e}", parent=self.window)
            self.transcription_text.config(state=tk.DISABLED)
            self._disable_audio_controls()

    def _parse_transcription_text_to_segments(self, text_lines: list[str]) -> bool:
        self.segments, self.unique_speaker_labels = [], set()
        malformed_lines, unique_id_counter = 0, 0
        for i, line in enumerate(l.strip() for l in text_lines if l.strip()):
            match = self.segment_pattern.match(line)
            if not match:
                logger.warning(f"Line {i+1} no match: '{line}'"); malformed_lines += 1; continue
            start_str, end_str, speaker_raw, text = match.groups()
            try:
                self.segments.append({
                    "id": f"seg_{unique_id_counter}", "start_time": self._time_str_to_seconds(start_str),
                    "end_time": self._time_str_to_seconds(end_str), "speaker_raw": speaker_raw.strip(),
                    "text": text.strip(), "original_line_num": i + 1
                })
                self.unique_speaker_labels.add(speaker_raw.strip()); unique_id_counter += 1
            except ValueError as ve: logger.warning(f"Time format error line {i+1}: '{line}'. {ve}"); malformed_lines +=1
        if malformed_lines: messagebox.showwarning("Parsing Issues", f"{malformed_lines} lines not fully parsed. See console.", parent=self.window)
        if not self.segments and text_lines: messagebox.showerror("Parsing Failed", "No valid segments parsed.", parent=self.window); return False
        return True

    def _render_segments_to_text_area(self):
        self.transcription_text.config(state=tk.NORMAL); self.transcription_text.delete("1.0", tk.END)
        if not self.segments:
            self.transcription_text.insert(tk.END, "No data.\n"); self.transcription_text.config(state=tk.DISABLED); return
        for idx, seg in enumerate(self.segments):
            display_speaker = self.speaker_map.get(seg['speaker_raw'], seg['speaker_raw'])
            prefix = "+ " if idx > 0 and self.segments[idx-1]["speaker_raw"] == seg["speaker_raw"] else "  "
            if prefix == "+ ": self.transcription_text.insert(tk.END, prefix, ("merge_tag", f"merge_{seg['id']}"))
            else: self.transcription_text.insert(tk.END, prefix)
            ts_str = f"[{self._seconds_to_time_str(seg['start_time'])} - {self._seconds_to_time_str(seg['end_time'])}] "
            self.transcription_text.insert(tk.END, ts_str, ("timestamp_tag", seg['id']))
            self.transcription_text.insert(tk.END, display_speaker, ("speaker_tag", f"speaker_{seg['id']}", seg['id']))
            self.transcription_text.insert(tk.END, f": {seg['text']}\n")
        self.transcription_text.config(state=tk.NORMAL)

    def _open_assign_speakers_dialog(self):
        if not self.unique_speaker_labels:
            messagebox.showinfo("Assign Speakers", "No speaker labels found to assign.", parent=self.window)
            return

        dialog = tk.Toplevel(self.window)
        dialog.title("Assign Speaker Names")
        dialog.transient(self.window) 
        dialog.grab_set() 

        entries = {}
        # Main frame within the dialog
        main_dialog_frame = ttk.Frame(dialog, padding="10")
        main_dialog_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(main_dialog_frame, text="Assign custom names to speaker labels:").pack(pady=(0,10), anchor="w")

        # Frame for the scrollable list of speaker entries
        # This frame will contain the canvas and scrollbar
        content_frame = ttk.Frame(main_dialog_frame)
        content_frame.pack(expand=True, fill=tk.BOTH, pady=5)

        canvas = tk.Canvas(content_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        
        # This frame is inside the canvas and will hold the actual speaker label/entry pairs
        scrollable_inner_frame = ttk.Frame(canvas)

        scrollable_inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_inner_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        for i, raw_label in enumerate(sorted(list(self.unique_speaker_labels))):
            ttk.Label(scrollable_inner_frame, text=f"{raw_label}:").grid(row=i, column=0, padx=5, pady=3, sticky="w")
            entry = ttk.Entry(scrollable_inner_frame, width=30)
            entry.insert(0, self.speaker_map.get(raw_label, "")) 
            entry.grid(row=i, column=1, padx=5, pady=3, sticky="ew")
            entries[raw_label] = entry
        
        scrollable_inner_frame.columnconfigure(1, weight=1) 

        # Pack canvas and scrollbar into their container frame
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Frame for the dialog's buttons, packed at the bottom of main_dialog_frame
        dialog_button_frame = ttk.Frame(main_dialog_frame)
        dialog_button_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10,0)) # Ensure this packs at the bottom

        def on_save():
            for raw_label, entry_widget in entries.items():
                custom_name = entry_widget.get().strip()
                if custom_name: 
                    self.speaker_map[raw_label] = custom_name
                elif raw_label in self.speaker_map: 
                    del self.speaker_map[raw_label]
            logger.info(f"Speaker names saved: {self.speaker_map}")
            self._render_segments_to_text_area() 
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        # Create and pack the Save and Cancel buttons for THIS dialog
        ttk.Button(dialog_button_frame, text="Save", command=on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(dialog_button_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)
        
        dialog.update_idletasks() 

        # Attempt to set a reasonable initial size for the dialog
        req_width = scrollable_inner_frame.winfo_reqwidth() + scrollbar.winfo_reqwidth() + 40 # Estimate
        req_height_content = scrollable_inner_frame.winfo_reqheight()
        req_height_buttons = dialog_button_frame.winfo_reqheight()
        
        # Cap the height for many speakers, but ensure enough for a few
        final_height = min(500, req_height_content + req_height_buttons + 80) # Added padding for labels/buttons
        if len(self.unique_speaker_labels) < 5: # If few speakers, don't make it excessively tall
             final_height = req_height_content + req_height_buttons + 80 # Recalculate based on content

        final_width = max(350, req_width) # Ensure a minimum width

        dialog.geometry(f"{final_width}x{final_height}")
        dialog.minsize(final_width, 150) # Minimum sensible height

        # Center dialog
        dialog.update_idletasks()
        parent_x = self.window.winfo_x()
        parent_y = self.window.winfo_y()
        parent_width = self.window.winfo_width()
        parent_height = self.window.winfo_height()
        dialog_x = parent_x + (parent_width // 2) - (final_width // 2)
        dialog_y = parent_y + (parent_height // 2) - (final_height // 2)
        dialog.geometry(f"+{dialog_x}+{dialog_y}")

        dialog.lift() # Bring to front
        entry_list = list(entries.values())
        if entry_list:
            entry_list[0].focus_set() # Set focus to the first entry field

    def _on_speaker_click(self, event):
        index = self.transcription_text.index(f"@{event.x},{event.y}")
        tags = self.transcription_text.tag_names(index)
        segment_id = next((t for t in tags if t.startswith("seg_")), None)
        if not segment_id: logger.warning(f"Speaker click, no segment ID at {index}. Tags: {tags}"); return
        
        clicked_segment = next((s for s in self.segments if s["id"] == segment_id), None)
        if not clicked_segment: logger.warning(f"Speaker click, segment ID {segment_id} not found."); return

        raw_label = clicked_segment['speaker_raw']
        display_name = self.speaker_map.get(raw_label, raw_label)
        logger.info(f"Clicked speaker '{display_name}' (raw: {raw_label}) for seg ID '{segment_id}'")
        
        # Placeholder for dropdown. For now, it shows current name and allows opening assign dialog.
        action = messagebox.askquestion("Change Speaker", 
                                    f"Speaker: {display_name}\nSegment: {clicked_segment['text'][:30]}...\n\n"
                                    "Do you want to open the 'Assign Speaker Names' dialog to manage all speaker names?",
                                    icon='question', type='yesno', parent=self.window)
        if action == 'yes':
            self._open_assign_speakers_dialog()
        # Actual dropdown for changing this specific instance will be the next step.

    def _on_merge_click(self, event):
        index = self.transcription_text.index(f"@{event.x},{event.y}")
        merge_tag_id = next((t for t in self.transcription_text.tag_names(index) if t.startswith("merge_")), None)
        if not merge_tag_id: logger.warning(f"Merge click, no merge tag at {index}"); return
        segment_id_to_merge = merge_tag_id.replace("merge_", "")
        logger.info(f"Merge icon for segment ID: {segment_id_to_merge}")
        messagebox.showinfo("Merge Clicked", f"Merge for seg ID: {segment_id_to_merge}\n(Logic to be implemented)", parent=self.window)

    def _toggle_play_pause(self):
        if not self.audio_player: return
        if self.audio_player.playing: self.audio_player.pause(); self.play_pause_button.config(text="Play")
        else: self.audio_player.playing = True; self.audio_player.play_audio(); self.play_pause_button.config(text="Pause")

    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.wf : return
        was_playing = self.audio_player.playing
        if was_playing: self.audio_player.pause()
        rate, total_frames = self.audio_player.wf.getframerate(), self.audio_player.wf.getnframes()
        new_pos = max(0, min(self.audio_player.current_frame + int(delta_seconds * rate), total_frames))
        self.audio_player.wf.setpos(new_pos); self.audio_player.current_frame = new_pos
        self._update_audio_progress_bar(new_pos / rate if rate > 0 else 0); self._update_time_labels()
        if was_playing: self.audio_player.playing = True; self.audio_player.play_audio()

    def _on_progress_bar_seek(self, value_str):
        if not self.audio_player or not self.audio_player.wf: return 
        seek_time_seconds = float(value_str); was_playing = self.audio_player.playing
        if was_playing: self.audio_player.pause()
        rate, total_frames = self.audio_player.wf.getframerate(), self.audio_player.wf.getnframes()
        new_pos = max(0, min(int(seek_time_seconds * rate), total_frames))
        self.audio_player.wf.setpos(new_pos); self.audio_player.current_frame = new_pos
        self._update_time_labels()
        if was_playing: self.audio_player.playing = True; self.audio_player.play_audio()

    def _update_time_labels(self):
        if not self.audio_player or not self.audio_player.wf: self.current_time_label.config(text="00:00.000 / 00:00.000"); return
        rate = self.audio_player.wf.getframerate()
        current_s = self.audio_player.current_frame / rate if rate > 0 else 0
        total_s = self.audio_player.wf.getnframes() / rate if rate > 0 else 0
        self.current_time_label.config(text=f"{self._seconds_to_time_str(current_s)} / {self._seconds_to_time_str(total_s)}")

    def _update_audio_progress_bar(self, current_seconds: float):
        if self.audio_player and self.audio_player.wf: self.audio_progress_var.set(current_seconds)

    def _update_audio_progress_loop(self):
        if self.audio_player and self.audio_player.playing and self.audio_player.wf:
            rate = self.audio_player.wf.getframerate()
            if rate > 0:
                current_s = self.audio_player.current_frame / rate
                self._update_audio_progress_bar(current_s); self._update_time_labels(); self._highlight_current_segment(current_s)
        self.window.after(100, self._update_audio_progress_loop) 

    def _highlight_current_segment(self, current_seconds: float):
        self.transcription_text.tag_remove("highlighted_segment", "1.0", tk.END)
        for segment in self.segments:
            if "start_time" in segment and segment["start_time"] <= current_seconds < segment["end_time"]:
                try:
                    tag_ranges = self.transcription_text.tag_ranges(segment['id'])
                    if tag_ranges:
                        start_idx, end_idx = self.transcription_text.index(f"{tag_ranges[0]} linestart"), self.transcription_text.index(f"{tag_ranges[1]} lineend")
                        self.transcription_text.tag_add("highlighted_segment", start_idx, end_idx)
                except tk.TclError: logger.warning(f"Could not highlight segment ID {segment['id']}")
                break 

    def _save_changes(self):
        content_to_save = ""
        if self.segments:
            lines = [f"[{self._seconds_to_time_str(s['start_time'])} - {self._seconds_to_time_str(s['end_time'])}] "
                     f"{self.speaker_map.get(s['speaker_raw'], s['speaker_raw'])}: {s['text']}"
                     for s in self.segments if "start_time" in s]
            content_to_save = "\n".join(lines) + ("\n" if lines else "")
        else: content_to_save = self.transcription_text.get("1.0", tk.END)

        if not content_to_save.strip(): messagebox.showinfo("Nothing to Save", "Content is empty.", parent=self.window); return
        
        initial_file = "corrected_transcription.txt"
        if self.transcription_file_path.get():
            name, ext = os.path.splitext(os.path.basename(self.transcription_file_path.get()))
            initial_file = f"{name}_corrected{ext}"
        
        save_path = filedialog.asksaveasfilename(initialfile=initial_file, defaultextension=".txt", filetypes=[("Text files", "*.txt")], parent=self.window)
        if not save_path: return
        try:
            with open(save_path, 'w', encoding='utf-8') as f: f.write(content_to_save)
            messagebox.showinfo("Saved", f"Transcription saved to {save_path}", parent=self.window)
        except Exception as e: messagebox.showerror("Error", f"Could not save: {e}", parent=self.window)

    def _disable_audio_controls(self):
        for btn in [self.play_pause_button, self.rewind_button, self.forward_button]: btn.config(state=tk.DISABLED)
        self.audio_progress_bar.config(state=tk.DISABLED); self.audio_progress_var.set(0)

    def _on_close(self):
        if self.audio_player: self.audio_player.stop()
        self.window.destroy()