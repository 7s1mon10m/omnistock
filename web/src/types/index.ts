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
