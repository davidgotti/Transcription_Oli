import wave
import pyaudio
import tkinter as tk #needed for the .after() method

class AudioPlayer:
    def __init__(self, filename):
        self.filename = filename
        self.wf = wave.open(filename, 'rb')
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                        channels=self.wf.getnchannels(),
                        rate=self.wf.getframerate(),
                        output=True)
        self.chunk = 1024
        self.frame_rate = self.wf.getframerate()
        self.current_frame = 0
        self.playing = False

    def play(self):
        if not self.playing:
            self.playing = True
            self.stream.start_stream()
            self.play_audio()

    def play_audio(self):
        if self.playing:
            data = self.wf.readframes(self.chunk)
            if data:
                self.stream.write(data)
                self.current_frame += self.chunk
                # Use after to keep the GUI responsive
                root = tk._default_root #get the root
                root.after(0, self.play_audio)
            else:
                self.stop() #stop at the end
                #self.wf.rewind()
                #self.current_frame = 0

    def pause(self):
        if self.playing:
            self.playing = False
            self.stream.stop_stream()

    def stop(self):
        if self.playing:
            self.playing = False
            self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
        self.wf.close()

    def set_speed(self, speed_factor):
        if not self.playing:
            return

        self.pause()
        self.wf = wave.open(self.filename, 'rb')
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=self.p.get_format_from_width(self.wf.getsampwidth()),
                        channels=self.wf.getnchannels(),
                        rate=int(self.wf.getframerate() * speed_factor),  # Change the rate
                        output=True)
        self.wf.setpos(self.current_frame)
        self.play()
