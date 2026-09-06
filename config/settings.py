"""Strongly typed application settings."""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_keys(value: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(item.strip() for item in value if item and item.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "rehan_bot"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///runtime/rehan_bot.db"
    session_file: str = "runtime/browser/storage_state.json"
    recovery_memory_file: str = "runtime/ai/recovery_memory.json"
    log_file: str = "runtime/logs/rehan_bot.log"
    visual_memory_file: str = "runtime/ai_memory.db"
    agent_memory_file: str = "runtime/memory/agent_memory.json"

    mp_base_url: str = "https://mnpcourier.com/cplight/"
    mp_login_url: str = "https://mnpcourier.com/cplight/login"
    # Leave empty by default: CP-Light's actual Tracking submenu route is
    # deployment-specific, so navigation uses the visible sidebar child.
    mp_tracking_url: str = ""
    mp_shipper_advice_url: str = ""
    mp_payments_url: str = ""
    mp_username: str = ""
    mp_password: str = ""

    tracking_loader_timeout_ms: int = Field(default=45_000, ge=1000)
    tracking_result_timeout_ms: int = Field(default=45_000, ge=1000)

    browser_headless: bool = True
    browser_timeout_ms: int = Field(default=30000, ge=1000)
    navigation_timeout_ms: int = Field(default=30000, ge=1000)

    gemini_model: str = "gemini-3.7-flash"
    gemini_api_keys: str = ""
    openai_model: str = "gpt-5.6"
    openai_api_keys: str = ""
    groq_model: str = "qwen/qwen3.6-27b"
    groq_api_keys: str = ""
    openrouter_model: str = "openai/gpt-5.6-sol"
    openrouter_api_keys: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_api_keys: str = ""
    # Vision is a recovery path: fail fast to the next provider instead of
    # leaving the browser stalled behind an unhealthy API key.
    ai_timeout_seconds: float = Field(default=8.0, gt=0)

    nextjs_base_url: str = ""
    nextjs_service_token: str | None = None
    nextjs_timeout_seconds: float = Field(default=15.0, gt=0)

    website_url: str = "https://primehub-one.vercel.app"
    primehub_api_key: str = ""
    primehub_products_dir: str = r"C:\Users\M.TT\Desktop\ustad-bot\Bangles_Assets"
    primehub_default_category: str = "Glass bangles"
    primehub_max_images: int = Field(default=0, ge=0)
    primehub_image_delay_seconds: float = Field(default=1.5, ge=0)
    primehub_folder_delay_seconds: float = Field(default=2.5, ge=0)
    imgbb_api_key: str = ""
    imgbb_api_keys: str = ""
    imgbb_cache_file: str = "runtime/memory/uploaded_images_cache.json"
    imgbb_upload_delay_seconds: float = Field(default=1.5, ge=0)
    catalog_state_file: str = "runtime/memory/catalog_state.json"
    r2_account_id: str = ""
    r2_bucket_name: str = "primehub"
    r2_public_base_url: str = "https://pub-157b90419bf04016bdea666e4cbce181.r2.dev"
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    vercel_protection_bypass: str = ""
    firebase_service_account_file: str = ""
    firebase_service_account_key: str = ""

    scheduler_timezone: str = "Asia/Karachi"
    scheduler_interval_minutes: int = Field(default=60, ge=1)
    morning_report_hour: int = Field(default=11, ge=0, le=23)
    morning_report_minute: int = Field(default=0, ge=0, le=59)
    evening_report_hour: int = Field(default=20, ge=0, le=23)
    evening_report_minute: int = Field(default=0, ge=0, le=59)

    tracking_numbers: str = ""
    payment_statement_file: str = ""
    shipper_advice_instruction: str = "Re-attempt delivery"
    tracking_min_interval_seconds: float = Field(default=1.5, ge=0)
    action_timeout_ms: int = Field(default=1500, ge=500)
    recovery_max_retries: int = Field(default=3, ge=1)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    webhook_url: str = ""
    escalation_after_days: int = Field(default=2, ge=1)
    escalation_recipient: str = ""
    escalation_sender: str = ""

    whatsapp_mode: str = "web"
    whatsapp_phone: str = ""
    whatsapp_headless: bool = True
    whatsapp_profile_dir: str = "runtime/browser/whatsapp_profile"
    whatsapp_session_file: str = "runtime/browser/whatsapp_state.json"
    whatsapp_log_file: str = "runtime/logs/whatsapp.log"
    whatsapp_session_ttl_days: int = Field(default=14, ge=1)
    whatsapp_qr_timeout_seconds: int = Field(default=180, ge=30)
    whatsapp_default_country_code: str = "92"
    whatsapp_browser_channel: str = ""
    whatsapp_api_url: str = ""
    whatsapp_callmebot_apikey: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    @field_validator("whatsapp_mode", mode="before")
    @classmethod
    def _validate_whatsapp_mode(cls, value: object) -> str:
        mode = str(value or "web").strip().lower()
        if mode not in {"web", "api", "off"}:
            raise ValueError("WHATSAPP_MODE must be one of: web, api, off")
        return mode

    @property
    def gemini_api_key_pool(self) -> tuple[str, ...]:
        return _split_keys(self.gemini_api_keys)

    @property
    def openai_api_key_pool(self) -> tuple[str, ...]:
        return _split_keys(self.openai_api_keys)

    def model_post_init(self, __context: object) -> None:
        """Expose the first pooled key for libraries expecting the singular name.

        The pool remains authoritative; this only preserves compatibility with
        SDKs that read ``OPENAI_API_KEY`` directly.
        """
        if self.openai_api_key_pool:
            os.environ["OPENAI_API_KEY"] = self.openai_api_key_pool[0]

    @property
    def groq_api_key_pool(self) -> tuple[str, ...]:
        return _split_keys(self.groq_api_keys)

    @property
    def openrouter_api_key_pool(self) -> tuple[str, ...]:
        return _split_keys(self.openrouter_api_keys)

    @property
    def deepseek_api_key_pool(self) -> tuple[str, ...]:
        return _split_keys(self.deepseek_api_keys)

    @property
    def session_path(self) -> Path:
        return Path(self.session_file)

    @property
    def recovery_memory_path(self) -> Path:
        return Path(self.recovery_memory_file)

    @property
    def log_path(self) -> Path:
        return Path(self.log_file)

    @property
    def visual_memory_path(self) -> Path:
        return Path(self.visual_memory_file)

    @property
    def agent_memory_path(self) -> Path:
        return Path(self.agent_memory_file)

    @property
    def imgbb_api_key_pool(self) -> tuple[str, ...]:
        """Merge the singular ImgBB key with the comma-separated pool."""
        return _split_keys(
            ",".join(
                part
                for part in (self.imgbb_api_key, self.imgbb_api_keys)
                if part and str(part).strip()
            )
        )

    @property
    def primehub_base_url(self) -> str:
        """Prefer WEBSITE_URL, then the existing Next.js integration URL."""
        return (
            self.website_url or self.nextjs_base_url or "https://primehub-one.vercel.app"
        ).rstrip("/")

    def split_image_limit(self, override: int | None = None) -> int | None:
        """How many folder images to turn into Set cards. ``None`` means all."""
        if override is not None:
            return max(1, int(override))
        configured = int(self.primehub_max_images or 0)
        return configured if configured > 0 else None

    @property
    def primehub_auth_key(self) -> str:
        """Prefer PRIMEHUB_API_KEY, then NEXTJS_SERVICE_TOKEN."""
        return str(self.primehub_api_key or self.nextjs_service_token or "").strip()

    @property
    def imgbb_cache_path(self) -> Path:
        return Path(self.imgbb_cache_file)

    @property
    def r2_is_configured(self) -> bool:
        return all(
            str(part or "").strip()
            for part in (
                self.r2_account_id,
                self.r2_bucket_name,
                self.r2_public_base_url,
                self.r2_access_key_id,
                self.r2_secret_access_key,
            )
        )

    @property
    def catalog_state_path(self) -> Path:
        return Path(self.catalog_state_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
