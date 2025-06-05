# ui/correction_window_callbacks.py
import tkinter as tk
from tkinter import filedialog, messagebox
import logging
import os

try:
    from utils import constants
    from core.correction_window_logic import SegmentManager # Already updated
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
        self.cw = correction_window_instance 
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
        if self.cw.is_any_edit_mode_active(): return # Check generic edit mode
        fp = filedialog.askopenfilename(title="Select Transcription File", filetypes=[("Text files", "*.txt"), ("All files", "*.*")], parent=self.window)
        if fp: self.ui.transcription_file_path_var.set(fp); logger.info(f"Tx file selected: {fp}")

    def browse_audio_file(self):
        if self.cw.is_any_edit_mode_active(): return
        fp = filedialog.askopenfilename(title="Select Audio File", filetypes=[("Audio files", "*.wav *.mp3 *.flac *.m4a"), ("All files", "*.*")], parent=self.window)
        if fp: self.ui.audio_file_path_var.set(fp); logger.info(f"Audio file selected: {fp}")

    def load_files(self):
        if self.cw.is_any_edit_mode_active():
            messagebox.showwarning("Action Blocked", "Please exit any active edit mode before loading new files.", parent=self.window)
            return

        txt_p = self.ui.get_transcription_file_path()
        aud_p = self.ui.get_audio_file_path()

        if not (txt_p and os.path.exists(txt_p)):
            messagebox.showerror("File Error", "Please select a valid transcription file.", parent=self.window); return
        if not (aud_p and os.path.exists(aud_p)):
            messagebox.showerror("File Error", "Please select a valid audio file.", parent=self.window); return
        
        self.cw._load_files_core_logic(txt_p, aud_p)

    def save_changes(self):
        if self.cw.is_any_edit_mode_active():
            messagebox.showwarning("Save Blocked", "Please finish any active editing before saving.", parent=self.window)
            return
        if not self.segment_manager.segments:
             messagebox.showinfo("Nothing to Save", "No transcription data loaded to save.", parent=self.window)
             return
        
        self.cw._save_changes_core_logic()

    # --- Speaker Assignment ---
    def open_assign_speakers_dialog(self):
        if self.cw.is_any_edit_mode_active():
            messagebox.showwarning("Action Blocked", "Please exit any active edit mode first.", parent=self.window); return
        if not self.segment_manager.segments:
            messagebox.showinfo("Assign Speakers", "No segments loaded. Please load files first.", parent=self.window); return
        
        self.cw._open_assign_speakers_dialog_core_logic()

    # --- Text Area and Segment Editing Callbacks ---
    def handle_text_area_double_click(self, event):
        """Handles double-click on text content for text editing."""
        if self.cw.is_any_edit_mode_active(): return # If already editing (text or TS), do nothing
        
        text_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        tags_at_click = self.ui.transcription_text.tag_names(text_index)

        # Check if the double click is on a text_content_TAG or timestamp_TAG
        clicked_on_text_content = any(tag.startswith("text_content_") for tag in tags_at_click)
        clicked_on_timestamp = any(tag.startswith("ts_content_") for tag in tags_at_click)

        segment_id = self.cw._get_segment_id_from_text_index(text_index)
        if not segment_id: return "break"

        if clicked_on_text_content:
            logger.info(f"Double-clicked on text of segment: {segment_id}. Entering text edit mode.")
            self.cw._enter_text_edit_mode(segment_id)
            return "break" 
        elif clicked_on_timestamp:
            logger.info(f"Double-clicked on timestamp of segment: {segment_id}. Entering timestamp edit mode.")
            self.cw._enter_timestamp_edit_mode(segment_id)
            return "break"
        return "break"


    def handle_text_area_right_click(self, event):
        # No change needed here for now, context menu setup will be in CorrectionWindow
        # This method primarily sets self.cw.right_clicked_segment_id
        # and then CorrectionWindow itself configures and pops up the menu.
        
        # If in any edit mode, we might want to disable most context menu items or behave differently.
        # For now, let's allow the context menu but the actions will check edit mode.
        
        text_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        self.cw.right_clicked_segment_id = self.cw._get_segment_id_from_text_index(text_index)
        
        # The actual enabling/disabling of menu items will be done in CorrectionWindow
        # before showing the menu, based on self.cw.edit_mode_active and self.cw.timestamp_edit_mode_active
        self.cw.configure_and_show_context_menu(event) # Delegate to CW
        return "break" 

    def handle_text_area_left_click_edit_mode(self, event):
        """ If in text or timestamp edit mode, clicking outside the editable region exits that mode. """
        if not self.cw.is_any_edit_mode_active(): return

        clicked_index_str = self.ui.transcription_text.index(f"@{event.x},{event.y}")

        if self.cw.text_edit_mode_active and self.cw.editing_segment_id:
            editing_seg = self.segment_manager.get_segment_by_id(self.cw.editing_segment_id)
            if not editing_seg: self.cw._exit_text_edit_mode(save_changes=False); return 

            text_content_tag_id = editing_seg["text_tag_id"]
            try:
                tag_ranges = self.ui.transcription_text.tag_ranges(text_content_tag_id)
                if tag_ranges:
                    start_idx, end_idx = tag_ranges[0], tag_ranges[1]
                    if self.ui.transcription_text.compare(clicked_index_str, ">=", start_idx) and \
                       self.ui.transcription_text.compare(clicked_index_str, "<", end_idx):
                        return # Click is inside the editable text, allow normal Tkinter text widget behavior
                
                logger.debug("Clicked outside editable text area during text edit mode. Saving and exiting text edit.")
                self.cw._exit_text_edit_mode(save_changes=True) 
            except tk.TclError: self.cw._exit_text_edit_mode(save_changes=False)
            except Exception as e:
                logger.exception(f"Error in _handle_click_during_text_edit_mode: {e}")
                self.cw._exit_text_edit_mode(save_changes=False)

        elif self.cw.timestamp_edit_mode_active and self.cw.editing_segment_id_for_ts:
            editing_seg_for_ts = self.segment_manager.get_segment_by_id(self.cw.editing_segment_id_for_ts)
            if not editing_seg_for_ts: self.cw._exit_timestamp_edit_mode(save_changes=False); return

            ts_tag_id = editing_seg_for_ts.get("timestamp_tag_id") # Using the new tag
            if not ts_tag_id: self.cw._exit_timestamp_edit_mode(save_changes=False); return

            try:
                tag_ranges = self.ui.transcription_text.tag_ranges(ts_tag_id)
                if tag_ranges:
                    start_idx, end_idx = tag_ranges[0], tag_ranges[1]
                    # If click is within the timestamp display area, do nothing (allow dialog to remain open)
                    if self.ui.transcription_text.compare(clicked_index_str, ">=", start_idx) and \
                       self.ui.transcription_text.compare(clicked_index_str, "<", end_idx):
                        return 
                
                # If click is outside the timestamp area, close the dialog (which handles saving)
                logger.debug("Clicked outside timestamp area during timestamp edit mode. Dialog should handle exit.")
                # The dialog itself will call _exit_timestamp_edit_mode upon its closure or OK/Cancel.
                # If the dialog is modeless, we might need to explicitly close it here.
                # For now, assume the timestamp edit dialog is modal or handles its own closure.
                # If not, we would call: self.cw._exit_timestamp_edit_mode(save_changes=True)
                # This logic might be better handled by the CorrectionWindow itself when the dialog loses focus or is explicitly closed.
                # For now, let's assume the dialog handles its own lifecycle and saving.
                # If the dialog is a simple Toplevel, clicking outside might not close it.
                # The CorrectionWindow will need to manage the dialog instance.
                # This specific click handler might not be the right place to close the TS edit dialog.
                # The primary purpose of this handler is for *text* edit mode.
                # Let's refine: if in TS edit mode, this click should probably do nothing,
                # letting the timestamp dialog be the focus.
                pass # Let the timestamp dialog manage its lifecycle

            except tk.TclError: self.cw._exit_timestamp_edit_mode(save_changes=False) # Should not happen for TS edit
            except Exception as e:
                logger.exception(f"Error in _handle_click_during_timestamp_edit_mode: {e}")
                self.cw._exit_timestamp_edit_mode(save_changes=False)


    # --- Context Menu Actions (called from CorrectionWindow) ---
    def edit_segment_text_action_from_menu(self):
        if not self.cw.right_clicked_segment_id: return
        if self.cw.is_any_edit_mode_active() and self.cw.editing_segment_id == self.cw.right_clicked_segment_id: return 
        elif self.cw.is_any_edit_mode_active(): self.cw._exit_all_edit_modes(save_changes=True)
        
        logger.info(f"Context menu 'Edit Segment Text' for: {self.cw.right_clicked_segment_id}")
        self.cw._enter_text_edit_mode(self.cw.right_clicked_segment_id)
        self.cw.right_clicked_segment_id = None 

    def edit_segment_timestamps_action_menu(self):
        """Initiates timestamp editing for the right-clicked segment."""
        if not self.cw.right_clicked_segment_id: return
        if self.cw.is_any_edit_mode_active() and self.cw.editing_segment_id_for_ts == self.cw.right_clicked_segment_id: return
        elif self.cw.is_any_edit_mode_active(): self.cw._exit_all_edit_modes(save_changes=True)

        logger.info(f"Context menu 'Edit Timestamps' for: {self.cw.right_clicked_segment_id}")
        self.cw._enter_timestamp_edit_mode(self.cw.right_clicked_segment_id)
        self.cw.right_clicked_segment_id = None

    def add_new_segment_action_menu(self):
        """Initiates adding a new segment, potentially splitting if in text edit mode."""
        ref_segment_id = self.cw.right_clicked_segment_id # Segment right-clicked on, or None if clicked on empty space
        
        if self.cw.text_edit_mode_active and self.cw.editing_segment_id:
            # If in text edit mode, this implies splitting the current segment
            # The 'ref_segment_id' in this case should be the segment being edited.
            # We need the cursor position within that segment's text.
            text_widget = self.ui.transcription_text
            cursor_pos_str = text_widget.index(tk.INSERT)
            
            # Check if cursor is within the currently edited segment's text tag
            editing_seg_obj = self.segment_manager.get_segment_by_id(self.cw.editing_segment_id)
            if not editing_seg_obj:
                messagebox.showerror("Error", "Cannot determine segment to split.", parent=self.window)
                return

            text_tag_id = editing_seg_obj.get("text_tag_id")
            try:
                tag_ranges = text_widget.tag_ranges(text_tag_id)
                if tag_ranges:
                    start_idx_text, end_idx_text = tag_ranges[0], tag_ranges[1]
                    if text_widget.compare(cursor_pos_str, ">=", start_idx_text) and \
                       text_widget.compare(cursor_pos_str, "<=", end_idx_text): # Use <= to include end
                        
                        # Calculate character offset from the start of the tagged text
                        char_offset = text_widget.count(start_idx_text, cursor_pos_str)[0] # count returns tuple (count, pixels, etc.)
                        
                        logger.info(f"Context menu 'Add New Segment' (split) from text edit mode. Segment: {self.cw.editing_segment_id}, Split at char: {char_offset}")
                        self.cw._add_new_segment_dialog_logic(
                            reference_segment_id_for_positioning=self.cw.editing_segment_id, 
                            split_char_index=char_offset
                        )
                    else: # Cursor not in the text of the segment being edited
                        messagebox.showwarning("Split Error", "Cursor is not within the text of the segment being edited. Cannot split.", parent=self.window)
                        return
                else: # No tag ranges found for the text of the segment being edited
                     messagebox.showerror("Split Error", "Cannot find text range of the segment being edited.", parent=self.window)
                     return
            except tk.TclError:
                messagebox.showerror("Split Error", "Error getting text information for splitting.", parent=self.window)
                return
        else:
            # Not in text edit mode, so it's a simple "Add New Segment" above/below the right_clicked_segment_id
            if self.cw.is_any_edit_mode_active(): self.cw._exit_all_edit_modes(save_changes=True)
            logger.info(f"Context menu 'Add New Segment' (insert). Reference segment: {ref_segment_id}")
            self.cw._add_new_segment_dialog_logic(reference_segment_id_for_positioning=ref_segment_id)
        
        self.cw.right_clicked_segment_id = None


    def remove_segment_action_from_menu(self):
        if self.cw.is_any_edit_mode_active() or not self.cw.right_clicked_segment_id: return
        
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
        if self.cw.is_any_edit_mode_active() or not self.cw.right_clicked_segment_id: return
        self.cw._change_segment_speaker_dialog_logic(self.cw.right_clicked_segment_id)
        # self.cw.right_clicked_segment_id is cleared within the dialog logic or after menu pops up

    # --- Tag Click Callbacks (Speaker, Merge) ---
    def on_speaker_click(self, event): 
        if self.cw.is_any_edit_mode_active(): return "break" 
        clicked_index = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        seg_id = self.cw._get_segment_id_from_text_index(clicked_index)
        logger.info(f"Speaker label left-clicked on segment {seg_id}. No direct action implemented yet for left-click.")
        return "break" 

    def on_merge_click(self, event):
        if self.cw.is_any_edit_mode_active(): 
            messagebox.showwarning("Action Blocked", "Please exit any active edit mode before merging.", parent=self.window)
            return "break"
        
        clicked_index_str = self.ui.transcription_text.index(f"@{event.x},{event.y}")
        tags_at_click = self.ui.transcription_text.tag_names(clicked_index_str)
        if "merge_tag_style" not in tags_at_click: return 

        segment_id_of_merge_symbol = self.cw._get_segment_id_from_text_index(clicked_index_str)
        if not segment_id_of_merge_symbol: return "break"

        current_segment = self.segment_manager.get_segment_by_id(segment_id_of_merge_symbol)
        current_segment_index = self.segment_manager.get_segment_index(segment_id_of_merge_symbol) # Use helper

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