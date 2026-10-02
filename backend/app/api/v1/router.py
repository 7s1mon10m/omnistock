"""Aggregate router for API version 1."""

from fastapi import APIRouter

from app.api.v1 import auth, bundles, inventory, products, users, warehouses
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(warehouses.router)
# products declares /skus/resolve before /skus/{sku_id} internally, so the
# literal path is never captured by the parameterised one.
api_router.include_router(products.router)
api_router.include_router(bundles.router)
api_router.include_router(inventory.router)
