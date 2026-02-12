from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DEVICE_NAME: str = "iot-gateway"
    APP_VERSION: str = "1.0.0"
    SCANNER_ENABLED: bool = False
    SCANNER_DEVICE: str = "/dev/hidraw0"
    SCANNER_NAME: str = "Datalogic Touch 65"
    LOG_LEVEL: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
