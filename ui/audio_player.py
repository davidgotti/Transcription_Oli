# ui/audio_player.py
import wave
import pyaudio
import logging
import threading
import queue
import time

logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, filename, on_error_callback=None): # tk_root removed
        self.filename = filename
        self.wf = None
        self.p = None
        self.stream = None
        self.chunk = 1024
        self.frame_rate = 0
        self.total_frames = 0
        self.current_frame = 0
        
        self._playing = False # Indicates if actively outputting audio
        self._paused = False  # Indicates if paused by user

        self.update_queue = queue.Queue()
        self.playback_thread = None
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.seek_request_event = threading.Event()
        self.seek_to_frame = 0

        self.on_error_callback = on_error_callback # Callback for critical errors

        self._ready = False
        try:
            self.wf = wave.open(filename, 'rb')
            self.p = pyaudio.PyAudio()
            self.frame_rate = self.wf.getframerate()
            self.total_frames = self.wf.getnframes()
            if self.frame_rate <= 0 or self.total_frames <= 0:
                raise ValueError("Invalid audio file properties (frame rate or total frames).")
            self._ready = True
            logger.info(f"AudioPlayer initialized for {filename}. Ready to play.")
            self.update_queue.put(('initialized', self.current_frame, self.total_frames, self.frame_rate))
        except Exception as e:
            logger.exception(f"Failed to initialize AudioPlayer for {filename}")
            self._ready = False
            self.stop_resources() # Clean up any partial resources
            if self.on_error_callback:
                self.on_error_callback(f"Failed to load audio: {e}")
            self.update_queue.put(('error', f"Failed to load audio: {e}"))


    def get_update_queue(self):
        return self.update_queue

    def is_ready(self):
        return self._ready

    def _open_stream_if_needed(self):
        if not self.is_ready() or not self.p or not self.wf:
            logger.error("AudioPlayer cannot open stream: not ready or resources missing.")
            return False
        if self.stream is None or not self.stream.is_active(): # Ensure stream is active
            try:
                # Close existing inactive stream if any before opening a new one
                if self.stream and not self.stream.is_active():
                    self._close_stream()

                self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                                          channels=self.wf.getnchannels(),
                                          rate=self.frame_rate,
                                          output=True)
                logger.debug("AudioPlayer: Stream opened/re-opened.")
                return True
            except Exception as e:
                logger.exception("AudioPlayer: Error opening stream.")
                self.stream = None
                self.update_queue.put(('error', f"PyAudio stream error: {e}"))
                if self.on_error_callback:
                    self.on_error_callback(f"PyAudio stream error: {e}")
                return False
        return True

    def _close_stream(self):
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logger.error(f"Error closing stream: {e}")
            finally:
                self.stream = None
                logger.debug("AudioPlayer: Stream closed.")
    
    def _playback_loop(self):
        logger.debug(f"Playback thread started for {self.filename}")
        self._playing = True
        self._paused = False
        
        if not self._open_stream_if_needed():
            self._playing = False
            logger.error("Playback loop: Stream could not be opened.")
            return

        try:
            self.wf.setpos(self.current_frame) # Ensure position before loop
            
            # Calculate ideal sleep time based on chunk size and frame rate
            # This helps in smoother playback and yielding control.
            # If frame_rate or chunk is zero, this will cause issues.
            if self.frame_rate > 0 and self.chunk > 0:
                chunk_duration_ms = (self.chunk / self.frame_rate) * 1000
            else: # Fallback, though frame_rate should be validated earlier
                chunk_duration_ms = 10 # approx 100 FPS for 1024 chunk, rough default
            
            min_sleep_ms = 1 # Minimum sleep to prevent busy-waiting too hard

            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    # self._playing = False # No, playing is true, but paused is true
                    time.sleep(0.05) # Sleep while paused
                    continue
                
                if self.seek_request_event.is_set():
                    logger.debug(f"Seek request detected in loop: frame {self.seek_to_frame}")
                    self.current_frame = self.seek_to_frame
                    self.wf.setpos(self.current_frame)
                    self.update_queue.put(('progress', self.current_frame))
                    self.seek_request_event.clear()
                    if self.current_frame >= self.total_frames: # Seeked to or past end
                        logger.debug("Seeked to end, stopping playback loop.")
                        break # Exit loop if seeked to end


                loop_start_time_ms = time.perf_counter() * 1000
                
                data = self.wf.readframes(self.chunk)
                if not data:
                    logger.info("Playback reached end of file.")
                    self.current_frame = self.total_frames # Ensure it's at the end
                    self.update_queue.put(('progress', self.current_frame)) # Final progress
                    self.update_queue.put(('finished',))
                    break

                if not self.stream or not self.stream.is_active():
                    logger.warning("Stream became inactive during playback. Attempting to reopen.")
                    if not self._open_stream_if_needed():
                        logger.error("Failed to reopen stream. Stopping playback.")
                        self.update_queue.put(('error', "Audio stream failed during playback."))
                        break
                
                try:
                    self.stream.write(data)
                    self.current_frame = self.wf.tell()
                    self.update_queue.put(('progress', self.current_frame))
                except IOError as e:
                    logger.error(f"PyAudio IOError during stream write: {e}. Stopping playback.")
                    self.update_queue.put(('error', f"Audio playback error: {e}"))
                    break
                except Exception as e:
                    logger.exception(f"Unexpected error during stream write. Stopping.")
                    self.update_queue.put(('error', f"Unexpected playback error: {e}"))
                    break

                # Calculate processing time and adjust sleep
                loop_end_time_ms = time.perf_counter() * 1000
                processing_time_ms = loop_end_time_ms - loop_start_time_ms
                sleep_time_ms = max(min_sleep_ms, chunk_duration_ms - processing_time_ms)
                time.sleep(sleep_time_ms / 1000.0)

        except Exception as e:
            logger.exception("Exception in playback loop.")
            self.update_queue.put(('error', f"Internal playback error: {e}"))
        finally:
            self._playing = False
            # self._close_stream() # Stream is often kept open for quick resume/replay
            logger.debug(f"Playback thread finished for {self.filename}")
            if self.stop_event.is_set(): # if stopped by user action
                 self.update_queue.put(('stopped',)) # Signal it was a deliberate stop if not end of file


    @property
    def playing(self): # Public property for playing state
        return self._playing and not self._paused

    @property
    def paused(self): # Public property for paused state
        return self._paused

    def play(self):
        if not self.is_ready():
            logger.warning("AudioPlayer: Not ready to play.")
            self.update_queue.put(('error', 'Audio player not ready.'))
            return

        if self.playing: # Already actively playing (not just paused)
            if self._paused: # Was paused, now resuming
                logger.debug("Resuming playback.")
                self._paused = False
                self.pause_event.clear()
                self._playing = True # Ensure this is set
                self.update_queue.put(('resumed',))
            else: # Truly already playing
                logger.debug("AudioPlayer: Already playing (and not paused).")
            return

        logger.debug(f"Play called. Current frame: {self.current_frame}, Total: {self.total_frames}")
        if self.current_frame >= self.total_frames: # If at end, rewind first
            logger.debug("At end of file, rewinding before play.")
            self.current_frame = 0 # Rewind explicitly
            if self.wf: self.wf.rewind()
            self.update_queue.put(('progress', self.current_frame))


        self.stop_event.clear()
        self.pause_event.clear()
        self._paused = False
        # self._playing = True # Will be set by the thread start

        if self.playback_thread is not None and self.playback_thread.is_alive():
            logger.warning("Playback thread already exists and is alive. This shouldn't happen if logic is correct.")
            # Attempt to stop previous thread cleanly if it's stuck
            self.stop_event.set()
            self.playback_thread.join(timeout=0.1) 
            self.stop_event.clear() # Clear for the new thread

        self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self.playback_thread.start()
        self.update_queue.put(('started',))


    def pause(self):
        if not self.is_ready() or not self._playing or self._paused : return # Not playing or already paused
        
        self.pause_event.set()
        self._paused = True
        # self._playing = False # Keep _playing true to indicate that playback *session* is active
        logger.debug("AudioPlayer: Pause requested.")
        self.update_queue.put(('paused',))


    def stop_resources(self): # Full stop and release all PyAudio/wave resources
        logger.debug("Stopping all resources for AudioPlayer.")
        self.stop_event.set()
        if self.playback_thread is not None and self.playback_thread.is_alive():
            logger.debug("Joining playback thread...")
            self.playback_thread.join(timeout=0.5) # Wait for thread to finish
            if self.playback_thread.is_alive():
                logger.warning("Playback thread did not terminate in time.")
        self.playback_thread = None
        
        self._close_stream()
        
        if self.p:
            try: 
                self.p.terminate()
                logger.debug("PyAudio instance terminated.")
            except Exception as e: logger.error(f"Error terminating PyAudio: {e}")
            finally: self.p = None
        
        if self.wf:
            try: 
                self.wf.close()
                logger.debug("Wave file closed.")
            except Exception as e: logger.error(f"Error closing wave file: {e}")
            finally: self.wf = None
        
        self.current_frame = 0
        self._playing = False
        self._paused = False
        self._ready = False # No longer ready after resources are stopped
        # Do not put 'stopped' on queue here, as this is a full cleanup, not a user stop action.


    def stop(self): # User-facing stop: stops playback, rewinds.
        if not self.is_ready(): return
        logger.debug("User stop requested.")
        
        self.stop_event.set() # Signal thread to stop
        if self.playback_thread is not None and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=0.2) # Give a short time for graceful exit
        
        # After thread has stopped (or timeout)
        self._playing = False
        self._paused = False
        self.pause_event.clear() # Ensure pause is not latched for next play
        
        self.rewind(send_update=True) # Rewind and send progress update
        # self.update_queue.put(('stopped',)) # 'rewind' sends progress, which implies stop for UI

    def rewind(self, send_update=False): # send_update for when UI needs to know
        if not self.wf: logger.warning("AudioPlayer: Cannot rewind, wave file not open."); return
        
        self.current_frame = 0
        self.wf.rewind() # wave.Error can be raised if stream is not seekable, but wf.rewind() is usually safe
        
        # If playback thread is running, it should pick this up via seek or be restarted.
        # For simplicity, if playing, we might need to signal a seek.
        if self._playing and self.playback_thread and self.playback_thread.is_alive():
             self.seek_to_frame = 0
             self.seek_request_event.set() # Signal running thread to seek

        logger.debug("AudioPlayer: Rewound to beginning.")
        if send_update:
            self.update_queue.put(('progress', self.current_frame))


    def set_pos_frames(self, frame_position):
        if not self.wf: return
        
        new_frame = max(0, min(int(frame_position), self.total_frames))
        self.current_frame = new_frame
        logger.debug(f"AudioPlayer: Position set to frame {self.current_frame}")

        if self._playing and self.playback_thread and self.playback_thread.is_alive() and not self.stop_event.is_set():
            self.seek_to_frame = self.current_frame
            self.seek_request_event.set() # Signal thread to handle seek
        else: # Not actively playing, just update position and wf object
            try:
                self.wf.setpos(self.current_frame)
            except wave.Error as e:
                logger.error(f"AudioPlayer: Error setting wave position: {e}. Attempting rewind.")
                self.rewind() # Fallback
            self.update_queue.put(('progress', self.current_frame)) # Update UI


    def is_finished(self):
        if not self.wf: return True 
        return self.current_frame >= self.total_frames