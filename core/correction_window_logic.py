# core/correction_window_logic.py
import logging
import re
from tkinter import messagebox # For showing warnings during parsing

# Assuming constants.py is in the utils directory, a sibling to core and ui
try:
    from utils import constants
except ImportError:
    # Fallback for different execution contexts or project structures
    import sys
    import os
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_script_dir) # Assumes core is one level down from project root
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from utils import constants

logger = logging.getLogger(__name__)

class SegmentManager:
    def __init__(self, parent_window_for_dialogs=None):
        self.segments = []  # List of segment dicts
        self.speaker_map = {}  # Maps raw speaker labels to custom display names
        self.unique_speaker_labels = set()  # Set of raw speaker labels encountered
        self.parent_window = parent_window_for_dialogs

        # Regex patterns
        self.pattern_start_end_ts_speaker = re.compile(
            r"^\[(\d{2}:\d{2}\.\d{3})\s*-\s*(\d{2}:\d{2}\.\d{3})\]\s*([^:]+?):\s*(.*)$"
        )
        self.pattern_start_end_ts_only = re.compile(
            r"^\[(\d{2}:\d{2}\.\d{3})\s*-\s*(\d{2}:\d{2}\.\d{3})\]\s*(.*)$"
        )
        self.pattern_start_ts_speaker = re.compile(
            r"^\[(\d{2}:\d{2}\.\d{3})\]\s*([^:]+?):\s*(.*)$"
        )
        self.pattern_start_ts_only = re.compile(
            r"^\[(\d{2}:\d{2}\.\d{3})\]\s*(.*)$"
        )
        self.pattern_speaker_only = re.compile(
            r"^\s*([^:]+?):\s*(.*)$"
        )
        logger.info("SegmentManager initialized.")

    def time_str_to_seconds(self, time_str: str) -> float | None:
        if not time_str or not isinstance(time_str, str): return None
        try:
            parts = time_str.split(':')
            if len(parts) == 3:  # HH:MM:SS.mmm
                h, m, s_ms = parts; s, ms = s_ms.split('.')
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
            elif len(parts) == 2:  # MM:SS.mmm
                m, s_ms = parts; s, ms = s_ms.split('.')
                return int(m) * 60 + int(s) + int(ms) / 1000.0
            return None
        except ValueError: return None

    def seconds_to_time_str(self, total_seconds: float | None, force_MM_SS: bool = True) -> str:
        if total_seconds is None: return "--:--.---"
        if not isinstance(total_seconds, (int, float)) or total_seconds < 0: total_seconds = 0.0
        
        abs_seconds = abs(total_seconds)
        h = 0
        if not force_MM_SS: h = int(abs_seconds // 3600); abs_seconds %= 3600
        m = int(abs_seconds // 60); s_float = abs_seconds % 60
        s_int = int(s_float); ms = int((s_float - s_int) * 1000)
        sign = "-" if total_seconds < 0 else ""
        
        if not force_MM_SS and h > 0: return f"{sign}{h:02d}:{m:02d}:{s_int:02d}.{ms:03d}"
        if force_MM_SS and h > 0: m += h * 60 # Accumulate hours into minutes
        return f"{sign}{m:02d}:{s_int:02d}.{ms:03d}"

    def parse_transcription_lines(self, text_lines: list[str]) -> bool:
        self.clear_segments()
        malformed_count = 0; id_counter = 0
        logger.debug(f"Parsing {len(text_lines)} lines.")

        for i, line_raw in enumerate(text_lines):
            line = line_raw.strip()
            if not line: continue

            start_s, end_s = 0.0, None
            speaker = constants.NO_SPEAKER_LABEL; text = line
            has_ts, has_explicit_end = False, False

            m_se_ts_spk = self.pattern_start_end_ts_speaker.match(line)
            m_se_ts_only = self.pattern_start_end_ts_only.match(line)
            m_s_ts_spk = self.pattern_start_ts_speaker.match(line)
            m_s_ts_only = self.pattern_start_ts_only.match(line)
            m_spk_only = self.pattern_speaker_only.match(line)

            parsed_ok = False
            if m_se_ts_spk:
                s, e, spk, txt = m_se_ts_spk.groups()
                ps, pe = self.time_str_to_seconds(s), self.time_str_to_seconds(e)
                if ps is not None and pe is not None and ps <= pe:
                    start_s, end_s, speaker, text, has_ts, has_explicit_end, parsed_ok = ps, pe, spk.strip(), txt.strip(), True, True, True
            elif m_se_ts_only:
                s, e, txt = m_se_ts_only.groups()
                ps, pe = self.time_str_to_seconds(s), self.time_str_to_seconds(e)
                if ps is not None and pe is not None and ps <= pe:
                    start_s, end_s, text, has_ts, has_explicit_end, parsed_ok = ps, pe, txt.strip(), True, True, True
            elif m_s_ts_spk:
                s, spk, txt = m_s_ts_spk.groups()
                ps = self.time_str_to_seconds(s)
                if ps is not None:
                    start_s, speaker, text, has_ts, parsed_ok = ps, spk.strip(), txt.strip(), True, True
            elif m_s_ts_only:
                s, txt = m_s_ts_only.groups()
                ps = self.time_str_to_seconds(s)
                if ps is not None:
                    start_s, text, has_ts, parsed_ok = ps, txt.strip(), True, True
            elif m_spk_only:
                spk, txt = m_spk_only.groups()
                speaker, text, parsed_ok = spk.strip(), txt.strip(), True
            else: # Text_Only
                parsed_ok = True
            
            if not parsed_ok : malformed_count +=1; logger.warning(f"L{i+1} Malformed: {line}")

            self.segments.append({
                "id": f"seg_{id_counter}", "start_time": start_s, "end_time": end_s,
                "speaker_raw": speaker, "text": text, "original_line_num": i + 1,
                "text_tag_id": f"text_content_{id_counter}",
                "has_timestamps": has_ts, "has_explicit_end_time": has_explicit_end
            })
            if speaker != constants.NO_SPEAKER_LABEL: self.unique_speaker_labels.add(speaker)
            id_counter += 1
        
        logger.info(f"Parsing done. {len(self.segments)} segments. {malformed_count} warnings.")
        if not self.segments and any(l.strip() for l in text_lines):
            if self.parent_window: messagebox.showerror("Parsing Error", "Could not parse segments.", parent=self.parent_window)
            return False
        if malformed_count > 0 and self.parent_window:
             messagebox.showwarning("Parsing Issues", f"{malformed_count} lines had issues.", parent=self.parent_window)
        return True

    def clear_segments(self):
        self.segments.clear(); self.speaker_map.clear(); self.unique_speaker_labels.clear()
        logger.info("Segment data cleared.")

    def get_segment_by_id(self, segment_id: str) -> dict | None:
        return next((s for s in self.segments if s["id"] == segment_id), None)

    def update_segment_text(self, segment_id: str, new_text: str) -> bool:
        segment = self.get_segment_by_id(segment_id)
        if segment:
            if segment["text"] != new_text:
                segment["text"] = new_text
                logger.debug(f"Segment {segment_id} text updated.")
                return True
        return False

    def update_segment_timestamps(self, segment_id: str, new_start_time: float, new_end_time: float | None) -> bool:
        segment = self.get_segment_by_id(segment_id)
        if segment:
            segment["start_time"] = new_start_time
            segment["end_time"] = new_end_time
            segment["has_timestamps"] = True
            segment["has_explicit_end_time"] = new_end_time is not None
            logger.debug(f"Segment {segment_id} timestamps updated: S={new_start_time} E={new_end_time}")
            return True
        return False
        
    def update_segment_speaker(self, segment_id: str, new_speaker_raw: str):
        segment = self.get_segment_by_id(segment_id)
        if segment:
            segment["speaker_raw"] = new_speaker_raw
            if new_speaker_raw != constants.NO_SPEAKER_LABEL:
                self.unique_speaker_labels.add(new_speaker_raw) # Ensure it's in the set
            logger.debug(f"Segment {segment_id} speaker updated to {new_speaker_raw}")

    def remove_segment(self, segment_id_to_remove: str) -> bool:
        original_len = len(self.segments)
        self.segments = [s for s in self.segments if s["id"] != segment_id_to_remove]
        if len(self.segments) < original_len:
            logger.info(f"Segment {segment_id_to_remove} removed.")
            return True
        logger.warning(f"Attempted to remove non-existent segment {segment_id_to_remove}.")
        return False

    def merge_segment_with_previous(self, current_segment_id: str) -> bool:
        current_segment_index = next((i for i, s in enumerate(self.segments) if s["id"] == current_segment_id), -1)

        if current_segment_index <= 0:
            logger.warning(f"Cannot merge segment {current_segment_id}: no previous segment or it's the first.")
            return False
            
        current_segment = self.segments[current_segment_index]
        previous_segment = self.segments[current_segment_index - 1]

        if previous_segment["speaker_raw"] != current_segment["speaker_raw"] or \
           previous_segment["speaker_raw"] == constants.NO_SPEAKER_LABEL:
            logger.warning(f"Cannot merge {current_segment_id}: speakers differ or previous has no speaker.")
            return False # Cannot merge if speakers are different or previous has no speaker

        # Logic for merging
        # Take end time from the current segment if it's later or if previous didn't have one
        if current_segment["end_time"] is not None:
            if previous_segment["end_time"] is None or current_segment["end_time"] > previous_segment["end_time"]:
                 previous_segment["end_time"] = current_segment["end_time"]
            # If current segment had explicit end time, the merged one now does too
            if current_segment.get("has_explicit_end_time"):
                 previous_segment["has_explicit_end_time"] = True
        
        # Concatenate text
        sep = " " if previous_segment["text"] and current_segment["text"] and \
                     not previous_segment["text"].endswith(" ") and \
                     not current_segment["text"].startswith(" ") else ""
        previous_segment["text"] += sep + current_segment["text"]
        
        # Update timestamp status if current segment had timestamps and previous didn't
        if not previous_segment.get("has_timestamps") and current_segment.get("has_timestamps"):
            previous_segment["has_timestamps"] = True
            # If previous didn't have explicit end but current did, it's still not fully explicit unless start also came from current
            # This logic might need refinement if merging segments with mixed timestamp presence.
            # For now, if either had explicit end, the merged one might be considered to have it.
            if current_segment.get("has_explicit_end_time"):
                 previous_segment["has_explicit_end_time"] = True


        logger.info(f"Merged segment {current_segment['id']} into {previous_segment['id']}.")
        self.segments.pop(current_segment_index) 
        return True

    def format_segments_for_saving(self, include_timestamps: bool, include_end_times: bool) -> list[str]:
        """Formats segments into a list of strings suitable for saving to a file."""
        output_lines = []
        for seg in self.segments:
            parts = []
            if include_timestamps and seg.get("has_timestamps"):
                start_str = self.seconds_to_time_str(seg['start_time'])
                if include_end_times and seg.get("has_explicit_end_time") and seg['end_time'] is not None:
                    end_str = self.seconds_to_time_str(seg['end_time'])
                    parts.append(f"[{start_str} - {end_str}]")
                else: # Only start time, or segment didn't have explicit end, or saving only start times
                    parts.append(f"[{start_str}]")
            
            if seg['speaker_raw'] != constants.NO_SPEAKER_LABEL:
                # Use mapped speaker name if available, otherwise raw
                speaker_display_name = self.speaker_map.get(seg['speaker_raw'], seg['speaker_raw'])
                parts.append(f"{speaker_display_name}:")
            
            parts.append(seg['text'])
            output_lines.append(" ".join(filter(None, parts))) # filter(None,...) removes empty strings
        return output_lines

