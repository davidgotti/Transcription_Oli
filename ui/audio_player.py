# ui/audio_player.py
import wave
import pyaudio
import logging

logger = logging.getLogger(__name__)

class AudioPlayer:
    def __init__(self, filename, tk_root):
        self.filename = filename
        self.tk_root = tk_root # Tkinter root for self.tk_root.after()
        self.wf = None
        self.p = None
        self.stream = None
        self.chunk = 1024
        self.frame_rate = 0
        self.total_frames = 0
        self.current_frame = 0
        self.playing = False
        self._ready = False
        self._paused = False 

        try:
            self.wf = wave.open(filename, 'rb')
            self.p = pyaudio.PyAudio()
            self.frame_rate = self.wf.getframerate()
            self.total_frames = self.wf.getnframes()
            
            # Stream is opened only when play() is called
            self._ready = True
            logger.info(f"AudioPlayer initialized for {filename}. Ready to play.")
        except Exception as e:
            logger.exception(f"Failed to initialize AudioPlayer for {filename}")
            self._ready = False
            self.stop_resources() # Clean up any partial resources

    def is_ready(self):
        return self._ready

    def _open_stream_if_needed(self):
        if not self.is_ready() or not self.p or not self.wf:
            logger.error("AudioPlayer cannot open stream: not ready or resources missing.")
            return False
        if self.stream is None: # Open stream only if it doesn't exist or was closed
            try:
                self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                                          channels=self.wf.getnchannels(),
                                          rate=self.frame_rate,
                                          output=True)
                logger.debug("AudioPlayer: Stream opened.")
                return True
            except Exception as e:
                logger.exception("AudioPlayer: Error opening stream.")
                self.stream = None
                return False
        return True # Stream already exists

    def _close_stream(self):
        if self.stream:
            try:
                if self.stream.is_active(): # Check if active before stopping
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logger.error(f"Error closing stream: {e}")
            finally:
                self.stream = None
                logger.debug("AudioPlayer: Stream closed.")
    
    def _play_frame_data(self):
        if not self.playing or not self.stream or not self.wf:
            self.playing = False # Ensure playing is false if we can't proceed
            return

        data = self.wf.readframes(self.chunk)
        if data:
            try:
                self.stream.write(data)
                self.current_frame = self.wf.tell() # More reliable way to get current frame after read
                self.tk_root.after(1, self._play_frame_data) # Schedule next chunk (1ms delay for responsiveness)
            except IOError as e: # Stream might be closed or in bad state
                 logger.error(f"AudioPlayer: IOError during stream write: {e}. Stopping playback.")
                 self.playing = False
                 self._close_stream() # Attempt to close problematic stream
            except Exception as e:
                 logger.exception(f"AudioPlayer: Unexpected error during stream write. Stopping playback.")
                 self.playing = False
        else: # No more data
            self.playing = False
            logger.info("AudioPlayer: Playback reached end of file.")
            # Let CorrectionWindow handle UI updates like button text change
            # self.current_frame = self.total_frames # Ensure current_frame is at end
            # self._close_stream() # Close stream when done. Play will re-open.


    def play(self):
        if not self.is_ready(): logger.warning("AudioPlayer: Not ready to play."); return
        if self.playing: logger.debug("AudioPlayer: Already playing."); return

        if not self._open_stream_if_needed(): # Ensure stream is open
            logger.error("AudioPlayer: Failed to open stream for playback.")
            return
        
        # If paused or starting fresh, ensure wave file pointer is correct
        if self.wf and self.wf.tell() != self.current_frame:
            try:
                self.wf.setpos(self.current_frame)
            except wave.Error as e:
                logger.error(f"Wave setpos error before play: {e}. Attempting rewind.")
                self.rewind() # If error, try full rewind
                if self.wf: self.wf.setpos(self.current_frame)


        self.playing = True
        self._paused = False
        self.tk_root.after(1, self._play_frame_data) # Start the playback loop
        logger.debug("AudioPlayer: Playback started/resumed.")

    def pause(self):
        if not self.is_ready(): return
        if self.playing:
            self.playing = False # This will stop the _play_frame_data loop
            self._paused = True
            logger.debug("AudioPlayer: Pause requested. Playback loop will stop.")
        # Stream remains open, current_frame holds position

    def stop_resources(self): # Full stop and release all PyAudio/wave resources
        self.playing = False
        self._paused = False
        self._close_stream() # Close the PyAudio stream
        if self.p:
            try: self.p.terminate()
            except Exception as e: logger.error(f"Error terminating PyAudio: {e}")
            finally: self.p = None; logger.debug("AudioPlayer: PyAudio instance terminated.")
        if self.wf:
            try: self.wf.close()
            except Exception as e: logger.error(f"Error closing wave file: {e}")
            finally: self.wf = None; logger.debug("AudioPlayer: Wave file closed.")
        self.current_frame = 0
        self._ready = False 

    def stop(self): # User-facing stop: pauses, rewinds, prepares for next play
        if not self.is_ready(): return
        self.playing = False
        self._paused = False
        self.rewind() # Rewind to beginning on stop
        # Stream can be closed here if desired, or left open for next play
        # self._close_stream() 
        logger.debug("AudioPlayer: Playback stopped and rewound.")


    def rewind(self):
        if not self.wf: logger.warning("AudioPlayer: Cannot rewind, wave file not open."); return
        self.current_frame = 0
        try:
            self.wf.rewind()
        except Exception as e:
            logger.error(f"Error rewinding wave file: {e}")
        logger.debug("AudioPlayer: Rewound to beginning.")

    def set_pos_frames(self, frame_position):
        if not self.wf: return
        self.current_frame = max(0, min(frame_position, self.total_frames))
        try:
            self.wf.setpos(self.current_frame)
        except wave.Error as e:
            logger.error(f"AudioPlayer: Error setting wave position: {e}. Attempting rewind.")
            self.rewind()
        logger.debug(f"AudioPlayer: Position set to frame {self.current_frame}")

    def is_finished(self):
        if not self.wf: return True 
        return self.current_frame >= self.total_frames