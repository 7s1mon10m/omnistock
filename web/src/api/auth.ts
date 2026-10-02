import http, { tokenStore } from './client'
import type { LoginResponse, TokenPair, UserProfile } from '@/types'

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/login', { username, password })
  tokenStore.set(data.access_token, data.refresh_token)
  return data
}

export async function fetchMe(): Promise<UserProfile> {
  const { data } = await http.get<UserProfile>('/auth/me')
  return data
}

export async function refresh(): Promise<TokenPair> {
  const { data } = await http.post<TokenPair>('/auth/refresh', {
    refresh_token: tokenStore.refresh,
  })
  tokenStore.set(data.access_token, data.refresh_token)
  return data
}

export async function logout(): Promise<void> {
  try {
    await http.post('/auth/logout', { refresh_token: tokenStore.refresh })
  } finally {
    tokenStore.clear()
  }
}
