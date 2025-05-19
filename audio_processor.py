
# audio_processor.py
import whisper
import torch
from pyannote.audio import Pipeline

class AudioProcessor:
    def __init__(self, hf_token=None): # Added hf_token parameter
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Determine how to use the token for pyannote.audio
        # If hf_token is a non-empty string, use it. Otherwise, pass False.
        use_auth_value = hf_token if isinstance(hf_token, str) and hf_token.strip() else False
        
        print(f"Initializing pyannote.audio.Pipeline with use_auth_token: {use_auth_value if isinstance(use_auth_value, bool) else 'provided token'}")

        try:
            self.pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=use_auth_value # Use the processed token value
            ).to(self.device)
        except Exception as e:
            # Handle cases where pipeline loading might fail due to token issues or network
            print(f"Error initializing pyannote.audio Pipeline: {e}")
            print("Ensure your Hugging Face token is correct and you have an internet connection if models need downloading.")
            print("If no token is provided, diarization accuracy might be affected or model loading might fail for some models.")
            # Depending on desired behavior, you might re-raise or set pipeline to None
            self.pipeline = None # Or raise e to stop app initialization
            # raise e # Uncomment to make this a fatal error for AudioProcessor

        self.model = whisper.load_model("large")  # Or specify the model size you want
        self.overlap_threshold_percentage = 1  # You can adjust this

    def process_audio(self, audio_file_path):
        if not self.pipeline:
            raise RuntimeError("Pyannote diarization pipeline is not initialized. Check Hugging Face token and errors.")
            
        diarization = self.pipeline(audio_file_path)
        result = self.model.transcribe(audio_file_path, language="fr")

        whisper_segments = result["segments"]
        diarization_segments = list(diarization.itertracks(yield_label=True))

        aligned_output_condensed = []
        last_speaker = None

        for whisper_segment in whisper_segments:
            whisper_start = whisper_segment['start']
            whisper_end = whisper_segment['end']
            whisper_duration = whisper_end - whisper_start
            if whisper_duration == 0: # Avoid division by zero
                continue
            whisper_text = whisper_segment['text'].strip()
            assigned_speaker = "Unknown"
            max_overlap = 0
            potential_speaker = "Unknown" # Initialize potential_speaker

            for diarization_turn, _, speaker in diarization_segments:
                diarization_start = diarization_turn.start
                diarization_end = diarization_turn.end

                overlap_start = max(whisper_start, diarization_start)
                overlap_end = min(whisper_end, diarization_end)
                overlap_duration = max(0, overlap_end - overlap_start)

                if overlap_duration > max_overlap:
                    max_overlap = overlap_duration
                    potential_speaker = speaker
            
            # Check if max_overlap is significant enough based on percentage of whisper_duration
            # And ensure there was some overlap
            if (max_overlap / whisper_duration) * 100 >= self.overlap_threshold_percentage and max_overlap > 0:
                assigned_speaker = potential_speaker

            timestamp = f"{int(whisper_start) // 60:02d}:{int(whisper_start) % 60:02d}"
            speaker_name = assigned_speaker

            current_segment_text = f": {whisper_text}" # Keep space before colon for splitting in UI

            if assigned_speaker == last_speaker and aligned_output_condensed:
                # Append text to the last segment
                aligned_output_condensed[-1] += f" {whisper_text}"
            else:
                # Start a new segment entry
                aligned_output_condensed.append(f"{timestamp} {speaker_name} {current_segment_text}")
                last_speaker = assigned_speaker
        return aligned_output_condensed
