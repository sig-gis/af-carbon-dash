import yaml
from pathlib import Path

class ColorConfig:
    def __init__(self, color_config):
        self.palette = color_config.get('palette', {})
        palette = self.palette

        # Resolve color names to hex values from palette
        self.foreground = palette.get(color_config.get('foreground', ''), color_config.get('foreground', ''))
        self.background = palette.get(color_config.get('background', ''), color_config.get('background', ''))
        self.primary = palette.get(color_config.get('primary', ''), color_config.get('primary', ''))
        self.secondary = palette.get(color_config.get('secondary', ''), color_config.get('secondary', ''))

class Brand:
    def __init__(self, config):
        self.color = ColorConfig(config.get('color', {}))
        self.typography = config.get('typography', {})

    @classmethod
    def from_yaml(cls, yaml_path=""):
        """Load brand configuration from _brand.yml"""
        if not yaml_path:
            yaml_path = "_brand.yml"

        config_path = Path(yaml_path)
        if not config_path.exists():
            # Try relative to current file
            config_path = Path(__file__).parent / "_brand.yml"

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        return cls(config)
