import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { public: true },
    },
    { path: '/', redirect: '/products' },
    {
      path: '/products',
      name: 'products',
      component: () => import('@/views/ProductList.vue'),
    },
    {
      path: '/skus/:id',
      name: 'sku-detail',
      component: () => import('@/views/SkuDetail.vue'),
      props: true,
    },
    {
      path: '/inventory',
      name: 'inventory',
      component: () => import('@/views/InventoryList.vue'),
    },
    {
      path: '/bundles',
      name: 'bundles',
      component: () => import('@/views/BundleConfig.vue'),
    },
    {
      path: '/warehouses',
      name: 'warehouses',
      component: () => import('@/views/WarehouseManage.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.isLoggedIn) {
    await auth.loadMe()
  }
  if (to.meta.public) {
    return true
  }
  if (!auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  const required = to.meta.roles as string[] | undefined
  if (required && !required.some((role) => auth.hasRole(role))) {
    return { name: 'products' }
  }
  return true
})

export default router
