# ui/audio_player.py
import wave
import pyaudio
import logging
import threading
import queue
import time

logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, filename, on_error_callback=None):
        self.filename = filename
        self.wf = None
        self.p = None
        self.stream = None
        self.chunk = 4096
        self.frame_rate = 0
        self.total_frames = 0
        self.current_frame = 0
        
        self._playing = False 
        self._paused = False  

        self.update_queue = queue.Queue()
        self.playback_thread = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.seek_request_event = threading.Event()
        self.seek_to_frame = 0

        self.on_error_callback = on_error_callback

        self._ready = False
        try:
            self.wf = wave.open(filename, 'rb')
            self.p = pyaudio.PyAudio()
            self.frame_rate = self.wf.getframerate()
            self.total_frames = self.wf.getnframes()
            if self.frame_rate <= 0 or self.total_frames <= 0: # Ensure total_frames is also positive
                error_msg = "Invalid audio file properties (frame rate or total frames is zero or negative)."
                logger.error(f"{error_msg} - File: {filename}")
                raise ValueError(error_msg)
            self._ready = True
            logger.info(f"AudioPlayer initialized for {filename}. Ready to play.")
            self.update_queue.put(('initialized', self.current_frame, self.total_frames, self.frame_rate))
        except Exception as e:
            logger.exception(f"Failed to initialize AudioPlayer for {filename}")
            self._ready = False
            self.stop_resources() 
            error_msg = f"Failed to load audio: {e}"
            if self.on_error_callback:
                self.on_error_callback(error_msg)
            self.update_queue.put(('error', error_msg))


    def get_update_queue(self):
        return self.update_queue

    def is_ready(self):
        return self._ready

    def _open_stream_if_needed(self):
        if not self.is_ready() or not self.p or not self.wf:
            logger.error("AudioPlayer cannot open stream: not ready or PyAudio/wave file resources missing.")
            return False
        
        if self.stream and not self.stream.is_active():
            logger.info("Stream found inactive, closing it before reopening.")
            self._close_stream() 

        if self.stream is None: 
            try:
                self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                                          channels=self.wf.getnchannels(),
                                          rate=self.frame_rate,
                                          output=True,
                                          frames_per_buffer=self.chunk) # <--- ADD THIS ARGUMENT
                logger.debug(f"AudioPlayer: New stream opened with frames_per_buffer={self.chunk}.")
                return True
            except Exception as e:
                logger.exception("AudioPlayer: Error opening new stream.")
                self.stream = None 
                error_msg = f"PyAudio stream error: {e}"
                self.update_queue.put(('error', error_msg))
                if self.on_error_callback:
                    self.on_error_callback(error_msg)
                return False
        return True

    def _close_stream(self):
        if self.stream:
            logger.debug("Attempting to close audio stream.")
            try:
                if self.stream.is_active(): # Only stop if active
                    self.stream.stop_stream()
                self.stream.close()
                logger.info("AudioPlayer: Stream closed successfully.")
            except Exception as e:
                logger.error(f"Error closing stream: {e}", exc_info=True)
            finally:
                self.stream = None
    
    def _playback_loop(self):
        logger.info(f"Playback thread started for {self.filename}. Current frame: {self.current_frame}")
        self._playing = True # Mark as active playback
        self._paused = False 
        
        if not self._open_stream_if_needed():
            self._playing = False
            logger.error("Playback loop: Stream could not be opened at start.")
            self.update_queue.put(('error', "Failed to open audio stream for playback."))
            return

        try:
            if self.current_frame < self.total_frames : # Ensure we only setpos if not at end already
                self.wf.setpos(self.current_frame)
            
            if self.frame_rate > 0 and self.chunk > 0:
                chunk_duration_ms = (self.chunk / self.frame_rate) * 1000
            else: 
                chunk_duration_ms = 20 # Fallback, approx 50 FPS for 1024 chunk if frame_rate broken

            min_sleep_ms = 1 

            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    time.sleep(0.05) 
                    continue # Loop back to check stop_event or if pause_event is cleared
                
                # Handle seek before reading data for this iteration
                if self.seek_request_event.is_set():
                    requested_frame = self.seek_to_frame
                    logger.debug(f"Playback loop: Seek request processing for frame {requested_frame}")
                    self.current_frame = max(0, min(requested_frame, self.total_frames))
                    self.wf.setpos(self.current_frame)
                    self.update_queue.put(('progress', self.current_frame))
                    self.seek_request_event.clear()
                    if self.current_frame >= self.total_frames:
                        logger.info("Playback loop: Seeked to or past end of file.")
                        break # End of file reached by seek

                if self.current_frame >= self.total_frames: # Check again after seek or normal increment
                    logger.info("Playback loop: Reached end of file naturally.")
                    break # End of file

                loop_start_time_ms = time.perf_counter() * 1000
                
                data = self.wf.readframes(self.chunk)
                if not data:
                    logger.info("Playback loop: End of data stream (readframes returned empty).")
                    self.current_frame = self.total_frames 
                    break 

                if not self.stream or not self.stream.is_active():
                    logger.warning("Playback loop: Stream became inactive. Attempting to reopen.")
                    if not self._open_stream_if_needed():
                        logger.error("Playback loop: Failed to reopen stream. Stopping playback.")
                        self.update_queue.put(('error', "Audio stream failed during playback."))
                        break 
                
                try:
                    self.stream.write(data)
                    self.current_frame = self.wf.tell() # Update after successful write
                    if self.current_frame > self.total_frames : # Should not happen if wf.tell() is accurate
                         self.current_frame = self.total_frames
                    self.update_queue.put(('progress', self.current_frame))
                except IOError as e:
                    logger.error(f"Playback loop: PyAudio IOError during stream write: {e}. Stopping playback.", exc_info=True)
                    self.update_queue.put(('error', f"Audio playback error: {e}"))
                    break 
                except Exception as e:
                    logger.exception(f"Playback loop: Unexpected error during stream write. Stopping.")
                    self.update_queue.put(('error', f"Unexpected playback error: {e}"))
                    break 

                loop_end_time_ms = time.perf_counter() * 1000
                processing_time_ms = loop_end_time_ms - loop_start_time_ms
                sleep_time_ms = max(min_sleep_ms, chunk_duration_ms - processing_time_ms)
                time.sleep(sleep_time_ms / 1000.0)

        except Exception as e:
            logger.exception("Playback loop: Unhandled exception.")
            self.update_queue.put(('error', f"Internal playback loop error: {e}"))
        finally:
            self._playing = False # Playback loop has ended
            if self.current_frame >= self.total_frames and not self.stop_event.is_set():
                self.update_queue.put(('progress', self.total_frames)) # Ensure final progress is sent
                self.update_queue.put(('finished',))
            elif self.stop_event.is_set():
                 self.update_queue.put(('stopped',))
            logger.info(f"Playback thread finished for {self.filename}. Stop event: {self.stop_event.is_set()}")
            # Stream is not closed here; managed by stop_resources or if it becomes inactive.

    @property
    def playing(self): 
        return self._playing and not self._paused

    @property
    def paused(self): 
        return self._paused

    def play(self):
        if not self.is_ready():
            logger.warning("AudioPlayer: Not ready to play (e.g., file load failed).")
            self.update_queue.put(('error', 'Audio player not ready.'))
            return

        if self._playing and not self._paused: # Actively playing and not paused
            logger.debug("AudioPlayer: Play called but already playing and not paused.")
            return
        
        if self._playing and self._paused: # Was paused, now resuming
            logger.info("Resuming playback.")
            self._paused = False
            self.pause_event.clear()
            # _playing is already true
            self.update_queue.put(('resumed',))
            return

        # This is a new play request or playing after being fully stopped
        logger.info(f"Play requested. Current frame: {self.current_frame}, Total: {self.total_frames}")

        # Ensure any previous thread is fully stopped.
        if self.playback_thread is not None and self.playback_thread.is_alive():
            logger.warning("Play: Existing playback thread detected. Attempting to stop it before starting a new one.")
            self.stop_event.set()
            self.pause_event.clear() # If paused, unpause to allow stop_event processing
            self.playback_thread.join(timeout=1.0) # Wait up to 1 sec

            if self.playback_thread.is_alive():
                logger.error("Play: Previous playback thread did NOT terminate in time. Aborting new play request to prevent instability.")
                self.update_queue.put(('error', "Critical: Previous audio session conflict."))
                # Do not clear stop_event here as the old thread might still be using it. A full re-init might be needed.
                return 
            logger.info("Play: Previous playback thread terminated successfully.")
            self.playback_thread = None # Clear the old thread reference

        # Reset events for the new thread
        self.stop_event.clear()
        self.pause_event.clear()
        self.seek_request_event.clear()
        self._paused = False
        
        if self.current_frame >= self.total_frames and self.total_frames > 0:
            logger.info("Play: At end of file, rewinding to start.")
            self.current_frame = 0
            if self.wf: 
                try:
                    self.wf.setpos(self.current_frame)
                except wave.Error as e: # Should not happen if wf is valid
                     logger.error(f"Error setting wave position during rewind: {e}")
                     self.update_queue.put(('error', "Failed to rewind audio."))
                     return
            self.update_queue.put(('progress', self.current_frame)) # Update UI about rewind

        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()
        self.update_queue.put(('started',))


    def pause(self):
        if not self._playing or self._paused: # Not in an active playback session or already paused
            logger.debug(f"Pause called but not actively playing or already paused. Playing: {self._playing}, Paused: {self._paused}")
            return
        
        self.pause_event.set()
        self._paused = True
        logger.info("AudioPlayer: Pause requested and set.")
        self.update_queue.put(('paused',))


    def stop_resources(self): 
        logger.info("Stopping all AudioPlayer resources.")
        if self.playback_thread is not None and self.playback_thread.is_alive():
            logger.debug("stop_resources: Playback thread is active. Setting stop_event and joining...")
            self.stop_event.set()
            self.pause_event.clear() # Ensure not stuck in pause
            self.playback_thread.join(timeout=1.0) 
            if self.playback_thread.is_alive():
                logger.warning("stop_resources: Playback thread did not terminate in time. Resources will be closed, but thread may be orphaned.")
        self.playback_thread = None # Dereference
        
        self._close_stream() # Ensure stream is closed
        
        if self.p:
            try: 
                self.p.terminate()
                logger.info("PyAudio instance terminated.")
            except Exception as e: logger.error(f"Error terminating PyAudio: {e}", exc_info=True)
            finally: self.p = None
        
        if self.wf:
            try: 
                self.wf.close()
                logger.info("Wave file closed.")
            except Exception as e: logger.error(f"Error closing wave file: {e}", exc_info=True)
            finally: self.wf = None
        
        self.current_frame = 0 # Reset position
        self._playing = False
        self._paused = False
        self._ready = False # Player is no longer ready
        self.stop_event.clear() # Clear for any future re-initialization (though usually a new instance is made)
        logger.info("AudioPlayer resources stopped and cleaned up.")


    def stop(self): 
        if not self._playing and not self._paused: # if not playing and not paused, nothing to stop.
             logger.debug("Stop called but player was not active.")
             # If we want to ensure it's rewound even if "stopped" when not playing:
             if self.is_ready() and self.current_frame != 0: self.rewind(send_update=True)
             return

        logger.info("User stop requested.")
        
        if self.playback_thread is not None and self.playback_thread.is_alive():
            self.stop_event.set() 
            self.pause_event.clear() # If paused, let it see stop event
            self.playback_thread.join(timeout=0.5) # Shorter timeout for user stop is okay, relies on loop seeing event
            if self.playback_thread.is_alive():
                 logger.warning("Stop: Playback thread join timed out. It might not have exited cleanly.")
        # No matter the thread state, update player state
        self._playing = False
        self._paused = False
        self.pause_event.clear() 
        
        if self.is_ready(): # Only rewind if player is still in a somewhat valid state
            self.rewind(send_update=True) 
        else: # If not ready, at least reset frame variable
             self.current_frame = 0
             self.update_queue.put(('progress', self.current_frame))
        
        # The playback_loop itself should send ('stopped',) when stop_event is processed.

    def rewind(self, send_update=False): 
        if not self.is_ready() or not self.wf: 
            logger.warning("AudioPlayer: Cannot rewind, not ready or wave file not open.")
            return
        
        logger.debug("AudioPlayer: Rewinding to beginning.")
        self.current_frame = 0
        try:
            self.wf.setpos(self.current_frame)
        except wave.Error as e:
            logger.error(f"AudioPlayer: Wave error on rewind setpos: {e}. Re-initializing may be needed.")
            # This indicates a potentially corrupted wave object state.
            self.update_queue.put(('error', "Failed to rewind audio file properly."))
            return # Avoid further operations if wf is bad
        
        if self._playing and self.playback_thread and self.playback_thread.is_alive():
             logger.debug("Rewind: Signaling active playback thread to seek to frame 0.")
             self.seek_to_frame = 0
             self.seek_request_event.set() 
        
        if send_update:
            self.update_queue.put(('progress', self.current_frame))


    def set_pos_frames(self, frame_position):
        if not self.is_ready() or not self.wf: 
            logger.warning("AudioPlayer: Cannot set position, not ready or wave file not open.")
            return
        
        new_frame = max(0, min(int(frame_position), self.total_frames))
        
        logger.debug(f"AudioPlayer: Position set request to frame {new_frame}. Current playing state: {self._playing}")

        if self._playing and self.playback_thread and self.playback_thread.is_alive() and not self.stop_event.is_set() and not self.pause_event.is_set() :
            # Only set seek_request_event if playing and not paused.
            # If paused, the position will be picked up when resumed or if seek happens while paused.
            self.current_frame = new_frame # Update immediately for external queries
            self.seek_to_frame = new_frame
            self.seek_request_event.set() 
            logger.debug(f"AudioPlayer: Seek event set for frame {new_frame}.")
        else: 
            # If not actively playing in the thread, or if paused, set position directly.
            # The playback loop will pick up self.current_frame when it resumes or starts.
            self.current_frame = new_frame
            try:
                self.wf.setpos(self.current_frame)
            except wave.Error as e:
                logger.error(f"AudioPlayer: Error setting wave position directly: {e}. Attempting rewind as fallback.")
                self.rewind(send_update=True) # Attempt to recover with a rewind
                return
            logger.debug(f"AudioPlayer: Position set directly in wave object to frame {self.current_frame}.")
            self.update_queue.put(('progress', self.current_frame))


    def is_finished(self):
        if not self.is_ready() or not self.wf: return True 
        return self.current_frame >= self.total_frames