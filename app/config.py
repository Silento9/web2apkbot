from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///./web2apk.db"
    build_timeout: int = 900
    max_concurrent_builds: int = 1
    apk_retention_days: int = 3
    port: int = 8080

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def admins(self) -> List[int]:
        out = []
        for value in self.admin_ids.split(","):
            value = value.strip()
            if value.isdigit():
                out.append(int(value))
        return out

settings = Settings()
