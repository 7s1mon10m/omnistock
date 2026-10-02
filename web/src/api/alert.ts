import http from './client'
import type {
  AlertItem,
  AlertRule,
  AlertRuleScope,
  AlertStatus,
  AlertType,
  NotificationItem,
  NotificationSetting,
  Page,
  ReplenishSuggestion,
  ScanResult,
  SuggestionStatus,
} from '@/types'

// ------------------------------------------------------------------ 规则
export interface AlertRuleIn {
  name: string
  scope?: AlertRuleScope
  spu_id?: number | null
  sku_id?: number | null
  warehouse_id?: number | null
  threshold_qty?: number | null
  enabled?: boolean
  notify_channels?: string
  remark?: string
}

export async function listAlertRules(params: {
  scope?: AlertRuleScope
  enabled?: boolean
} = {}): Promise<AlertRule[]> {
  const { data } = await http.get<AlertRule[]>('/alert-rules', { params })
  return data
}

export async function createAlertRule(payload: AlertRuleIn): Promise<AlertRule> {
  const { data } = await http.post<AlertRule>('/alert-rules', payload)
  return data
}

export async function updateAlertRule(
  id: number,
  payload: { name?: string; threshold_qty?: number | null; enabled?: boolean; notify_channels?: string; remark?: string },
): Promise<AlertRule> {
  const { data } = await http.put<AlertRule>(`/alert-rules/${id}`, payload)
  return data
}

export async function deleteAlertRule(id: number): Promise<void> {
  await http.delete(`/alert-rules/${id}`)
}

// ------------------------------------------------------------------ 预警
export interface AlertQuery {
  status?: AlertStatus
  type?: AlertType
  warehouse_id?: number
  sku_id?: number
  page?: number
  page_size?: number
}

export async function listAlerts(params: AlertQuery = {}): Promise<Page<AlertItem>> {
  const { data } = await http.get<Page<AlertItem>>('/alerts', { params })
  return data
}

export async function scanAlerts(warehouseId?: number): Promise<ScanResult> {
  const { data } = await http.post<ScanResult>('/alerts/scan', null, {
    params: warehouseId ? { warehouse_id: warehouseId } : {},
  })
  return data
}

export async function ackAlert(id: number, remark = ''): Promise<AlertItem> {
  const { data } = await http.post<AlertItem>(`/alerts/${id}/ack`, { remark })
  return data
}

export async function resolveAlert(id: number): Promise<AlertItem> {
  const { data } = await http.post<AlertItem>(`/alerts/${id}/resolve`)
  return data
}

// ---------------------------------------------------------------- 补货建议
export interface SuggestionQuery {
  status?: SuggestionStatus
  warehouse_id?: number
  sku_id?: number
  page?: number
  page_size?: number
}

export async function listSuggestions(params: SuggestionQuery = {}): Promise<Page<ReplenishSuggestion>> {
  const { data } = await http.get<Page<ReplenishSuggestion>>('/replenishment-suggestions', { params })
  return data
}

export async function generateSuggestions(params: {
  warehouse_id?: number
  sku_id?: number
} = {}): Promise<ReplenishSuggestion[]> {
  const { data } = await http.post<ReplenishSuggestion[]>(
    '/replenishment-suggestions/generate',
    null,
    { params },
  )
  return data
}

export async function dismissSuggestion(id: number): Promise<ReplenishSuggestion> {
  const { data } = await http.post<ReplenishSuggestion>(
    `/replenishment-suggestions/${id}/dismiss`,
  )
  return data
}

export async function suggestionToPurchaseOrder(
  id: number,
  payload: { supplier_id?: number; warehouse_id?: number; quantity?: number; unit_price_cents?: number; remark?: string } = {},
): Promise<{ purchase_order: Record<string, unknown>; suggestion: ReplenishSuggestion }> {
  const { data } = await http.post(`/replenishment-suggestions/${id}/to-purchase-order`, payload)
  return data
}

// -------------------------------------------------------------------- 通知
export async function listNotifications(params: {
  category?: string
  is_read?: boolean
  page?: number
  page_size?: number
} = {}): Promise<Page<NotificationItem>> {
  const { data } = await http.get<Page<NotificationItem>>('/notifications', { params })
  return data
}

export async function unreadCount(): Promise<number> {
  const { data } = await http.get<{ unread: number }>('/notifications/unread-count')
  return data.unread
}

export async function markNotificationRead(id: number): Promise<NotificationItem> {
  const { data } = await http.post<NotificationItem>(`/notifications/${id}/read`)
  return data
}

export async function markAllRead(): Promise<number> {
  const { data } = await http.post<{ unread: number }>('/notifications/read-all')
  return data.unread
}

export async function listNotificationSettings(): Promise<NotificationSetting[]> {
  const { data } = await http.get<NotificationSetting[]>('/notifications/settings/all')
  return data
}

export async function updateNotificationSetting(
  channel: string,
  payload: { enabled?: boolean; config?: Record<string, unknown> },
): Promise<NotificationSetting> {
  const { data } = await http.put<NotificationSetting>(`/notifications/settings/${channel}`, payload)
  return data
}
