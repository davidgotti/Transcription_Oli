# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox # Keep messagebox here for direct use by CW
import logging
import os
import queue

# Assuming constants.py is in utils, SegmentManager in core, others in ui
try:
    from utils import constants
    from core.correction_window_logic import SegmentManager
    from .correction_window_ui import CorrectionWindowUI
    from .correction_window_callbacks import CorrectionCallbackHandler
    from .audio_player import AudioPlayer # AudioPlayer is in the same 'ui' directory
except ImportError:
    # Fallback for different execution contexts
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__)) # ui directory
    project_root = os.path.dirname(current_dir) # Project root
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Try imports again with adjusted path
    from utils import constants
    from core.correction_window_logic import SegmentManager
    from ui.correction_window_ui import CorrectionWindowUI # Relative to project root
    from ui.correction_window_callbacks import CorrectionCallbackHandler # Relative to project root
    from ui.audio_player import AudioPlayer # Relative to project root

logger = logging.getLogger(__name__)

class CorrectionWindow:
    def __init__(self, parent_root, initial_include_timestamps=True, initial_include_end_times=False):
        self.parent_root = parent_root
        self.window = tk.Toplevel(parent_root)
        self.window.title("Transcription Correction Tool")
        self.window.geometry("850x650")

        # --- Core Components ---
        self.segment_manager = SegmentManager(parent_window_for_dialogs=self.window)
        self.audio_player = None # Initialized in _load_files_core_logic
        self.audio_player_update_queue = None

        # --- UI and Callbacks ---
        # Note: Callbacks are passed to UI, UI then calls them.
        # CorrectionCallbackHandler needs 'self' (CorrectionWindow instance) to access other components.
        self.callback_handler = CorrectionCallbackHandler(self)
        
        self.ui = CorrectionWindowUI(
            parent_tk_window=self.window,
            browse_transcription_callback=self.callback_handler.browse_transcription_file,
            browse_audio_callback=self.callback_handler.browse_audio_file,
            load_files_callback=self.callback_handler.load_files, # This will call self._load_files_core_logic
            assign_speakers_callback=self.callback_handler.open_assign_speakers_dialog, # This will call self._open_assign_speakers_dialog_core_logic
            save_changes_callback=self.callback_handler.save_changes, # This will call self._save_changes_core_logic
            toggle_play_pause_callback=self._toggle_play_pause, # Direct to CW method
            seek_audio_callback=self._seek_audio, # Direct to CW method
            on_progress_bar_seek_callback=self._on_progress_bar_seek, # Direct to CW method
            jump_to_segment_start_callback=self._jump_to_segment_start_action, # Direct to CW method
            text_area_double_click_callback=self.callback_handler.handle_text_area_double_click,
            text_area_right_click_callback=self.callback_handler.handle_text_area_right_click,
            text_area_left_click_edit_mode_callback=self.callback_handler.handle_text_area_left_click_edit_mode,
            on_speaker_click_callback=self.callback_handler.on_speaker_click,
            on_merge_click_callback=self.callback_handler.on_merge_click
        )
        
        # --- State Variables ---
        self.output_include_timestamps = initial_include_timestamps
        self.output_include_end_times = initial_include_end_times
        
        self.currently_highlighted_text_seg_id = None
        self.edit_mode_active = False
        self.editing_segment_id = None
        self.editing_segment_text_start_index = None # Not strictly needed here if UI handles focus
        self.right_clicked_segment_id = None # Used by context menu logic

        # --- Context Menu (Managed by CorrectionWindow directly) ---
        self.context_menu = tk.Menu(self.ui.transcription_text, tearoff=0)
        self.context_menu.add_command(label="Edit Segment Text", command=self.callback_handler.edit_segment_text_action_from_menu)
        self.context_menu.add_command(label="Set/Edit Timestamps", command=self.callback_handler.set_segment_timestamps_action_menu, state=tk.DISABLED)
        self.context_menu.add_command(label="Remove Segment", command=self.callback_handler.remove_segment_action_from_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Change Speaker for this Segment", command=self.callback_handler.change_segment_speaker_action_menu)

        # --- Window Setup ---
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda e: self.callback_handler.save_changes()) 
        self.window.after(100, self._poll_audio_player_queue)
        logger.info("CorrectionWindow fully initialized with refactored components.")

    # --- Core Logic Methods (called by CallbackHandler or internally) ---
    def _load_files_core_logic(self, transcription_path: str, audio_path: str):
        logger.info(f"Core load: TXT='{transcription_path}', AUDIO='{audio_path}'")
        try:
            if self.audio_player:
                self.audio_player.stop_resources(); self.audio_player = None
            if self.audio_player_update_queue:
                while not self.audio_player_update_queue.empty(): self.audio_player_update_queue.get_nowait()
                self.audio_player_update_queue = None

            with open(transcription_path, 'r', encoding='utf-8') as f: lines = f.readlines()
            
            # Use SegmentManager for parsing
            if not self.segment_manager.parse_transcription_lines(lines):
                 self._disable_audio_controls(); return 
            
            self._render_segments_to_text_area() 
            
            self.audio_player = AudioPlayer(audio_path, on_error_callback=self._handle_audio_player_error)
            if not self.audio_player.is_ready(): return 

            self.audio_player_update_queue = self.audio_player.get_update_queue()
            
            max_prog = self.audio_player.total_frames / self.audio_player.frame_rate if self.audio_player.frame_rate > 0 else 100
            curr_prog = self.audio_player.current_frame / self.audio_player.frame_rate if self.audio_player.frame_rate > 0 else 0
            self.ui.update_audio_progress_bar_display(curr_prog, max_prog)
            self._update_time_labels_display()

            self.ui.set_widgets_state([self.ui.play_pause_button, self.ui.rewind_button, self.ui.forward_button, self.ui.audio_progress_bar, self.ui.save_changes_button], tk.NORMAL)
            self.ui.assign_speakers_button.config(state=tk.NORMAL if self.segment_manager.segments else tk.DISABLED)
            self.ui.load_files_button.config(text="Reload Files")
            self.ui.set_play_pause_button_text("Play")
            logger.info("Files loaded successfully (core logic).")
        except Exception as e: 
            logger.exception("Error during _load_files_core_logic.")
            messagebox.showerror("Load Error", f"Unexpected error during file loading: {e}", parent=self.window)
            self._disable_audio_controls()

    def _save_changes_core_logic(self):
        formatted_lines = self.segment_manager.format_segments_for_saving(
            self.output_include_timestamps, self.output_include_end_times
        )
        if not formatted_lines: 
            messagebox.showwarning("Nothing to Save", "No valid segments found to save.", parent=self.window); return
            
        content_to_save = "\n".join(formatted_lines) + "\n" 
        initial_filename = "corrected_transcription.txt"
        if self.ui.get_transcription_file_path(): 
            try:
                base, ext = os.path.splitext(os.path.basename(self.ui.get_transcription_file_path()))
                initial_filename = f"{base}_corrected{ext if ext else '.txt'}"
            except Exception: pass 

        save_path = filedialog.asksaveasfilename(
            initialfile=initial_filename, defaultextension=".txt", 
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")], 
            parent=self.window, title="Save Corrected Transcription As"
        )
        if not save_path: logger.info("Save operation cancelled."); return
        try:
            with open(save_path, 'w', encoding='utf-8') as f: f.write(content_to_save)
            messagebox.showinfo("Saved Successfully", f"Corrected transcription saved to:\n{save_path}", parent=self.window)
            logger.info(f"Changes saved to {save_path}")
        except Exception as e: 
            messagebox.showerror("Save Error", f"Could not save file: {e}", parent=self.window)
            logger.exception(f"Error during _save_changes_core_logic to {save_path}")

    def _open_assign_speakers_dialog_core_logic(self):
        # This method contains the Tkinter dialog creation for assigning speakers.
        # It directly uses self.segment_manager.speaker_map and self.segment_manager.unique_speaker_labels
        dialog = tk.Toplevel(self.window); dialog.title("Assign Speaker Names"); dialog.transient(self.window); dialog.grab_set()
        main_frame = ttk.Frame(dialog, padding="10"); main_frame.pack(expand=True, fill=tk.BOTH)
        ttk.Label(main_frame, text="Assign custom names to raw speaker labels or add new speakers:").pack(anchor="w", pady=(0,5))

        canvas_frame = ttk.Frame(main_frame); canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0); scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas)
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"), width=e.width))
        canvas.create_window((0,0), window=inner_frame, anchor="nw"); canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Mousewheel scrolling for the dialog (specific to this dialog)
        def _on_mousewheel_dialog(event): canvas.yview_scroll(-1*(event.delta // 120), "units")
        dialog.bind_all("<MouseWheel>", _on_mousewheel_dialog) 

        add_new_speaker_frame = ttk.Frame(inner_frame); add_new_speaker_frame.pack(fill=tk.X, pady=(5,10), padx=5)
        ttk.Label(add_new_speaker_frame, text="Add New Speaker:").pack(side=tk.LEFT, padx=(0,2))
        new_raw_id_var = tk.StringVar(); ttk.Entry(add_new_speaker_frame, textvariable=new_raw_id_var, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Label(add_new_speaker_frame, text="Display Name:").pack(side=tk.LEFT, padx=(5,2))
        new_display_name_var = tk.StringVar(); ttk.Entry(add_new_speaker_frame, textvariable=new_display_name_var, width=15).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Separator(inner_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        
        entries = {}
        if not self.segment_manager.unique_speaker_labels:
             ttk.Label(inner_frame, text="No existing speaker labels found.").pack(pady=10)
        for raw_label in sorted(list(self.segment_manager.unique_speaker_labels)):
            row_frame = ttk.Frame(inner_frame); row_frame.pack(fill=tk.X, expand=True, padx=5) 
            ttk.Label(row_frame, text=f"{raw_label}:", width=20).pack(side=tk.LEFT, padx=5, pady=3) 
            entry = ttk.Entry(row_frame); entry.insert(0, self.segment_manager.speaker_map.get(raw_label, "")); entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=3)
            entries[raw_label] = entry
        
        btn_frame = ttk.Frame(main_frame); btn_frame.pack(fill=tk.X, pady=(10,0), side=tk.BOTTOM) 
        def on_save_dialog():
            for raw_label, entry_widget in entries.items():
                custom_name = entry_widget.get().strip()
                if custom_name: self.segment_manager.speaker_map[raw_label] = custom_name 
                elif raw_label in self.segment_manager.speaker_map: del self.segment_manager.speaker_map[raw_label] 
            new_raw_id = new_raw_id_var.get().strip(); new_display_name = new_display_name_var.get().strip()
            if new_raw_id: 
                if new_raw_id not in self.segment_manager.unique_speaker_labels: self.segment_manager.unique_speaker_labels.add(new_raw_id)
                if new_display_name: self.segment_manager.speaker_map[new_raw_id] = new_display_name
                elif new_raw_id in self.segment_manager.speaker_map and not new_display_name: del self.segment_manager.speaker_map[new_raw_id]
            self._render_segments_to_text_area(); dialog.unbind_all("<MouseWheel>"); dialog.destroy()
        
        ttk.Button(btn_frame, text="Save", command=on_save_dialog).pack(side=tk.RIGHT, padx=5) 
        ttk.Button(btn_frame, text="Cancel", command=lambda: (dialog.unbind_all("<MouseWheel>"), dialog.destroy())).pack(side=tk.RIGHT) 
        # Dialog sizing and centering logic (can be a helper)
        self._center_dialog(dialog, min_width=580, base_height=350)
        dialog.wait_window()

    def _set_segment_timestamps_dialog_logic(self, segment_id: str):
        segment = self.segment_manager.get_segment_by_id(segment_id)
        if not segment: logger.warning(f"Set Timestamps: Could not find segment {segment_id}"); return

        dialog = tk.Toplevel(self.window); dialog.title(f"Set Timestamps"); dialog.transient(self.window); dialog.grab_set(); dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding="10"); frame.pack(expand=True, fill=tk.BOTH)
        ttk.Label(frame, text=f"Segment: '{segment['text'][:50]}...'").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,10))
        
        start_val = self.segment_manager.seconds_to_time_str(segment['start_time']) if segment.get("has_timestamps") else "00:00.000"
        end_val = self.segment_manager.seconds_to_time_str(segment['end_time']) if segment.get("has_explicit_end_time") and segment['end_time'] is not None else "00:00.000"
        
        ttk.Label(frame, text="Start (MM:SS.mmm):").grid(row=1,column=0,sticky="w"); start_var=tk.StringVar(value=start_val); start_e=ttk.Entry(frame,textvariable=start_var,width=12); start_e.grid(row=1,column=1,sticky="ew")
        ttk.Label(frame, text="End (MM:SS.mmm):").grid(row=2,column=0,sticky="w"); end_var=tk.StringVar(value=end_val); end_e=ttk.Entry(frame,textvariable=end_var,width=12); end_e.grid(row=2,column=1,sticky="ew")
        
        btn_frame=ttk.Frame(frame); btn_frame.grid(row=3,column=0,columnspan=2,pady=(10,0))
        def on_ok():
            new_start = self.segment_manager.time_str_to_seconds(start_var.get())
            new_end = self.segment_manager.time_str_to_seconds(end_var.get())
            if new_start is None or new_end is None: messagebox.showerror("Invalid Format", "Use MM:SS.mmm.", parent=dialog); return
            if new_start > new_end: messagebox.showerror("Invalid Range", "Start must be <= End.", parent=dialog); return # Allow start == end for point events?
            
            if self.segment_manager.update_segment_timestamps(segment_id, new_start, new_end):
                self._render_segments_to_text_area()
            dialog.destroy()
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.LEFT); ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
        start_e.focus_set(); start_e.selection_range(0, tk.END)
        self._center_dialog(dialog); dialog.wait_window()

    def _change_segment_speaker_dialog_logic(self, segment_id: str):
        segment = self.segment_manager.get_segment_by_id(segment_id)
        if not segment: return

        choices = {raw: self.segment_manager.speaker_map.get(raw, raw) for raw in self.segment_manager.unique_speaker_labels}
        if constants.NO_SPEAKER_LABEL not in choices: choices[constants.NO_SPEAKER_LABEL] = "(No Speaker)"
        if not choices: messagebox.showinfo("Change Speaker", "No speakers available.", parent=self.window); return
        
        menu = tk.Menu(self.window, tearoff=0)
        def set_speaker(raw_label):
            self.segment_manager.update_segment_speaker(segment_id, raw_label)
            self._render_segments_to_text_area()
        for raw, display in sorted(choices.items(), key=lambda item: item[1]): 
            menu.add_command(label=display, command=lambda rl=raw: set_speaker(rl))
        try: menu.tk_popup(self.window.winfo_pointerx(), self.window.winfo_pointery())
        except tk.TclError: menu.tk_popup(self.window.winfo_rootx()+100, self.window.winfo_rooty()+100)


    # --- UI Rendering and State Management ---
    def _render_segments_to_text_area(self):
        if self.edit_mode_active: self._exit_edit_mode(save_changes=False)
        
        self.ui.transcription_text.config(state=tk.NORMAL)
        self.ui.transcription_text.delete("1.0", tk.END)
        self.currently_highlighted_text_seg_id = None
        
        if not self.segment_manager.segments:
            self.ui.transcription_text.insert(tk.END, "No transcription data loaded or all lines were unparsable.")
            self.ui.transcription_text.config(state=tk.DISABLED)
            return
        
        for idx, seg in enumerate(self.segment_manager.segments):
            line_start_idx = self.ui.transcription_text.index(tk.END + "-1c linestart")
            
            has_ts = seg.get("has_timestamps", False)
            has_explicit_end = seg.get("has_explicit_end_time", False)
            has_speaker = seg['speaker_raw'] != constants.NO_SPEAKER_LABEL
            display_speaker = self.segment_manager.speaker_map.get(seg['speaker_raw'], seg['speaker_raw']) if has_speaker else ""
            
            prefix, merge_tuple = "  ", ()
            if idx > 0 and has_speaker and self.segment_manager.segments[idx-1].get("speaker_raw") == seg["speaker_raw"]:
                prefix, merge_tuple = "+ ", ("merge_tag_style", seg['id'])
            if not has_ts and not has_speaker: prefix = ""; merge_tuple = ()
            self.ui.transcription_text.insert(tk.END, prefix, merge_tuple)
            
            if has_ts:
                start_str = self.segment_manager.seconds_to_time_str(seg['start_time'])
                ts_str = f"[{start_str} - {self.segment_manager.seconds_to_time_str(seg['end_time'])}] " if has_explicit_end and seg['end_time'] is not None else f"[{start_str}] "
                self.ui.transcription_text.insert(tk.END, ts_str, ("timestamp_tag_style", seg['id']))
            elif has_speaker:
                self.ui.transcription_text.insert(tk.END, "[No Timestamps] ", ("no_timestamp_tag_style", seg['id']))
            
            if has_speaker:
                spk_start = self.ui.transcription_text.index(tk.END)
                self.ui.transcription_text.insert(tk.END, display_speaker, ("speaker_tag_style", seg['id']))
                self.ui.transcription_text.tag_add(f"speaker_{seg['id']}", spk_start, self.ui.transcription_text.index(tk.END))
                self.ui.transcription_text.insert(tk.END, ": ")
            
            self.ui.transcription_text.insert(tk.END, seg['text'], ("inactive_text_default", seg["text_tag_id"]))
            self.ui.transcription_text.insert(tk.END, "\n")
            self.ui.transcription_text.tag_add(seg['id'], line_start_idx, self.ui.transcription_text.index(tk.END + "-1c lineend"))
            
        self.ui.transcription_text.config(state=tk.DISABLED)

    def _toggle_ui_for_edit_mode(self, disable: bool):
        """Enable/disable UI elements when entering/exiting text edit mode."""
        new_state = tk.DISABLED if disable else tk.NORMAL
        widgets_to_toggle = [
            self.ui.browse_transcription_button, self.ui.browse_audio_button,
            self.ui.load_files_button, self.ui.save_changes_button
        ]
        self.ui.set_widgets_state(widgets_to_toggle, new_state)
        self.ui.assign_speakers_button.config(state=new_state if not disable and self.segment_manager.segments else tk.DISABLED)

        # Context menu items
        is_segment_sel = bool(self.right_clicked_segment_id) and not disable
        for item_label in ["Edit Segment Text", "Set/Edit Timestamps", "Remove Segment", "Change Speaker for this Segment"]:
            self.context_menu.entryconfig(item_label, state=(tk.NORMAL if is_segment_sel else tk.DISABLED) if not disable else tk.DISABLED)

    def _enter_edit_mode(self, segment_id_to_edit: str):
        if self.edit_mode_active and self.editing_segment_id == segment_id_to_edit: return
        if self.edit_mode_active: self._exit_edit_mode(save_changes=True)

        target_segment = self.segment_manager.get_segment_by_id(segment_id_to_edit)
        if not target_segment: return

        self.edit_mode_active = True; self.editing_segment_id = segment_id_to_edit
        self.ui.transcription_text.config(state=tk.NORMAL)
        self._toggle_ui_for_edit_mode(disable=True)
        
        text_tag_id = target_segment["text_tag_id"]
        try:
            ranges = self.ui.transcription_text.tag_ranges(text_tag_id)
            if ranges:
                self.ui.transcription_text.tag_remove("inactive_text_default", ranges[0], ranges[1])
                self.ui.transcription_text.tag_add("editing_active_segment_text", ranges[0], ranges[1])
                self.ui.transcription_text.focus_set()
                self.ui.transcription_text.mark_set(tk.INSERT, ranges[0])
                self.ui.transcription_text.see(ranges[0])
            else: self._exit_edit_mode(save_changes=False); return
        except tk.TclError: self._exit_edit_mode(save_changes=False); return

        if target_segment.get("has_timestamps", False):
            self.ui.jump_to_segment_button.pack(side=tk.LEFT, padx=(5,0), before=self.ui.audio_progress_bar)
        else: self.ui.jump_to_segment_button.pack_forget()
        logger.info(f"Entered edit mode for segment: {self.editing_segment_id}")

    def _exit_edit_mode(self, save_changes: bool = True):
        if not self.edit_mode_active or not self.editing_segment_id: return
        
        original_segment = self.segment_manager.get_segment_by_id(self.editing_segment_id)
        text_updated = False
        if original_segment:
            text_tag_id = original_segment["text_tag_id"]
            try:
                ranges = self.ui.transcription_text.tag_ranges(text_tag_id)
                if ranges:
                    self.ui.transcription_text.tag_remove("editing_active_segment_text", ranges[0], ranges[1])
                    self.ui.transcription_text.tag_add("inactive_text_default", ranges[0], ranges[1])
                    if save_changes:
                        modified_text = self.ui.transcription_text.get(ranges[0], ranges[1]).strip()
                        if self.segment_manager.update_segment_text(self.editing_segment_id, modified_text):
                            text_updated = True
            except Exception as e: logger.exception(f"Error updating segment text for {self.editing_segment_id}: {e}")
        
        self.ui.jump_to_segment_button.pack_forget()
        self.ui.transcription_text.config(state=tk.DISABLED)
        self._toggle_ui_for_edit_mode(disable=False)
        self.edit_mode_active = False; self.editing_segment_id = None
        if text_updated: self._render_segments_to_text_area()

    def _get_segment_id_from_text_index(self, text_index_str: str) -> str | None:
        """Helper to find a segment ID tag at a given text index."""
        tags_at_index = self.ui.transcription_text.tag_names(text_index_str)
        for tag in tags_at_index:
            if tag.startswith("seg_") and tag.count('_') == 1: 
                parts = tag.split('_')
                if len(parts) == 2 and parts[0] == 'seg' and parts[1].isdigit():
                    return tag 
        return None

    # --- Audio Player Logic ---
    def _poll_audio_player_queue(self):
        if self.audio_player_update_queue:
            try:
                while not self.audio_player_update_queue.empty():
                    message = self.audio_player_update_queue.get_nowait()
                    msg_type = message[0]
                    if msg_type == 'initialized': 
                        current_f, total_f, rate = message[1], message[2], message[3]
                        max_val = total_f / rate if rate > 0 else 100
                        curr_val = current_f / rate if rate > 0 else 0
                        self.ui.update_audio_progress_bar_display(curr_val, max_val)
                        self._update_time_labels_display()
                    elif msg_type == 'progress':
                        current_f = message[1]
                        if self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                            self._update_time_labels_display() # Uses audio_player.current_frame
                            current_s = current_f / self.audio_player.frame_rate
                            self.ui.update_audio_progress_bar_display(current_s)
                            if not self.edit_mode_active: self._highlight_current_segment(current_s)
                    elif msg_type in ['started', 'resumed']: self.ui.set_play_pause_button_text("Pause")
                    elif msg_type == 'paused': self.ui.set_play_pause_button_text("Play")
                    elif msg_type == 'finished':
                        self.ui.set_play_pause_button_text("Play")
                        if self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                            end_s = self.audio_player.total_frames / self.audio_player.frame_rate
                            self.ui.update_audio_progress_bar_display(end_s); self._update_time_labels_display()
                    elif msg_type == 'stopped': self.ui.set_play_pause_button_text("Play")
                    elif msg_type == 'error': self._handle_audio_player_error(message[1])
                    self.audio_player_update_queue.task_done()
            except queue.Empty: pass 
            except Exception as e: logger.exception("Error processing audio player queue.")
        if hasattr(self, 'window') and self.window.winfo_exists(): self.window.after(50, self._poll_audio_player_queue) 

    def _toggle_play_pause(self):
        if not self.audio_player or not self.audio_player.is_ready(): 
            msg = "Audio player not ready." if self.ui.get_audio_file_path() and os.path.exists(self.ui.get_audio_file_path()) else "Please load an audio file."
            messagebox.showinfo("Audio Not Ready", msg, parent=self.window); return
        if self.audio_player.playing: self.audio_player.pause()
        else: self.audio_player.play() 

    def _seek_audio(self, delta_seconds):
        if not self.audio_player or not self.audio_player.is_ready() or self.audio_player.frame_rate <= 0: return
        target_frame = int((self.audio_player.current_frame / self.audio_player.frame_rate + delta_seconds) * self.audio_player.frame_rate)
        self.audio_player.set_pos_frames(target_frame) 

    def _on_progress_bar_seek(self, value_str: str): 
        if not self.audio_player or not self.audio_player.is_ready() or self.audio_player.frame_rate <= 0: return
        self.audio_player.set_pos_frames(int(float(value_str) * self.audio_player.frame_rate)) 

    def _update_time_labels_display(self): # Renamed to avoid conflict with UI method
        if not self.audio_player or not self.audio_player.is_ready() or self.audio_player.frame_rate <= 0:
            self.ui.update_time_labels_display("--:--.---", "--:--.---"); return
        current_s = self.audio_player.current_frame / self.audio_player.frame_rate
        total_s = self.audio_player.total_frames / self.audio_player.frame_rate 
        self.ui.update_time_labels_display(self.segment_manager.seconds_to_time_str(current_s), 
                                           self.segment_manager.seconds_to_time_str(total_s))

    def _highlight_current_segment(self, current_playback_seconds: float):
        if self.edit_mode_active: return
        newly_highlighted_id = None
        for i, seg in enumerate(self.segment_manager.segments):
            if not seg.get("has_timestamps"): continue
            start = seg["start_time"]
            # Determine effective end time for highlighting
            effective_end = seg["end_time"] if seg.get("has_explicit_end_time") and seg["end_time"] is not None \
                  else (self.segment_manager.segments[i+1]["start_time"] if (i + 1) < len(self.segment_manager.segments) and self.segment_manager.segments[i+1].get("has_timestamps") \
                  else (self.audio_player.total_frames / self.audio_player.frame_rate if self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0 else float('inf')))
            
            if effective_end is not None and start <= current_playback_seconds < effective_end:
                newly_highlighted_id = seg['id']; break 
        
        if self.currently_highlighted_text_seg_id != newly_highlighted_id:
            # De-highlight old
            if self.currently_highlighted_text_seg_id:
                old_seg = self.segment_manager.get_segment_by_id(self.currently_highlighted_text_seg_id)
                if old_seg: self._apply_text_highlight(old_seg["text_tag_id"], active=False)
            # Highlight new
            if newly_highlighted_id:
                new_seg = self.segment_manager.get_segment_by_id(newly_highlighted_id)
                if new_seg: self._apply_text_highlight(new_seg["text_tag_id"], active=True, scroll_to=True)
            self.currently_highlighted_text_seg_id = newly_highlighted_id

    def _apply_text_highlight(self, text_tag_id: str, active: bool, scroll_to: bool = False):
        try:
            ranges = self.ui.transcription_text.tag_ranges(text_tag_id)
            if ranges:
                active_tag = "active_text_highlight"
                inactive_tag = "inactive_text_default"
                self.ui.transcription_text.tag_remove(inactive_tag if active else active_tag, ranges[0], ranges[1])
                self.ui.transcription_text.tag_add(active_tag if active else inactive_tag, ranges[0], ranges[1])
                if active and scroll_to: self.ui.transcription_text.see(ranges[0])
        except tk.TclError: pass # Tag might not exist or other Tcl issue

    def _jump_to_segment_start_action(self): # This is an audio control action
        if not self.edit_mode_active or not self.editing_segment_id: return
        segment = self.segment_manager.get_segment_by_id(self.editing_segment_id)
        if not segment or not self.audio_player or not self.audio_player.is_ready(): return
        if not segment.get("has_timestamps", False): 
            messagebox.showwarning("Playback Warning", "Segment has no original timestamps.", parent=self.window); return
        target_time = max(0, segment["start_time"] - 1.0) # Jump 1s before
        if self.audio_player.frame_rate > 0: self.audio_player.set_pos_frames(int(target_time * self.audio_player.frame_rate))

    def _handle_audio_player_error(self, error_message):
        logger.error(f"AudioPlayer reported error: {error_message}")
        messagebox.showerror("Audio Player Error", error_message, parent=self.window)
        self._disable_audio_controls()
        if self.audio_player: self.audio_player.stop_resources(); self.audio_player = None
        self.ui.set_play_pause_button_text("Play")

    def _disable_audio_controls(self):
        widgets = [self.ui.play_pause_button, self.ui.rewind_button, self.ui.forward_button, self.ui.audio_progress_bar]
        self.ui.set_widgets_state(widgets, tk.DISABLED)
        self.ui.update_audio_progress_bar_display(0)
        if hasattr(self.ui, 'jump_to_segment_button') and self.ui.jump_to_segment_button.winfo_exists():
            self.ui.jump_to_segment_button.pack_forget()

    def _center_dialog(self, dialog_window, min_width=300, base_height=200, height_per_item=30, num_items=0):
        """Helper to center a Toplevel dialog relative to its parent."""
        dialog_window.update_idletasks() # Ensure dimensions are calculated
        
        # Calculate desired height
        desired_height = base_height + (num_items * height_per_item)
        max_dialog_height = int(self.window.winfo_height() * 0.8)
        dialog_height = max(200, min(desired_height, max_dialog_height))
        dialog_width = min_width

        dialog_window.minsize(min_width, 150)
        dialog_window.geometry(f"{dialog_width}x{dialog_height}")
        
        # Recalculate actual dialog width/height after setting geometry (it might adjust)
        dialog_window.update_idletasks() 
        d_width = dialog_window.winfo_width()
        d_height = dialog_window.winfo_height()

        parent_x = self.window.winfo_rootx()
        parent_y = self.window.winfo_rooty()
        parent_width = self.window.winfo_width()
        parent_height = self.window.winfo_height()
        
        x = parent_x + (parent_width // 2) - (d_width // 2)
        y = parent_y + (parent_height // 2) - (d_height // 2)
        dialog_window.geometry(f"+{max(0,x)}+{max(0,y)}")
        dialog_window.lift()

    def _on_close(self):
        logger.info("CorrectionWindow: Close requested.")
        if self.edit_mode_active:
            if not messagebox.askyesno("Unsaved Edit", "You are currently editing a segment. Exiting now will discard this specific change. Are you sure?", parent=self.window, icon=messagebox.WARNING):
                logger.info("CorrectionWindow: Close cancelled by user due to active edit.")
                return 
            self._exit_edit_mode(save_changes=False) 
        
        if self.audio_player: 
            logger.debug("CorrectionWindow: Stopping audio player resources on close.")
            self.audio_player.stop_resources() 
        self.audio_player = None 
        self.audio_player_update_queue = None 

        try: # Unbind mousewheel if it was bound by a dialog
            if hasattr(self, 'window') and self.window.winfo_exists():
                 self.window.unbind_all("<MouseWheel>") 
        except tk.TclError: pass 

        logger.debug("CorrectionWindow: Destroying window.")
        if hasattr(self, 'window') and self.window.winfo_exists(): 
            self.window.destroy()
