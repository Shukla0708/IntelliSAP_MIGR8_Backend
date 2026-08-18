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

    app_env: str = "development"
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    # auto | local | s3 — auto uses local disk when no AWS credentials; s3 uses IAM role on EC2
    storage_backend: str = "auto"
    public_api_base_url: str = "http://localhost:8000"

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-south-1"
    s3_bucket: str = "migr8-ai-validation"
    s3_presign_ttl_seconds: int = 300

    # Optional Bedrock API key (ABSK...) — bypasses IAM for bedrock-runtime when set
    bedrock_access_key: str | None = None
    bedrock_model_id: str = "us.anthropic.claude-sonnet-5"
    bedrock_haiku_model_id: str = "us.anthropic.claude-haiku-4-5"
    bedrock_embed_model_id: str = "cohere.embed-v4:0"
    # auto | bedrock | local — auto uses Cohere when Bedrock creds exist
    embedding_backend: str = "auto"
    # Bedrock endpoint region (us.* models → us-east-1; separate from AWS_REGION for S3/RDS)
    bedrock_region: str = "us-east-1"
    cors_origins: str = _DEFAULT_CORS

    admin_email: str | None = None
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    sap_mcp_url: str | None = None
    sap_mcp_token: str | None = None
    json_logs: bool = True

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def is_production(self) -> bool:
        return (self.app_env or "").lower() in ("production", "prod")


settings = Settings()
