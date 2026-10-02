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

    # ------------------------------------------------------ purchasing (M4)
    SUPPLIER_CODE_PREFIX: str = "SUP"
    PURCHASE_ORDER_PREFIX: str = "PO"
    PURCHASE_RECEIPT_PREFIX: str = "PR"
    # 建采购单时若不填预计到货日，按供应商的交期推
    PURCHASE_DEFAULT_LEAD_TIME_DAYS: int = 7
    # 采购单允许超收的比例（%）—— 0 表示严格不超过下单量
    PURCHASE_OVER_RECEIPT_PERCENT: int = 0

    # ------------------------------------------------------- transfers (M5)
    TRANSFER_CODE_PREFIX: str = "TR"
    # 调拨是否需要审批。小团队可以关掉，直接进入待发出。
    TRANSFER_REQUIRE_APPROVAL: bool = True
    # 收货时允许出现次品的比例上限（%），用于验收把关；0 表示不限制
    TRANSFER_MAX_DEFECTIVE_PERCENT: int = 0

    # --------------------------------------------------- alerts & notify (M6)
    # 销量预测回看窗口：日均销量按这个天数取平均，窗口内没有出库即视为无销量。
    FORECAST_WINDOW_DAYS: int = 30
    # 补货周期：预测销量 = 日均销量 × 这个天数，代表「下次到货之前要卖掉的量」。
    REPLENISH_LEAD_TIME_DAYS: int = 7
    # 定时扫描的 cron 表达式，供外部调度器（cron / systemd timer）使用。
    ALERT_SCAN_CRON: str = "0 8 * * *"
    ALERT_CODE_PREFIX: str = "AL"
    # 默认启用的通知通道，逗号分隔：inapp / email / webhook
    NOTIFY_CHANNELS: str = "inapp"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    WEBHOOK_TIMEOUT_SECONDS: int = 10
    # 投递失败的重试次数与退避基数（2/4/8/16 秒由它推算）。
    NOTIFY_MAX_RETRIES: int = 4
    NOTIFY_RETRY_BASE_SECONDS: int = 2

    # ---------------------------------------------- returns & stocktake (M7)
    RETURN_CODE_PREFIX: str = "RT"
    STOCKTAKE_CODE_PREFIX: str = "ST"
    # 退货窗口：超过这个天数的原订单不允许再建退货单（0 表示不限制）。
    RETURN_WINDOW_DAYS: int = 30
    # 盘点差异数量超过这个绝对值就必须走审核，不能直接调整。
    STOCKTAKE_VARIANCE_THRESHOLD: int = 1
    # 盘点是否需要审核才能落账。小团队可以关掉，直接生效。
    STOCKTAKE_REQUIRE_APPROVAL: bool = True
    # 质检判为报损时是否直接生成报损流水。
    DAMAGE_AUTO_SCRAP: bool = True

    # ---------------------------------------------- reports & adapters (M8)
    # 报表不传日期范围时的默认回看天数。
    REPORT_DEFAULT_RANGE_DAYS: int = 30
    # 导出 CSV 的行数上限，超过直接报错而不是把内存打满。
    EXPORT_MAX_ROWS: int = 50_000
    EXPORT_CSV_DELIMITER: str = ","
    AUDIT_LOG_RETENTION_DAYS: int = 180
    # 渠道适配器同步间隔（分钟），供外部调度器参考。
    ADAPTER_SYNC_INTERVAL_MINUTES: int = 30

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
