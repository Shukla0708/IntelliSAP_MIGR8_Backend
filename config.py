from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # auto | local | s3 — auto uses local disk when AWS keys are placeholders
    storage_backend: str = "auto"
    public_api_base_url: str = "http://localhost:8000"

    aws_access_key_id: str = "your-key"
    aws_secret_access_key: str = "your-secret"
    aws_region: str = "ap-south-1"
    s3_bucket: str = "migr8-ai-validation"

    groq_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
