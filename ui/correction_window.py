# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
import re # Import the re module for regular expressions
# Assuming AudioPlayer will be used here eventually
from .audio_player import AudioPlayer # Ensure this path is correct relative to your project structure

logger = logging.getLogger(__name__)

class CorrectionWindow:
    def __init__(self, parent_root):
        self.parent_root = parent_root
        self.window = tk.Toplevel(parent_root)
        self.window.title("Transcription Correction Tool")
        self.window.geometry("800x600")

        self.transcription_file_path = tk.StringVar()
        self.audio_file_path = tk.StringVar()
        self.audio_player = None
        self.segments = [] # To store parsed transcription segments
        self.speaker_map = {} # To store SPEAKER_XX -> UserDefinedName

        # Regex for parsing transcription lines
        # Format: [00:00.000 - 00:01.000] SPEAKER_01: Text here.
        self.segment_pattern = re.compile(
            r"\[(\d{2}:\d{2}\.\d{3}) - (\d{2}:\d{2}\.\d{3})\] (SPEAKER_\d+|SPEAKER_UNKNOWN):\s*(.*)"
        )

        # --- Main Panes ---
        # Top pane for file selection and global actions
        top_pane = ttk.Frame(self.window, padding="10")
        top_pane.pack(fill=tk.X, side=tk.TOP)

        # Middle pane for audio controls and text area
        middle_pane = ttk.Frame(self.window, padding="10")
        middle_pane.pack(fill=tk.BOTH, expand=True)

        # --- Top Pane: File Selection & Global Actions ---
        # Transcription file
        ttk.Label(top_pane, text="Transcription File:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.transcription_entry = ttk.Entry(top_pane, textvariable=self.transcription_file_path, width=50)
        self.transcription_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_transcription_button = ttk.Button(top_pane, text="Browse...", command=self._browse_transcription_file)
        self.browse_transcription_button.grid(row=0, column=2, padx=5, pady=5)

        # Audio file
        ttk.Label(top_pane, text="Audio File:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.audio_entry = ttk.Entry(top_pane, textvariable=self.audio_file_path, width=50)
        self.audio_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_audio_button = ttk.Button(top_pane, text="Browse...", command=self._browse_audio_file)
        self.browse_audio_button.grid(row=1, column=2, padx=5, pady=5)

        # Load Files Button
        self.load_files_button = ttk.Button(top_pane, text="Load Files", command=self._load_files)
        self.load_files_button.grid(row=0, column=3, rowspan=2, padx=10, pady=5, sticky="ns")
        
        # Global Action Buttons (Placeholders)
        self.assign_speakers_button = ttk.Button(top_pane, text="Assign Speakers", command=self._assign_speakers, state=tk.DISABLED)
        self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5)

        self.save_changes_button = ttk.Button(top_pane, text="Save Changes", command=self._save_changes, state=tk.DISABLED)
        self.save_changes_button.grid(row=1, column=4, padx=5, pady=5)


        top_pane.columnconfigure(1, weight=1)


        # --- Middle Pane: Audio Controls & Text Area ---
        # Audio Controls Frame
        audio_controls_frame = ttk.Frame(middle_pane)
        audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,10))

        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=self._toggle_play_pause, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=2)
        
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: self._seek_audio(-5), state=tk.DISABLED)
        self.rewind_button.pack(side=tk.LEFT, padx=2)
        
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: self._seek_audio(5), state=tk.DISABLED)
        self.forward_button.pack(side=tk.LEFT, padx=2)

        # Placeholder for precise audio bar (Scale widget)
        self.audio_progress_var = tk.DoubleVar()
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=self._on_progress_bar_seek, state=tk.DISABLED)
        self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000")
        self.current_time_label.pack(side=tk.LEFT, padx=5)


        # Text Area for Transcription
        text_area_frame = ttk.Frame(middle_pane) # Frame to hold text and scrollbar
        text_area_frame.pack(fill=tk.BOTH, expand=True)

        self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True)
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview)
        self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.transcription_text.config(state=tk.DISABLED) # Initially disabled, enabled after load/parse

        # --- Event Bindings ---
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda event: self._save_changes())

        # Start update loop for audio progress
        self._update_audio_progress_loop()

    def _time_str_to_seconds(self, time_str: str) -> float:
        """Converts MM:SS.mmm time string to seconds."""
        minutes, seconds_ms = time_str.split(':')
        seconds, ms = seconds_ms.split('.')
        return int(minutes) * 60 + int(seconds) + int(ms) / 1000.0

    def _seconds_to_time_str(self, total_seconds: float) -> str:
        """Converts seconds to MM:SS.mmm time string."""
        if total_seconds is None or not isinstance(total_seconds, (int, float)): return "00:00.000"
        total_seconds = max(0, total_seconds)
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        ms = int((total_seconds - minutes * 60 - seconds) * 1000)
        return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


    def _browse_transcription_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Transcription File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            self.transcription_file_path.set(file_path)
            logger.info(f"Transcription file selected: {file_path}")

    def _browse_audio_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio Files", "*.wav *.mp3 *.aac *.flac *.m4a"), ("All files", "*.*")]
        )
        if file_path:
            self.audio_file_path.set(file_path)
            logger.info(f"Audio file selected: {file_path}")

    def _load_files(self):
        txt_path = self.transcription_file_path.get()
        audio_path = self.audio_file_path.get()

        if not txt_path or not os.path.exists(txt_path):
            messagebox.showerror("Error", "Transcription file not found or not selected.", parent=self.window)
            return
        if not audio_path or not os.path.exists(audio_path):
            messagebox.showerror("Error", "Audio file not found or not selected.", parent=self.window)
            return

        logger.info(f"Loading transcription from: {txt_path}")
        logger.info(f"Loading audio from: {audio_path}")
        
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                raw_text_lines = f.readlines()
            
            parsed_successfully = self._parse_transcription_text_to_segments(raw_text_lines)
            if not parsed_successfully:
                 # Error already shown by _parse_transcription_text_to_segments
                return

            self._render_segments_to_text_area() # Display parsed (or raw if parsing failed slightly)
            logger.info(f"Transcription file parsed. {len(self.segments)} segments loaded.")
            
            if self.audio_player:
                self.audio_player.stop() 
            self.audio_player = AudioPlayer(audio_path, self.window) 
            self.audio_progress_bar.config(to=self.audio_player.wf.getnframes() / self.audio_player.wf.getframerate())
            self._update_time_labels()

            self.play_pause_button.config(state=tk.NORMAL, text="Play")
            self.rewind_button.config(state=tk.NORMAL)
            self.forward_button.config(state=tk.NORMAL)
            self.audio_progress_bar.config(state=tk.NORMAL)
            self.assign_speakers_button.config(state=tk.NORMAL)
            self.save_changes_button.config(state=tk.NORMAL)
            self.transcription_text.config(state=tk.NORMAL) # Allow editing

            messagebox.showinfo("Success", "Files loaded and transcription parsed.", parent=self.window)
        except Exception as e:
            logger.exception("Error loading files into correction window.")
            messagebox.showerror("Error", f"Failed to load files: {e}", parent=self.window)
            self.transcription_text.config(state=tk.DISABLED)
            self._disable_audio_controls()


    def _parse_transcription_text_to_segments(self, text_lines: list[str]) -> bool:
        self.segments = []
        malformed_lines = 0
        unique_id_counter = 0
        for i, line in enumerate(text_lines):
            line = line.strip()
            if not line: # Skip empty lines
                continue

            match = self.segment_pattern.match(line)
            if match:
                start_time_str, end_time_str, speaker_raw, text_content = match.groups()
                try:
                    segment = {
                        "id": f"seg_{unique_id_counter}",
                        "start_time": self._time_str_to_seconds(start_time_str),
                        "end_time": self._time_str_to_seconds(end_time_str),
                        "speaker_raw": speaker_raw.strip(),
                        "text": text_content.strip(),
                        "original_line_num": i + 1
                    }
                    self.segments.append(segment)
                    unique_id_counter += 1
                except ValueError as ve:
                    logger.warning(f"Malformed time format in line {i+1}: '{line}'. Error: {ve}")
                    malformed_lines +=1
            else:
                logger.warning(f"Line {i+1} does not match expected format: '{line}'")
                # Option: add as a raw, unparsed segment if needed for full text reconstruction
                # self.segments.append({"id": f"seg_{unique_id_counter}", "raw_text": line, "original_line_num": i + 1, "is_malformed": True})
                # unique_id_counter +=1
                malformed_lines += 1
        
        if malformed_lines > 0:
            messagebox.showwarning("Parsing Issues", 
                                   f"{malformed_lines} line(s) in the transcription file did not match the expected format "
                                   "or had errors and were not fully parsed. Please check the console log for details. "
                                   "The application will proceed with correctly parsed segments.", 
                                   parent=self.window)
        if not self.segments and text_lines: # File had content but nothing was parsed
             messagebox.showerror("Parsing Failed", "No valid transcription segments could be parsed from the file.", parent=self.window)
             return False
        elif not self.segments and not text_lines: # Empty file
            logger.info("Transcription file was empty. No segments loaded.")
            # No error message needed for an empty file, just proceed with no segments
        
        logger.info(f"Parsed {len(self.segments)} segments. Encountered {malformed_lines} malformed lines.")
        return True


    def _render_segments_to_text_area(self):
        self.transcription_text.config(state=tk.NORMAL)
        self.transcription_text.delete("1.0", tk.END)
        
        if not self.segments:
            self.transcription_text.insert(tk.END, "No transcription data loaded or parsed.\n")
            self.transcription_text.config(state=tk.DISABLED) # Disable if truly nothing to show/edit
            return

        # This is still a basic render. Future steps will add tags for interactivity.
        for segment in self.segments:
            if "start_time" in segment: # Properly parsed segment
                line_to_display = (
                    f"[{self._seconds_to_time_str(segment['start_time'])} - {self._seconds_to_time_str(segment['end_time'])}] "
                    f"{segment['speaker_raw']}: {segment['text']}\n"
                )
            elif "raw_text" in segment : # Malformed line, display as is (if we choose to keep them)
                line_to_display = segment['raw_text'] + "\n"
            else: # Should not happen if parsing logic is correct
                line_to_display = "Error: Unknown segment format\n"
            
            self.transcription_text.insert(tk.END, line_to_display)
        
        # Keep it normal for editing if segments exist
        self.transcription_text.config(state=tk.NORMAL if self.segments else tk.DISABLED)


    def _toggle_play_pause(self):
        if not self.audio_player: return
        if self.audio_player.playing:
            self.audio_player.pause()
            self.play_pause_button.config(text="Play")
            logger.debug("Audio paused.")
        else:
            self.audio_player.playing = True 
            self.audio_player.play_audio() 
            self.play_pause_button.config(text="Pause")
            logger.debug("Audio playing.")

    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.wf : return # Check wf too
        
        was_playing = self.audio_player.playing
        if was_playing:
            self.audio_player.pause()

        current_pos_frames = self.audio_player.current_frame
        rate = self.audio_player.wf.getframerate()
        
        new_pos_frames = current_pos_frames + int(delta_seconds * rate)
        # Ensure new_pos_frames is within bounds (0 to total_frames)
        total_frames = self.audio_player.wf.getnframes()
        new_pos_frames = max(0, min(new_pos_frames, total_frames))
        
        self.audio_player.wf.setpos(new_pos_frames)
        self.audio_player.current_frame = new_pos_frames # Update player's current frame
        self._update_audio_progress_bar(new_pos_frames / rate if rate > 0 else 0)
        self._update_time_labels()

        if was_playing:
            self.audio_player.playing = True
            self.audio_player.play_audio()
        logger.debug(f"Seeked audio by {delta_seconds}s. New pos: {self.audio_player.current_frame / rate if rate > 0 else 0:.3f}s")

    def _on_progress_bar_seek(self, value_str):
        if not self.audio_player or not self.audio_player.wf: return 
        
        seek_time_seconds = float(value_str)

        was_playing = self.audio_player.playing
        if was_playing:
            self.audio_player.pause()

        rate = self.audio_player.wf.getframerate()
        total_frames = self.audio_player.wf.getnframes()
        new_pos_frames = int(seek_time_seconds * rate)
        new_pos_frames = max(0, min(new_pos_frames, total_frames)) # Clamp to bounds

        self.audio_player.wf.setpos(new_pos_frames)
        self.audio_player.current_frame = new_pos_frames
        self._update_time_labels() # Update time labels based on the new position

        if was_playing:
            self.audio_player.playing = True
            self.audio_player.play_audio()
        logger.debug(f"Audio progress bar seeked to {seek_time_seconds:.3f}s")


    def _update_time_labels(self):
        if not self.audio_player or not self.audio_player.wf:
            self.current_time_label.config(text="00:00.000 / 00:00.000")
            return
        
        rate = self.audio_player.wf.getframerate()
        current_seconds = self.audio_player.current_frame / rate if rate > 0 else 0
        total_seconds = self.audio_player.wf.getnframes() / rate if rate > 0 else 0
        
        self.current_time_label.config(text=f"{self._seconds_to_time_str(current_seconds)} / {self._seconds_to_time_str(total_seconds)}")


    def _update_audio_progress_bar(self, current_seconds: float):
        if self.audio_player and self.audio_player.wf:
            self.audio_progress_var.set(current_seconds)


    def _update_audio_progress_loop(self):
        if self.audio_player and self.audio_player.playing and self.audio_player.wf:
            rate = self.audio_player.wf.getframerate()
            if rate > 0:
                current_seconds = self.audio_player.current_frame / rate
                self._update_audio_progress_bar(current_seconds)
                self._update_time_labels()
                self._highlight_current_segment(current_seconds)

        self.window.after(100, self._update_audio_progress_loop) 


    def _highlight_current_segment(self, current_seconds: float):
        # Placeholder - will be implemented later when text area has tags
        # For now, just log to show it's being called
        # logger.debug(f"Highlight check at {current_seconds:.3f}s")
        pass

    def _assign_speakers(self):
        messagebox.showinfo("Assign Speakers", "Functionality to assign speaker names to be implemented.", parent=self.window)
        logger.info("Assign Speakers button clicked (placeholder).")

    def _add_segment(self):
        messagebox.showinfo("Add Segment", "Functionality to add a new segment to be implemented.", parent=self.window)
        logger.info("Add Segment button clicked (placeholder).")


    def _save_changes(self):
        if not self.segments and not self.transcription_text.get("1.0", tk.END).strip():
             messagebox.showinfo("Nothing to Save", "There is no content to save.", parent=self.window)
             return

        # Decide if we save from self.segments (ideal) or self.transcription_text (fallback)
        # For now, let's try to reconstruct from self.segments if available and valid.
        # This also means any direct text edits that don't update self.segments yet won't be saved perfectly.
        
        content_to_save = ""
        if self.segments:
            lines = []
            for segment in self.segments:
                 if "start_time" in segment: # Properly parsed segment
                    lines.append(
                        f"[{self._seconds_to_time_str(segment['start_time'])} - {self._seconds_to_time_str(segment['end_time'])}] "
                        f"{segment['speaker_raw']}: {segment['text']}"
                    )
                 elif "raw_text" in segment: # Malformed line saved as is
                     lines.append(segment['raw_text'])
            content_to_save = "\n".join(lines)
            if content_to_save: content_to_save += "\n" # Add trailing newline if content exists
        else: # Fallback to text area content if segments are empty (e.g., parsing failed entirely)
            content_to_save = self.transcription_text.get("1.0", tk.END)


        if not content_to_save.strip():
            messagebox.showinfo("Nothing to Save", "The content is empty.", parent=self.window)
            return

        initial_file_name = "corrected_transcription.txt"
        if self.transcription_file_path.get():
            initial_file_name = os.path.basename(self.transcription_file_path.get())
            # Optionally, add a suffix like "_corrected"
            name, ext = os.path.splitext(initial_file_name)
            initial_file_name = f"{name}_corrected{ext}"


        save_path = filedialog.asksaveasfilename(
            initialfile=initial_file_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            parent=self.window
        )
        if not save_path:
            return

        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content_to_save)
            messagebox.showinfo("Saved", f"Transcription saved to {save_path}", parent=self.window)
            logger.info(f"Changes saved to {save_path}")
        except Exception as e:
            logger.exception(f"Error saving transcription to {save_path}")
            messagebox.showerror("Error", f"Could not save file: {e}", parent=self.window)


    def _disable_audio_controls(self):
        self.play_pause_button.config(state=tk.DISABLED)
        self.rewind_button.config(state=tk.DISABLED)
        self.forward_button.config(state=tk.DISABLED)
        self.audio_progress_bar.config(state=tk.DISABLED)
        self.audio_progress_var.set(0)


    def _on_close(self):
        logger.info("Correction window closing.")
        if self.audio_player:
            self.audio_player.stop()
            logger.debug("Audio player stopped on close.")
        self.window.destroy()