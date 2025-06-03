    # hook-whisper.py
from PyInstaller.utils.hooks import collect_data_files

    # Collect the 'assets' directory from the whisper package.
    # This should include mel_filters.npz and other necessary assets like vocabularies.
datas = collect_data_files('whisper', subdir='assets', destdir='whisper/assets', include_py_files=False)

    # Whisper might also have other data at its root, like model configurations or multilingual files.
    # If you encounter errors for other missing whisper files, add them here. For example:
    # datas += collect_data_files('whisper', subdir='.', includes=['*.json', '*.txt', '*.pt'], destdir='whisper')
    # For now, let's focus on 'assets'.
print(f"Hook-whisper: Adding data files: {datas}")