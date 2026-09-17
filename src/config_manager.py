from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load a YAML configuration file into a dictionary."""
    return ConfigManager(config_path).all()


class ConfigManager:
    """
    Loads and provides access to YAML configuration files.
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.config: dict[str, Any] = {}

        self.load_config()

    def load_config(self) -> None:
        """
        Load configuration from the YAML file.
        """

        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}"
            )

        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded_config = yaml.safe_load(file)

        except yaml.YAMLError as error:
            raise ValueError(
                f"Invalid YAML configuration: {self.config_path}"
            ) from error

        if loaded_config is None:
            self.config = {}

        elif not isinstance(loaded_config, dict):
            raise ValueError(
                "The configuration file must contain a YAML dictionary/object."
            )

        else:
            self.config = loaded_config

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a top-level configuration value.
        """

        return self.config.get(key, default)

    def get_nested(
        self,
        *keys: str,
        default: Any = None,
    ) -> Any:
        """
        Get a nested configuration value.

        Example:
            config.get_nested("search", "locations")
        """

        current_value: Any = self.config

        for key in keys:
            if not isinstance(current_value, dict):
                return default

            if key not in current_value:
                return default

            current_value = current_value[key]

        return current_value

    def has(self, key: str) -> bool:
        """
        Check whether a top-level configuration key exists.
        """

        return key in self.config

    def reload(self) -> None:
        """
        Reload the configuration from disk.
        """

        self.load_config()

    def all(self) -> dict[str, Any]:
        """
        Return the complete configuration.
        """

        return self.config.copy()