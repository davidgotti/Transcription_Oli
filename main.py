# main.py
import tkinter as tk
from tkinter import ttk # Import ttk for the start button example
import ui
import audio_processor
import audio_player
import threading
import config_manager # Import the new config manager

class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Diarization and Transcription App")

        self.hf_token = config_manager.load_token()
        self.audio_file_path = None # Initialize audio_file_path

        # Initialize the UI and pass the loaded token
        self.app_ui = ui.DiarizationAppUI(root, self, initial_hf_token=self.hf_token)

        # Initialize the audio processor (will use self.hf_token)
        self.audio_processor = None
        self._initialize_audio_processor() # Initial attempt to initialize

        self.audio_player = None
        self.processing_thread = None


    def _initialize_audio_processor(self):
        """Initializes or re-initializes the audio processor with the current HF token."""
        print(f"Attempting to initialize AudioProcessor with token: {'Set' if self.hf_token else 'Not Set'}")
        try:
            self.audio_processor = audio_processor.AudioProcessor(hf_token=self.hf_token)
            print("AudioProcessor initialized successfully.")
        except Exception as e:
            self.audio_processor = None # Ensure it's None if init fails
            error_message = f"Failed to initialize AudioProcessor: {e}\n"
            error_message += "Please ensure your Hugging Face token is correct (if required by models) and you have an internet connection for model downloads."
            if not self.hf_token:
                error_message += "\nThe Hugging Face token is currently not set. Please add it via the UI and save."
            self.app_ui.show_error_message(error_message)
            print(error_message) # Also print to console for debugging

    def on_save_hf_token(self, token):
        """Called by UI when 'Save Token' is clicked."""
        config_manager.save_token(token)
        self.hf_token = token
        print("Hugging Face token saved. Re-initializing AudioProcessor...")
        self._initialize_audio_processor() # Re-initialize with the new token

    def on_file_selected(self, audio_file_path):
        self.audio_file_path = audio_file_path
        if self.audio_player: # Stop and close previous player if any
            try:
                self.audio_player.stop()
            except Exception as e:
                print(f"Error stopping previous audio player: {e}")
        try:
            self.audio_player = audio_player.AudioPlayer(audio_file_path)
        except Exception as e:
            self.app_ui.show_error_message(f"Error loading audio: {e}")
            self.audio_player = None
            self.app_ui.play_pause_button['state'] = tk.DISABLED # Ensure play is disabled
            self.app_ui.stop_button['state'] = tk.DISABLED      # Ensure stop is disabled


    def on_play_pause(self):
        if not self.audio_file_path or not self.audio_player:
            self.app_ui.show_error_message("Please select a valid audio file first.")
            return

        try:
            if self.app_ui.is_playing:
                self.audio_player.pause()
                self.app_ui.set_play_button_text("Play")
            else:
                self.audio_player.play()
                self.app_ui.set_play_button_text("Pause")
            self.app_ui.is_playing = not self.app_ui.is_playing
        except Exception as e:
            self.app_ui.show_error_message(f"Error during playback: {e}")
            # Reset UI state if playback fails
            self.app_ui.is_playing = False
            self.app_ui.set_play_button_text("Play")


    def on_stop(self):
        if not self.audio_file_path or not self.audio_player:
            return # No file loaded or player not initialized
        try:
            self.audio_player.stop() # This should handle closing resources
            # Re-initialize player for next play, or ensure play() can handle a stopped then re-played stream
            # For simplicity, let's re-initialize the player instance for the same file
            self.audio_player = audio_player.AudioPlayer(self.audio_file_path)
        except Exception as e:
            self.app_ui.show_error_message(f"Error stopping audio: {e}")
            # Potentially disable player buttons if stop fails critically
        finally: # Always reset UI after stop attempt
            self.app_ui.is_playing = False
            self.app_ui.set_play_button_text("Play")


    def on_playback_speed_changed(self, speed):
        if not self.audio_file_path or not self.audio_player:
            return
        try:
            current_position_frames = self.audio_player.current_frame # Get current position before changing speed
            is_currently_playing = self.app_ui.is_playing

            if is_currently_playing:
                self.audio_player.pause()

            self.audio_player.set_speed(speed) # This re-opens the stream at the new rate

            # If you want to resume from the same position, set_speed would need to handle it,
            # or you'd manage frame position here. pyAudio stream rate changes often mean
            # re-opening the stream, so exact position retention can be tricky.
            # The current AudioPlayer.set_speed re-opens and sets pos, so it should be okay.

            if is_currently_playing:
                self.audio_player.play() # Resume play if it was playing
        except Exception as e:
            self.app_ui.show_error_message(f"Error changing playback speed: {e}")


    def on_start_processing(self):
        if not self.audio_file_path:
            self.app_ui.show_error_message("Please select an audio file before processing.")
            return

        if not self.audio_processor:
            self.app_ui.show_error_message("Audio processor is not initialized. Please check your Hugging Face token and any errors in the console, then try again.")
            # Optionally, try to re-initialize here if it makes sense for your UX
            # self._initialize_audio_processor()
            # if not self.audio_processor:
            #     return # Still not initialized
            return

        if self.processing_thread and self.processing_thread.is_alive():
            self.app_ui.show_error_message("Processing is already in progress.")
            return

        self.app_ui.disable_ui()
        self.app_ui.clear_text_output()
        self.app_ui.text_output.configure(state=tk.NORMAL)
        self.app_ui.text_output.insert(tk.END, "Processing started...\n")
        self.app_ui.text_output.configure(state=tk.DISABLED)


        self.processing_thread = threading.Thread(target=self.process_audio, daemon=True) # daemon=True allows app to exit if thread is running
        self.processing_thread.start()

    def process_audio(self):
        try:
            result_lines = self.audio_processor.process_audio(self.audio_file_path)
            self.root.after(0, self.app_ui.display_results, result_lines)
        except RuntimeError as e: # Catch specific RuntimeError from process_audio if pipeline failed
             self.root.after(0, self.app_ui.show_error_message, str(e))
        except Exception as e:
            self.root.after(0, self.app_ui.show_error_message, f"An error occurred during processing: {e}")
        finally:
            self.root.after(0, self.app_ui.enable_ui)

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    # Example of how to tie the external button to the app's processing logic
    # If you have a "Start Processing" button in your UI, connect its command to app.on_start_processing
    # For now, this external button can trigger it:
    # Note: This button is outside the main UI class structure.
    # It's better to integrate such a button within DiarizationAppUI.
    # However, if it's for testing main.py directly:
    # start_button = ttk.Button(root, text="Start Processing (External Test)", command=app.on_start_processing)
    # start_button.pack(pady=10)
    root.mainloop()