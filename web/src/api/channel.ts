import http from './client'
import type { Channel, ChannelProduct, ChannelShop, Page } from '@/types'

// -------------------------------------------------------------------- channel
export async function listChannels(params: { page_size?: number } = {}): Promise<Page<Channel>> {
  const { data } = await http.get<Page<Channel>>('/channels', {
    params: { page_size: 100, ...params },
  })
  return data
}

export async function createChannel(payload: Partial<Channel>): Promise<Channel> {
  const { data } = await http.post<Channel>('/channels', payload)
  return data
}

export async function updateChannel(id: number, payload: Partial<Channel>): Promise<Channel> {
  const { data } = await http.patch<Channel>(`/channels/${id}`, payload)
  return data
}

// ----------------------------------------------------------------------- shop
export async function listShops(channelId: number): Promise<ChannelShop[]> {
  const { data } = await http.get<ChannelShop[]>(`/channels/${channelId}/shops`)
  return data
}

export async function createShop(
  channelId: number,
  payload: { code: string; name?: string; remark?: string },
): Promise<ChannelShop> {
  const { data } = await http.post<ChannelShop>(`/channels/${channelId}/shops`, payload)
  return data
}

// ----------------------------------------------------------- product mapping
export interface MappingQuery {
  channel_id?: number
  sku_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export async function listMappings(params: MappingQuery = {}): Promise<Page<ChannelProduct>> {
  const { data } = await http.get<Page<ChannelProduct>>('/channel-products', { params })
  return data
}

export async function createMapping(payload: {
  channel_id: number
  shop_id?: number | null
  channel_product_code: string
  sku_id: number
  channel_title?: string
  remark?: string
}): Promise<ChannelProduct> {
  const { data } = await http.post<ChannelProduct>('/channel-products', payload)
  return data
}

export async function updateMapping(
  id: number,
  payload: Partial<ChannelProduct>,
): Promise<ChannelProduct> {
  const { data } = await http.patch<ChannelProduct>(`/channel-products/${id}`, payload)
  return data
}

export async function deleteMapping(id: number): Promise<void> {
  await http.delete(`/channel-products/${id}`)
}
