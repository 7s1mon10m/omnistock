import http from './client'
import type {
  Page,
  PurchaseOrder,
  PurchaseOrderListItem,
  PurchaseOrderStatus,
  PurchaseReceipt,
  ReceiptResult,
  Supplier,
} from '@/types'

// ------------------------------------------------------------------ supplier
export async function listSuppliers(
  params: { keyword?: string; is_active?: boolean; page?: number; page_size?: number } = {},
): Promise<Page<Supplier>> {
  const { data } = await http.get<Page<Supplier>>('/suppliers', {
    params: { page_size: 100, ...params },
  })
  return data
}

export async function createSupplier(payload: Partial<Supplier>): Promise<Supplier> {
  const { data } = await http.post<Supplier>('/suppliers', payload)
  return data
}

export async function updateSupplier(id: number, payload: Partial<Supplier>): Promise<Supplier> {
  const { data } = await http.patch<Supplier>(`/suppliers/${id}`, payload)
  return data
}

// ------------------------------------------------------------ purchase order
export interface PurchaseQuery {
  supplier_id?: number
  warehouse_id?: number
  status?: PurchaseOrderStatus
  keyword?: string
  page?: number
  page_size?: number
}

export async function listPurchaseOrders(
  params: PurchaseQuery = {},
): Promise<Page<PurchaseOrderListItem>> {
  const { data } = await http.get<Page<PurchaseOrderListItem>>('/purchase-orders', { params })
  return data
}

export async function createPurchaseOrder(payload: {
  supplier_id: number
  warehouse_id: number
  expected_at?: string | null
  remark?: string
  items: { sku_id: number; quantity: number; unit_price_cents: number; remark?: string }[]
}): Promise<PurchaseOrder> {
  const { data } = await http.post<PurchaseOrder>('/purchase-orders', payload)
  return data
}

export async function getPurchaseOrder(id: number): Promise<PurchaseOrder> {
  const { data } = await http.get<PurchaseOrder>(`/purchase-orders/${id}`)
  return data
}

export async function updatePurchaseOrder(
  id: number,
  payload: Partial<PurchaseOrder> & { items?: unknown[] },
): Promise<PurchaseOrder> {
  const { data } = await http.patch<PurchaseOrder>(`/purchase-orders/${id}`, payload)
  return data
}

export async function submitPurchaseOrder(id: number): Promise<PurchaseOrder> {
  const { data } = await http.post<PurchaseOrder>(`/purchase-orders/${id}/submit`)
  return data
}

export async function cancelPurchaseOrder(id: number, reason = ''): Promise<PurchaseOrder> {
  const { data } = await http.post<PurchaseOrder>(`/purchase-orders/${id}/cancel`, null, {
    params: { reason },
  })
  return data
}

export async function createReceipt(
  orderId: number,
  payload: {
    items: { order_item_id: number; quantity: number; defective_qty?: number; location_id?: number | null }[]
    remark?: string
  },
): Promise<ReceiptResult> {
  const { data } = await http.post<ReceiptResult>(`/purchase-orders/${orderId}/receipts`, payload)
  return data
}

export async function listReceipts(
  params: { order_id?: number; page?: number; page_size?: number } = {},
): Promise<Page<PurchaseReceipt>> {
  const { data } = await http.get<Page<PurchaseReceipt>>('/purchase-receipts', { params })
  return data
}

export async function getReceipt(id: number): Promise<PurchaseReceipt> {
  const { data } = await http.get<PurchaseReceipt>(`/purchase-receipts/${id}`)
  return data
}
