# utils/config_manager.py
import configparser
import os

# The module-level CONFIG_FILE is only used by the older save_token/load_token functions.
# If those functions are no longer used, this can be removed.
# For consistency, they should also use the path derived from constants.DEFAULT_CONFIG_FILE.
# However, the ConfigManager class is the primary focus.

TOKEN_SECTION = 'HuggingFace'
USE_AUTH_TOKEN_OPTION = 'use_auth_token'
TOKEN_OPTION = 'hf_token'

# (Old save_token and load_token functions - consider refactoring or removing if unused)
# def save_token(token): ...
# def load_token(): ...

class ConfigManager:
    def __init__(self, config_path): # config_path comes from constants.DEFAULT_CONFIG_FILE
        self.config = configparser.ConfigParser()
        self.path = config_path  # This will now be an absolute path

        # Ensure the directory for the config file exists
        config_dir = os.path.dirname(self.path)
        if config_dir and not os.path.exists(config_dir): # Check if config_dir is not empty
            try:
                os.makedirs(config_dir, exist_ok=True) # exist_ok=True is helpful
                # print(f"ConfigManager: Created directory {config_dir}") # Optional: for debugging
            except OSError as e:
                print(f"ConfigManager: CRITICAL - Could not create config directory '{config_dir}'. Config will not load/save. Error: {e}")
                # Depending on desired robustness, you might raise an error here
                # or allow the app to continue with in-memory defaults (but no persistence).

        if os.path.exists(self.path):
            try:
                self.config.read(self.path)
            except configparser.Error as e:
                # If config file is corrupted or unreadable
                print(f"ConfigManager: Error reading config file {self.path}: {e}. Using default config in memory.")
                self._create_default_config_in_memory()
        else:
            # Config file does not exist, create it with defaults
            # print(f"ConfigManager: Config file not found at {self.path}. Creating with defaults.") # Optional: for debugging
            self._create_default_config_and_write()

    def _create_default_config_in_memory(self):
        """Creates a default configuration in memory (e.g., if file read fails)."""
        self.config['HuggingFace'] = {
            'use_auth_token': 'no',
            'hf_token': ''
        }
        # print(f"ConfigManager: Loaded default config into memory for {self.path}") # Optional: for debugging

    def _create_default_config_and_write(self):
        """Creates a default configuration and writes it to the specified path."""
        self.config['HuggingFace'] = {
            'use_auth_token': 'no',
            'hf_token': ''
        }
        try:
            # Ensure directory exists one last time before writing (os.makedirs in __init__ should handle it)
            config_dir = os.path.dirname(self.path)
            if config_dir and not os.path.exists(config_dir):
                 os.makedirs(config_dir, exist_ok=True)

            with open(self.path, 'w') as configfile:
                self.config.write(configfile)
            # print(f"ConfigManager: Created default config file at {self.path}") # Optional: for debugging
        except IOError as e:
            print(f"ConfigManager: Error creating default config file {self.path}: {e}")

    def get(self, section, key, default=None):
        return self.config.get(section, key, fallback=default)

    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = str(value) # ConfigParser values should be strings
        try:
            # Ensure directory exists before writing
            config_dir = os.path.dirname(self.path)
            if config_dir and not os.path.exists(config_dir):
                 os.makedirs(config_dir, exist_ok=True)

            with open(self.path, 'w') as configfile:
                self.config.write(configfile)
        except IOError as e:
            print(f"ConfigManager: Error writing to config file {self.path}: {e}")
            # Consider how to handle this - maybe re-raise, or notify user through UI

    def save_huggingface_token(self, token):
        self.set('HuggingFace', 'hf_token', token if token else "") # Ensure empty string if None

    def load_huggingface_token(self):
        return self.get('HuggingFace', 'hf_token')

    def set_use_auth_token(self, use_auth: bool): # Ensure boolean input
        self.set('HuggingFace', 'use_auth_token', 'yes' if use_auth else 'no')

    def get_use_auth_token(self) -> bool: # Return boolean
        return self.get('HuggingFace', 'use_auth_token', 'no').lower() == 'yes'