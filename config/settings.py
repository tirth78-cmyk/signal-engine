"""
Improzo Signal Engine — Configuration Management
Loads from environment variables / .env file with sensible defaults.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from enum import Enum


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class ScraperSettings(BaseSettings):
    """Web scraper configuration."""
    max_concurrent_scrapers: int = Field(default=5, description="Max parallel scrapers")
    request_timeout: int = Field(default=30, description="HTTP request timeout (seconds)")
    rate_limit_per_domain: float = Field(default=1.0, description="Seconds between requests per domain")
    max_retries: int = Field(default=3, description="Max retries per failed request")
    user_agent: str = Field(
        default="ImprozoSignalBot/1.0 (+https://improzo.com/bot)",
        description="HTTP User-Agent string"
    )
    playwright_headless: bool = Field(default=True, description="Run Playwright in headless mode")
    proxy_url: Optional[str] = Field(default=None, description="Optional proxy URL for scrapers")


class NLPSettings(BaseSettings):
    """NLP pipeline configuration."""
    spacy_model: str = Field(default="en_core_web_sm", description="spaCy model name")
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model for semantic similarity"
    )
    classification_threshold: float = Field(default=0.65, description="Min confidence to auto-classify")
    dedup_similarity_threshold: float = Field(default=0.85, description="Cosine similarity threshold for dedup")
    batch_size: int = Field(default=32, description="NLP batch processing size")


class HubSpotSettings(BaseSettings):
    """HubSpot CRM connector configuration."""
    api_key: str = Field(default="", description="HubSpot private app access token")
    portal_id: str = Field(default="", description="HubSpot portal ID")
    signal_object_type: str = Field(default="signals", description="Custom object type name")
    batch_size: int = Field(default=100, description="Batch size for HubSpot API calls")
    rate_limit_per_second: int = Field(default=10, description="HubSpot API rate limit")


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    url: str = Field(default="sqlite+aiosqlite:///./signal_engine.db", description="Database URL")
    echo: bool = Field(default=False, description="Echo SQL queries")
    pool_size: int = Field(default=5, description="Connection pool size")


class RedisSettings(BaseSettings):
    """Redis configuration for caching and Celery broker."""
    url: str = Field(default="redis://localhost:6379/0", description="Redis URL")
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds")


class APISettings(BaseSettings):
    """FastAPI server configuration."""
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "https://tirthankarray.github.io"],
        description="Allowed CORS origins"
    )
    api_key: str = Field(default="", description="API authentication key")
    docs_enabled: bool = Field(default=True, description="Enable Swagger/ReDoc")


class SchedulerSettings(BaseSettings):
    """Scheduler configuration for scraping jobs."""
    news_interval_minutes: int = Field(default=30, description="News scraper interval")
    jobs_interval_minutes: int = Field(default=360, description="Job board scraper interval")
    regulatory_interval_minutes: int = Field(default=720, description="Regulatory scraper interval")
    full_scan_cron: str = Field(default="0 6 * * *", description="Full scan cron expression")


class Settings(BaseSettings):
    """Root settings — aggregates all sub-configs."""
    app_name: str = "Improzo Signal Engine"
    version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    scraper: ScraperSettings = ScraperSettings()
    nlp: NLPSettings = NLPSettings()
    hubspot: HubSpotSettings = HubSpotSettings()
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    api: APISettings = APISettings()
    scheduler: SchedulerSettings = SchedulerSettings()

    model_config = {"env_prefix": "SIGNAL_", "env_file": ".env", "env_nested_delimiter": "__"}


# Singleton
settings = Settings()
