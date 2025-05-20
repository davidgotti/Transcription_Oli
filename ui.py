# ui.py
import tkinter as tk
from tkinter import ttk
import logging # Added logging

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

        # Output Area (adjust row if needed due to new widgets)
        self.output_label = ttk.Label(root, text="Processed Output:")
        self.output_label.grid(row=7, column=0, padx=5, pady=5, sticky="w") # Adjusted row

        self.output_text_area = tk.Text(root, height=15, width=70)
        self.output_text_area.grid(row=8, column=0, columnspan=3, padx=5, pady=5, sticky="nsew") # Adjusted row
        self.output_text_area.config(state=tk.DISABLED)

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(8, weight=1) # Adjusted row for text area weight

        self.elements_to_disable = [
            self.browse_button, self.process_button, self.audio_file_entry,
            self.token_entry, self.save_token_button
        ]
        self.save_token_callback = None # Placeholder for the callback function

    def update_status_and_progress(self, status_text=None, progress_value=None):
        if status_text is not None:
            self.status_label.config(text=f"Status: {status_text}")
        if progress_value is not None:
            self.progress_bar['value'] = progress_value
        self.root.update_idletasks() # Ensure UI updates immediately

    def set_save_token_callback(self, callback):
        """Sets the callback function to save the token."""
        self.save_token_callback = callback

    def save_token_ui(self):
        """Gets the token from the entry and calls the save token callback."""
        if self.save_token_callback:
            token = self.token_entry.get()
            self.save_token_callback(token)

    def load_token_ui(self, token):
        """Populates the token entry field."""
        self.token_entry.delete(0, tk.END)
        self.token_entry.insert(0, token)

    def disable_ui(self):
        logging.debug("ui.py: disable_ui: Disabling UI elements.") # Changed print to logging
        for element in self.elements_to_disable:
            element.config(state=tk.DISABLED)

    def enable_ui(self):
        logging.debug("ui.py: enable_ui: Enabling UI elements.") # Changed print to logging
        for element in self.elements_to_disable:
            element.config(state=tk.NORMAL)

    def update_output_text(self, text):
        self.output_text_area.config(state=tk.NORMAL)
        self.output_text_area.delete("1.0", tk.END)
        self.output_text_area.insert(tk.END, text)
        self.output_text_area.config(state=tk.DISABLED)

    def display_processed_output(self, output_file_path: str, processing_returned_empty: bool = False):
        """
        Reads the processed output from the given file path and displays it in the UI.
        Handles cases where the processing returned no speech or the file is not found.
        """
        logging.info(f"UI: Displaying results from '{output_file_path}'. processing_returned_empty: {processing_returned_empty}")
        try:
            if processing_returned_empty:
                self.update_output_text("No speech was detected or transcribed from the audio file.")
                logging.info("UI: Displayed 'no speech detected' message.")
                return

            # This part only runs if processing_returned_empty is False
            with open(output_file_path, 'r', encoding='utf-8') as f:
                output_text = f.read()

            if output_text.strip():
                self.update_output_text(output_text)
                logging.info("UI: Results displayed successfully.")
            else: # File is empty, but we didn't expect it to be
                self.update_output_text("Processing complete, but the output file was unexpectedly empty.")
                logging.warning("UI: Output file was empty, though processing_returned_empty was False.")

        except FileNotFoundError:
            logging.error(f"UI: Output file '{output_file_path}' not found for display.")
            msg_to_show = f"Error: Output file '{output_file_path}' not found. The save step might have failed or the path is incorrect."
            self.update_output_text(msg_to_show)
            # Consider if this specific error should also trigger a messagebox via MainApp
        except Exception as e:
            logging.exception("UI: An unexpected error occurred during display_processed_output.")
            err_msg = f"An error occurred while trying to display results: {str(e)}"
            self.update_output_text(err_msg)