#!/usr/bin/env python3
"""
Configuration Loader for SEED Framework
Loads settings from config.yaml and environment variables.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed.")
    print("TIP: You are likely not using the virtual environment.")
    print("Try running: .\\.venv\\Scripts\\python.exe run_pipeline.py")
    sys.exit(1)

# Try to load dotenv for .env file support
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


class ConfigLoader:
    """
    Loads and manages configuration from YAML file.
    Supports environment variable substitution.
    """
    
    DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
    
    _instance: Optional['ConfigLoader'] = None
    _config: Dict[str, Any] = {}
    
    def __new__(cls, config_path: Optional[str] = None):
        """Singleton pattern - only one config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config(config_path)
        return cls._instance
    
    def _load_config(self, config_path: Optional[str] = None):
        """Load configuration from YAML file."""
        path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        
        if not path.exists():
            print(f"[WARN] Config file not found: {path}")
            print("   Using default configuration.")
            self._config = self._get_default_config()
            return
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
            
            # Substitute environment variables
            self._config = self._substitute_env_vars(raw_config)
            print(f"[OK] Configuration loaded from: {path}")
            
        except Exception as e:
            print(f"[ERROR] Error loading config: {e}")
            self._config = self._get_default_config()
    
    def _substitute_env_vars(self, config: Any) -> Any:
        """
        Recursively substitute ${VAR_NAME} with environment variables.
        """
        if isinstance(config, dict):
            return {k: self._substitute_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_vars(item) for item in config]
        elif isinstance(config, str):
            # Match ${VAR_NAME} pattern
            pattern = r'\$\{([^}]+)\}'
            matches = re.findall(pattern, config)
            
            for var_name in matches:
                env_value = os.environ.get(var_name, "")
                config = config.replace(f"${{{var_name}}}", env_value)
            
            return config
        else:
            return config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration if file not found."""
        return {
            "target": {
                "provider": "ollama",
                "model": "deepseek-r1:1.5b",
                "temperature": 0.7
            },
            "helper": {
                "provider": "ollama",
                "model": "llama3.2:1b",
                "temperature": 0.8
            },
            "embedding": {
                "provider": "ollama",
                "model": "llama3.2:1b"
            },
            "providers": {
                "ollama": {
                    "base_url": "http://localhost:11434"
                }
            },
            "analysis": {
                "domain_detection": {
                    "max_iterations": 5,
                    "confidence_threshold": 0.55
                },
                "profiler": {
                    "active_probing": False,
                    "percentile_threshold": 0.85
                },
                "mcts": {
                    "iterations": 100,
                    "exploration_weight": 1.414,
                    "top_k": 5
                }
            }
        }
    
    # === ACCESSOR METHODS ===
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get full configuration dictionary."""
        return self._config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value."""
        return self._config.get(key, default)
    
    # --- Target Configuration ---
    @property
    def target_provider(self) -> str:
        return self._config.get("target", {}).get("provider", "ollama")
    
    @property
    def target_model(self) -> str:
        return self._config.get("target", {}).get("model", "deepseek-r1:1.5b")
    
    @property
    def target_temperature(self) -> float:
        return self._config.get("target", {}).get("temperature", 0.7)
    
    # --- Helper Configuration ---
    @property
    def helper_provider(self) -> str:
        return self._config.get("helper", {}).get("provider", "ollama")
    
    @property
    def helper_model(self) -> str:
        return self._config.get("helper", {}).get("model", "llama3.2:1b")
    
    @property
    def helper_temperature(self) -> float:
        return self._config.get("helper", {}).get("temperature", 0.8)
    
    # --- Embedding Configuration ---
    @property
    def embedding_provider(self) -> str:
        return self._config.get("embedding", {}).get("provider", "ollama")
    
    @property
    def embedding_model(self) -> str:
        return self._config.get("embedding", {}).get("model", "llama3.2:1b")
    
    # --- Provider Settings ---
    def get_provider_settings(self, provider: str) -> Dict[str, Any]:
        """Get settings for a specific provider."""
        return self._config.get("providers", {}).get(provider, {})
    
    # --- Analysis Settings ---
    @property
    def domain_detection_settings(self) -> Dict[str, Any]:
        return self._config.get("analysis", {}).get("domain_detection", {})
    
    @property
    def profiler_settings(self) -> Dict[str, Any]:
        return self._config.get("analysis", {}).get("profiler", {})
    
    @property
    def social_engineering_settings(self) -> Dict[str, Any]:
        return self._config.get("analysis", {}).get("social_engineering", {})
    
    @property
    def mcts_settings(self) -> Dict[str, Any]:
        return self._config.get("analysis", {}).get("mcts", {})
    
    # --- Output Settings ---
    @property
    def output_settings(self) -> Dict[str, str]:
        return self._config.get("output", {})
    
    def __repr__(self) -> str:
        return f"ConfigLoader(target={self.target_model}, helper={self.helper_model})"


# Global accessor function
def get_config(config_path: Optional[str] = None) -> ConfigLoader:
    """Get the global configuration instance."""
    return ConfigLoader(config_path)


# === CLI Test ===
if __name__ == "__main__":
    config = get_config()
    
    print("\n" + "=" * 60)
    print("📋 SEED Framework Configuration")
    print("=" * 60)
    
    print(f"\n🎯 TARGET:")
    print(f"   Provider: {config.target_provider}")
    print(f"   Model:    {config.target_model}")
    print(f"   Temp:     {config.target_temperature}")
    
    print(f"\n🤖 HELPER:")
    print(f"   Provider: {config.helper_provider}")
    print(f"   Model:    {config.helper_model}")
    
    print(f"\n📊 EMBEDDING:")
    print(f"   Provider: {config.embedding_provider}")
    print(f"   Model:    {config.embedding_model}")
    
    print(f"\n⚙️ ANALYSIS SETTINGS:")
    print(f"   Domain Detection: {config.domain_detection_settings}")
    print(f"   Profiler:         {config.profiler_settings}")
    print(f"   MCTS:             {config.mcts_settings}")
    
    print("\n" + "=" * 60)
