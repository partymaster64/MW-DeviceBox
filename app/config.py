from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DEVICE_NAME: str = "iot-gateway"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"

    # Watchtower integration
    WATCHTOWER_URL: str = "http://watchtower:8080"
    WATCHTOWER_TOKEN: str = "devicebox-watchtower"
    WATCHTOWER_INTERVAL: int = 15

    # POS polling default interval (overridden by settings store)
    POS_POLL_INTERVAL: int = 2

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
