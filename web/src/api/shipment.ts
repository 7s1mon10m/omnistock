import http from './client'
import type {
  Page,
  PickRecord,
  PickResult,
  Shipment,
  ShipmentActionResult,
  ShipmentListItem,
  ShipmentStatus,
} from '@/types'

export interface ShipmentQuery {
  status?: ShipmentStatus
  warehouse_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export async function listShipments(params: ShipmentQuery = {}): Promise<Page<ShipmentListItem>> {
  const { data } = await http.get<Page<ShipmentListItem>>('/shipments', { params })
  return data
}

export async function createShipment(orderId: number, remark = ''): Promise<Shipment> {
  const { data } = await http.post<Shipment>('/shipments', { order_id: orderId, remark })
  return data
}

export async function getShipment(id: number): Promise<Shipment> {
  const { data } = await http.get<Shipment>(`/shipments/${id}`)
  return data
}

export async function claimShipment(id: number, pickerId?: number): Promise<Shipment> {
  const { data } = await http.post<Shipment>(`/shipments/${id}/claim`, {
    picker_id: pickerId ?? null,
  })
  return data
}

/** One scan. Rejections come back as a 200 with ``accepted: false``. */
export async function pickBarcode(
  id: number,
  barcode: string,
  quantity = 1,
): Promise<PickResult> {
  const { data } = await http.post<PickResult>(`/shipments/${id}/pick`, { barcode, quantity })
  return data
}

export async function pickManual(
  id: number,
  shipmentItemId: number,
  quantity: number,
): Promise<PickResult> {
  const { data } = await http.post<PickResult>(`/shipments/${id}/pick-manual`, {
    shipment_item_id: shipmentItemId,
    quantity,
  })
  return data
}

export async function packShipment(
  id: number,
  payload: { package_count?: number; weight_g?: number; remark?: string } = {},
): Promise<Shipment> {
  const { data } = await http.post<Shipment>(`/shipments/${id}/pack`, {
    package_count: 1,
    weight_g: 0,
    ...payload,
  })
  return data
}

export async function shipShipment(
  id: number,
  payload: { carrier?: string; tracking_no?: string; remark?: string } = {},
): Promise<ShipmentActionResult> {
  const { data } = await http.post<ShipmentActionResult>(`/shipments/${id}/ship`, payload)
  return data
}

export async function cancelShipment(id: number, reason = ''): Promise<Shipment> {
  const { data } = await http.post<Shipment>(`/shipments/${id}/cancel`, { reason })
  return data
}

export async function listPickRecords(
  id: number,
  params: { page?: number; page_size?: number } = {},
): Promise<Page<PickRecord>> {
  const { data } = await http.get<Page<PickRecord>>(`/shipments/${id}/pick-records`, { params })
  return data
}

export async function setStockLocation(
  skuId: number,
  warehouseId: number,
  locationId: number | null,
): Promise<unknown> {
  const { data } = await http.patch('/inventory/location', {
    sku_id: skuId,
    warehouse_id: warehouseId,
    location_id: locationId,
  })
  return data
}

export async function listLocations(warehouseId: number) {
  const { data } = await http.get(`/warehouses/${warehouseId}/locations`)
  return data
}
