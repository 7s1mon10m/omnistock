"""Application settings.

Every secret is read from the environment (or a local ``.env`` that is never
tracked by git).  The repository only ships ``.env.example`` with placeholder
values, so a public checkout contains no credentials of any kind.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --------------------------------------------------------------------- app
    APP_NAME: str = "OmniStock"
    APP_ENV: str = "development"  # development | testing | production
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    # Docs and the interactive schema are hidden in production by default.
    EXPOSE_DOCS: bool = True

    # ---------------------------------------------------------------- database
    DATABASE_URL: str = "sqlite:///./omnistock.db"
    SQL_ECHO: bool = False

    # -------------------------------------------------------------------- auth
    AUTH_SECRET_KEY: str = "change-me-in-env"
    AUTH_ALGORITHM: str = "HS256"
    AUTH_ACCESS_TTL_MINUTES: int = 30
    AUTH_REFRESH_TTL_DAYS: int = 7
    AUTH_MAX_LOGIN_ATTEMPTS: int = 5
    AUTH_LOCK_MINUTES: int = 15
    # PBKDF2-HMAC-SHA256 rounds for the standard library password hasher.
    AUTH_PBKDF2_ROUNDS: int = 120_000

    # ----------------------------------------------------------- bootstrap user
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "change-me-in-env"
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"

    # ------------------------------------------------------------------ product
    SKU_CODE_PREFIX: str = "SKU"
    SPU_CODE_PREFIX: str = "SPU"
    # Default warehouse created on first start, e.g. the head office warehouse.
    DEFAULT_WAREHOUSE_CODE: str = "WH-MAIN"
    DEFAULT_WAREHOUSE_NAME: str = "总仓"
    # When False (the default) stock may never go negative; a shortage is a
    # business error rather than silent data corruption.
    INVENTORY_ALLOW_NEGATIVE: bool = False
    # Reject an inventory adjustment that would be a no-op.
    INVENTORY_REJECT_ZERO_DELTA: bool = True
    CURRENCY: str = "CNY"

    # ------------------------------------------------- channels and orders (M2)
    # ``exception`` refuses the whole order when any SKU is short; ``partial``
    # reserves whatever is available and books the remainder as a shortage.
    ORDER_SHORTAGE_STRATEGY: str = "exception"  # exception | partial
    ORDER_SYNC_BATCH_SIZE: int = 200
    # Reserved stock older than this is reported as a stale reservation.
    ORDER_IDEMPOTENT_WINDOW_HOURS: int = 72
    ORDER_CODE_PREFIX: str = "SO"
    # Import guard rails: a small deployment should never parse a 1M row file.
    IMPORT_MAX_ROWS: int = 5_000
    # ``utf-8-sig`` transparently strips the BOM Excel adds when saving CSV.
    IMPORT_ENCODING: str = "utf-8-sig"
    # Channel exports are almost always already-paid orders, so treat a missing
    # paid_at as "paid now" and reserve stock straight away.  Set to false if
    # your platform exports unpaid carts too.
    ORDER_IMPORT_ASSUME_PAID: bool = True

    # ----------------------------------------------------------- shipping (M3)
    SHIPMENT_CODE_PREFIX: str = "SHP"
    # When true, an item can only be picked by scanning its barcode.  Turn off
    # for warehouses that tick items off on paper instead.
    PICK_REQUIRE_BARCODE: bool = True
    # Allow shipping an order whose pick list is not fully picked.  Off by
    # default: a short pick must be fixed or the order stays blocked.
    SHIPMENT_ALLOW_PARTIAL_PICK: bool = False
    # 拣货单里没有维护库位的 SKU 的排序值，越往后越晚拣
    PICK_UNASSIGNED_LOCATION_ORDER: str = "zzzz"

    # ----------------------------------------------------------------- logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    LOG_FILE: str = ""
    LOG_ACCESS: bool = True

    # -------------------------------------------------------------------- misc
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
