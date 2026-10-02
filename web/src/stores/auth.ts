import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '@/api/auth'
import type { UserProfile } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => user.value !== null)
  const roles = computed(() => user.value?.roles ?? [])
  const displayName = computed(() => user.value?.full_name || user.value?.username || '未登录')

  function hasRole(...names: string[]): boolean {
    return names.some((name) => roles.value.includes(name))
  }

  /** 商品 / SKU / 组合商品维护 */
  function canManageProducts(): boolean {
    return hasRole('admin', 'owner', 'operator')
  }

  /** 仓库与库位配置 */
  function canManageWarehouse(): boolean {
    return hasRole('admin', 'owner')
  }

  /** 库存调整（仓内作业） */
  function canAdjustStock(): boolean {
    return hasRole('admin', 'owner', 'warehouse')
  }

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.login(username, password)
      user.value = response.user
    } finally {
      loading.value = false
    }
  }

  async function loadMe() {
    try {
      user.value = await authApi.fetchMe()
    } catch {
      user.value = null
    }
  }

  async function logout() {
    await authApi.logout()
    user.value = null
  }

  return {
    user,
    loading,
    isLoggedIn,
    roles,
    displayName,
    hasRole,
    canManageProducts,
    canManageWarehouse,
    canAdjustStock,
    login,
    loadMe,
    logout,
  }
})
