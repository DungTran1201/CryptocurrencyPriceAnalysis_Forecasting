"""Configuration management for the LLM core system.

Loads and validates configuration from YAML files.
Centralizes all environment-based settings per rules.md.
Provides ConfigLoader for convenient access to nested configuration values.
"""

import os
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path


from config import ( 
    OperationLogger, 
    ExceptionLogger, 
    PerformanceLogger
)

op_log = OperationLogger("ConfigManager - OP")
ex_log = ExceptionLogger("ConfigManager - EX")
pref_og = PerformanceLogger("ConfigManager - PE")


def load_config(config_path: str) -> Dict[str, Any]:
    """Load and parse YAML configuration file.
    
    Args:
        config_path: Absolute or relative path to config.yaml
    
    Returns:
        Parsed configuration dictionary
    
    Raises:
        FileNotFoundError: If config file does not exist
        yaml.YAMLError: If YAML parsing fails
    
    Example:
        config = load_config("config.yaml")
        data_dir = config["parameters"]["data"]["data_directory"]
    """
    if not os.path.exists(config_path):
        ex_log.handle(FileNotFoundError, f"Configuration file not found: {config_path}")
    
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        op_log.info("Configuration loaded successfully from %s", config_path)
        return config
    except yaml.YAMLError as e:
        ex_log.handle(e, f"YAML parsing error in {config_path}, e")

def get_data_directory(config: Dict[str, Any]) -> str:
    """Resolve data directory path from configuration (legacy support).
    
    Args:
        config: Configuration dictionary from load_config()
    
    Returns:
        Absolute path to data directory
    
    Raises:
        KeyError: If data_directory not in config
        FileNotFoundError: If path does not exist
    """
    # Support both old and new config structures
    if "data" in config:
        data_dir = config['data'].get("save_dir")
    elif "save_dir" in config:
        data_dir = config.get("save_dir")
    else:
        data_dir = None
    
    if not data_dir:
        ex_log.handle(KeyError, "'save' dir not found in config")
        
    if not os.path.exists(data_dir):
        ex_log.handle(FileNotFoundError, f"Data dir not found {data_dir}")
    
    op_log.debug("Data directory resolved: %s", data_dir)
    return data_dir


class ConfigLoader:
    """Unified configuration loader for centralized configuration management.
    
    Provides convenient methods to access paths and parameters from the
    structured config.yaml file. Resolves relative paths to absolute paths.
    
    Example:
        config_loader = ConfigLoader("config.yaml")
        server_port = config_loader.get_parameter("server.port")
        data_dir = config_loader.get_path("data")
        tts_host = config_loader.get_parameter("tts.voicevox_host")
    """
    
    def __init__(self, config_path: str = "config.yaml") -> None:
        """Initialize ConfigLoader with a configuration file.
        
        Args:
            config_path: Path to config.yaml (absolute or relative)
        
        Raises:
            FileNotFoundError: If config file does not exist
            yaml.YAMLError: If YAML parsing fails
        """
        self.config = load_config(config_path)
        self.config_path = Path(config_path).resolve()
        self.project_root = self.config_path.parent
        op_log.debug("ConfigLoader initialized with project root: %s", self.project_root)
    
    def get_path(self, path_key: str) -> Path:
        """Get a resolved absolute path from the paths section.
        
        Args:
            path_key: Key in paths section (e.g., "data", "backend", "models")
        
        Returns:
            Absolute Path object
        
        Raises:
            KeyError: If path_key not found in paths section
        
        Example:
            data_path = config_loader.get_path("data")
            backend_path = config_loader.get_path("backend")
        """
        if "paths" not in self.config:
            ex_log.handle(KeyError,"'paths' section not found in configuration" )
        
        paths = self.config["paths"]
        
        if path_key not in paths:
            ex_log.handle(KeyError, f"Path key '{path_key}' not found in configuration")
        
        path_value = paths[path_key]
        
        # Resolve relative to project root
        resolved_path = Path(path_value)
        if not resolved_path.is_absolute():
            resolved_path = self.project_root / path_value
        
        op_log.debug("Resolved path '%s' to %s", path_key, resolved_path)
        return resolved_path

    
    def get_data_directory(self) -> Path:
        """Get absolute path to the data directory.
        
        Returns:
            Absolute Path to data directory
        
        Raises:
            KeyError: If data directory not configured
        
        Example:
            data_dir = config_loader.get_data_directory()
        """
        data_path_str = self.get_parameter("data.data_directory")
        
        resolved_path = Path(data_path_str)
        if not resolved_path.is_absolute():
            resolved_path = self.project_root / data_path_str
        
        if not resolved_path.exists():
            ex_log.handle(FileNotFoundError, f"Data directory does not exist: {resolved_path}")
        
        op_log.debug("Data directory resolved: %s", resolved_path)
        return resolved_path
