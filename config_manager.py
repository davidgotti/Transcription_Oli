# config_manager.py
import configparser
import os

CONFIG_FILE = 'config.ini'
TOKEN_SECTION = 'HuggingFace'
TOKEN_OPTION = 'AuthToken'

def save_token(token):
    """Saves the Hugging Face token to the config file."""
    config = configparser.ConfigParser()
    # Read existing config if it exists, to preserve other sections/options
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

def load_token():
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