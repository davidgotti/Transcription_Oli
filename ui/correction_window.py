# ui/correction_window.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog 
import logging
import os
import queue

try:
    from utils import constants 
    from core.correction_window_logic import SegmentManager
    from .correction_window_ui import CorrectionWindowUI 
    from .correction_window_callbacks import CorrectionCallbackHandler
    from .audio_player import AudioPlayer
except ImportError:
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir) 
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from utils import constants
    from core.correction_window_logic import SegmentManager
    from ui.correction_window_ui import CorrectionWindowUI
    from ui.correction_window_callbacks import CorrectionCallbackHandler
    from ui.audio_player import AudioPlayer

logger = logging.getLogger(__name__)

class CorrectionWindow:
    def __init__(self, parent_root, initial_include_timestamps=True, initial_include_end_times=False):
        self.parent_root = parent_root
        self.window = tk.Toplevel(parent_root)
        self.window.title("Transcription Correction Tool")
        self.window.geometry("900x700") 

        self.segment_manager = SegmentManager(parent_window_for_dialogs=self.window)
        self.audio_player = None 
        self.audio_player_update_queue = None

        self.callback_handler = CorrectionCallbackHandler(self)
        
        self.ui = CorrectionWindowUI(
            parent_tk_window=self.window,
            browse_transcription_callback=self.callback_handler.browse_transcription_file,
            browse_audio_callback=self.callback_handler.browse_audio_file,
            load_files_callback=self.callback_handler.load_files,
            assign_speakers_callback=self.callback_handler.open_assign_speakers_dialog,
            save_changes_callback=self.callback_handler.save_changes,
            toggle_play_pause_callback=self._toggle_play_pause,
            seek_audio_callback=self._seek_audio,
            on_progress_bar_seek_callback=self._on_progress_bar_seek,
            jump_to_segment_start_callback=self._jump_to_segment_start_action,
            text_area_double_click_callback=self.callback_handler.handle_text_area_double_click,
            text_area_right_click_callback=self.callback_handler.handle_text_area_right_click, 
            text_area_left_click_edit_mode_callback=self.callback_handler.handle_text_area_left_click_edit_mode,
            on_speaker_click_callback=self.callback_handler.on_speaker_click,
            on_merge_click_callback=self.callback_handler.on_merge_click
        )
        
        self.output_include_timestamps = initial_include_timestamps
        self.output_include_end_times = initial_include_end_times
        
        self.currently_highlighted_text_seg_id = None
        
        self.text_edit_mode_active = False 
        self.editing_segment_id = None    
        self.text_content_start_index_in_edit = None # Store precise start index for text edit

        self.timestamp_edit_mode_active = False 
        self.editing_segment_id_for_ts = None 
        self.timestamp_edit_dialog_instance = None 

        self.right_clicked_segment_id = None 

        self._setup_context_menu() 

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind('<Control-s>', lambda e: self.callback_handler.save_changes()) 
        self.window.bind('<Escape>', self._handle_escape_key) 
        self.window.after(100, self._poll_audio_player_queue)
        logger.info("CorrectionWindow fully initialized with new edit mode states.")

    def _setup_context_menu(self):
        self.context_menu = tk.Menu(self.ui.transcription_text, tearoff=0)
        self.context_menu.add_command(label="Edit Segment Text", command=self.callback_handler.edit_segment_text_action_from_menu)
        self.context_menu.add_command(label="Edit Timestamps", command=self.callback_handler.edit_segment_timestamps_action_menu) 
        self.context_menu.add_command(label="Add New Segment", command=self.callback_handler.add_new_segment_action_menu) 
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Remove Segment", command=self.callback_handler.remove_segment_action_from_menu)
        self.context_menu.add_command(label="Change Speaker for this Segment", command=self.callback_handler.change_segment_speaker_action_menu)

    def configure_and_show_context_menu(self, event):
        is_segment_selected = bool(self.right_clicked_segment_id)
        
        can_edit_text = is_segment_selected and not self.timestamp_edit_mode_active
        can_edit_ts = is_segment_selected and not self.text_edit_mode_active
        can_remove = is_segment_selected and not self.is_any_edit_mode_active()
        can_change_speaker = is_segment_selected and not self.is_any_edit_mode_active()
        
        self.context_menu.entryconfig("Add New Segment", state=tk.NORMAL)

        self.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if can_edit_text else tk.DISABLED)
        self.context_menu.entryconfig("Edit Timestamps", state=tk.NORMAL if can_edit_ts else tk.DISABLED)
        self.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if can_remove else tk.DISABLED)
        self.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if can_change_speaker else tk.DISABLED)
        
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError: 
            self.context_menu.tk_popup(self.window.winfo_pointerx(), self.window.winfo_pointery())

    def is_any_edit_mode_active(self) -> bool:
        return self.text_edit_mode_active or self.timestamp_edit_mode_active

    def _exit_all_edit_modes(self, save_changes: bool = True):
        exited_text = self.text_edit_mode_active
        exited_ts = self.timestamp_edit_mode_active

        if self.text_edit_mode_active:
            self._exit_text_edit_mode(save_changes=save_changes)
        if self.timestamp_edit_mode_active: # Check again in case first exit affected it
            self._exit_timestamp_edit_mode(save_changes=False if not save_changes else True) 
        
        # If no re-render was triggered by save_changes=True in either exit method,
        # but a mode was active, re-render to ensure consistent UI state (e.g. remove highlights)
        # This is now handled by _exit_text_edit_mode always calling render,
        # and _exit_timestamp_edit_mode calling render if save_changes is false.

    def _handle_escape_key(self, event=None):
        if self.text_edit_mode_active:
            logger.debug("Escape key pressed during text edit mode. Exiting without saving text change.")
            self._exit_text_edit_mode(save_changes=False) 
            return "break"
        elif self.timestamp_edit_mode_active and self.timestamp_edit_dialog_instance:
            logger.debug("Escape key pressed during timestamp edit mode. Closing dialog (cancel).")
            self.timestamp_edit_dialog_instance.destroy() # This will trigger _on_timestamp_dialog_close
            return "break"
        return None

    def _load_files_core_logic(self, transcription_path: str, audio_path: str):
        logger.info(f"Core load: TXT='{transcription_path}', AUDIO='{audio_path}'")
        self._exit_all_edit_modes(save_changes=False) 
        try:
            if self.audio_player:
                self.audio_player.stop_resources(); self.audio_player = None
            if self.audio_player_update_queue:
                while not self.audio_player_update_queue.empty(): self.audio_player_update_queue.get_nowait()
                self.audio_player_update_queue = None

            with open(transcription_path, 'r', encoding='utf-8') as f: lines = f.readlines()
            
            if not self.segment_manager.parse_transcription_lines(lines):
                 self._disable_audio_controls(); return 
            
            self._render_segments_to_text_area() 
            
            self.audio_player = AudioPlayer(audio_path, on_error_callback=self._handle_audio_player_error)
            if not self.audio_player.is_ready(): self._disable_audio_controls(); return 

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
        self._exit_all_edit_modes(save_changes=True) 
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
        self._exit_all_edit_modes(save_changes=True)
        dialog = tk.Toplevel(self.window); dialog.title("Assign Speaker Names"); dialog.transient(self.window); dialog.grab_set()
        main_frame = ttk.Frame(dialog, padding="10"); main_frame.pack(expand=True, fill=tk.BOTH)
        ttk.Label(main_frame, text="Assign custom names to raw speaker labels or add new speakers:").pack(anchor="w", pady=(0,5))

        canvas_frame = ttk.Frame(main_frame); canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0); scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas)
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"), width=e.width))
        canvas.create_window((0,0), window=inner_frame, anchor="nw"); canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
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
        self._center_dialog(dialog, min_width=580, base_height=350)
        dialog.wait_window()

    def _edit_segment_timestamps_dialog_logic(self, segment_id: str):
        segment = self.segment_manager.get_segment_by_id(segment_id)
        if not segment: 
            logger.warning(f"Edit Timestamps: Could not find segment {segment_id}")
            self._exit_timestamp_edit_mode(save_changes=False) 
            return

        dialog = tk.Toplevel(self.window)
        dialog.title(f"Edit Timestamps")
        dialog.transient(self.window)
        dialog.grab_set() 
        dialog.resizable(False, False)
        self.timestamp_edit_dialog_instance = dialog 

        frame = ttk.Frame(dialog, padding="15")
        frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(frame, text=f"Segment: '{segment['text'][:50].strip()}...'").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        
        current_start_str = self.segment_manager.seconds_to_time_str(segment.get('start_time')) if segment.get("has_timestamps") else ""
        current_end_str = self.segment_manager.seconds_to_time_str(segment.get('end_time')) if segment.get("has_explicit_end_time") and segment.get('end_time') is not None else ""

        ttk.Label(frame, text="Start (MM:SS.mmm):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        start_var = tk.StringVar(value=current_start_str)
        start_entry = ttk.Entry(frame, textvariable=start_var, width=12)
        start_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

        ttk.Label(frame, text="End (MM:SS.mmm):").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        end_var = tk.StringVar(value=current_end_str)
        end_entry = ttk.Entry(frame, textvariable=end_var, width=12)
        end_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        
        def clear_timestamps_action():
            start_var.set("")
            end_var.set("")
        ttk.Button(frame, text="Clear", command=clear_timestamps_action).grid(row=1, column=2, rowspan=2, padx=5, pady=2, sticky="ns")

        feedback_label = ttk.Label(frame, text="", foreground="red", wraplength=250)
        feedback_label.grid(row=3, column=0, columnspan=3, pady=(5,0), sticky="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=(10, 0))

        def on_ok():
            new_start_str = start_var.get().strip()
            new_end_str = end_var.get().strip()
            
            success, msg = self.segment_manager.update_segment_timestamps(segment_id, new_start_str or None, new_end_str or None)

            if success:
                self._on_timestamp_dialog_close(dialog, save=True) 
                self._render_segments_to_text_area() 
                if msg: 
                    messagebox.showwarning("Timestamp Warning", msg, parent=self.window) 
            else:
                feedback_label.config(text=f"Error: {msg}")
        
        def on_cancel():
            self._on_timestamp_dialog_close(dialog, save=False)

        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=5)
        
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._on_timestamp_dialog_close(dialog, save=False))
        start_entry.focus_set()
        start_entry.selection_range(0, tk.END)
        self._center_dialog(dialog, min_width=350)

    def _on_timestamp_dialog_close(self, dialog_instance, save: bool):
        if dialog_instance == self.timestamp_edit_dialog_instance: 
            self.timestamp_edit_dialog_instance = None 
            self._exit_timestamp_edit_mode(save_changes=save) 
        if dialog_instance and dialog_instance.winfo_exists(): 
            dialog_instance.destroy()

    def _add_new_segment_dialog_logic(self, reference_segment_id_for_positioning: str | None, split_char_index: int | None = None):
        self._exit_all_edit_modes(save_changes=True) 

        dialog = tk.Toplevel(self.window)
        dialog_title = "Split Segment" if split_char_index is not None else "Add New Segment"
        dialog.title(dialog_title)
        dialog.transient(self.window)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding="15")
        frame.pack(expand=True, fill=tk.BOTH)

        position_var = tk.StringVar(value="below")
        if split_char_index is None and reference_segment_id_for_positioning:
            ttk.Label(frame, text="Position relative to selected:").grid(row=0, column=0, sticky="w", pady=2)
            pos_frame = ttk.Frame(frame)
            ttk.Radiobutton(pos_frame, text="Above", variable=position_var, value="above").pack(side=tk.LEFT)
            ttk.Radiobutton(pos_frame, text="Below", variable=position_var, value="below").pack(side=tk.LEFT, padx=5)
            pos_frame.grid(row=0, column=1, columnspan=2, sticky="w", pady=2)
        elif split_char_index is None and not reference_segment_id_for_positioning: 
             ttk.Label(frame, text="Adding new segment to the end.").grid(row=0, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Label(frame, text="New Segment Timestamp Type:").grid(row=1, column=0, sticky="w", pady=2)
        ts_type_var = tk.StringVar(value="No Timestamps") 
        ts_type_options = ["No Timestamps", "Start Time Only", "Start and End Times"]
        ts_type_map = {"No Timestamps": "none", "Start Time Only": "start_only", "Start and End Times": "start_end"}
        ts_type_dropdown = ttk.Combobox(frame, textvariable=ts_type_var, values=ts_type_options, state="readonly", width=25)
        ts_type_dropdown.set(ts_type_options[0]) 
        ts_type_dropdown.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(frame, text="New Segment Speaker:").grid(row=2, column=0, sticky="w", pady=2)
        speaker_choices = {constants.NO_SPEAKER_LABEL: "(No Speaker / Unknown)"}
        for raw_label in sorted(list(self.segment_manager.unique_speaker_labels)):
            speaker_choices[raw_label] = self.segment_manager.speaker_map.get(raw_label, raw_label)
        
        speaker_display_names = list(speaker_choices.values())
        speaker_raw_map = {v: k for k, v in speaker_choices.items()} 

        speaker_var = tk.StringVar()
        speaker_dropdown = ttk.Combobox(frame, textvariable=speaker_var, values=speaker_display_names, state="readonly", width=25)
        if speaker_display_names: speaker_dropdown.set(speaker_display_names[0]) 
        speaker_dropdown.grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)

        feedback_label = ttk.Label(frame, text="", foreground="red")
        feedback_label.grid(row=3, column=0, columnspan=3, pady=(5,0), sticky="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=(10,0))

        def on_ok_add_segment():
            selected_ts_type_display = ts_type_var.get()
            actual_ts_type = ts_type_map.get(selected_ts_type_display, "none")
            
            selected_speaker_display = speaker_var.get()
            actual_speaker_raw = speaker_raw_map.get(selected_speaker_display, constants.NO_SPEAKER_LABEL)

            if split_char_index is not None: 
                original_seg_id = reference_segment_id_for_positioning 
                if not original_seg_id:
                    feedback_label.config(text="Error: Original segment for split not identified.")
                    return

                _, new_seg_id = self.segment_manager.split_segment(
                    original_segment_id=original_seg_id,
                    text_split_index=split_char_index,
                    new_segment_speaker=actual_speaker_raw,
                    new_segment_ts_type=actual_ts_type
                )
                if new_seg_id:
                    self._render_segments_to_text_area()
                    messagebox.showinfo("Segment Split", f"Segment split. New segment '{new_seg_id}' created. You may need to edit its text and timestamps.", parent=self.window) 
                    dialog.destroy()
                else:
                    feedback_label.config(text="Error: Failed to split segment.")
            else: 
                new_segment_data = {
                    "text": "", # Stored as empty, render will show placeholder
                    "speaker_raw": actual_speaker_raw,
                    "start_time": 0.0, 
                    "end_time": None,
                    "has_timestamps": actual_ts_type != "none",
                    "has_explicit_end_time": actual_ts_type == "start_end"
                }
                position_to_insert = position_var.get() if reference_segment_id_for_positioning else "end"
                
                new_seg_id = self.segment_manager.add_segment(
                    new_segment_data,
                    reference_segment_id=reference_segment_id_for_positioning,
                    position=position_to_insert
                )
                if new_seg_id:
                    self._render_segments_to_text_area()
                    messagebox.showinfo("Segment Added", f"New segment '{new_seg_id}' added. Please edit its text and timestamps as needed.",parent=self.window) 
                    dialog.destroy()
                else:
                    feedback_label.config(text="Error: Failed to add new segment.")

        ttk.Button(btn_frame, text="OK", command=on_ok_add_segment).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

        self._center_dialog(dialog, min_width=400)
        dialog.wait_window()


    def _change_segment_speaker_dialog_logic(self, segment_id: str):
        self._exit_all_edit_modes(save_changes=True)
        segment = self.segment_manager.get_segment_by_id(segment_id)
        if not segment: return

        choices = {raw: self.segment_manager.speaker_map.get(raw, raw) for raw in self.segment_manager.unique_speaker_labels}
        if constants.NO_SPEAKER_LABEL not in choices: choices[constants.NO_SPEAKER_LABEL] = "(No Speaker / Unknown)" 
        if not choices: messagebox.showinfo("Change Speaker", "No speakers available to assign.", parent=self.window); return
        
        menu = tk.Menu(self.window, tearoff=0)
        def set_speaker(raw_label):
            self.segment_manager.update_segment_speaker(segment_id, raw_label)
            self._render_segments_to_text_area()
        for raw, display in sorted(choices.items(), key=lambda item: item[1]): 
            menu.add_command(label=display, command=lambda rl=raw: set_speaker(rl))
        try: menu.tk_popup(self.window.winfo_pointerx(), self.window.winfo_pointery())
        except tk.TclError: menu.tk_popup(self.window.winfo_rootx()+100, self.window.winfo_rooty()+100)

    def _render_segments_to_text_area(self):
        # Important: Exit any edit mode *before* clearing and re-rendering.
        # This prevents trying to save data from a text area that's about to be wiped.
        # Also, don't save changes from this specific call, as it's often a refresh.
        if self.text_edit_mode_active:
             self._exit_text_edit_mode(save_changes=False) # Exit without saving, render will show true state
        if self.timestamp_edit_mode_active:
             self._exit_timestamp_edit_mode(save_changes=False) # Dialog handles its own saves
        
        self.ui.transcription_text.config(state=tk.NORMAL)
        self.ui.transcription_text.delete("1.0", tk.END)
        self.currently_highlighted_text_seg_id = None 
        
        if not self.segment_manager.segments:
            self.ui.transcription_text.insert(tk.END, "No transcription data loaded or all lines were unparsable.")
            self.ui.transcription_text.config(state=tk.DISABLED)
            return
        
        for idx, seg in enumerate(self.segment_manager.segments):
            line_start_idx_str = self.ui.transcription_text.index(tk.END + "-1c linestart") 
            
            has_ts = seg.get("has_timestamps", False)
            has_explicit_end = seg.get("has_explicit_end_time", False)
            has_speaker = seg['speaker_raw'] != constants.NO_SPEAKER_LABEL
            display_speaker = self.segment_manager.speaker_map.get(seg['speaker_raw'], seg['speaker_raw']) if has_speaker else ""
            
            prefix, merge_tuple = "  ", ()
            if idx > 0 and has_speaker and self.segment_manager.segments[idx-1].get("speaker_raw") == seg["speaker_raw"] and seg['speaker_raw'] != constants.NO_SPEAKER_LABEL:
                prefix, merge_tuple = "+ ", ("merge_tag_style", seg['id']) 
            if not has_ts and not has_speaker: prefix = ""; merge_tuple = () 
            self.ui.transcription_text.insert(tk.END, prefix, merge_tuple)
            
            ts_area_start_idx_str = self.ui.transcription_text.index(tk.END) 
            ts_tag_for_double_click = seg.get("timestamp_tag_id") 

            if has_ts:
                start_str = self.segment_manager.seconds_to_time_str(seg['start_time'])
                ts_str_display = f"[{start_str} - {self.segment_manager.seconds_to_time_str(seg['end_time'])}] " if has_explicit_end and seg['end_time'] is not None else f"[{start_str}] "
                self.ui.transcription_text.insert(tk.END, ts_str_display, ("timestamp_tag_style", seg['id'], ts_tag_for_double_click))
            elif has_speaker: 
                self.ui.transcription_text.insert(tk.END, "[No Timestamps] ", ("no_timestamp_tag_style", seg['id'], ts_tag_for_double_click))
            
            ts_area_end_idx_str = self.ui.transcription_text.index(tk.END)
            if ts_tag_for_double_click: 
                 self.ui.transcription_text.tag_add(ts_tag_for_double_click, ts_area_start_idx_str, ts_area_end_idx_str)

            if has_speaker:
                self.ui.transcription_text.insert(tk.END, display_speaker, ("speaker_tag_style", seg['id']))
                self.ui.transcription_text.insert(tk.END, ": ")
            
            text_to_display = seg['text']
            current_text_tags = ["inactive_text_default", seg.get("text_tag_id")] # Base tags

            if not text_to_display: # Check if actual text is empty
                text_to_display = constants.EMPTY_SEGMENT_PLACEHOLDER
                current_text_tags = ["placeholder_text_style", seg.get("text_tag_id")] 

            text_content_actual_start_idx_str = self.ui.transcription_text.index(tk.END) 
            self.ui.transcription_text.insert(tk.END, text_to_display, tuple(filter(None, current_text_tags))) # Ensure only valid tags
            text_content_actual_end_idx_str = self.ui.transcription_text.index(tk.END)

            if seg.get("text_tag_id"): 
                 self.ui.transcription_text.tag_add(seg.get("text_tag_id"), text_content_actual_start_idx_str, text_content_actual_end_idx_str)

            self.ui.transcription_text.insert(tk.END, "\n")
            self.ui.transcription_text.tag_add(seg['id'], line_start_idx_str, self.ui.transcription_text.index(tk.END + "-1c lineend"))
            
        self.ui.transcription_text.config(state=tk.DISABLED)

    def _toggle_global_ui_for_edit_mode(self, disable: bool):
        new_state = tk.DISABLED if disable else tk.NORMAL
        widgets_to_toggle = [
            self.ui.browse_transcription_button, self.ui.browse_audio_button,
            self.ui.load_files_button, self.ui.save_changes_button,
            self.ui.assign_speakers_button 
        ]
        self.ui.set_widgets_state(widgets_to_toggle, new_state)

    def _enter_text_edit_mode(self, segment_id_to_edit: str):
        if self.is_any_edit_mode_active(): self._exit_all_edit_modes(save_changes=True)

        target_segment = self.segment_manager.get_segment_by_id(segment_id_to_edit)
        if not target_segment: return

        self.text_edit_mode_active = True
        self.editing_segment_id = segment_id_to_edit
        self.text_content_start_index_in_edit = None 
        
        self.ui.transcription_text.config(state=tk.NORMAL)
        self._toggle_global_ui_for_edit_mode(disable=True)
        
        text_tag_id = target_segment.get("text_tag_id")
        if not text_tag_id:
            logger.error(f"Segment {segment_id_to_edit} has no text_tag_id. Cannot enter text edit mode.")
            self._exit_text_edit_mode(save_changes=False); return

        try:
            ranges = self.ui.transcription_text.tag_ranges(text_tag_id)
            if not ranges: 
                logger.error(f"No ranges found for text_tag_id {text_tag_id} of segment {segment_id_to_edit} on entering edit mode.")
                self._exit_text_edit_mode(save_changes=False); return

            edit_start_index = ranges[0]
            edit_end_index = ranges[1]
            
            current_text_in_widget = self.ui.transcription_text.get(edit_start_index, edit_end_index)
            
            # If current text is placeholder, clear it for editing
            if current_text_in_widget == constants.EMPTY_SEGMENT_PLACEHOLDER:
                self.ui.transcription_text.delete(edit_start_index, edit_end_index)
                # The text_tag_id now effectively becomes zero-length at edit_start_index
                # We'll re-apply it if necessary, or just use edit_start_index as the known start
                edit_end_index = edit_start_index # Update end_index for styling the (now empty) spot

            # Remove previous style tags from the precise range
            self.ui.transcription_text.tag_remove("placeholder_text_style", edit_start_index, edit_end_index)
            self.ui.transcription_text.tag_remove("inactive_text_default", edit_start_index, edit_end_index)
            # Apply editing style to the precise range (which is zero-length if placeholder was just deleted)
            self.ui.transcription_text.tag_add("editing_active_segment_text", edit_start_index, edit_end_index) 
            
            self.text_content_start_index_in_edit = edit_start_index # Store the precise Tkinter index
            
            self.ui.transcription_text.focus_set()
            self.ui.transcription_text.mark_set(tk.INSERT, edit_start_index) 
            self.ui.transcription_text.see(edit_start_index)

        except tk.TclError as e:
            logger.error(f"TclError entering text edit mode for {text_tag_id}: {e}")
            self._exit_text_edit_mode(save_changes=False); return

        if target_segment.get("has_timestamps", False):
            self.ui.jump_to_segment_button.pack(side=tk.LEFT, padx=(5,0), before=self.ui.audio_progress_bar)
        else: self.ui.jump_to_segment_button.pack_forget()
        logger.info(f"Entered text edit mode for segment: {self.editing_segment_id}")

    def _exit_text_edit_mode(self, save_changes: bool = True):
        if not self.text_edit_mode_active or not self.editing_segment_id:
            return
        
        logger.debug(f"Exiting text edit mode for segment: {self.editing_segment_id}. Save changes: {save_changes}")
        text_updated = False
        original_segment_obj = self.segment_manager.get_segment_by_id(self.editing_segment_id) 

        if save_changes and original_segment_obj:
            # Use the stored self.text_content_start_index_in_edit as the definitive start
            true_start_of_text_content = self.text_content_start_index_in_edit
            
            if true_start_of_text_content:
                try:
                    # Get text from this known start to the end of its line in the widget
                    text_content_end_index_on_line = self.ui.transcription_text.index(f"{true_start_of_text_content} lineend")
                    modified_text = self.ui.transcription_text.get(true_start_of_text_content, text_content_end_index_on_line).strip()
                    
                    logger.debug(f"Retrieved modified text for {self.editing_segment_id} from {true_start_of_text_content} to {text_content_end_index_on_line}: '{modified_text}'")

                    # If the user typed the placeholder text, or if it's empty, save as ""
                    if modified_text == constants.EMPTY_SEGMENT_PLACEHOLDER or not modified_text:
                        final_text_to_save = ""
                        logger.debug("Modified text is placeholder or empty, will save as empty string.")
                    else:
                        final_text_to_save = modified_text
                    
                    if self.segment_manager.update_segment_text(self.editing_segment_id, final_text_to_save):
                        text_updated = True
                    logger.info(f"Segment {self.editing_segment_id} text updated in SegmentManager to: '{final_text_to_save}'")

                except tk.TclError as e:
                    logger.error(f"TclError getting/setting text for segment {self.editing_segment_id}: {e}")
                except Exception as e: 
                    logger.exception(f"Error updating segment text for {self.editing_segment_id}: {e}")
            else:
                logger.warning(f"Segment {self.editing_segment_id} missing cached start_index_in_edit on exit. Cannot reliably save text.")
        
        # Clean up UI tag "editing_active_segment_text".
        # The subsequent _render_segments_to_text_area will apply correct default/placeholder styles.
        try:
            self.ui.transcription_text.tag_remove("editing_active_segment_text", "1.0", tk.END)
        except tk.TclError:
            logger.warning("TclError removing 'editing_active_segment_text' globally.")


        self.ui.jump_to_segment_button.pack_forget()
        self._toggle_global_ui_for_edit_mode(disable=False) 
        
        editing_segment_id_before_clear = self.editing_segment_id 
        self.text_edit_mode_active = False
        self.editing_segment_id = None
        self.text_content_start_index_in_edit = None # Clear the stored index
        
        logger.info(f"Exited text edit mode for segment {editing_segment_id_before_clear}. Text updated status: {text_updated}")
        
        self._render_segments_to_text_area() # Always re-render to reflect placeholder or actual text
        if editing_segment_id_before_clear:
            self._scroll_to_segment_if_visible(editing_segment_id_before_clear)


    def _enter_timestamp_edit_mode(self, segment_id_to_edit_ts: str):
        if self.is_any_edit_mode_active(): self._exit_all_edit_modes(save_changes=True)

        target_segment = self.segment_manager.get_segment_by_id(segment_id_to_edit_ts)
        if not target_segment: return

        self.timestamp_edit_mode_active = True
        self.editing_segment_id_for_ts = segment_id_to_edit_ts
        self._toggle_global_ui_for_edit_mode(disable=True) 

        ts_tag_id = target_segment.get("timestamp_tag_id") 
        if ts_tag_id:
            try:
                ranges = self.ui.transcription_text.tag_ranges(ts_tag_id)
                if ranges:
                    self.ui.transcription_text.tag_add("editing_active_timestamp", ranges[0], ranges[1])
            except tk.TclError: pass
        
        if target_segment.get("has_timestamps", False):
            self.ui.jump_to_segment_button.pack(side=tk.LEFT, padx=(5,0), before=self.ui.audio_progress_bar)
        else: self.ui.jump_to_segment_button.pack_forget()

        logger.info(f"Entered timestamp edit mode for segment: {self.editing_segment_id_for_ts}")
        self._edit_segment_timestamps_dialog_logic(segment_id_to_edit_ts) 

    def _exit_timestamp_edit_mode(self, save_changes: bool): 
        if not self.timestamp_edit_mode_active or not self.editing_segment_id_for_ts: return

        logger.info(f"Exiting timestamp edit mode for segment: {self.editing_segment_id_for_ts}. Save flag from dialog: {save_changes}")
        
        editing_segment_id_for_ts_before_clear = self.editing_segment_id_for_ts # Store before clearing
        
        segment_exited = self.segment_manager.get_segment_by_id(editing_segment_id_for_ts_before_clear)
        if segment_exited:
            ts_tag_id = segment_exited.get("timestamp_tag_id")
            if ts_tag_id:
                try:
                    self.ui.transcription_text.tag_remove("editing_active_timestamp", "1.0", tk.END) 
                except tk.TclError: pass
        
        self.ui.jump_to_segment_button.pack_forget()
        self._toggle_global_ui_for_edit_mode(disable=False) 
        
        self.timestamp_edit_mode_active = False
        self.editing_segment_id_for_ts = None
        
        logger.info(f"Exited timestamp edit mode for {editing_segment_id_for_ts_before_clear}.")
        
        # Re-render if dialog was cancelled (save_changes=False) or if OK but no data change (render in dialog handles data change)
        # To be safe and ensure consistent UI (e.g. highlight removal):
        if not save_changes: # If dialog was cancelled or closed via 'X'
            self._render_segments_to_text_area()
        
        # Always try to scroll, _render_segments_to_text_area might have been called by dialog's OK
        if editing_segment_id_for_ts_before_clear:
             self._scroll_to_segment_if_visible(editing_segment_id_for_ts_before_clear)


    def _get_segment_id_from_text_index(self, text_index_str: str) -> str | None:
        tags_at_index = self.ui.transcription_text.tag_names(text_index_str)
        for tag_prefix in ["text_content_seg_", "ts_content_seg_"]:
            for tag in tags_at_index:
                if tag.startswith(tag_prefix):
                    base_id = "seg_" + tag.split("_seg_")[-1]
                    if any(s["id"] == base_id for s in self.segment_manager.segments):
                        return base_id
        for tag in tags_at_index:
            if tag.startswith("seg_") and tag.count('_') == 1: 
                 parts = tag.split('_', 1)
                 if len(parts) == 2 and parts[0] == 'seg': 
                    if any(s["id"] == tag for s in self.segment_manager.segments):
                        return tag
        return None

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
                            self._update_time_labels_display() 
                            current_s = current_f / self.audio_player.frame_rate
                            self.ui.update_audio_progress_bar_display(current_s)
                            if not self.is_any_edit_mode_active(): 
                                self._highlight_current_segment(current_s)
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

    def _update_time_labels_display(self): 
        if not self.audio_player or not self.audio_player.is_ready() or self.audio_player.frame_rate <= 0:
            self.ui.update_time_labels_display("--:--.---", "--:--.---"); return
        current_s = self.audio_player.current_frame / self.audio_player.frame_rate
        total_s = self.audio_player.total_frames / self.audio_player.frame_rate 
        self.ui.update_time_labels_display(self.segment_manager.seconds_to_time_str(current_s), 
                                           self.segment_manager.seconds_to_time_str(total_s))

    def _highlight_current_segment(self, current_playback_seconds: float):
        if self.is_any_edit_mode_active(): return 
        newly_highlighted_id = None
        for i, seg in enumerate(self.segment_manager.segments):
            if not seg.get("has_timestamps"): continue
            start_s = seg["start_time"] 
            if start_s is None: continue 

            effective_end_s = None
            if seg.get("has_explicit_end_time") and seg["end_time"] is not None:
                effective_end_s = seg["end_time"]
            elif (i + 1) < len(self.segment_manager.segments) and \
                 self.segment_manager.segments[i+1].get("has_timestamps") and \
                 self.segment_manager.segments[i+1]["start_time"] is not None:
                effective_end_s = self.segment_manager.segments[i+1]["start_time"]
            elif self.audio_player and self.audio_player.is_ready() and self.audio_player.frame_rate > 0:
                effective_end_s = self.audio_player.total_frames / self.audio_player.frame_rate
            else:
                effective_end_s = float('inf')
            
            if effective_end_s is not None and start_s <= current_playback_seconds < effective_end_s:
                newly_highlighted_id = seg['id']; break 
        
        if self.currently_highlighted_text_seg_id != newly_highlighted_id:
            if self.currently_highlighted_text_seg_id:
                old_seg = self.segment_manager.get_segment_by_id(self.currently_highlighted_text_seg_id)
                if old_seg: self._apply_text_highlight(old_seg.get("text_tag_id"), active=False) 
            if newly_highlighted_id:
                new_seg = self.segment_manager.get_segment_by_id(newly_highlighted_id)
                if new_seg: self._apply_text_highlight(new_seg.get("text_tag_id"), active=True, scroll_to=True)
            self.currently_highlighted_text_seg_id = newly_highlighted_id

    def _apply_text_highlight(self, text_tag_id: str | None, active: bool, scroll_to: bool = False):
        if not text_tag_id: return 
        try:
            ranges = self.ui.transcription_text.tag_ranges(text_tag_id)
            if ranges:
                active_tag = "active_text_highlight"
                inactive_tag = "inactive_text_default" 
                placeholder_tag = "placeholder_text_style"
                
                current_text_in_widget = self.ui.transcription_text.get(ranges[0], ranges[1])
                is_placeholder = (current_text_in_widget == constants.EMPTY_SEGMENT_PLACEHOLDER)

                # Remove all potentially conflicting style tags first
                self.ui.transcription_text.tag_remove(active_tag, ranges[0], ranges[1])
                self.ui.transcription_text.tag_remove(inactive_tag, ranges[0], ranges[1])
                self.ui.transcription_text.tag_remove(placeholder_tag, ranges[0], ranges[1])

                if active:
                    self.ui.transcription_text.tag_add(active_tag, ranges[0], ranges[1])
                else: # Deactivating
                    if is_placeholder:
                         self.ui.transcription_text.tag_add(placeholder_tag, ranges[0], ranges[1])
                    else:
                         self.ui.transcription_text.tag_add(inactive_tag, ranges[0], ranges[1])
                
                if active and scroll_to: self.ui.transcription_text.see(ranges[0])
        except tk.TclError: 
            logger.warning(f"TclError applying highlight for tag {text_tag_id}. Tag might not exist or range is invalid.")
            pass 

    def _jump_to_segment_start_action(self): 
        segment_id_to_jump = self.editing_segment_id if self.text_edit_mode_active else self.editing_segment_id_for_ts
        if not segment_id_to_jump: return

        segment = self.segment_manager.get_segment_by_id(segment_id_to_jump)
        if not segment or not self.audio_player or not self.audio_player.is_ready(): return
        if not segment.get("has_timestamps", False) or segment.get("start_time") is None: 
            messagebox.showwarning("Playback Warning", "Segment has no valid start timestamp.", parent=self.window); return
        target_time = max(0, segment["start_time"] - 1.0) 
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
        dialog_window.update_idletasks() 
        desired_height = base_height + (num_items * height_per_item)
        max_dialog_height = int(self.window.winfo_height() * 0.8)
        dialog_height = max(150, min(desired_height, max_dialog_height)) 
        dialog_width = min_width

        dialog_window.minsize(min_width, 150) 
        dialog_window.geometry(f"{dialog_width}x{dialog_height}")
        
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

    def _scroll_to_segment_if_visible(self, segment_id: str):
        segment_to_see = self.segment_manager.get_segment_by_id(segment_id)
        if segment_to_see:
            line_id_tag = segment_to_see.get("id") 
            if line_id_tag:
                try:
                    ranges = self.ui.transcription_text.tag_ranges(line_id_tag)
                    if ranges:
                        self.ui.transcription_text.see(ranges[0]) 
                        logger.debug(f"Scrolled to segment {segment_id} (line tag {line_id_tag}) after edit and re-render.")
                        return
                except tk.TclError:
                    logger.warning(f"TclError trying to scroll to line tag {line_id_tag} for segment {segment_id}.")
            
            text_content_tag = segment_to_see.get("text_tag_id")
            if text_content_tag:
                try:
                    ranges = self.ui.transcription_text.tag_ranges(text_content_tag)
                    if ranges:
                        self.ui.transcription_text.see(ranges[0])
                        logger.debug(f"Scrolled to segment {segment_id} (text tag {text_content_tag}) after edit and re-render.")
                        return
                except tk.TclError:
                    logger.warning(f"TclError trying to scroll to text tag {text_content_tag} for segment {segment_id}.")
            logger.warning(f"Could not find a suitable tag for segment {segment_id} to scroll to after re-render.")


    def _on_close(self):
        logger.info("CorrectionWindow: Close requested.")
        if self.is_any_edit_mode_active():
            if self.timestamp_edit_mode_active and self.timestamp_edit_dialog_instance:
                if not messagebox.askyesno("Unsaved Edit", "You are currently editing timestamps. Exiting now will discard these changes. Are you sure?", parent=self.window, icon=messagebox.WARNING):
                    return
                self._on_timestamp_dialog_close(self.timestamp_edit_dialog_instance, save=False) 
            elif self.text_edit_mode_active: 
                if not messagebox.askyesno("Unsaved Edit", "You are currently editing text. Exiting now will discard this specific change. Are you sure?", parent=self.window, icon=messagebox.WARNING):
                    return
                self._exit_text_edit_mode(save_changes=False)
        
        self._exit_all_edit_modes(save_changes=False) 

        if self.audio_player: 
            logger.debug("CorrectionWindow: Stopping audio player resources on close.")
            self.audio_player.stop_resources() 
        self.audio_player = None 
        self.audio_player_update_queue = None 

        try: 
            if hasattr(self, 'window') and self.window.winfo_exists():
                 self.window.unbind_all("<MouseWheel>") 
        except tk.TclError: pass 

        logger.debug("CorrectionWindow: Destroying window.")
        if hasattr(self, 'window') and self.window.winfo_exists(): 
            self.window.destroy()

