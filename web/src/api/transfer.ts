import http from './client'
import type { Page, StockTransfer, TransferListItem, TransferStatus } from '@/types'

export interface TransferQuery {
  status?: TransferStatus
  from_warehouse_id?: number
  to_warehouse_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export async function listTransfers(params: TransferQuery = {}): Promise<Page<TransferListItem>> {
  const { data } = await http.get<Page<TransferListItem>>('/transfers', { params })
  return data
}

export async function createTransfer(payload: {
  from_warehouse_id: number
  to_warehouse_id: number
  reason?: string
  remark?: string
  items: { sku_id: number; quantity: number; remark?: string }[]
}): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>('/transfers', payload)
  return data
}

export async function getTransfer(id: number): Promise<StockTransfer> {
  const { data } = await http.get<StockTransfer>(`/transfers/${id}`)
  return data
}

export async function approveTransfer(id: number): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>(`/transfers/${id}/approve`)
  return data
}

export async function rejectTransfer(id: number, reason: string): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>(`/transfers/${id}/reject`, { reason })
  return data
}

export async function shipTransfer(
  id: number,
  items?: { transfer_item_id: number; quantity?: number | null }[],
): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>(`/transfers/${id}/ship`, { items: items ?? null })
  return data
}

export async function receiveTransfer(
  id: number,
  items?: { transfer_item_id: number; quantity?: number | null; defective_qty?: number }[],
): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>(`/transfers/${id}/receive`, {
    items: items ?? null,
  })
  return data
}

export async function cancelTransfer(id: number, reason = ''): Promise<StockTransfer> {
  const { data } = await http.post<StockTransfer>(`/transfers/${id}/cancel`, { reason })
  return data
}
