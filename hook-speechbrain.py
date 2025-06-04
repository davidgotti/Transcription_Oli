# hook-speechbrain.py
import os
from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    copy_metadata,
    get_package_paths
)

# Collect all Python submodules from speechbrain.
hiddenimports = collect_submodules('speechbrain')
# Also explicitly add submodules that might be dynamically imported by importutils
hiddenimports.extend([
    'speechbrain.dataio.sampler',
    'speechbrain.dataio.dataloader',
    'speechbrain.dataio.dataset',
    'speechbrain.dataio.batch',
    'speechbrain.dataio.wer', # If WER calculation utilities are used
    'speechbrain.utils.checkpoints',
    'speechbrain.utils.data_pipeline',
    'speechbrain.utils.distributed',
    'speechbrain.utils.dynamic_chunking',
    'speechbrain.utils.edit_distance',
    'speechbrain.utils.fetching',
    'speechbrain.utils.hpopt',
    'speechbrain.utils.importutils', # Already tried
    'speechbrain.utils.Accuracy',
    'speechbrain.utils.metric_stats',
    'speechbrain.utils.parallel',
    'speechbrain.utils.profiler',
    'speechbrain.utils.text_to_sequence',
    'speechbrain.utils.torch_audio_backend',
    'speechbrain.utils.train_logger',
    'speechbrain.utils.wav2vec2_prepare',
    'speechbrain.utils.wer',
])


datas = []
try:
    datas += copy_metadata('speechbrain')
except Exception as e:
    print(f"Hook-speechbrain: Warning - could not copy metadata for speechbrain: {e}")

try:
    datas += collect_data_files(
        'speechbrain',
        include_py_files=False,
        excludes=['**/__pycache__', '*.pyc']
    )
except Exception as e:
    print(f"Hook-speechbrain: Warning - could not collect general data files for speechbrain: {e}")

try:
    pkg_base, pkg_dir = get_package_paths('speechbrain')
    
# Handle speechbrain/utils
    utils_source_path = os.path.join(pkg_dir, 'utils')
    if os.path.isdir(utils_source_path):
        datas.append((utils_source_path, 'speechbrain/utils'))
        print(f"Hook-speechbrain: Added speechbrain/utils from {utils_source_path}")
        # Removed problematic collect_data_files line for speechbrain.utils
    else:
        print(f"Hook-speechbrain: Critical - Could not find speechbrain/utils directory at {utils_source_path}")

    # Handle speechbrain/dataio
    dataio_source_path = os.path.join(pkg_dir, 'dataio')
    if os.path.isdir(dataio_source_path):
        datas.append((dataio_source_path, 'speechbrain/dataio'))
        print(f"Hook-speechbrain: Added speechbrain/dataio from {dataio_source_path}")
        # Removed problematic collect_data_files line for speechbrain.dataio

    # Add other specific subdirectories if they cause issues later, e.g.:
    # pretrained_models_source_path = os.path.join(pkg_dir, 'pretrained_models')
    # if os.path.isdir(pretrained_models_source_path):
    #     datas.append((pretrained_models_source_path, 'speechbrain/pretrained_models', 'DATA'))

    # Add specific yaml/json config files if SpeechBrain loads them from its root or specific locations
    # Example: if there are .yaml files directly in pkg_dir that are needed
    # for item in os.listdir(pkg_dir):
    #     if item.endswith(".yaml") or item.endswith(".json"):
    #          datas.append((os.path.join(pkg_dir, item), 'speechbrain', 'DATA'))


except Exception as e:
    print(f"Hook-speechbrain: Error processing speechbrain subdirectories: {e}")