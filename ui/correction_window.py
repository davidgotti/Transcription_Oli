# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox 
import logging
import os
import re 

logger = logging.getLogger(__name__)

from .audio_player import AudioPlayer 

class EditSegmentDialog(tk.Toplevel): # Custom dialog for editing text
    def __init__(self, parent, title, current_text):
        super().__init__(parent)
        self.transient(parent); self.grab_set(); self.title(title); self.result = None
        main_frame = ttk.Frame(self, padding="10"); main_frame.pack(expand=True, fill=tk.BOTH)
        text_frame = ttk.Frame(main_frame); text_frame.pack(expand=True, fill=tk.BOTH, pady=(0,10))
        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, height=10, width=60, undo=True)
        self.text_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=self.text_scrollbar.set)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y); self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text_widget.insert("1.0", current_text); self.text_widget.focus_set()
        button_frame = ttk.Frame(main_frame); button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Save", command=self.on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.on_cancel).pack(side=tk.RIGHT)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel); self.wait_window(self)
    def on_save(self): self.result = self.text_widget.get("1.0", tk.END).strip(); self.destroy()
    def on_cancel(self): self.result = None; self.destroy()

class CorrectionWindow:
    def __init__(self, parent_root):
        self.parent_root = parent_root; self.window = tk.Toplevel(parent_root)
        self.window.title("Transcription Correction Tool"); self.window.geometry("800x600")
        self.transcription_file_path = tk.StringVar(); self.audio_file_path = tk.StringVar()
        self.audio_player = None; self.segments = []; self.speaker_map = {}; self.unique_speaker_labels = set()
        self.currently_highlighted_text_seg_id = None 
        self.segment_pattern = re.compile(r"\[(\d{2}:\d{2}\.\d{3}) - (\d{2}:\d{2}\.\d{3})\] (SPEAKER_\d+|SPEAKER_UNKNOWN):\s*(.*)")
        main_container_frame = ttk.Frame(self.window, padding="10"); main_container_frame.pack(expand=True, fill=tk.BOTH)
        top_controls_frame = ttk.Frame(main_container_frame); top_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 5))
        ttk.Label(top_controls_frame, text="Transcription File:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.transcription_entry = ttk.Entry(top_controls_frame, textvariable=self.transcription_file_path, width=40); self.transcription_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_transcription_button = ttk.Button(top_controls_frame, text="Browse...", command=self._browse_transcription_file); self.browse_transcription_button.grid(row=0, column=2, padx=5, pady=5)
        ttk.Label(top_controls_frame, text="Audio File:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.audio_entry = ttk.Entry(top_controls_frame, textvariable=self.audio_file_path, width=40); self.audio_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_audio_button = ttk.Button(top_controls_frame, text="Browse...", command=self._browse_audio_file); self.browse_audio_button.grid(row=1, column=2, padx=5, pady=5)
        self.load_files_button = ttk.Button(top_controls_frame, text="Load Files", command=self._load_files); self.load_files_button.grid(row=0, column=3, rowspan=2, padx=(10,5), pady=5, sticky="ns")
        self.assign_speakers_button = ttk.Button(top_controls_frame, text="Assign Speakers", command=self._open_assign_speakers_dialog, state=tk.DISABLED); self.assign_speakers_button.grid(row=0, column=4, padx=5, pady=5, sticky="ew")
        self.save_changes_button = ttk.Button(top_controls_frame, text="Save Changes", command=self._save_changes, state=tk.DISABLED); self.save_changes_button.grid(row=1, column=4, padx=5, pady=5, sticky="ew")
        top_controls_frame.columnconfigure(1, weight=1); top_controls_frame.columnconfigure(4, minsize=120)
        audio_controls_frame = ttk.Frame(main_container_frame); audio_controls_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,5))
        self.play_pause_button = ttk.Button(audio_controls_frame, text="Play", command=self._toggle_play_pause, state=tk.DISABLED); self.play_pause_button.pack(side=tk.LEFT, padx=2)
        self.rewind_button = ttk.Button(audio_controls_frame, text="<< 5s", command=lambda: self._seek_audio(-5), state=tk.DISABLED); self.rewind_button.pack(side=tk.LEFT, padx=2)
        self.forward_button = ttk.Button(audio_controls_frame, text="5s >>", command=lambda: self._seek_audio(5), state=tk.DISABLED); self.forward_button.pack(side=tk.LEFT, padx=2)
        self.audio_progress_var = tk.DoubleVar()
        self.audio_progress_bar = ttk.Scale(audio_controls_frame, orient=tk.HORIZONTAL, from_=0, to=100, variable=self.audio_progress_var, command=self._on_progress_bar_seek, state=tk.DISABLED); self.audio_progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.current_time_label = ttk.Label(audio_controls_frame, text="00:00.000 / 00:00.000"); self.current_time_label.pack(side=tk.LEFT, padx=5)
        text_area_frame = ttk.Frame(main_container_frame); text_area_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self.transcription_text = tk.Text(text_area_frame, wrap=tk.WORD, height=15, width=80, undo=True, background="#2E2E2E", foreground="white", insertbackground="white")
        self.text_scrollbar = ttk.Scrollbar(text_area_frame, orient=tk.VERTICAL, command=self.transcription_text.yview); self.transcription_text.configure(yscrollcommand=self.text_scrollbar.set)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y); self.transcription_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.transcription_text.tag_configure("speaker_tag_style", foreground="lightblue", underline=True) 
        self.transcription_text.tag_configure("merge_tag_style", foreground="lightgreen", underline=True, font=('TkDefaultFont', 9, 'bold'))
        self.transcription_text.tag_configure("timestamp_tag_style", foreground="gray")
        self.transcription_text.tag_configure("active_text_highlight", foreground="black", underline=True) # Text color for active segment
        self.transcription_text.tag_configure("inactive_text_default", foreground="white") # Default text color for inactive segments
        self.transcription_text.tag_bind("speaker_tag_style", "<Button-1>", self._on_speaker_click)
        self.transcription_text.tag_bind("merge_tag_style", "<Button-1>", self._on_merge_click)
        for tag_style in ["speaker_tag_style", "merge_tag_style"]:
            self.transcription_text.tag_bind(tag_style, "<Enter>", lambda e, ts=self: ts.transcription_text.config(cursor="hand2"))
            self.transcription_text.tag_bind(tag_style, "<Leave>", lambda e, ts=self: ts.transcription_text.config(cursor=""))
        self.context_menu = tk.Menu(self.transcription_text, tearoff=0)
        self.context_menu.add_command(label="Edit Segment Text", command=self._edit_segment_text_action)
        self.context_menu.add_command(label="Remove Segment", command=self._remove_segment_action)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Change Speaker for this Segment", command=self._change_segment_speaker_action_menu) 
        self.transcription_text.bind("<Button-3>", self._show_context_menu)
        self.transcription_text.config(state=tk.DISABLED) 
        self.window.protocol("WM_DELETE_WINDOW", self._on_close); self.window.bind('<Control-s>', lambda e: self._save_changes())
        self._update_audio_progress_loop(); self.right_clicked_segment_id = None 

    def _time_str_to_seconds(self, time_str: str) -> float:
        m, s_ms = time_str.split(':'); s, ms = s_ms.split('.')
        return int(m) * 60 + int(s) + int(ms) / 1000.0

    def _seconds_to_time_str(self, total_seconds: float) -> str:
        if not isinstance(total_seconds, (int, float)): total_seconds = 0
        total_seconds = max(0, total_seconds)
        m, s_rem = divmod(int(total_seconds), 60); ms = int((total_seconds - int(total_seconds)) * 1000)
        return f"{m:02d}:{s_rem:02d}.{ms:03d}"

    def _browse_transcription_file(self):
        fp = filedialog.askopenfilename(title="Select Transcription", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if fp: self.transcription_file_path.set(fp)

    def _browse_audio_file(self):
        fp = filedialog.askopenfilename(title="Select Audio", filetypes=[("Audio", "*.wav *.mp3"), ("All", "*.*")])
        if fp: self.audio_file_path.set(fp)

    def _load_files(self):
        txt_p, aud_p = self.transcription_file_path.get(), self.audio_file_path.get()
        if not (txt_p and os.path.exists(txt_p) and aud_p and os.path.exists(aud_p)):
            messagebox.showerror("Error", "Select valid transcription & audio files.", parent=self.window); return
        try:
            with open(txt_p, 'r', encoding='utf-8') as f: lines = f.readlines()
            if not self._parse_transcription_text_to_segments(lines): return
            self._render_segments_to_text_area()
            if self.audio_player: self.audio_player.stop_resources()
            self.audio_player = AudioPlayer(aud_p, self.window)
            if self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                 self.audio_progress_bar.config(to=self.audio_player.total_frames / self.audio_player.frame_rate)
            else: self.audio_progress_bar.config(to=100) # Default if audio fails
            self._update_time_labels()
            for btn in [self.play_pause_button, self.rewind_button, self.forward_button, self.save_changes_button]: btn.config(state=tk.NORMAL)
            self.play_pause_button.config(text="Play"); self.audio_progress_bar.config(state=tk.NORMAL)
            self.assign_speakers_button.config(state=tk.NORMAL if self.unique_speaker_labels else tk.DISABLED)
        except Exception as e:
            logger.exception("Error loading files"); messagebox.showerror("Load Error", f"{e}", parent=self.window)
            self.transcription_text.config(state=tk.DISABLED); self._disable_audio_controls()

    def _parse_transcription_text_to_segments(self, text_lines: list[str]) -> bool:
        self.segments, self.unique_speaker_labels = [], set(); malformed, id_counter = 0, 0
        for i, line in enumerate(l.strip() for l in text_lines if l.strip()):
            match = self.segment_pattern.match(line)
            if not match: logger.warning(f"L{i+1} no match: '{line}'"); malformed += 1; continue
            s_str, e_str, spk_raw, txt = match.groups()
            try:
                seg = {"id": f"seg_{id_counter}", "start_time": self._time_str_to_seconds(s_str),
                       "end_time": self._time_str_to_seconds(e_str), "speaker_raw": spk_raw.strip(),
                       "text": txt.strip(), "original_line_num": i + 1}
                self.segments.append(seg); self.unique_speaker_labels.add(seg['speaker_raw']); id_counter += 1
            except ValueError as ve: logger.warning(f"Time err L{i+1}: '{line}'. {ve}"); malformed +=1
        if malformed: messagebox.showwarning("Parsing Issues", f"{malformed} lines not parsed.", parent=self.window)
        if not self.segments and any(text_lines): messagebox.showerror("Parsing Failed", "No segments parsed.", parent=self.window); return False
        return True

    def _render_segments_to_text_area(self):
        self.transcription_text.config(state=tk.NORMAL); self.transcription_text.delete("1.0", tk.END)
        self.currently_highlighted_text_seg_id = None 
        if not self.segments:
            self.transcription_text.insert(tk.END, "No data.\n"); self.transcription_text.config(state=tk.DISABLED); return
        for idx, seg in enumerate(self.segments):
            if not all(k in seg for k in ["id","start_time","end_time","speaker_raw","text"]): continue # Skip malformed
            line_start_idx = self.transcription_text.index(tk.END + "-1c linestart")
            disp_spk = self.speaker_map.get(seg['speaker_raw'], seg['speaker_raw'])
            prefix, merge_tags = "  ", ()
            if idx > 0 and self.segments[idx-1].get("speaker_raw") == seg["speaker_raw"]:
                # Apply general style "merge_tag_style" and specific segment ID
                prefix, merge_tags = "+ ", ("merge_tag_style", seg['id']) 
            self.transcription_text.insert(tk.END, prefix, merge_tags)
            ts_str = f"[{self._seconds_to_time_str(seg['start_time'])} - {self._seconds_to_time_str(seg['end_time'])}] "
            self.transcription_text.insert(tk.END, ts_str, ("timestamp_tag_style", seg['id'])) # seg['id'] for line context
            self.transcription_text.insert(tk.END, disp_spk, ("speaker_tag_style", seg['id'])) # seg['id'] for line context
            self.transcription_text.insert(tk.END, ": ")
            text_content_tag = f"text_{seg['id']}" # Unique tag for just the text part for precise highlighting
            self.transcription_text.insert(tk.END, seg['text'], ("inactive_text_default", text_content_tag))
            self.transcription_text.insert(tk.END, "\n")
            line_end_idx = self.transcription_text.index(tk.END + "-1c lineend")
            self.transcription_text.tag_add(seg['id'], line_start_idx, line_end_idx) # Tag whole line with base seg ID
        self.transcription_text.config(state=tk.DISABLED)

    def _open_assign_speakers_dialog(self):
        if not self.unique_speaker_labels: messagebox.showinfo("Assign Speakers", "No labels to assign.", parent=self.window); return
        dialog = tk.Toplevel(self.window); dialog.title("Assign Speaker Names"); dialog.transient(self.window); dialog.grab_set()
        entries = {}; main_frame = ttk.Frame(dialog, padding="10"); main_frame.pack(expand=True, fill=tk.BOTH)
        main_frame.rowconfigure(1, weight=1); main_frame.columnconfigure(0, weight=1)
        ttk.Label(main_frame, text="Assign names:").grid(row=0, column=0, pady=(0,10), sticky="w")
        content_frame = ttk.Frame(main_frame); content_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        content_frame.rowconfigure(0, weight=1); content_frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(content_frame, highlightthickness=0); scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas); inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=inner_frame, anchor="nw"); canvas.configure(yscrollcommand=scrollbar.set)
        for i, raw_label in enumerate(sorted(list(self.unique_speaker_labels))):
            ttk.Label(inner_frame,text=f"{raw_label}:").grid(row=i,column=0,padx=5,pady=3,sticky="w")
            entry = ttk.Entry(inner_frame, width=30); entry.insert(0, self.speaker_map.get(raw_label, "")); entry.grid(row=i,column=1,padx=5,pady=3,sticky="ew"); entries[raw_label]=entry
        inner_frame.columnconfigure(1,weight=1); canvas.grid(row=0,column=0,sticky="nsew"); scrollbar.grid(row=0,column=1,sticky="ns")
        btn_frame = ttk.Frame(main_frame); btn_frame.grid(row=2,column=0,sticky="ew",pady=(10,0)); btn_frame.columnconfigure(0,weight=1)
        
        # CORRECTED on_save_dialog:
        def on_save_dialog():
            for raw_label, entry_widget in entries.items():
                custom_name = entry_widget.get().strip()
                if custom_name: 
                    self.speaker_map[raw_label] = custom_name 
                elif raw_label in self.speaker_map: 
                    del self.speaker_map[raw_label] 
            logger.info(f"Speaker names saved: {self.speaker_map}")
            self._render_segments_to_text_area()
            dialog.destroy()

        ttk.Button(btn_frame,text="Cancel",command=dialog.destroy).pack(side=tk.RIGHT,padx=(0,5))
        ttk.Button(btn_frame,text="Save",command=on_save_dialog).pack(side=tk.RIGHT,padx=5) # Ensure this command is on_save_dialog
        
        dialog.update_idletasks(); min_w=350; n_spk=len(self.unique_speaker_labels); est_h=n_spk*30 if n_spk>0 else 30; btn_h=100; min_h=max(150,min(400,est_h+btn_h))
        dialog.minsize(min_w,min_h); dialog.update_idletasks(); px,py,pw,ph=self.window.winfo_x(),self.window.winfo_y(),self.window.winfo_width(),self.window.winfo_height()
        dw,dh=dialog.winfo_width(),dialog.winfo_height(); dialog.geometry(f"+{px+(pw//2)-(dw//2)}+{py+(ph//2)-(dh//2)}"); dialog.lift()
        if entries: list(entries.values())[0].focus_set()


    def _get_segment_id_from_text_index(self, text_index) -> str | None:
        tags = self.transcription_text.tag_names(text_index)
        for tag in tags:
            if tag.startswith("seg_") and tag.count('_') == 1: # Check for "seg_ID" applied to whole line
                parts = tag.split('_')
                if parts[0] == 'seg' and parts[1].isdigit():
                    return tag
        return None

    def _show_context_menu(self, event):
        text_index = self.transcription_text.index(f"@{event.x},{event.y}")
        self.right_clicked_segment_id = self._get_segment_id_from_text_index(text_index)
        is_segment_sel = bool(self.right_clicked_segment_id)
        for label in ["Edit Segment Text", "Remove Segment", "Change Speaker for this Segment"]:
            self.context_menu.entryconfig(label, state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        if is_segment_sel: logger.info(f"Right-clicked on segment: {self.right_clicked_segment_id}")
        else: logger.info("Right-clicked on non-segment area.")
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _edit_segment_text_action(self):
        if not self.right_clicked_segment_id: return
        seg_edit = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not seg_edit: return
        dialog = EditSegmentDialog(self.window, f"Edit Text: [{self._seconds_to_time_str(seg_edit['start_time'])}]", seg_edit.get("text", ""))
        if dialog.result is not None:
            seg_edit["text"] = dialog.result; self._render_segments_to_text_area()
        self.right_clicked_segment_id = None

    def _remove_segment_action(self):
        if not self.right_clicked_segment_id: return
        seg_rem = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not seg_rem: return
        if messagebox.askyesno("Confirm Remove", "Remove this segment?", parent=self.window):
            self.segments = [s for s in self.segments if s["id"] != self.right_clicked_segment_id]
            self._render_segments_to_text_area()
        self.right_clicked_segment_id = None

    def _change_segment_speaker_action_menu(self): 
        if not self.right_clicked_segment_id: return
        seg_change = next((s for s in self.segments if s["id"] == self.right_clicked_segment_id), None)
        if not seg_change: return
        
        choices = {} # Use dict to ensure unique raw_labels as keys
        for rl, cn in self.speaker_map.items(): choices[rl] = cn if cn else rl # Mapped: custom name or raw if custom is empty
        for rl in self.unique_speaker_labels: 
            if rl not in choices: choices[rl] = rl # Unmapped: raw label
        if "SPEAKER_UNKNOWN" not in choices: choices["SPEAKER_UNKNOWN"] = "Unknown Speaker"
        
        # Sort by display name (value in dict)
        sorted_choices = sorted(choices.items(), key=lambda item: item[1]) 

        if not sorted_choices: messagebox.showinfo("Change Speaker", "No speakers available.", parent=self.window); self.right_clicked_segment_id = None; return
        
        menu = tk.Menu(self.window, tearoff=0)
        def set_spk(chosen_raw_label):
            seg_change['speaker_raw'] = chosen_raw_label; self._render_segments_to_text_area(); self.right_clicked_segment_id = None
        for raw_label, display_name in sorted_choices: # Iterate items which are (raw_label, display_name)
            menu.add_command(label=display_name, command=lambda rl=raw_label: set_spk(rl))
        try: x,y = self.window.winfo_pointerx(), self.window.winfo_pointery(); menu.tk_popup(x,y)
        except: menu.tk_popup(self.window.winfo_rootx() + 150, self.window.winfo_rooty() + 150)

    def _on_speaker_click(self, event): 
        logger.info(f"Speaker label left-clicked. No direct action. Index: {self.transcription_text.index(f'@{event.x},{event.y}')}")
        return "break" 

    def _on_merge_click(self, event):
        idx_clk = self.transcription_text.index(f"@{event.x},{event.y}")
        tags_clk = self.transcription_text.tag_names(idx_clk)
        seg_id_merge = next((t for t in tags_clk if t.startswith("seg_") and t.count('_')==1),None) # Find "seg_X" tag
        if not seg_id_merge or "merge_tag_style" not in tags_clk: return "break" 
        curr_idx = next((i for i,s in enumerate(self.segments) if s["id"]==seg_id_merge),-1)
        if curr_idx <= 0: messagebox.showwarning("Merge Error", "Cannot merge.", parent=self.window); return "break"
        curr_s, prev_s = self.segments[curr_idx], self.segments[curr_idx-1]
        if prev_s["speaker_raw"] != curr_s["speaker_raw"]: messagebox.showwarning("Merge Error", "Diff spkrs.", parent=self.window); return "break"
        prev_s["end_time"] = curr_s["end_time"]
        sep = " " if prev_s["text"] and curr_s["text"] and not prev_s["text"].endswith(" ") and not curr_s["text"].startswith(" ") else ""
        prev_s["text"] += sep + curr_s["text"]
        self.segments.pop(curr_idx); self._render_segments_to_text_area()
        return "break"

    def _toggle_play_pause(self):
        if not self.audio_player or not self.audio_player.is_ready(): logger.warning("Audio player not ready."); return
        if self.audio_player.playing: 
            self.audio_player.pause(); self.play_pause_button.config(text="Play")
        else: 
            if self.audio_player.is_finished():
                self.audio_player.rewind(); logger.info("Audio ended, rewound.")
                self._update_time_labels(); self._update_audio_progress_bar(0)
            self.audio_player.play(); self.play_pause_button.config(text="Pause")

    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.is_ready(): return
        was_playing = self.audio_player.playing; 
        if was_playing: self.audio_player.pause()
        rate = self.audio_player.frame_rate; total_f = self.audio_player.total_frames
        if rate <= 0: logger.error("Audio rate 0, cannot seek."); return
        new_pos_f = max(0, min(self.audio_player.current_frame + int(delta_seconds * rate), total_f))
        self.audio_player.set_pos_frames(new_pos_f)
        self._update_audio_progress_bar(new_pos_f / rate if rate > 0 else 0); self._update_time_labels()
        if was_playing: self.audio_player.play()

    def _on_progress_bar_seek(self, value_str):
        if not self.audio_player or not self.audio_player.is_ready(): return 
        seek_t_s = float(value_str); was_playing = self.audio_player.playing
        if was_playing: self.audio_player.pause()
        rate = self.audio_player.frame_rate; total_f = self.audio_player.total_frames
        if rate <= 0: logger.error("Audio rate 0, cannot seek by bar."); return
        new_pos_f = max(0, min(int(seek_t_s * rate), total_f))
        self.audio_player.set_pos_frames(new_pos_f); self._update_time_labels()
        if was_playing: self.audio_player.play()

    def _update_time_labels(self):
        if not self.audio_player or not self.audio_player.is_ready(): self.current_time_label.config(text="00:00.000 / 00:00.000"); return
        rate = self.audio_player.frame_rate
        if rate <= 0: self.current_time_label.config(text="Error: No Rate"); return
        current_s = self.audio_player.current_frame / rate if rate > 0 else 0 # Prevent div by zero
        total_s = self.audio_player.total_frames / rate if rate > 0 else 0   # Prevent div by zero
        self.current_time_label.config(text=f"{self._seconds_to_time_str(current_s)} / {self._seconds_to_time_str(total_s)}")

    def _update_audio_progress_bar(self, current_seconds: float):
        if self.audio_player and self.audio_player.is_ready(): self.audio_progress_var.set(current_seconds)

    def _update_audio_progress_loop(self):
        if self.audio_player and self.audio_player.is_ready() and self.audio_player.playing:
            rate = self.audio_player.frame_rate
            if rate > 0:
                current_s = self.audio_player.current_frame / rate
                self._update_audio_progress_bar(current_s); self._update_time_labels(); self._highlight_current_segment(current_s)
                if self.audio_player.is_finished():
                    self.audio_player.playing = False; self.play_pause_button.config(text="Play"); logger.info("Audio playback finished.")
        self.window.after(100, self._update_audio_progress_loop) 

    def _highlight_current_segment(self, current_seconds: float):
        # Remove active highlight from previously highlighted text part
        if self.currently_highlighted_text_seg_id:
            prev_text_specific_tag = f"text_{self.currently_highlighted_text_seg_id}"
            try:
                ranges = self.transcription_text.tag_ranges(prev_text_specific_tag)
                for i in range(0, len(ranges), 2):
                    self.transcription_text.tag_remove("active_text_highlight", ranges[i], ranges[i+1])
                    self.transcription_text.tag_add("inactive_text_default", ranges[i], ranges[i+1])
            except tk.TclError: pass 
            self.currently_highlighted_text_seg_id = None

        for segment in self.segments:
            if "start_time" in segment and segment["start_time"] <= current_seconds < segment["end_time"]:
                current_text_specific_tag = f"text_{segment['id']}"
                try:
                    ranges = self.transcription_text.tag_ranges(current_text_specific_tag)
                    if ranges:
                        for i in range(0, len(ranges), 2):
                            self.transcription_text.tag_remove("inactive_text_default", ranges[i], ranges[i+1])
                            self.transcription_text.tag_add("active_text_highlight", ranges[i], ranges[i+1])
                        self.currently_highlighted_text_seg_id = segment['id']
                except tk.TclError: logger.warning(f"TclError highlighting text for seg ID {segment['id']}")
                break 
    
    def _save_changes(self):
        content_to_save = ""
        if self.segments:
            lines = [f"[{self._seconds_to_time_str(s['start_time'])} - {self._seconds_to_time_str(s['end_time'])}] "
                     f"{self.speaker_map.get(s['speaker_raw'], s['speaker_raw'])}: {s['text']}"
                     for s in self.segments if "start_time" in s] 
            content_to_save = "\n".join(lines) + ("\n" if lines else "")
        else: content_to_save = self.transcription_text.get("1.0", tk.END)
        if not content_to_save.strip(): messagebox.showinfo("Nothing to Save", "Content empty.", parent=self.window); return
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
        if self.audio_player: self.audio_player.stop_resources() # Full cleanup
        self.window.destroy()