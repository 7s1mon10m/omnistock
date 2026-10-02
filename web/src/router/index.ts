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
    { path: '/', redirect: '/orders' },
    {
      path: '/orders',
      name: 'orders',
      component: () => import('@/views/OrderList.vue'),
    },
    {
      path: '/orders/:id',
      name: 'order-detail',
      component: () => import('@/views/OrderDetail.vue'),
      props: true,
    },
    {
      path: '/order-import',
      name: 'order-import',
      component: () => import('@/views/OrderImport.vue'),
    },
    {
      path: '/order-exceptions',
      name: 'order-exceptions',
      component: () => import('@/views/OrderExceptions.vue'),
    },
    {
      path: '/channels',
      name: 'channels',
      component: () => import('@/views/ChannelConfig.vue'),
    },
    {
      path: '/channel-products',
      name: 'channel-products',
      component: () => import('@/views/ChannelProducts.vue'),
    },
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
    return { name: 'orders' }
  }
  return true
})

export default router
