# audio_player.py
import wave
import pyaudio
import tkinter as tk #needed for the .after() method
import logging

logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, filename, tk_root): # Add tk_root parameter
        self.filename = filename
        self.tk_root = tk_root # Store the root reference
        self.wf = None
        self.p = None
        self.stream = None
        self.chunk = 1024
        self.frame_rate = 0
        self.current_frame = 0
        self.playing = False
        
        try:
            self.wf = wave.open(filename, 'rb')
            self.p = pyaudio.PyAudio()
            self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                            channels=self.wf.getnchannels(),
                            rate=self.wf.getframerate(),
                            output=True,
                            stream_callback=self._audio_callback) # Use callback for non-blocking
            self.frame_rate = self.wf.getframerate()
            self.stream.stop_stream() # Start paused
            logger.info(f"AudioPlayer initialized for {filename}")
        except Exception as e:
            logger.exception(f"Failed to initialize AudioPlayer for {filename}")
            self.wf = None # Ensure wf is None if init fails
            raise # Re-raise exception to be caught by caller

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if not self.playing:
            return (b'', pyaudio.paComplete) # Send empty data if paused to avoid issues

        data = self.wf.readframes(frame_count)
        self.current_frame += len(data) // (self.wf.getsampwidth() * self.wf.getnchannels()) # More accurate frame count
        
        if len(data) < frame_count * self.wf.getsampwidth() * self.wf.getnchannels(): # End of file
            self.playing = False # Stop playing
            # self.tk_root.after_idle(self._on_playback_finished) # Schedule UI update
            return (data, pyaudio.paComplete)
        return (data, pyaudio.paContinue)

    # def _on_playback_finished(self):
    #     # This method can be used to update UI elements when playback naturally ends
    #     # For example, changing the play/pause button text
    #     if hasattr(self.tk_root, 'play_pause_button'): # Check if the calling UI has this
    #         self.tk_root.play_pause_button.config(text="Play")
    #     logger.info("Audio playback finished.")
    #     self.wf.rewind()
    #     self.current_frame = 0


    def play_audio(self): # Renamed from original play_audio for clarity, this is now more like 'resume'
        if not self.stream or not self.wf: return
        if not self.playing: # If it was paused
            self.playing = True
        if not self.stream.is_active():
            self.stream.start_stream()
            logger.debug("AudioPlayer: Stream (re)started.")
        # The actual data feeding is handled by the callback and the _update_audio_progress_loop in CorrectionWindow

    def pause(self):
        if not self.stream or not self.wf: return
        if self.playing:
            self.playing = False
            if self.stream.is_active():
                 self.stream.stop_stream() # Pauses the callback
            logger.debug("AudioPlayer: Stream stopped (paused).")

    def stop(self): # Full stop and release resources
        self.playing = False
        if self.stream:
            if self.stream.is_active():
                self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            logger.debug("AudioPlayer: Stream closed.")
        if self.p:
            self.p.terminate()
            self.p = None
            logger.debug("AudioPlayer: PyAudio instance terminated.")
        if self.wf:
            self.wf.close()
            self.wf = None
            logger.debug("AudioPlayer: Wave file closed.")
        self.current_frame = 0


    def set_speed(self, speed_factor):
        # This is more complex with callback-based PyAudio stream.
        # Changing rate often requires closing and reopening the stream.
        # For now, this might be disabled or simplified.
        logger.warning("AudioPlayer: set_speed is complex with current callback stream and not fully implemented.")
        if not self.wf or not self.p: return
        
        # Simple approach: pause, reopen stream with new rate, try to resume
        # This will likely lose current position or require careful management.
        was_playing = self.playing
        self.pause()

        try:
            current_pos_seconds = self.current_frame / self.frame_rate if self.frame_rate > 0 else 0
            
            # Close existing stream
            if self.stream:
                self.stream.close()

            # Reopen stream with new rate
            new_rate = int(self.wf.getframerate() * speed_factor)
            self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                            channels=self.wf.getnchannels(),
                            rate=new_rate,
                            output=True,
                            stream_callback=self._audio_callback)
            
            # Attempt to seek to the original position in terms of audio content
            # This is tricky because frame counts change with rate for the same duration
            # For simplicity, we might just reset or seek to nearest equivalent frame
            # self.wf.rewind() # Or try to set pos based on time
            # self.current_frame = 0
            
            # Try to set position based on time
            self.frame_rate = new_rate # Update internal frame rate
            target_frame_at_new_rate = int(current_pos_seconds * new_rate)
            self.wf.setpos(min(target_frame_at_new_rate, self.wf.getnframes()))
            self.current_frame = self.wf.tell()


            if was_playing:
                self.play_audio()
            logger.info(f"AudioPlayer: Speed set to {speed_factor}x. Stream reconfigured.")

        except Exception as e:
            logger.exception(f"AudioPlayer: Error setting speed to {speed_factor}x.")
            # Attempt to restore previous state or alert user