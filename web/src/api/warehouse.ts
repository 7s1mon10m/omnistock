import http from './client'
import type { Page, Warehouse, WarehouseLocation } from '@/types'

export async function listWarehouses(params: { page_size?: number } = {}): Promise<Page<Warehouse>> {
  const { data } = await http.get<Page<Warehouse>>('/warehouses', {
    params: { page_size: 100, ...params },
  })
  return data
}

export async function createWarehouse(payload: Partial<Warehouse>): Promise<Warehouse> {
  const { data } = await http.post<Warehouse>('/warehouses', payload)
  return data
}

export async function updateWarehouse(id: number, payload: Partial<Warehouse>): Promise<Warehouse> {
  const { data } = await http.patch<Warehouse>(`/warehouses/${id}`, payload)
  return data
}

export async function listLocations(warehouseId: number): Promise<WarehouseLocation[]> {
  const { data } = await http.get<WarehouseLocation[]>(`/warehouses/${warehouseId}/locations`)
  return data
}

export async function createLocation(
  warehouseId: number,
  payload: { code: string; name?: string; zone?: string },
): Promise<WarehouseLocation> {
  const { data } = await http.post<WarehouseLocation>(
    `/warehouses/${warehouseId}/locations`,
    payload,
  )
  return data
}
