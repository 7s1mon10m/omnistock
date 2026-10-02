import http from './client'
import type { Barcode, Bundle, Page, Sku, Spu } from '@/types'

// ------------------------------------------------------------------------ SPU
export interface SpuQuery {
  keyword?: string
  status?: string
  type?: string
  page?: number
  page_size?: number
}

export async function listSpus(params: SpuQuery = {}): Promise<Page<Spu>> {
  const { data } = await http.get<Page<Spu>>('/spus', { params })
  return data
}

export async function createSpu(payload: Partial<Spu>): Promise<Spu> {
  const { data } = await http.post<Spu>('/spus', payload)
  return data
}

export async function getSpu(id: number): Promise<Spu> {
  const { data } = await http.get<Spu>(`/spus/${id}`)
  return data
}

export async function updateSpu(id: number, payload: Partial<Spu>): Promise<Spu> {
  const { data } = await http.patch<Spu>(`/spus/${id}`, payload)
  return data
}

// ------------------------------------------------------------------------ SKU
export interface SkuQuery {
  spu_id?: number
  keyword?: string
  status?: string
  page?: number
  page_size?: number
}

export async function listSkus(params: SkuQuery = {}): Promise<Page<Sku>> {
  const { data } = await http.get<Page<Sku>>('/skus', { params })
  return data
}

export interface SkuPayload {
  spu_id: number
  sku_code?: string
  spec_json?: Record<string, unknown>
  barcode?: string
  weight_g?: number
  package_spec?: string
  purchase_price_cents?: number
  safety_qty?: number
}

export async function createSku(payload: SkuPayload): Promise<Sku> {
  const { data } = await http.post<Sku>('/skus', payload)
  return data
}

export async function getSku(id: number): Promise<Sku> {
  const { data } = await http.get<Sku>(`/skus/${id}`)
  return data
}

export async function updateSku(id: number, payload: Partial<Sku>): Promise<Sku> {
  const { data } = await http.patch<Sku>(`/skus/${id}`, payload)
  return data
}

export async function resolveBarcode(barcode: string): Promise<Sku> {
  const { data } = await http.get<Sku>('/skus/resolve', { params: { barcode } })
  return data
}

// ------------------------------------------------------------------- barcodes
export async function listBarcodes(skuId: number): Promise<Barcode[]> {
  const { data } = await http.get<Barcode[]>(`/skus/${skuId}/barcodes`)
  return data
}

export async function addBarcode(
  skuId: number,
  payload: { barcode: string; is_primary?: boolean; remark?: string },
): Promise<Barcode> {
  const { data } = await http.post<Barcode>(`/skus/${skuId}/barcodes`, payload)
  return data
}

export async function deleteBarcode(skuId: number, barcodeId: number): Promise<void> {
  await http.delete(`/skus/${skuId}/barcodes/${barcodeId}`)
}

// -------------------------------------------------------------------- bundles
export async function getBundle(bundleSkuId: number, warehouseId?: number): Promise<Bundle> {
  const { data } = await http.get<Bundle>(`/bundles/${bundleSkuId}`, {
    params: warehouseId ? { warehouse_id: warehouseId } : {},
  })
  return data
}

export async function setBundleComponents(
  bundleSkuId: number,
  components: { component_sku_id: number; quantity: number }[],
  warehouseId?: number,
): Promise<Bundle> {
  const { data } = await http.put<Bundle>(
    `/bundles/${bundleSkuId}/components`,
    { components },
    { params: warehouseId ? { warehouse_id: warehouseId } : {} },
  )
  return data
}
