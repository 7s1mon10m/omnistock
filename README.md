# OmniStock · 多渠道电商库存与采购协同平台

> 给小团队的**多渠道库存中枢**：多个平台同时卖货、库存分散在不同仓库、订单容易超卖、采购靠经验、退货后库存不准——这个项目就是来解决这些问题的。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776ab.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)

---

## 为什么不是又一个库存 CRUD

普通库存系统只有一张表、加加减减。真实电商的库存难在**并发**和**状态**：

| 真实问题 | 本项目的做法 |
| --- | --- |
| 多渠道订单同时抢同一批货 | 条件 `UPDATE` 原子占用，先到先得，**不超卖** |
| 同一订单被渠道重复推送 | 唯一约束 + 幂等键 + 同步日志短路，**不重复扣库存** |
| 组合商品（套装）怎么记库存 | 下单时**拆解**为实际 SKU，组合商品自身不持库存 |
| 采购在途、调拨在途算不算可售 | 明确口径：**在途不可售**，收货后才转可售 |
| 退货后库存到底对不对 | 质检**四分流**：可售 / 次品 / 维修 / 报损 |
| 发错货、少发货 | 拣货按库位排序，**扫码校验**不符当场拦截 |
| 拣完一堆货，谁复核的 | 复核打包是独立关卡，未复核不能出库，操作人留痕 |
| 盘点差异查不出原因 | 差异必须**审核后**才生成调整流水，留操作人、时间、原因 |
| 少了 12 件是谁改的 | 库存流水 **append-only**，每次变动写明来源单据 |

---

## 核心业务模型

### 商品的三层结构

```
SPU（纯棉短袖）
├── SKU（白色 / L 码）        ← 真正持有库存、价格、条码
├── SKU（白色 / M 码）
└── 组合商品（洗发水 + 护发素套装）  ← 下单时拆解为上面这些 SKU
```

### 库存不是一个数字，而是五个口径

```
可售库存 = 实际库存 - 已占用库存 - 安全库存
```

| 口径 | 含义 |
| --- | --- |
| 实际库存 `on_hand` | 仓库里物理存在的数量 |
| 已占用 `reserved` | 已被未发货订单锁定 |
| 可售 `available` | 能继续卖的数量（**实时计算，不落库**） |
| 在途 `in_transit` | 采购 / 调拨在路上，**不计入可售** |
| 安全库存 `safety` | 低于它就该补货的缓冲 |

### 库存流水是一切变化的唯一真相

所有入库、出库、订单占用、取消释放、退货、报损、调拨、盘点调整，都写入 `inventory_transactions`：

```
库存不允许"直接改数字" —— 任何变动都必须产生一条可追溯的流水。
流水只增不改，记录 前值 → 后值、来源单据、操作人、原因、幂等键。
```

---

## 已实现功能

### M1 · 商品与库存基础

- **商品分层管理**：SPU / SKU / 组合商品，规格、条码、重量、包装规格、采购价、安全库存
- **多渠道归一的基础**：内部 SKU 编码体系（`SKU-<SPU>-<规格>`，中文规格自动回退序号）
- **条码体系**：主条码 + 附加条码，唯一性校验，支持按条码反查 SKU
- **多仓库与库位**：总仓 / 直播间仓 / 退货仓，库位编码（拣货排序用）
- **库存五口径**：SKU × 仓库的聚合视图，可售实时计算
- **库存流水**：12 种流水类型，支持按 SKU / 仓库 / 类型 / 来源单据 / 时间检索
- **库存操作**：手工调整（强制填原因）、占用、释放、组合商品按套占用（全有或全无）
- **RBAC**：店主 / 运营 / 采购 / 仓库 + 系统管理员，五角色权限矩阵
- **认证**：JWT（access + refresh 轮转）、登录失败锁定、密码 PBKDF2-HMAC-SHA256

### M2 · 电商订单处理

- **渠道与店铺**：淘宝 / 抖音 / Shopify 等平台，一个渠道下可挂多个店铺
- **渠道商品映射**：`TB-100238`、`DY-883021`、`SHOP-TS-001` 三个平台编码统一映射到同一个内部 SKU，共享同一池库存
- **订单导入**：CSV 上传 + JSON 请求体，同一 `(渠道, 店铺, 渠道单号)` 的多行自动合并成一张订单
- **容错解析**：单行出错只跳过该行并回报行号，不影响文件里其他行；自动识别 Excel 的 BOM 与 GB18030
- **幂等同步**：`(渠道, 渠道单号)` 唯一约束 + 同步日志，重复推送记为 `duplicate`，绝不二次扣减库存
- **订单状态机**：待支付 → 待配货 → 已占用库存（→ 拣货 → 发货 → 完成）/ 异常 / 已取消
- **库存占用**：导入已付款订单即刻占用；缺货默认整单不占用并转入异常队列（可配置为部分占用）
- **异常订单闭环**：补货后点「重新占用」补齐缺口，无需重新导入订单
- **取消释放**：取消订单按**库存流水**反算释放量，即使组合商品定义后来变了也释放得准确
- **组合商品拆解**：买套装占用的是拆解后的子 SKU，套装自身永不持有库存
- **可观测**：导入批次记录 + 每次同步结果（created / duplicate / failed）

### M3 · 仓库发货

- **拣货清单**：从**库存流水**生成（M2 占用了什么就拣什么），不是从订单行猜
- **拣货路线**：按库位编码排序，从上到下走一遍就是最短路线；未维护库位的排最后
- **扫码校验**：扫到不在单上的 SKU、扫超量、报错条码——**当场拦截**，不留到客户投诉
- **拒绝也留痕**：被拦下的扫码照样写进记录，一串 `wrong_sku` 就是「货放错位置了」的信号
- **复核门槛**：必须全部拣完才能复核打包；未复核不能出库
- **出库扣减**：实际库存与占用**同时**减少（条件 UPDATE，永不为负）
- **组合商品**：拣货清单自动展开成子 SKU，套装本身永不持有库存
- **取消与重开**：取消发货单不影响占用（占用属于订单），可重新开单；一个订单同时只有一张进行中的拣货单（部分唯一索引兜底）
- **短拣**：默认禁止；开启 `SHIPMENT_ALLOW_PARTIAL_PICK` 后按实际拣到的数量发货，未发部分释放占用

### 接口一览（M1 + M2 + M3）

```
POST   /api/v1/auth/login | refresh | logout | change-password
GET    /api/v1/auth/me

GET    /api/v1/users            POST /api/v1/users
GET    /api/v1/users/roles      PATCH /api/v1/users/{id}

GET    /api/v1/warehouses       POST /api/v1/warehouses
GET    /api/v1/warehouses/{id}/locations
POST   /api/v1/warehouses/{id}/locations

GET    /api/v1/spus             POST /api/v1/spus
GET    /api/v1/skus             POST /api/v1/skus
GET    /api/v1/skus/resolve?barcode=...
GET    /api/v1/skus/{id}/barcodes
POST   /api/v1/skus/{id}/barcodes

GET    /api/v1/bundles/{sku_id}
PUT    /api/v1/bundles/{sku_id}/components

GET    /api/v1/inventory
GET    /api/v1/inventory/ledger      # 只读，无任何写接口
POST   /api/v1/inventory/adjust      # 必填原因
POST   /api/v1/inventory/reserve
POST   /api/v1/inventory/release
POST   /api/v1/inventory/reserve-bundle

# --- M2 电商订单处理 ---
GET    /api/v1/channels              POST /api/v1/channels
GET    /api/v1/channels/{id}/shops   POST /api/v1/channels/{id}/shops
GET    /api/v1/channel-products      POST /api/v1/channel-products
PATCH  /api/v1/channel-products/{id} DELETE /api/v1/channel-products/{id}

GET    /api/v1/orders                # 支持渠道 / 状态 / 关键字 / 只看异常
GET    /api/v1/orders/{id}
POST   /api/v1/orders/import          # 上传 CSV / JSON 文件
POST   /api/v1/orders/import-json     # JSON 请求体导入
GET    /api/v1/orders/import-template.csv
GET    /api/v1/orders/import-batches  # 导入批次记录
GET    /api/v1/orders/sync-logs       # 每次同步的结果（created / duplicate / failed）
GET    /api/v1/orders/exceptions      # 异常订单队列
POST   /api/v1/orders/{id}/mark-paid      # 待支付 → 占用库存
POST   /api/v1/orders/{id}/retry-reserve  # 补货后重试占用
POST   /api/v1/orders/{id}/cancel         # 取消并释放库存

# --- M3 仓库发货 ---
PATCH  /api/v1/inventory/location         # 设置 SKU 的默认拣货库位
GET    /api/v1/shipments                  # 支持状态 / 仓库 / 单号筛选
POST   /api/v1/shipments                  # 由已占用订单生成拣货单
GET    /api/v1/shipments/{id}             # 拣货单（按库位排好序）
GET    /api/v1/shipments/{id}/pick-records
POST   /api/v1/shipments/{id}/claim           # 领取任务
POST   /api/v1/shipments/{id}/pick            # 扫码拣货（不一致当场拦截）
POST   /api/v1/shipments/{id}/pick-manual     # 无条码时手工确认
POST   /api/v1/shipments/{id}/pack            # 复核打包（未拣完不放行）
POST   /api/v1/shipments/{id}/ship            # 出库发货（扣减实际库存）
POST   /api/v1/shipments/{id}/cancel          # 取消拣货单，占用仍属于订单
```

---

## 技术栈

| 层次 | 选型 |
| --- | --- |
| 后端 | FastAPI 0.115+ / Python 3.12 / SQLAlchemy 2.0 / Alembic |
| 数据库 | PostgreSQL 16（推荐）或 SQLite（开箱即用） |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Element Plus |
| 认证 | PyJWT（HS256）+ PBKDF2-HMAC-SHA256 |
| 部署 | Docker Compose + Nginx |
| 测试 | pytest + httpx |

---

## 快速开始

### 本地开发

```bash
# 1. 后端
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env                             # 按需修改数据库地址
python -m alembic upgrade head                      # 建表
python -m app.seed                                  # 写入演示数据
uvicorn app.main:app --reload                       # http://localhost:8000/docs

# 2. 前端
cd ../web
npm install
npm run dev                                         # http://localhost:5173
```

### Docker 一键启动

```bash
cp .env.example .env        # 修改 AUTH_SECRET_KEY 与 DEFAULT_ADMIN_PASSWORD
docker compose --profile postgres up -d --build
# 前端 http://localhost:8080
# 接口文档 http://localhost:8080/docs （需 EXPOSE_DOCS=true）
```

### 演示账号（种子数据，仅本地）

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 店主 / 管理员 |
| `operator` | `operator123` | 运营人员 |
| `buyer` | `buyer123` | 采购人员 |
| `warehouse` | `warehouse123` | 仓库人员 |

> 全部为虚构数据，请勿用于生产环境。

---

## 测试

```bash
cd backend && python -m pytest tests -q
```

M1 + M2 + M3 共 **141 个用例**，重点覆盖：

- 越权访问返回 `40301`，登录失败锁定，刷新令牌轮转
- SPU / SKU 编码与条码唯一性冲突
- 新 SKU 自动铺货到每个启用仓库
- 流水满足 `前值 + 变动 = 后值`
- 手工调整必须填原因、不允许库存为负、不允许 0 变动
- 幂等键重复提交只扣一次库存
- **20 个并发请求抢 10 件可售库存，恰好 10 个成功，绝不超卖**
- 组合商品拆解占用、子项不足时**整单不占用**
- 同一渠道订单重复导入 / 重放 4 次，库存只被占用一次
- 两条渠道并发同步**同一张订单**，只创建一张、只占一次库存
- CSV 单行损坏只跳过该行，其余照常导入并回报行号
- 渠道商品编码未映射时只有该订单失败，不影响同文件其他订单
- 缺货转异常 → 补货 → 重新占用成功；异常列表只反映最新一次尝试
- 部分占用策略下先占能占的，缺口进异常
- 取消订单按流水精确释放；取消后再同步同单号只记为重复
- 两个平台并发下单抢同一池库存，先到先得、不超卖
- 组合商品下单占用子 SKU，取消时精确释放
- 拣货清单按**库位**而非 SKU 排序（刻意把两个 SKU 的库位反着放来验证）
- 扫到不在单上的 SKU / 扫超量 / 未知条码，全部被拦并留下记录
- 未拣完不能复核、未复核不能出库
- 出库同时扣减实际库存与占用，且**重复出库只扣一次**
- 两个请求并发开拣货单，只生成一张（部分唯一索引兜底）
- 6 次并发扫码抢同一条 3 件的拣货行，已拣数不会超过 3
- 取消拣货单不动库存、订单回到「已占用」，随后可以重新开单
- 套装出库按子件扣减，套装 SKU 自身库存始终为 0

---

## 目录结构

```
omnistock/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置 / 安全 / 错误码 / 依赖 / 日志
│   │   ├── db.py          # 引擎与会话
│   │   ├── models/        # 26 张表：商品三层 / 仓库库位 / 库存与流水 / 渠道订单 / 发货拣货 / RBAC
│   │   ├── schemas/       # Pydantic 出入参
│   │   ├── repositories/  # 数据访问（占用 / 出库 / 拣货均为条件 UPDATE 原子操作）
│   │   ├── services/      # 业务逻辑：库存 / 商品 / 渠道 / 订单 / 导入 / 发货
│   │   ├── domain/        # 纯规则：可售公式 / 组合拆解计算
│   │   ├── adapters/      # 渠道适配器：CSV / JSON（可插拔，M8 接真实平台 API）
│   │   ├── api/v1/        # 路由与角色守卫
│   │   ├── main.py
│   │   └── seed.py        # 演示数据（含渠道、映射、演示订单与拣货单）
│   ├── alembic/versions/  # 0001 M1 / 0002 M2 / 0003 M3 迁移
│   ├── tests/             # 141 个用例
│   └── requirements.txt
├── web/
│   └── src/
│       ├── api/           # 后端接口封装
│       ├── views/         # 订单 / 导入 / 异常 / 拣货发货 / 商品 / SKU / 库存 / 组合 / 仓库 / 渠道
│       ├── components/    # 布局、库存流水表格
│       ├── stores/        # Pinia
│       └── types/
├── docker-compose.yml
└── Makefile
```

---

## 路线图

| 里程碑 | 主题 | 状态 |
| --- | --- | --- |
| **M1** | 商品与库存基础 | ✅ 已完成 |
| **M2** | 电商订单处理（渠道映射 / 导入 / 占用 / 幂等 / 异常单） | ✅ 已完成 |
| **M3** | 仓库发货（拣货 / 扫码 / 复核 / 打包 / 出库） | ✅ 已完成 |
| M4 | 采购与收货（供应商 / 采购单 / 分批到货 / 质检入库） | 规划中 |
| M5 | 多仓库调拨（申请 / 审批 / 在途 / 目标仓收货） | 规划中 |
| M6 | 库存预警（安全库存 / 补货建议 / 通知） | 规划中 |
| M7 | 退货与盘点（质检分流 / 盘点差异审核） | 规划中 |
| M8 | 报表与渠道适配（经营报表 / CSV 导出 / 适配器 / 审计） | 规划中 |

每个里程碑都围绕一个完整需求闭环：数据库迁移、后端接口、前端页面、后台任务、权限、错误处理、测试一起完成。

---

## 许可

[MIT](LICENSE)

本项目为独立实现，仅使用通用开源框架与库；库存占用、组合拆解、在途口径、退货分流、盘点审核等业务逻辑全部自研。
