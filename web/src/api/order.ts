import http from './client'
import type {
  ImportBatch,
  ImportResult,
  OrderActionResult,
  OrderDetail,
  OrderException,
  OrderStatus,
  OrderSummary,
  Page,
  SyncLog,
} from '@/types'

export interface OrderQuery {
  channel_id?: number
  status?: OrderStatus
  keyword?: string
  only_exception?: boolean
  page?: number
  page_size?: number
}

export async function listOrders(params: OrderQuery = {}): Promise<Page<OrderSummary>> {
  const { data } = await http.get<Page<OrderSummary>>('/orders', { params })
  return data
}

export async function getOrder(id: number): Promise<OrderDetail> {
  const { data } = await http.get<OrderDetail>(`/orders/${id}`)
  return data
}

export async function markPaid(id: number, paidAt?: string): Promise<OrderActionResult> {
  const { data } = await http.post<OrderActionResult>(`/orders/${id}/mark-paid`, {
    paid_at: paidAt ?? null,
  })
  return data
}

export async function cancelOrder(id: number, reason = ''): Promise<OrderActionResult> {
  const { data } = await http.post<OrderActionResult>(`/orders/${id}/cancel`, { reason })
  return data
}

export async function retryReserve(id: number): Promise<OrderActionResult> {
  const { data } = await http.post<OrderActionResult>(`/orders/${id}/retry-reserve`)
  return data
}

// ------------------------------------------------------------------- imports
export async function importOrdersJson(payload: {
  filename?: string
  source?: string
  orders: unknown[]
}): Promise<ImportResult> {
  const { data } = await http.post<ImportResult>('/orders/import-json', payload)
  return data
}

export async function importOrdersFile(file: File): Promise<ImportResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<ImportResult>('/orders/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
  return data
}

export const TEMPLATE_URL = '/api/v1/orders/import-template.csv'

export async function listImportBatches(params: { page?: number; page_size?: number } = {}) {
  const { data } = await http.get<Page<ImportBatch>>('/orders/import-batches', { params })
  return data
}

export async function listSyncLogs(
  params: { channel_id?: number; channel_order_no?: string; result?: string; page?: number; page_size?: number } = {},
): Promise<Page<SyncLog>> {
  const { data } = await http.get<Page<SyncLog>>('/orders/sync-logs', { params })
  return data
}

// ---------------------------------------------------------------- exceptions
export async function listExceptions(
  params: { status?: string; type?: string; order_id?: number; page?: number; page_size?: number } = {},
): Promise<Page<OrderException>> {
  const { data } = await http.get<Page<OrderException>>('/orders/exceptions', { params })
  return data
}
