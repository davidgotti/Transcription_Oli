# ui.py
import tkinter as tk
from tkinter import ttk
import logging

class UI:
    def __init__(self, root, start_processing_callback, select_audio_file_callback):
        self.root = root
        self.root.title("Audio Transcription and Diarization")

        self.start_processing_callback = start_processing_callback
        self.select_audio_file_callback = select_audio_file_callback

        # Hugging Face Token Input
        self.token_label = ttk.Label(root, text="Hugging Face Token:")
        self.token_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.token_entry = ttk.Entry(root, width=50)
        self.token_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.save_token_button = ttk.Button(root, text="Save Token", command=self.save_token_ui)
        self.save_token_button.grid(row=0, column=2, padx=5, pady=5, sticky="w")

        # Audio File Selection
        self.audio_file_label = ttk.Label(root, text="Audio File:")
        self.audio_file_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        self.audio_file_entry = ttk.Entry(root, width=50)
        self.audio_file_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        self.browse_button = ttk.Button(root, text="Browse", command=self.select_audio_file_callback)
        self.browse_button.grid(row=1, column=2, padx=5, pady=5, sticky="w")

        # Processing Button
        self.process_button = ttk.Button(root, text="Start Processing", command=self.start_processing_callback)
        self.process_button.grid(row=2, column=0, columnspan=3, padx=5, pady=10)

        # Progress Bar and Status Label
        self.status_label = ttk.Label(root, text="Status: Idle")
        self.status_label.grid(row=5, column=0, columnspan=3, padx=5, pady=5, sticky="w")

        self.progress_bar = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.grid(row=6, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        # Output Area
        self.output_label = ttk.Label(root, text="Processed Output:")
        self.output_label.grid(row=7, column=0, padx=5, pady=5, sticky="w")

        self.output_text_area = tk.Text(root, height=15, width=70)
        self.output_text_area.grid(row=8, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")
        self.output_text_area.config(state=tk.DISABLED)

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(8, weight=1)

        self.elements_to_disable = [
            self.browse_button, self.process_button, self.audio_file_entry,
            self.token_entry, self.save_token_button
        ]
        self.save_token_callback = None

    def update_status_and_progress(self, status_text=None, progress_value=None):
        if status_text is not None:
            self.status_label.config(text=f"Status: {status_text}")
        if progress_value is not None:
            self.progress_bar['value'] = progress_value
        self.root.update_idletasks()

    def set_save_token_callback(self, callback):
        self.save_token_callback = callback

    def save_token_ui(self):
        if self.save_token_callback:
            token = self.token_entry.get()
            self.save_token_callback(token)

    def load_token_ui(self, token):
        self.token_entry.delete(0, tk.END)
        self.token_entry.insert(0, token)

    def disable_ui(self):
        logging.debug("ui.py: disable_ui: Disabling UI elements.")
        for element in self.elements_to_disable:
            element.config(state=tk.DISABLED)

    def enable_ui(self):
        logging.debug("ui.py: enable_ui: Enabling UI elements.")
        for element in self.elements_to_disable:
            element.config(state=tk.NORMAL)

    def update_output_text(self, text):
        self.output_text_area.config(state=tk.NORMAL)
        self.output_text_area.delete("1.0", tk.END)
        self.output_text_area.insert(tk.END, text)
        self.output_text_area.config(state=tk.DISABLED)

    def display_processed_output(self, output_file_path: str = None, processing_returned_empty: bool = False):
        """
        Displays processed output. If processing_returned_empty is True, shows a specific message.
        Otherwise, tries to read from output_file_path.
        """
        logging.info(f"UI: Displaying results. Path: '{output_file_path}', Empty: {processing_returned_empty}")
        try:
            if processing_returned_empty:
                # This specific message comes from the AudioProcessor or MainApp if no speech was detected
                # or if diarization/transcription results in an empty interpretable output.
                self.update_output_text("No speech was detected or transcribed from the audio file, or the processing yielded no usable segments.")
                logging.info("UI: Displayed 'no speech/segments' message.")
                return

            if not output_file_path:
                # This case might happen if processing was meant to be successful but somehow
                # the path was not provided to display_processed_output.
                # The main app should handle this, but as a fallback:
                msg_to_show = "Error: No output file path provided to display results, though processing was not marked as empty."
                logging.error(f"UI: {msg_to_show}")
                self.update_output_text(msg_to_show)
                return

            # If not empty and path is provided, read the file
            with open(output_file_path, 'r', encoding='utf-8') as f:
                output_text = f.read()

            if output_text.strip():
                self.update_output_text(output_text)
                logging.info(f"UI: Results from '{output_file_path}' displayed successfully.")
            else: # File is empty, but we didn't expect it to be (as processing_returned_empty was False)
                self.update_output_text(f"Processing complete, but the output file ('{output_file_path}') was unexpectedly empty.")
                logging.warning(f"UI: Output file '{output_file_path}' was empty, though processing_returned_empty was False.")

        except FileNotFoundError:
            logging.error(f"UI: Output file '{output_file_path}' not found for display.")
            msg_to_show = (f"Error: Output file '{output_file_path}' not found. "
                           "The save step might have failed or the path is incorrect. "
                           "Content might have been shown directly if save was cancelled or failed.")
            self.update_output_text(msg_to_show)
        except Exception as e:
            logging.exception("UI: An unexpected error occurred during display_processed_output.")
            err_msg = f"An error occurred while trying to display results from '{output_file_path}': {str(e)}"
            self.update_output_text(err_msg)