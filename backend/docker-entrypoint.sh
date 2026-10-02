#!/usr/bin/env bash
#
# Container entrypoint: apply migrations, optionally seed, then hand over to the
# CMD.  Keeping the migration step here means `docker compose up` works on a
# completely empty volume.
set -euo pipefail

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] 执行数据库迁移 ..."
  python -m alembic upgrade head
fi

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  echo "[entrypoint] 写入演示种子数据 ..."
  python -m app.seed || echo "[entrypoint] 种子数据跳过（可能已存在）"
fi

echo "[entrypoint] 启动：$*"
exec "$@"
