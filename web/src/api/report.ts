import http from './client'
import type {
  AdapterDescriptor,
  AdapterSyncResult,
  AuditLog,
  ChannelAdapter,
  ChannelSalesRow,
  DashboardSummary,
  LowStockRow,
  Page,
  PurchaseAmountRow,
  ReturnRateRow,
  SlowMovingRow,
  SkuStockRow,
  StockoutRow,
  StocktakeVarianceRow,
  SupplierOnTimeRow,
  TurnoverRow,
} from '@/types'

export type Granularity = 'day' | 'week' | 'month'

export interface RangeParams {
  start?: string
  end?: string
  days?: number
}

// ------------------------------------------------------------------ 看板
export async function dashboard(params: RangeParams = {}): Promise<DashboardSummary> {
  const { data } = await http.get<DashboardSummary>('/reports/dashboard', { params })
  return data
}

// ------------------------------------------------------------------ 报表
export async function skuStock(warehouseId?: number): Promise<SkuStockRow[]> {
  const { data } = await http.get<SkuStockRow[]>('/reports/sku-stock', {
    params: warehouseId ? { warehouse_id: warehouseId } : {},
  })
  return data
}

export async function turnover(
  params: RangeParams & { warehouse_id?: number } = {},
): Promise<TurnoverRow[]> {
  const { data } = await http.get<TurnoverRow[]>('/reports/turnover', { params })
  return data
}

export async function supplierOnTime(): Promise<SupplierOnTimeRow[]> {
  const { data } = await http.get<SupplierOnTimeRow[]>('/reports/supplier-ontime')
  return data
}

export async function channelSales(
  params: RangeParams & { granularity?: Granularity; channel_id?: number } = {},
): Promise<ChannelSalesRow[]> {
  const { data } = await http.get<ChannelSalesRow[]>('/reports/channel-sales', { params })
  return data
}

export async function stockout(params: RangeParams = {}): Promise<StockoutRow[]> {
  const { data } = await http.get<StockoutRow[]>('/reports/stockout', { params })
  return data
}

export async function returnRate(params: RangeParams = {}): Promise<ReturnRateRow[]> {
  const { data } = await http.get<ReturnRateRow[]>('/reports/return-rate', { params })
  return data
}

export async function slowMoving(params: RangeParams = {}): Promise<SlowMovingRow[]> {
  const { data } = await http.get<SlowMovingRow[]>('/reports/slow-moving', { params })
  return data
}

export async function purchaseAmount(
  params: RangeParams & { granularity?: Granularity; supplier_id?: number } = {},
): Promise<PurchaseAmountRow[]> {
  const { data } = await http.get<PurchaseAmountRow[]>('/reports/purchase-amount', { params })
  return data
}

export async function stocktakeVariance(): Promise<StocktakeVarianceRow[]> {
  const { data } = await http.get<StocktakeVarianceRow[]>('/reports/stocktake-variance')
  return data
}

export async function lowStock(): Promise<LowStockRow[]> {
  const { data } = await http.get<LowStockRow[]>('/reports/low-stock')
  return data
}

// ------------------------------------------------------------------ 导出
export function exportUrl(report: string, params: RangeParams & { granularity?: Granularity } = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return `/api/v1/exports/${report}.csv${suffix}`
}

// ------------------------------------------------------------------ 审计
export interface AuditQuery {
  actor?: string
  action?: string
  resource?: string
  resource_id?: string
  start?: string
  end?: string
  page?: number
  page_size?: number
}

export async function listAuditLogs(params: AuditQuery = {}): Promise<Page<AuditLog>> {
  const { data } = await http.get<Page<AuditLog>>('/audit-logs', { params })
  return data
}

// ------------------------------------------------------------ 渠道适配器
export async function listDescriptors(): Promise<AdapterDescriptor[]> {
  const { data } = await http.get<AdapterDescriptor[]>('/channel-adapters/descriptors')
  return data
}

export async function listChannelAdapters(channelId?: number): Promise<ChannelAdapter[]> {
  const { data } = await http.get<ChannelAdapter[]>('/channel-adapters', {
    params: channelId ? { channel_id: channelId } : {},
  })
  return data
}

export async function createChannelAdapter(payload: {
  channel_id: number
  adapter_key: string
  enabled?: boolean
  config?: Record<string, unknown>
  sync_interval_minutes?: number
  remark?: string
}): Promise<ChannelAdapter> {
  const { data } = await http.post<ChannelAdapter>('/channel-adapters', payload)
  return data
}

export async function updateChannelAdapter(
  id: number,
  payload: {
    adapter_key?: string
    enabled?: boolean
    config?: Record<string, unknown>
    sync_interval_minutes?: number
    remark?: string
  },
): Promise<ChannelAdapter> {
  const { data } = await http.put<ChannelAdapter>(`/channel-adapters/${id}`, payload)
  return data
}

export async function syncChannelAdapter(
  id: number,
  payload: Record<string, unknown>,
): Promise<AdapterSyncResult> {
  const { data } = await http.post<AdapterSyncResult>(`/channel-adapters/${id}/sync`, payload)
  return data
}
