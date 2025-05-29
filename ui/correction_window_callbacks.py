# ui/correction_window_callbacks.py
import tkinter as tk
from tkinter import filedialog, messagebox
import logging
import os

try:
    from utils import constants
    # SegmentManager is now in core
    from core.correction_window_logic import SegmentManager
except ImportError:
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir) 
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from utils import constants
    from core.correction_window_logic import SegmentManager


logger = logging.getLogger(__name__)

class CorrectionCallbackHandler:
    def __init__(self, correction_window_instance):
        self.cw = correction_window_instance # Main CorrectionWindow instance
        # self.ui = correction_window_instance.ui # CorrectionWindowUI instance
        # self.segment_manager = correction_window_instance.segment_manager # SegmentManager instance
        # self.audio_player = correction_window_instance.audio_player # AudioPlayer instance
        logger.info("CorrectionCallbackHandler initialized.")

    # --- Properties to access components from CorrectionWindow ---
    @property
    def ui(self): return self.cw.ui
    @property
    def segment_manager(self) -> SegmentManager: return self.cw.segment_manager
    @property
    def audio_player(self): return self.cw.audio_player
    @property
    def window(self): return self.cw.window


    # --- File Operations Callbacks ---
    def browse_transcription_file(self):
        if self.cw.edit_mode_active: return
        fp = filedialog.askopenfilename(title="Select Transcription File", filetypes=[("Text files", "*.txt"), ("All files", "*.*")], parent=self.window)
        if fp: self.ui.transcription_file_path_var.set(fp); logger.info(f"Tx file selected: {fp}")

    def browse_audio_file(self):
        if self.cw.edit_mode_active: return
        fp = filedialog.askopenfilename(title="Select Audio File", filetypes=[("Audio files", "*.wav *.mp3 *.flac *.m4a"), ("All files", "*.*")], parent=self.window)
        if fp: self.ui.audio_file_path_var.set(fp); logger.info(f"Audio file selected: {fp}")

    def load_files(self):
        if self.cw.edit_mode_active:
            messagebox.showwarning("Action Blocked", "Please exit text edit mode before loading new files.", parent=self.window)
            return

        txt_p = self.ui.get_transcription_file_path()
        aud_p = self.ui.get_audio_file_path()

        if not (txt_p and os.path.exists(txt_p)):
            messagebox.showerror("File Error", "Please select a valid transcription file.", parent=self.window); return
        if not (aud_p and os.path.exists(aud_p)):
            messagebox.showerror("File Error", "Please select a valid audio file.", parent=self.window); return
        
        self.cw._load_files_core_logic(txt_p, aud_p) # Delegate core loading to main CW

    def save_changes(self):
        if self.cw.edit_mode_active:
            messagebox.showwarning("Save Blocked", "Please finish editing the current segment before saving.", parent=self.window)
            return
        if not self.segment_manager.segments:
             messagebox.showinfo("Nothing to Save", "No transcription data loaded to save.", parent=self.window)
             return
        
        self.cw._save_changes_core_logic() # Delegate core saving to main CW

    # --- Speaker Assignment ---
    def open_assign_speakers_dialog(self):
        if self.cw.edit_mode_active:
            messagebox.showwarning("Action Blocked", "Please exit text edit mode first.", parent=self.window); return
        if not self.segment_manager.segments:
            messagebox.showinfo("Assign Speakers", "No segments loaded. Please load files first.", parent=self.window); return
        
        self.cw._open_assign_speakers_dialog_core_logic() # Delegate to main CW

    # --- Text Area and Segment Editing Callbacks ---
    def handle_text_area_double_click(self, event):
        if self.cw.edit_mode_active: return 
        text_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        segment_id = self.cw._get_segment_id_from_text_index(text_index)
        if segment_id:
            logger.info(f"Double-clicked on segment: {segment_id}. Entering edit mode.")
            self.cw._enter_edit_mode(segment_id)
            return "break" 

    def handle_text_area_right_click(self, event): # For context menu
        if self.cw.edit_mode_active: return "break" 
        text_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        self.cw.right_clicked_segment_id = self.cw._get_segment_id_from_text_index(text_index)
        
        is_segment_sel = bool(self.cw.right_clicked_segment_id)
        self.cw.context_menu.entryconfig("Edit Segment Text", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.cw.context_menu.entryconfig("Set/Edit Timestamps", state=tk.NORMAL if is_segment_sel else tk.DISABLED) 
        self.cw.context_menu.entryconfig("Remove Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        self.cw.context_menu.entryconfig("Change Speaker for this Segment", state=tk.NORMAL if is_segment_sel else tk.DISABLED)
        
        self.cw.context_menu.tk_popup(event.x_root, event.y_root)
        return "break" 

    def handle_text_area_left_click_edit_mode(self, event):
        """ If in edit mode, clicking outside the editable text region exits edit mode. """
        if not self.cw.edit_mode_active or not self.cw.editing_segment_id: return

        clicked_index_str = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        editing_seg = self.segment_manager.get_segment_by_id(self.cw.editing_segment_id)
        if not editing_seg: self.cw._exit_edit_mode(save_changes=False); return 

        text_content_tag_id = editing_seg["text_tag_id"]
        try:
            tag_ranges = self.ui.transcription_text.tag_ranges(text_content_tag_id)
            if tag_ranges:
                start_idx, end_idx = tag_ranges[0], tag_ranges[1]
                if self.ui.transcription_text.compare(clicked_index_str, ">=", start_idx) and \
                   self.ui.transcription_text.compare(clicked_index_str, "<", end_idx):
                    return # Click is inside the editable text, allow normal Tkinter text widget behavior
            
            logger.debug("Clicked outside editable text area during edit mode. Saving and exiting.")
            self.cw._exit_edit_mode(save_changes=True) 
        except tk.TclError: self.cw._exit_edit_mode(save_changes=False)
        except Exception as e:
            logger.exception(f"Error in _handle_click_during_edit_mode: {e}")
            self.cw._exit_edit_mode(save_changes=False)

    # --- Context Menu Actions ---
    def edit_segment_text_action_from_menu(self):
        if not self.cw.right_clicked_segment_id: return
        if self.cw.edit_mode_active and self.cw.editing_segment_id == self.cw.right_clicked_segment_id: return 
        elif self.cw.edit_mode_active: self.cw._exit_edit_mode(save_changes=True)
        
        logger.info(f"Context menu 'Edit Segment Text' for: {self.cw.right_clicked_segment_id}")
        self.cw._enter_edit_mode(self.cw.right_clicked_segment_id)
        self.cw.right_clicked_segment_id = None 

    def set_segment_timestamps_action_menu(self):
        if not self.cw.right_clicked_segment_id: return
        self.cw._set_segment_timestamps_dialog_logic(self.cw.right_clicked_segment_id) # Delegate
        self.cw.right_clicked_segment_id = None

    def remove_segment_action_from_menu(self):
        if self.cw.edit_mode_active or not self.cw.right_clicked_segment_id: return
        
        segment_to_remove = self.segment_manager.get_segment_by_id(self.cw.right_clicked_segment_id)
        if not segment_to_remove: return

        confirm = messagebox.askyesno("Confirm Remove", 
                                     f"Are you sure you want to remove this segment?\n'{segment_to_remove['text'][:70]}...'", 
                                     parent=self.window)
        if confirm:
            if self.segment_manager.remove_segment(self.cw.right_clicked_segment_id):
                self.cw._render_segments_to_text_area() 
        self.cw.right_clicked_segment_id = None 

    def change_segment_speaker_action_menu(self): 
        if self.cw.edit_mode_active or not self.cw.right_clicked_segment_id: return
        self.cw._change_segment_speaker_dialog_logic(self.cw.right_clicked_segment_id) # Delegate
        # self.cw.right_clicked_segment_id is cleared within the dialog logic or after menu pops up

    # --- Tag Click Callbacks (Speaker, Merge) ---
    def on_speaker_click(self, event): 
        if self.cw.edit_mode_active: return "break" 
        clicked_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        seg_id = self.cw._get_segment_id_from_text_index(clicked_index)
        logger.info(f"Speaker label left-clicked on segment {seg_id}. No direct action implemented yet for left-click.")
        # Could potentially open a quick change speaker menu here in the future.
        return "break" 

    def on_merge_click(self, event):
        if self.cw.edit_mode_active: 
            messagebox.showwarning("Action Blocked", "Please exit text edit mode before merging.", parent=self.window)
            return "break"
        
        clicked_index_str = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        tags_at_click = self.ui.transcription_text.tag_names(clicked_index_str)
        if "merge_tag_style" not in tags_at_click: return 

        segment_id_of_merge_symbol = self.cw._get_segment_id_from_text_index(clicked_index_str)
        if not segment_id_of_merge_symbol: return "break"

        current_segment = self.segment_manager.get_segment_by_id(segment_id_of_merge_symbol)
        current_segment_index = next((i for i, s in enumerate(self.segment_manager.segments) if s["id"] == segment_id_of_merge_symbol), -1)

        if current_segment_index <= 0: 
            messagebox.showwarning("Merge Error", "Cannot merge: No previous segment.", parent=self.window)
            return "break"
            
        previous_segment = self.segment_manager.segments[current_segment_index - 1]

        if previous_segment["speaker_raw"] != current_segment["speaker_raw"] or \
           previous_segment["speaker_raw"] == constants.NO_SPEAKER_LABEL:
            messagebox.showwarning("Merge Error", "Cannot merge: Speakers differ or previous has no assigned speaker.", parent=self.window)
            return "break"

        confirm_merge = messagebox.askyesno("Confirm Merge", 
                                           f"Merge segment:\n'{current_segment['text'][:70]}...'\n\nwith previous segment:\n'{previous_segment['text'][:70]}...'?",
                                           parent=self.window)
        if not confirm_merge: return "break"

        if self.segment_manager.merge_segment_with_previous(segment_id_of_merge_symbol):
            self.cw._render_segments_to_text_area() 
        else:
            messagebox.showerror("Merge Error", "An internal error occurred during merge operation.", parent=self.window)
        return "break"