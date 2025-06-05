# utils/tips_data.py

MAIN_WINDOW_TIPS = {
    "audio_file_browse": "Click to browse and select one or more audio files (e.g., .wav, .mp3) for transcription.",
    "transcription_model_dropdown": "Select the speech-to-text model. 'Large' is recommended for highest accuracy, but is slower. Smaller models are faster but less accurate.",
    # Specific model tips are handled by the existing Combobox mechanism,
    # but we can add a general one if that mechanism is tied to the new "Show Tips" feature.
    "model_option_tiny": "Tiny: Fastest, lowest accuracy. Good for quick tests where precision is not critical.",
    "model_option_base": "Base: Faster than Small, better accuracy than Tiny. A step up in quality from Tiny.",
    "model_option_small": "Small: Good balance between speed and accuracy. Suitable for many general use cases.",
    "model_option_medium": "Medium: Slower than Small, but offers better accuracy. Use when quality is more important than speed.",
    "model_option_large": "Large (v3): Slowest model, but provides the highest accuracy. Recommended for final or critical transcriptions.",
    "model_option_turbo": "Turbo: An optimized version, currently maps to the 'small' model, offering a balance of speed and quality.",
    "enable_diarization_checkbox": "Check to enable speaker diarization. This attempts to identify and label different speakers in the audio. Requires a Hugging Face token.",
    "include_timestamps_checkbox": "Check to include timestamps (e.g., [00:00.000]) at the beginning of each transcribed segment.",
    "include_end_times_checkbox": "Check to include end timestamps (e.g., [00:00.000 - 00:01.500]) for each segment. Only active if 'Include Timestamps' is checked.",
    "auto_merge_checkbox": "When speaker diarization is enabled, check this to automatically merge consecutive segments if they are identified as being from the same speaker. Helps create more readable transcripts.",
    "huggingface_token_entry": "Enter your Hugging Face User Access Token here. Required for speaker diarization as it uses a gated model. You can get a token from your Hugging Face account settings (huggingface.co/settings/tokens). Ensure the token has 'read' access.",
    "save_huggingface_token_button": "Click to save the entered Hugging Face token. The application will remember it for future sessions.",
    "start_processing_button": "Click to start the transcription (and diarization, if enabled) process for the selected audio file(s).",
    "status_label": "Displays the current status of the application (e.g., Idle, Loading models, Processing, Error).",
    "progress_bar": "Shows the progress of tasks like model loading or audio processing.",
    "output_text_area": "Displays the transcribed text of the last processed file or a summary if batch processing was performed.",
    "correction_window_button": "Opens a new window to manually correct the transcription of the last successfully processed single audio file. Allows editing text, timestamps, and speaker labels.",
    "show_tips_checkbox_main": "Enable or disable these helpful tips throughout the main application window."
}

CORRECTION_WINDOW_TIPS = {
    "transcription_file_browse_corr": "Browse for a text file (.txt) containing the transcription you want to load and correct.",
    "audio_file_browse_corr": "Browse for the corresponding audio file (.wav, .mp3, etc.) for the transcription you are loading.",
    "load_files_button_corr": "Loads the selected transcription and audio files into the correction tool. Any unsaved changes will be lost.",
    "assign_speakers_button_corr": "Opens a dialog to assign custom display names to the raw speaker labels (e.g., SPEAKER_00, SPEAKER_01) found in the transcription or to add new speaker labels.",
    "save_changes_button_corr": "Saves the currently displayed (and potentially corrected) transcription to a new text file.",
    "play_pause_button_corr": "Plays or pauses the loaded audio file. Keyboard shortcut: Spacebar (when text area is not focused).",
    "rewind_button_corr": "Rewinds the audio playback by 5 seconds.",
    "forward_button_corr": "Forwards the audio playback by 5 seconds.",
    "jump_to_segment_button_corr": "When editing a segment with a timestamp, this button (if visible) jumps playback to 1 second before the segment's start time.",
    "audio_progress_bar_corr": "Shows the current playback position of the audio. Click to seek to a specific position.",
    "time_labels_corr": "Displays the current playback time and the total duration of the loaded audio file.",
    "transcription_text_area_corr": (
        "Displays the transcription segments. \n"
        "- Double-click a segment's text to edit it. \n"
        "- Double-click a segment's timestamp to edit its start/end times. \n"
        "- Right-click on a segment for more options (add, remove, split, change speaker). \n"
        "- Click the '+' symbol (if shown) to merge a segment with the one above it (if speakers match)."
    ),
    "show_tips_checkbox_corr": "Enable or disable these helpful tips throughout the correction window."
    # Individual context menu items or specific parts of the text area could also have tips if needed,
    # but a general one for the text area covers many interactions.
}

# Combined dictionary for easier access if needed, or keep separate
ALL_TIPS = {
    "main_window": MAIN_WINDOW_TIPS,
    "correction_window": CORRECTION_WINDOW_TIPS
}

def get_tip(window_name: str, widget_key: str) -> str | None:
    """
    Retrieves a tip for a given window and widget key.
    Example: get_tip("main_window", "enable_diarization_checkbox")
    """
    if window_name in ALL_TIPS and widget_key in ALL_TIPS[window_name]:
        return ALL_TIPS[window_name][widget_key]
    return None
