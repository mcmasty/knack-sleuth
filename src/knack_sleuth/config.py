from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Settings loaded from environment variables."""
    
    knack_app_id: str = Field(default='', alias='KNACK_APP_ID')
    knack_api_key: str = Field(default='', alias='KNACK_API_KEY')
    knack_next_gen_builder: bool = Field(default=False, alias='KNACK_NEXT_GEN_BUILDER')
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
    )


KNACK_API_BASE_URL = 'https://api.knack.com/v1'
KNACK_BUILDER_BASE_URL = "https://builder.knack.com"  # Classic Builder
KNACK_NG_BUILDER_BASE_URL = "https://builder-next.knack.com"  # Next-Gen Builder



