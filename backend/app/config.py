from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All application configuration loaded from environment variables.
    Pydantic-settings automatically reads from the .env file.
    If a variable is missing, the app crashes at startup — this is intentional.
    Fail fast is better than silently running with wrong config.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ──────────────────────────────────────────
    postgres_host: str
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: str
    postgres_db: str

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """Synchronous DSN for Alembic — uses psycopg2 instead of asyncpg."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ───────────────────────────────────────────────
    redis_host: str
    redis_port: int = 6379

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"

    # ── RabbitMQ ────────────────────────────────────────────
    rabbitmq_host: str
    rabbitmq_port: int = 5672
    rabbitmq_user: str
    rabbitmq_password: str

    @property
    def rabbitmq_url(self) -> str:
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/"
        )

    # ── App ─────────────────────────────────────────────────
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # ── Rate Limiting ────────────────────────────────────────
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # ── Reservation ──────────────────────────────────────────
    reservation_ttl_seconds: int = 600

    # ── JWT ──────────────────────────────────────────────────
    # No default — app crashes at startup if not set in .env
    # This prevents accidentally running with a weak/default secret
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # ── Observability ─────────────────────────────────────────
    jaeger_otlp_endpoint: str = "http://jaeger:4317"


# Single shared instance — imported by all other modules
settings = Settings()