# config_manager.py
import configparser
import os

CONFIG_FILE = 'config.ini'
TOKEN_SECTION = 'HuggingFace'
USE_AUTH_TOKEN_OPTION = 'use_auth_token'
TOKEN_OPTION = 'hf_token'

def save_token(token): # This function is no longer the primary way, but can remain
    """Saves the Hugging Face token to the config file."""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    if TOKEN_SECTION not in config:
        config[TOKEN_SECTION] = {}
    config[TOKEN_SECTION][TOKEN_OPTION] = token
    try:
        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)
    except IOError as e:
        print(f"Error saving token to {CONFIG_FILE}: {e}")

def load_token(): # This function is no longer the primary way, but can remain
    """Loads the Hugging Face token from the config file."""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            config.read(CONFIG_FILE)
            return config.get(TOKEN_SECTION, TOKEN_OPTION, fallback=None)
        except configparser.Error as e:
            print(f"Error reading token from {CONFIG_FILE}: {e}")
            return None
    return None

class ConfigManager:
    def __init__(self, config_path):
        self.config = configparser.ConfigParser()
        self.path = config_path
        if os.path.exists(self.path):
            self.config.read(self.path)
        else:
            self._create_default_config()

    def _create_default_config(self):
        self.config['HuggingFace'] = {
            'use_auth_token': 'no',
            'hf_token': ''
        }
        with open(self.path, 'w') as configfile:
            self.config.write(configfile)

    def get(self, section, key, default=None):
        return self.config.get(section, key, fallback=default)

    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value
        with open(self.path, 'w') as configfile:
            self.config.write(configfile)

    def save_huggingface_token(self, token):
        self.set('HuggingFace', 'hf_token', token)

    def load_huggingface_token(self):
        return self.get('HuggingFace', 'hf_token')

    def set_use_auth_token(self, use_auth):
        self.set('HuggingFace', 'use_auth_token', 'yes' if use_auth else 'no')

    def get_use_auth_token(self):
        return self.get('HuggingFace', 'use_auth_token') == 'yes'