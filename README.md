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
| 采购在途、到货破损 | 采购单不动库存，**到货才入库**；合格与次品**分开记账** |
| 跨仓调货，货在路上算谁的 | 在途**显式建模**：调出仓已减、调入仓在途+，两边都不算可售 |

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

### M4 · 采购与收货

- **供应商档案**：编码、联系人、结算方式、**交期**（用来推算采购单的预计到货日）
- **采购单**：草稿 → 已下单 → 部分到货 → 已收齐，只有草稿可改
- **采购单本身不动库存**：下单只是承诺，**只有到货登记才入库**
- **分批到货**：一张采购单可以对应多张收货单，每张只收一部分
- **质检分流**：到货时拆成合格与次品，**合格进可售、次品只进次品区**，永远不参与可售
- **超收拦截**：默认严格不超过下单量（可用 `PURCHASE_OVER_RECEIPT_PERCENT` 放宽）
- **流水自洽**：合格与次品各写一条流水，带齐 `在途 / 次品` 的前后值

### M5 · 多仓库调拨

- **四步流程**：申请 → 审批 → 发出 → 收货，**每一步的责任人不同**（仓管提、店主批、源仓发、目标仓收）
- **在途被显式建模**：发出后调出仓实际库存减少、**调入仓在途增加**；在途**不计入可售**
- **收货转实际**：在途清零、实际库存增加；到货破损可以记次品，次品不进可售
- **允许少发与分批收**：发出时可以少发，收货可以分几次收，没收完的继续挂在在途
- **发出前可取消，发出后必须走完**：货一旦上路就不能取消，否则在途会变成黑洞
- **整单一起发**：发出的每一行都会先校验可售，任何一行不够就整单不发

### M6 · 库存预警

- **安全库存规则**：全局 / 按品类 / 按 SKU / 按仓库四档，**范围越窄越优先**；没设阈值时沿用 SKU 自身的安全库存
- **扫描去重**：`可售 + 在途 < 安全库存` 才告警；**同一 SKU 未解决前只保留一条**，补货到位后自动关闭
- **在途算覆盖**：已下单在路上的货计入覆盖，所以「货在路上」不会误报
- **补货建议**：`建议采购量 = 预测销量 + 安全库存 − 可售 − 在途`，结果不为负；**一键转采购单生成的是草稿**
- **通知三通道**：站内 / 邮件（SMTP）/ Webhook，每条通知的**每次投递尝试**都单独留痕
- **指数退避重试**：2 → 4 → 8 → 16 秒；4xx 立刻失败不重试，没配 SMTP 时邮件通道立刻报 `42402`
- **站内始终可达**：外部通道坏掉也不会让人看不到低库存预警

### M7 · 退货与盘点

- **退货两步走**：**质检只记结论不动库存**，入库才落账 —— 质检结论可以反悔，不会把账做脏
- **四路分流**：可再售回可售 / 次品进次品区 / 待维修进维修区 / 报损直接出账
- **次品与维修永不进可售**：混成一条「退货入库」会让次品立刻变成能卖的货
- **退货量校验**：不能超过「已售 − 已退」，超出返回 `40960`
- **盘点差异必须审核**：提交只是「我盘完了」，**审核通过才写调整流水**，留操作人 / 时间 / 原因
- **未审核不动库存**：这是盘点模块的底线，有专门用例守着

### M8 · 报表与渠道适配

- **经营看板**：在库 / 可售 / 库存金额 / 预警 / 异常 / 低库存等核心数字，附渠道销量与供应商及时率图表
- **十张报表**：SKU 库存、周转天数、供应商及时率、渠道销量、缺货次数、退货率、滞销、采购金额、盘点差异、低库存清单
- **统一口径**：净销量 = 出库 − 退货入库；零销量时周转天数是 `None`（卖不动）而不是 0（周转极快）
- **CSV 导出**：带 **UTF-8 BOM**，Excel 双击打开不乱码；中文文件名用 RFC 5987 编码；超上限报错而非截断
- **渠道适配器**：淘宝 / 抖音字段映射（淘宝金额是「元」字符串、抖音是「分」整数），**渠道身份由配置给出**
- **审计日志**：自动记录成功的写操作，支持按人 / 动作 / 资源检索，**只读，没有也不该有改删接口**

### 接口一览（M1 – M8）

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

# --- M4 采购与收货 ---
GET    /api/v1/suppliers                POST /api/v1/suppliers
GET    /api/v1/suppliers/{id}           PATCH /api/v1/suppliers/{id}
GET    /api/v1/purchase-orders          POST /api/v1/purchase-orders
GET    /api/v1/purchase-orders/{id}     PATCH /api/v1/purchase-orders/{id}
POST   /api/v1/purchase-orders/{id}/submit    # 草稿 → 已下单
POST   /api/v1/purchase-orders/{id}/cancel
POST   /api/v1/purchase-orders/{id}/receipts  # 登记到货（合格 / 次品分流）
GET    /api/v1/purchase-receipts        GET /api/v1/purchase-receipts/{id}

# --- M5 多仓库调拨 ---
GET    /api/v1/transfers                POST /api/v1/transfers
GET    /api/v1/transfers/{id}
POST   /api/v1/transfers/{id}/approve   # 审批通过
POST   /api/v1/transfers/{id}/reject    # 审批驳回
POST   /api/v1/transfers/{id}/ship      # 调出仓发出 → 进入在途
POST   /api/v1/transfers/{id}/receive   # 调入仓收货 → 在途转实际
POST   /api/v1/transfers/{id}/cancel    # 仅未发出可取消

# M6 预警与通知
GET/PUT  /api/v1/alert-rules            POST /api/v1/alert-rules   DELETE /api/v1/alert-rules/{id}
GET      /api/v1/alerts                 # 支持 status / type / warehouse / sku 过滤
POST     /api/v1/alerts/scan            # 手动触发一次扫描
POST     /api/v1/alerts/{id}/ack        POST /api/v1/alerts/{id}/resolve
GET      /api/v1/replenishment-suggestions
POST     /api/v1/replenishment-suggestions/generate
POST     /api/v1/replenishment-suggestions/{id}/dismiss
POST     /api/v1/replenishment-suggestions/{id}/to-purchase-order
GET      /api/v1/notifications          GET /api/v1/notifications/unread-count
POST     /api/v1/notifications/{id}/read    POST /api/v1/notifications/read-all
GET      /api/v1/notifications/settings/all  PUT /api/v1/notifications/settings/{channel}

# M7 退货与盘点
GET/POST /api/v1/return-orders
GET      /api/v1/return-orders/{id}
POST     /api/v1/return-orders/{id}/inspect   # 质检分流（不动库存）
POST     /api/v1/return-orders/{id}/inbound   # 入库（此时才动库存）
POST     /api/v1/return-orders/{id}/cancel
GET/POST /api/v1/stocktakes             GET /api/v1/stocktakes/{id}
POST     /api/v1/stocktakes/{id}/counts       # 批量录入实盘数
POST     /api/v1/stocktakes/{id}/scan         # 扫码录入
POST     /api/v1/stocktakes/{id}/submit       # 提交（仍不动库存）
POST     /api/v1/stocktakes/{id}/approve      # 审核（此时才落账）
POST     /api/v1/stocktakes/{id}/cancel

# M8 报表与渠道适配
GET  /api/v1/reports/dashboard
GET  /api/v1/reports/sku-stock | turnover | supplier-ontime | channel-sales
GET  /api/v1/reports/stockout | return-rate | slow-moving | purchase-amount
GET  /api/v1/reports/stocktake-variance | low-stock
GET  /api/v1/exports/{report}.csv       # 带 BOM，Excel 可直接打开
GET  /api/v1/audit-logs                 # 只读
GET  /api/v1/channel-adapters/descriptors
GET/POST /api/v1/channel-adapters       PUT /api/v1/channel-adapters/{id}
POST /api/v1/channel-adapters/{id}/sync
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

M1 – M8 共 **324 个用例**，重点覆盖：

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
- 采购单本身不产生库存；到货 60 件含 5 件次品 → 实际 +55、次品 +5、可售 +55
- 分批到货：两次收货后采购单自动结单；超收被拦且库存不受影响
- 调拨发出后调出仓实际减少、调入仓在途增加，**在途不计入可售**
- 分批收货：没收完的继续挂在在途，全部收齐才结单
- 已发出的调拨不能取消（否则在途变黑洞）
- 源仓可售不足时**整单不发**，任何一侧的库存都不动
- 补货公式：在途要扣减、结果为负时不生成建议（纯函数单测）
- 扫描 5 次只产生 1 条预警；补货到位后自动关闭，再次缺货能重新告警
- 建议转采购单生成的是**草稿**；转换后去重键释放，下一轮可重新评估
- 退 6 件按 3/1/1/1 四路分流：可售只 +3，次品 +1，维修 +1，报损不入账
- 整批次品时，可售库存**一点都不许变**
- 盘点提交后库存不变；审核后才写调整流水且留下操作人
- 盘点重复审核返回 `40961`；已审核的盘点不能取消
- 周转天数 = 平均库存 / 日均销量，零销量时是 `None` 而不是 0
- 退货后净销量减少（净销量 = 出库 − 退货入库），退货率按此计算
- 供应商及时率：**没有预计到货日的采购单不计入分母**
- 导出带 BOM、中文文件名用 `filename*`；超过上限报错而非截断
- 写操作必留审计，审计接口只读（`PUT`/`DELETE` 均 405），登录不进审计
- 淘宝金额「元」字符串转分、抖音「分」直接采用
- 渠道适配器重复同步同一批订单，库存**只占用一次**

---

## 目录结构

```
omnistock/
├── backend/
│   ├── app/
│   │   ├── core/          # 配置 / 安全 / 错误码 / 依赖 / 日志
│   │   ├── db.py          # 引擎与会话
│   │   ├── models/        # 44 张表：商品 / 仓库库位 / 库存流水 / 渠道订单 / 发货拣货 /
│   │   │                  #   采购收货 / 调拨 / 预警通知 / 退货盘点 / 审计 / 适配器 / RBAC
│   │   ├── schemas/       # Pydantic 出入参
│   │   ├── repositories/  # 数据访问（占用 / 出库 / 拣货均为条件 UPDATE 原子操作）
│   │   ├── services/      # 业务逻辑：库存 / 商品 / 渠道 / 订单 / 导入 / 发货 / 采购 /
│   │   │                  #   调拨 / 预警 / 补货 / 通知 / 退货 / 盘点 / 报表 / 导出 / 审计
│   │   ├── domain/        # 纯规则：可售公式 / 组合拆解 / 补货公式 / 退货状态机
│   │   ├── adapters/      # 渠道适配器：CSV / JSON（文件）+ 淘宝 / 抖音（平台 API）
│   │   ├── middlewares/   # 请求上下文 / 审计留痕
│   │   ├── tasks/         # 后台入口：预警扫描、通知重试
│   │   ├── api/v1/        # 路由与角色守卫
│   │   ├── main.py
│   │   └── seed.py        # 演示数据（含渠道、订单、拣货单、采购单、调拨单、
│   │                      #   预警规则、退货单、盘点单与渠道适配器）
│   ├── alembic/versions/  # 0001 M1 … 0008 M8
│   ├── tests/             # 324 个用例
│   └── requirements.txt
├── web/
│   └── src/
│       ├── api/           # 后端接口封装
│       ├── views/         # 看板 / 订单 / 拣货发货 / 采购收货 / 调拨 / 商品 / 库存 /
│       │                  #   渠道 / 仓库 / 退货 / 盘点 / 预警 / 补货 / 通知 / 报表 / 审计
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
| **M4** | 采购与收货（供应商 / 采购单 / 分批到货 / 质检入库） | ✅ 已完成 |
| **M5** | 多仓库调拨（申请 / 审批 / 在途 / 目标仓收货） | ✅ 已完成 |
| **M6** | 库存预警（安全库存 / 补货建议 / 通知） | ✅ 已完成 |
| **M7** | 退货与盘点（质检分流 / 盘点差异审核） | ✅ 已完成 |
| **M8** | 报表与渠道适配（经营报表 / CSV 导出 / 适配器 / 审计） | ✅ 已完成 |

每个里程碑都围绕一个完整需求闭环：数据库迁移、后端接口、前端页面、后台任务、权限、错误处理、测试一起完成。

---

## 许可

[MIT](LICENSE)

本项目为独立实现，仅使用通用开源框架与库；库存占用、组合拆解、在途口径、退货分流、盘点审核等业务逻辑全部自研。
