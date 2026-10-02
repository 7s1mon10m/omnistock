import http from './client'
import type { Page, Stocktake, StocktakeListItem, StocktakeStatus } from '@/types'

export interface StocktakeQuery {
  status?: StocktakeStatus
  warehouse_id?: number
  page?: number
  page_size?: number
}

export async function listStocktakes(params: StocktakeQuery = {}): Promise<Page<StocktakeListItem>> {
  const { data } = await http.get<Page<StocktakeListItem>>('/stocktakes', { params })
  return data
}

export async function getStocktake(id: number): Promise<Stocktake> {
  const { data } = await http.get<Stocktake>(`/stocktakes/${id}`)
  return data
}

export async function createStocktake(payload: {
  warehouse_id: number
  scope?: string
  remark?: string
  sku_ids?: number[]
}): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>('/stocktakes', payload)
  return data
}

export interface CountLine {
  stocktake_item_id: number
  counted_qty: number
  reason?: string
}

export async function countStocktake(
  id: number,
  payload: { items: CountLine[] },
): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>(`/stocktakes/${id}/counts`, payload)
  return data
}

export async function scanStocktake(
  id: number,
  payload: { barcode: string; counted_qty: number },
): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>(`/stocktakes/${id}/scan`, payload)
  return data
}

export async function submitStocktake(id: number): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>(`/stocktakes/${id}/submit`)
  return data
}

export async function approveStocktake(id: number, remark = ''): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>(`/stocktakes/${id}/approve`, { remark })
  return data
}

export async function cancelStocktake(id: number, reason = ''): Promise<Stocktake> {
  const { data } = await http.post<Stocktake>(`/stocktakes/${id}/cancel`, { reason })
  return data
}
