from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_CORS = (
    "http://localhost:3000,"
    "http://127.0.0.1:3000,"
    "http://localhost:3001,"
    "http://127.0.0.1:3001,"
    "http://localhost:5173,"
    "http://127.0.0.1:5173,"
    "http://localhost:4173,"
    "http://127.0.0.1:4173"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # auto | local | s3 — auto uses local disk when no AWS credentials; s3 uses IAM role on EC2
    storage_backend: str = "auto"
    public_api_base_url: str = "http://localhost:8000"

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-south-1"
    s3_bucket: str = "migr8-ai-validation"

    # Optional Bedrock API key (ABSK...) — bypasses IAM for bedrock-runtime when set
    bedrock_access_key: str | None = None
    bedrock_model_id: str = "us.anthropic.claude-sonnet-5"
    # Bedrock endpoint region (us.* models → us-east-1; separate from AWS_REGION for S3/RDS)
    bedrock_region: str = "us-east-1"
    cors_origins: str = _DEFAULT_CORS

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
