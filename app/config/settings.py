from pathlib import Path
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings, 
    SettingsConfigDict)


def load_config (config_path: str): 
    try: 
        with open (config_path, "r", encoding = "utf-8") as f: 
            yaml_load = yaml.safe_load(f) 
        return yaml_load
    except FileNotFoundError as e: 
        raise e


class TimeSettings(BaseModel): 
    '''
        Arguments: 
        * frame: 
    '''
    frame: str = "1min" 
    start: str = "2023-01-01 00:00:00" 
    end: str = "2023-01-10 00:00:00"

class DataSettings(BaseModel): 
    symbol: str ="BTCUSDT" 
    time: TimeSettings
    save_dir: str = "data_raw" 
    

class Settings(BaseSettings):
    """
    Setup parameters
    """
    data: DataSettings = Field(default_factory=DataSettings)
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent)

    model_config = SettingsConfigDict(extra="ignore")

    @classmethod
    def load_from_yaml(cls, filename: str = "config.yaml") -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent.parent
        config_path = base_dir / filename
        
        yaml_data = load_config(config_path)

        if not config_path.exists():
            default_settings = cls()
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(default_settings.model_dump(), f, default_flow_style=False)
            return default_settings
        
        return cls(**yaml_data) 

setup = Settings.load_from_yaml(filename = "/workspaces/Binance-Predict-Value-And-Trend/config.yaml")