"""
Configuration module for JobHunt
Handles oMLX settings and user configuration
"""
import os
import json
from functools import lru_cache
from pydantic import BaseModel


class OEMLXSettings(BaseModel):
    base_url: str
    api_key: str


def load_omlx_settings() -> OEMLXSettings:
    """
    Load oMLX settings from ~/.omlx/settings.json or environment variables
    Environment variables take precedence over settings file
    """
    # Try to load from oMLX settings file
    omx_settings_path = os.path.expanduser("~/.omlx/settings.json")
    if os.path.exists(omx_settings_path):
        try:
            with open(omx_settings_path, 'r') as f:
                settings = json.load(f)
            
            # Extract base_url and api_key from settings file.
            # oMLX stores the key under auth.api_key; accept top-level api_key too.
            auth = settings.get("auth") or {}
            api_key = auth.get("api_key") or settings.get("api_key")

            server = settings.get("server") or {}
            base_url = settings.get("base_url")
            if not base_url and server.get("host") and server.get("port"):
                base_url = f"http://{server['host']}:{server['port']}/v1"
            if not base_url:
                base_url = "http://127.0.0.1:8000/v1"
            
            # If API key is found in settings file, but we have env var, env var takes precedence
            env_api_key = os.environ.get('OMLX_API_KEY')
            if env_api_key:
                api_key = env_api_key
                
            # If API key is found in settings file, but we have env var, env var takes precedence
            env_base_url = os.environ.get('OMLX_BASE_URL')
            if env_base_url:
                base_url = env_base_url
            
            if not api_key:
                raise ValueError("No API key found in settings.json or environment variables (OMLX_API_KEY)")
                
            return OEMLXSettings(base_url=base_url, api_key=api_key)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not read oMLX settings from {omx_settings_path}: {e}")
    
    # Fall back to environment variables
    base_url = os.environ.get('OMLX_BASE_URL', 'http://127.0.0.1:8000/v1')
    api_key = os.environ.get('OMLX_API_KEY')
    
    if not api_key:
        raise ValueError("No API key found in environment variables (OMLX_API_KEY)")
    
    return OEMLXSettings(base_url=base_url, api_key=api_key)


@lru_cache(maxsize=1)
def get_omlx_settings() -> OEMLXSettings:
    """Cached accessor for oMLX settings (loaded lazily on first use)."""
    return load_omlx_settings()