export type UserStatus = 'active' | 'locked' | 'disabled'

export interface UserProfile {
  id: number
  username: string
  email: string
  full_name: string
  phone: string
  status: UserStatus
  roles: string[]
  last_login_at: string | null
  created_at: string | null
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface LoginResponse extends TokenPair {
  user: UserProfile
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** Business error envelope returned by every failing endpoint. */
export interface ApiErrorBody {
  code: number
  message: string
  detail?: unknown
}

// --------------------------------------------------------------------- product
export type SpuType = 'single' | 'bundle'
export type SpuStatus = 'active' | 'archived'
export type SkuStatus = 'active' | 'archived'

export interface Spu {
  id: number
  code: string
  name: string
  category: string
  brand: string
  type: SpuType
  images: string[]
  description: string
  status: SpuStatus
  sku_count: number
  created_at: string | null
}

export interface Sku {
  id: number
  spu_id: number
  sku_code: string
  display_name: string
  spec_json: Record<string, unknown>
  barcode: string | null
  weight_g: number
  package_spec: string
  purchase_price_cents: number
  default_supplier_id: number | null
  safety_qty: number
  status: SkuStatus
  is_bundle: boolean
  created_at: string | null
}

export interface Barcode {
  id: number
  sku_id: number
  barcode: string
  is_primary: boolean
  remark: string
}

export interface BundleComponent {
  component_sku_id: number
  component_sku_code: string
  component_name: string
  quantity: number
  available_qty: number
}

export interface Bundle {
  bundle_sku_id: number
  bundle_sku_code: string
  bundle_name: string
  components: BundleComponent[]
  buildable_qty: number
}

// ------------------------------------------------------------------- warehouse
export type WarehouseType = 'main' | 'live' | 'return' | 'other'

export interface Warehouse {
  id: number
  code: string
  name: string
  type: WarehouseType
  address: string
  contact_name: string
  contact_phone: string
  is_active: boolean
  remark: string
  location_count: number
  created_at: string | null
}

export interface WarehouseLocation {
  id: number
  warehouse_id: number
  code: string
  name: string
  zone: string
  is_active: boolean
}

// ------------------------------------------------------------------- inventory
export interface InventoryStock {
  id: number
  sku_id: number
  sku_code: string
  sku_name: string
  warehouse_id: number
  warehouse_code: string
  warehouse_name: string
  on_hand_qty: number
  reserved_qty: number
  in_transit_qty: number
  safety_qty: number
  defective_qty: number
  repair_qty: number
  available_qty: number
  /** 默认拣货库位（M3）：拣货清单按它排序 */
  default_location_id: number | null
  default_location_code: string
  version: number
  updated_at: string | null
}

export type TransactionType =
  | 'purchase_inbound'
  | 'order_reserve'
  | 'order_release'
  | 'order_outbound'
  | 'return_inbound'
  | 'return_defective'
  | 'return_repair'
  | 'damage_scrap'
  | 'transfer_out'
  | 'transfer_in'
  | 'stocktake_adjust'
  | 'manual_adjust'

export interface InventoryTransaction {
  id: number
  sku_id: number
  sku_code: string
  warehouse_id: number
  warehouse_code: string
  location_id: number | null
  type: TransactionType
  qty_delta: number
  on_hand_before: number
  on_hand_after: number
  reserved_before: number
  reserved_after: number
  ref_type: string
  ref_id: number | null
  operator_id: number | null
  operator_name: string
  remark: string
  created_at: string
}

export const TRANSACTION_LABELS: Record<TransactionType, string> = {
  purchase_inbound: '采购入库',
  order_reserve: '订单占用',
  order_release: '取消释放',
  order_outbound: '拣货出库',
  return_inbound: '退货入库',
  return_defective: '退货次品',
  return_repair: '退货维修',
  damage_scrap: '报损',
  transfer_out: '调拨出库',
  transfer_in: '调拨入库',
  stocktake_adjust: '盘点调整',
  manual_adjust: '手工调整',
}

export const WAREHOUSE_TYPE_LABELS: Record<WarehouseType, string> = {
  main: '总仓',
  live: '直播间仓',
  return: '退货仓',
  other: '其他',
}

// -------------------------------------------------------- channels & orders
export type ChannelPlatform = 'taobao' | 'douyin' | 'shopify' | 'jd' | 'pdd' | 'other'

export const CHANNEL_PLATFORM_LABELS: Record<ChannelPlatform, string> = {
  taobao: '淘宝',
  douyin: '抖音',
  shopify: 'Shopify',
  jd: '京东',
  pdd: '拼多多',
  other: '其他',
}

export interface Channel {
  id: number
  code: string
  name: string
  platform: ChannelPlatform
  is_active: boolean
  remark: string
  shop_count: number
  product_count: number
  created_at: string | null
}

export interface ChannelShop {
  id: number
  channel_id: number
  code: string
  name: string
  is_active: boolean
  remark: string
}

export interface ChannelProduct {
  id: number
  channel_id: number
  channel_code: string
  channel_name: string
  shop_id: number | null
  shop_code: string
  channel_product_code: string
  sku_id: number
  sku_code: string
  sku_name: string
  channel_title: string
  is_active: boolean
  remark: string
  created_at: string | null
}

export type OrderStatus =
  | 'pending_payment'
  | 'pending_fulfillment'
  | 'reserved'
  | 'picking'
  | 'shipped'
  | 'completed'
  | 'cancelled'
  | 'exception'

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  pending_payment: '待支付',
  pending_fulfillment: '待配货',
  reserved: '已占用库存',
  picking: '拣货中',
  shipped: '已发货',
  completed: '已完成',
  cancelled: '已取消',
  exception: '异常订单',
}

export const ORDER_STATUS_TAG: Record<OrderStatus, string> = {
  pending_payment: 'info',
  pending_fulfillment: 'warning',
  reserved: 'success',
  picking: 'warning',
  shipped: 'success',
  completed: 'success',
  cancelled: 'info',
  exception: 'danger',
}

export type OrderSource = 'import_csv' | 'import_json' | 'adapter' | 'manual'

export interface OrderItem {
  id: number
  line_no: number
  channel_product_code: string
  sku_id: number
  sku_code: string
  sku_name: string
  quantity: number
  unit_price_cents: number
  is_bundle: boolean
}

export interface ReservationLine {
  sku_id: number
  sku_code: string
  warehouse_id: number
  warehouse_code: string
  quantity: number
}

export interface OrderSummary {
  id: number
  order_no: string
  channel_code: string
  shop_code: string
  channel_order_no: string
  status: OrderStatus
  buyer_nick: string
  total_amount_cents: number
  total_quantity: number
  item_count: number
  is_bundle: boolean
  source: OrderSource
  created_at: string | null
}

export interface OrderDetail extends OrderSummary {
  channel_id: number
  channel_name: string
  shop_id: number | null
  warehouse_id: number | null
  warehouse_code: string
  paid_at: string | null
  remark: string
  items: OrderItem[]
  reservations: ReservationLine[]
  open_exceptions: number
}

export type ExceptionType = 'stock_shortage' | 'mapping_missing' | 'other'
export type ExceptionStatus = 'open' | 'resolved' | 'ignored'

export interface OrderException {
  id: number
  order_id: number
  order_no: string
  channel_order_no: string
  sku_id: number | null
  sku_code: string
  sku_name: string
  warehouse_code: string
  type: ExceptionType
  status: ExceptionStatus
  required_qty: number
  available_qty: number
  shortage_qty: number
  message: string
  created_at: string | null
}

export interface OrderActionResult {
  order: OrderDetail
  reserved: ReservationLine[]
  released: ReservationLine[]
  exceptions: OrderException[]
  message: string
}

export interface ImportErrorRow {
  row: number
  code: number
  message: string
  channel_order_no: string
}

export interface ImportResult {
  batch_id: number
  source: OrderSource
  total_rows: number
  created_orders: number
  duplicate_orders: number
  failed_rows: number
  reserved_orders: number
  exception_orders: number
  errors: ImportErrorRow[]
}

export interface ImportBatch {
  id: number
  source: OrderSource
  filename: string
  total_rows: number
  created_orders: number
  duplicate_orders: number
  failed_rows: number
  reserved_orders: number
  exception_orders: number
  created_at: string | null
}

export interface SyncLog {
  id: number
  channel_id: number
  channel_code: string
  shop_id: number | null
  channel_order_no: string
  order_id: number | null
  batch_id: number | null
  result: 'created' | 'duplicate' | 'failed'
  message: string
  created_at: string | null
}

export const SYNC_RESULT_LABELS: Record<string, string> = {
  created: '已创建',
  duplicate: '重复同步',
  failed: '失败',
}

// ------------------------------------------------------ shipping & picking
export type ShipmentStatus =
  | 'pending'
  | 'picking'
  | 'picked'
  | 'packed'
  | 'shipped'
  | 'cancelled'

export const SHIPMENT_STATUS_LABELS: Record<ShipmentStatus, string> = {
  pending: '待拣货',
  picking: '拣货中',
  picked: '拣货完成',
  packed: '已复核打包',
  shipped: '已出库',
  cancelled: '已取消',
}

export const SHIPMENT_STATUS_TAG: Record<ShipmentStatus, string> = {
  pending: 'info',
  picking: 'warning',
  picked: 'primary',
  packed: 'success',
  shipped: 'success',
  cancelled: 'info',
}

export interface ShipmentItem {
  id: number
  line_no: number
  sku_id: number
  sku_code: string
  sku_name: string
  barcode: string
  location_id: number | null
  location_code: string
  location_name: string
  quantity: number
  picked_qty: number
  status: 'pending' | 'picked'
  is_bundle_component: boolean
  remark: string
}

export interface ShipmentListItem {
  id: number
  shipment_no: string
  order_no: string
  channel_code: string
  channel_order_no: string
  buyer_nick: string
  warehouse_code: string
  status: ShipmentStatus
  picker_name: string
  total_quantity: number
  picked_quantity: number
  carrier: string
  tracking_no: string
  created_at: string | null
}

export interface Shipment extends ShipmentListItem {
  order_id: number
  warehouse_id: number
  warehouse_name: string
  picker_id: number | null
  picked_at: string | null
  packed_by: number | null
  packed_by_name: string
  packed_at: string | null
  package_count: number
  weight_g: number
  shipped_at: string | null
  remark: string
  is_fully_picked: boolean
  items: ShipmentItem[]
}

export type PickResultType =
  | 'ok'
  | 'wrong_sku'
  | 'barcode_not_found'
  | 'over_quantity'
  | 'not_on_list'

export interface PickResult {
  accepted: boolean
  result: PickResultType
  message: string
  shipment_id: number
  shipment_item_id: number | null
  sku_id: number | null
  sku_code: string
  picked_qty: number
  quantity: number
  shipment_status: ShipmentStatus
  progress: string
}

export interface PickRecord {
  id: number
  shipment_id: number
  shipment_item_id: number | null
  barcode: string
  quantity: number
  result: PickResultType
  accepted: boolean
  message: string
  sku_id: number | null
  sku_code: string
  operator_id: number | null
  operator_name: string
  created_at: string | null
}

export interface OutboundLine {
  sku_id: number
  sku_code: string
  warehouse_code: string
  quantity: number
}

export interface ShipmentActionResult {
  shipment: Shipment
  message: string
  outbound: OutboundLine[]
}

export function yuan(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}
