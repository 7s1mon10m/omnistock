import http from './client'
import type {
  InventoryStock,
  InventoryTransaction,
  Page,
  TransactionType,
} from '@/types'

export interface InventoryQuery {
  sku_id?: number
  warehouse_id?: number
  keyword?: string
  low_only?: boolean
  page?: number
  page_size?: number
}

export async function listInventory(params: InventoryQuery = {}): Promise<Page<InventoryStock>> {
  const { data } = await http.get<Page<InventoryStock>>('/inventory', { params })
  return data
}

export interface LedgerQuery {
  sku_id?: number
  warehouse_id?: number
  type?: TransactionType
  ref_type?: string
  ref_id?: number
  start?: string
  end?: string
  page?: number
  page_size?: number
}

export async function listLedger(params: LedgerQuery = {}): Promise<Page<InventoryTransaction>> {
  const { data } = await http.get<Page<InventoryTransaction>>('/inventory/ledger', { params })
  return data
}

export interface AdjustPayload {
  sku_id: number
  warehouse_id: number
  qty_delta: number
  reason: string
  location_id?: number
  idempotency_key?: string
}

export async function adjustStock(payload: AdjustPayload): Promise<InventoryTransaction> {
  const { data } = await http.post<InventoryTransaction>('/inventory/adjust', payload)
  return data
}

export async function reserveStock(payload: {
  sku_id: number
  warehouse_id: number
  quantity: number
  ref_type?: string
  idempotency_key?: string
}): Promise<InventoryTransaction> {
  const { data } = await http.post<InventoryTransaction>('/inventory/reserve', payload)
  return data
}

export async function releaseStock(payload: {
  sku_id: number
  warehouse_id: number
  quantity: number
  ref_type?: string
  idempotency_key?: string
}): Promise<InventoryTransaction> {
  const { data } = await http.post<InventoryTransaction>('/inventory/release', payload)
  return data
}

export async function reserveBundle(payload: {
  bundle_sku_id: number
  warehouse_id: number
  quantity: number
  ref_type?: string
}): Promise<InventoryTransaction[]> {
  const { data } = await http.post<InventoryTransaction[]>('/inventory/reserve-bundle', payload)
  return data
}
