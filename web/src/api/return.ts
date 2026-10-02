import http from './client'
import type {
  Page,
  ReturnDisposition,
  ReturnListItem,
  ReturnOrder,
  ReturnReason,
  ReturnStatus,
} from '@/types'

export interface ReturnQuery {
  status?: ReturnStatus
  warehouse_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export async function listReturns(params: ReturnQuery = {}): Promise<Page<ReturnListItem>> {
  const { data } = await http.get<Page<ReturnListItem>>('/return-orders', { params })
  return data
}

export async function getReturn(id: number): Promise<ReturnOrder> {
  const { data } = await http.get<ReturnOrder>(`/return-orders/${id}`)
  return data
}

export async function createReturn(payload: {
  warehouse_id: number
  order_id?: number | null
  channel_id?: number | null
  channel_order_no?: string
  buyer_nick?: string
  reason?: ReturnReason
  remark?: string
  items: { sku_id: number; quantity: number; remark?: string }[]
}): Promise<ReturnOrder> {
  const { data } = await http.post<ReturnOrder>('/return-orders', payload)
  return data
}

export interface InspectLine {
  return_item_id: number
  disposition: ReturnDisposition
  resellable_qty?: number
  defective_qty?: number
  repair_qty?: number
  scrap_qty?: number
  remark?: string
}

export async function inspectReturn(
  id: number,
  payload: { items: InspectLine[]; remark?: string },
): Promise<ReturnOrder> {
  const { data } = await http.post<ReturnOrder>(`/return-orders/${id}/inspect`, payload)
  return data
}

export async function inboundReturn(id: number): Promise<ReturnOrder> {
  const { data } = await http.post<ReturnOrder>(`/return-orders/${id}/inbound`, {})
  return data
}

export async function cancelReturn(id: number, reason = ''): Promise<ReturnOrder> {
  const { data } = await http.post<ReturnOrder>(`/return-orders/${id}/cancel`, { reason })
  return data
}
