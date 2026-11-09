from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "autoservice"

    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 дней

    YOOKASSA_SHOP_ID: str = "test_shop_id"
    YOOKASSA_SECRET_KEY: str = "test_secret_key"
    YOOKASSA_RETURN_URL: str = "http://localhost:8000/payment/return"

    class Config:
        env_file = ".env"


settings = Settings()
