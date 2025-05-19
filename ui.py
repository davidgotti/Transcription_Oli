# ui.py
import tkinter as tk
from tkinter import filedialog, ttk, messagebox # Added messagebox
from tkinter.scrolledtext import ScrolledText

class DiarizationAppUI:
    def __init__(self, root, main_app, initial_hf_token=None): # Added initial_hf_token
        self.root = root
        self.main_app = main_app
        self.is_playing = False
        self.audio_file_path = None # Initialize attribute
        self.create_ui(initial_hf_token) # Pass token to create_ui

    def create_ui(self, initial_hf_token=None): # Added initial_hf_token parameter
        # --- File Selection ---
        self.file_frame = ttk.Frame(self.root)
        self.file_frame.pack(pady=10, padx=10, fill=tk.X) # Added padx

        self.file_label = ttk.Label(self.file_frame, text="Audio File:")
        self.file_label.pack(side=tk.LEFT, padx=(0,5)) # Adjusted padx

        self.file_path_var = tk.StringVar()
        self.file_path_entry = ttk.Entry(self.file_frame, textvariable=self.file_path_var, width=50, state='readonly') # state readonly
        self.file_path_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.browse_button = ttk.Button(self.file_frame, text="Browse", command=self.browse_file)
        self.browse_button.pack(side=tk.LEFT, padx=(5,0)) # Adjusted padx

        # --- Hugging Face Token ---
        self.token_frame = ttk.Frame(self.root)
        self.token_frame.pack(pady=5, padx=10, fill=tk.X)

        self.token_label = ttk.Label(self.token_frame, text="HF Token:")
        self.token_label.pack(side=tk.LEFT, padx=(0,5))

        self.hf_token_var = tk.StringVar(value=initial_hf_token if initial_hf_token else "")
        self.token_entry = ttk.Entry(self.token_frame, textvariable=self.hf_token_var, width=40, show="*")
        self.token_entry.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.save_token_button = ttk.Button(self.token_frame, text="Save Token", command=self.save_hf_token)
        self.save_token_button.pack(side=tk.LEFT, padx=(5,0))


        # --- Play/Pause/Stop ---
        self.audio_frame = ttk.Frame(self.root)
        self.audio_frame.pack(pady=10, padx=10, fill=tk.X) # Added padx
        self.play_pause_button = ttk.Button(self.audio_frame, text="Play", command=self.main_app.on_play_pause, state=tk.DISABLED)
        self.play_pause_button.pack(side=tk.LEFT, padx=(0,10)) # Adjusted padx
        self.stop_button = ttk.Button(self.audio_frame, text="Stop", command=self.main_app.on_stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0,10)) # Adjusted padx

        self.playback_speed_label = ttk.Label(self.audio_frame, text="Playback Speed:")
        self.playback_speed_label.pack(side=tk.LEFT, padx=(0,5)) # Adjusted padx

        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_scale = tk.Scale(self.audio_frame, from_=0.5, to=2.0, resolution=0.1,
                                    variable=self.speed_var, orient=tk.HORIZONTAL,
                                    command=self.on_speed_changed)
        self.speed_scale.pack(side=tk.LEFT, padx=(0,10)) # Adjusted padx

        # --- Text Output ---
        self.output_label = ttk.Label(self.root, text="Transcription Output:")
        self.output_label.pack(pady=5, anchor=tk.W, padx=10)
        self.text_output = ScrolledText(self.root, wrap=tk.WORD, height=20, width=80, state=tk.DISABLED)
        self.text_output.pack(padx=10, pady=(0,10), fill=tk.BOTH, expand=True) # Adjusted pady
        self.text_output.tag_configure("speaker-a", foreground="#6ee7b7") # Ensure lowercase tags
        self.text_output.tag_configure("speaker-b", foreground="#f472b6")
        self.text_output.tag_configure("speaker-c", foreground="#8b5cf6")
        self.text_output.tag_configure("speaker-d", foreground="#3b82f6")
        self.text_output.tag_configure("speaker-e", foreground="#f59e0b")
        self.text_output.tag_configure("speaker-f", foreground="#ec4899")
        self.text_output.tag_configure("speaker-g", foreground="#10b981")
        self.text_output.tag_configure("speaker-h", foreground="#d946ef")
        self.text_output.tag_configure("speaker-i", foreground="#22c55e")
        self.text_output.tag_configure("speaker-j", foreground="#ef4444")
        self.text_output.tag_configure("unknown", foreground="#9ca3af") # Renamed from "unknown-speaker" for simplicity
        self.text_output.tag_configure("timestamp", foreground="gray") # For timestamp

    def browse_file(self):
        audio_file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.wav")])
        if audio_file:
            self.audio_file_path = audio_file # Set UI's copy of path
            self.file_path_var.set(self.audio_file_path)
            self.play_pause_button['state'] = tk.NORMAL
            self.stop_button['state'] = tk.NORMAL # Enable stop button when file is loaded
            self.main_app.on_file_selected(self.audio_file_path)
            self.set_play_button_text("Play") # Reset to Play
            self.is_playing = False


    def save_hf_token(self):
        token = self.hf_token_var.get()
        if token and token.strip():
            self.main_app.on_save_hf_token(token)
            messagebox.showinfo("Token Saved", "Hugging Face token saved. Audio processor will be re-initialized with the new token.")
        else:
            messagebox.showwarning("Token Empty", "Hugging Face token cannot be empty.")


    def on_speed_changed(self, speed):
        self.main_app.on_playback_speed_changed(self.speed_var.get())

    def show_error_message(self, message):
        messagebox.showerror("Error", message) # Use messagebox directly

    def set_play_button_text(self, text):
        self.play_pause_button.config(text=text)

    def disable_ui(self):
        self.browse_button['state'] = tk.DISABLED
        self.play_pause_button['state'] = tk.DISABLED
        self.stop_button['state'] = tk.DISABLED
        self.token_entry['state'] = tk.DISABLED
        self.save_token_button['state'] = tk.DISABLED
        # Keep speed_scale active or disable as per preference
        # self.speed_scale['state'] = tk.DISABLED
        # self.text_output already managed

    def enable_ui(self):
        self.browse_button['state'] = tk.NORMAL
        self.token_entry['state'] = tk.NORMAL
        self.save_token_button['state'] = tk.NORMAL
        # self.speed_scale['state'] = tk.NORMAL
        if self.audio_file_path: # Check UI's audio_file_path
            self.play_pause_button['state'] = tk.NORMAL
            self.stop_button['state'] = tk.NORMAL
        else:
            self.play_pause_button['state'] = tk.DISABLED
            self.stop_button['state'] = tk.DISABLED
        # self.text_output state is managed by display/clear methods

    def clear_text_output(self):
        self.text_output['state'] = tk.NORMAL
        self.text_output.delete(1.0, tk.END)
        self.text_output['state'] = tk.DISABLED

    def display_results(self, result_lines):
        self.text_output.configure(state=tk.NORMAL)
        self.text_output.delete(1.0, tk.END)
        for line in result_lines:
            try:
                # Expected format from audio_processor: "timestamp SPEAKER_X : text"
                parts = line.split(" : ", 1)
                if len(parts) == 2:
                    header, text_content = parts
                    header_parts = header.rsplit(" ", 1) # Split "timestamp SPEAKER_X"
                    timestamp = header_parts[0] if len(header_parts) > 1 else ""
                    speaker_id_full = header_parts[1] if len(header_parts) > 1 else "Unknown"
                    
                    # Normalize speaker ID for tagging (e.g., "SPEAKER_A" -> "speaker-a")
                    speaker_tag = speaker_id_full.lower().replace("_", "-")
                    if not speaker_tag.startswith("speaker-") and speaker_tag != "unknown":
                        speaker_tag = "unknown" # Default if not matching "speaker-x" or "unknown"
                    
                    # Check if specific tag exists, else use 'unknown'
                    if speaker_tag not in self.text_output.tag_names():
                        speaker_tag = "unknown"

                    self.text_output.insert(tk.END, f"{timestamp} ", "timestamp")
                    self.text_output.insert(tk.END, f"{speaker_id_full} : ", speaker_tag)
                    self.text_output.insert(tk.END, f"{text_content}\n")
                else:
                    self.text_output.insert(tk.END, line + "\n", "unknown") # Fallback for unexpected format
            except Exception as e:
                print(f"Error displaying line: '{line}'. Error: {e}")
                self.text_output.insert(tk.END, line + "\n", "unknown") # Display line as is on error
        self.text_output.configure(state=tk.DISABLED)