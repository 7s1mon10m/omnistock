import axios, { AxiosError } from 'axios'
import type { ApiErrorBody } from '@/types'

const TOKEN_KEY = 'omnistock.access_token'
const REFRESH_KEY = 'omnistock.refresh_token'

export const tokenStore = {
  get access() {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY) ?? ''
  },
  set(access: string, refresh: string) {
    localStorage.setItem(TOKEN_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const token = tokenStore.access
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** Normalise every backend failure into a readable Chinese message. */
export function describeError(error: unknown): string {
  if (error instanceof AxiosError) {
    const body = error.response?.data as ApiErrorBody | undefined
    if (body?.message) {
      return `${body.message}（错误码 ${body.code}）`
    }
    if (error.response?.status === 401) return '未登录或登录已过期'
    if (error.response?.status === 403) return '没有执行该操作的权限'
    if (error.response?.status === 404) return '资源不存在'
    if (!error.response) return '无法连接服务器'
  }
  return '请求失败'
}

export default http
