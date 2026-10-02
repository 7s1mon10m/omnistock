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
    { path: '/', redirect: '/dashboard' },
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
      path: '/shipments',
      name: 'shipments',
      component: () => import('@/views/ShipmentList.vue'),
    },
    {
      path: '/shipments/:id',
      name: 'shipment-detail',
      component: () => import('@/views/ShipmentDetail.vue'),
      props: true,
    },
    {
      path: '/transfers',
      name: 'transfers',
      component: () => import('@/views/TransferList.vue'),
    },
    {
      path: '/transfers/:id',
      name: 'transfer-detail',
      component: () => import('@/views/TransferDetail.vue'),
      props: true,
    },
    {
      path: '/suppliers',
      name: 'suppliers',
      component: () => import('@/views/SupplierList.vue'),
    },
    {
      path: '/purchase-orders',
      name: 'purchase-orders',
      component: () => import('@/views/PurchaseOrderList.vue'),
    },
    {
      path: '/purchase-orders/:id',
      name: 'purchase-detail',
      component: () => import('@/views/PurchaseOrderDetail.vue'),
      props: true,
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

    // ------------------------------------------------------------ M6 预警
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      path: '/alerts',
      name: 'alerts',
      component: () => import('@/views/AlertCenter.vue'),
    },
    {
      path: '/alert-rules',
      name: 'alert-rules',
      component: () => import('@/views/AlertRules.vue'),
    },
    {
      path: '/replenish',
      name: 'replenish',
      component: () => import('@/views/ReplenishSuggestions.vue'),
    },
    {
      path: '/notifications',
      name: 'notifications',
      component: () => import('@/views/NotificationCenter.vue'),
    },

    // -------------------------------------------------------- M7 退货盘点
    {
      path: '/returns',
      name: 'returns',
      component: () => import('@/views/ReturnOrderList.vue'),
    },
    {
      path: '/returns/:id',
      name: 'return-detail',
      component: () => import('@/views/ReturnDetail.vue'),
      props: true,
    },
    {
      path: '/stocktakes',
      name: 'stocktakes',
      component: () => import('@/views/StocktakeList.vue'),
    },
    {
      path: '/stocktakes/:id',
      name: 'stocktake-detail',
      component: () => import('@/views/StocktakeDetail.vue'),
      props: true,
    },

    // -------------------------------------------------------- M8 报表审计
    {
      path: '/reports',
      name: 'reports',
      component: () => import('@/views/ReportCenter.vue'),
    },
    {
      path: '/channel-adapters',
      name: 'channel-adapters',
      component: () => import('@/views/ChannelAdapters.vue'),
    },
    {
      path: '/audit-logs',
      name: 'audit-logs',
      component: () => import('@/views/AuditLogs.vue'),
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
