<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// Longest prefixes first so /orders/:id highlights 订单管理 rather than 订单导入.
const MENU_PREFIXES = [
  '/order-exceptions',
  '/order-import',
  '/purchase-orders',
  '/suppliers',
  '/transfers',
  '/channel-products',
  '/channel-adapters',
  '/channels',
  '/audit-logs',
  '/returns',
  '/stocktakes',
  '/replenish',
  '/alert-rules',
  '/alerts',
  '/notifications',
  '/reports',
  '/dashboard',
  '/orders',
  '/shipments',
  '/skus',
  '/products',
  '/inventory',
  '/bundles',
  '/warehouses',
]

const activeMenu = computed(() => {
  for (const prefix of MENU_PREFIXES) {
    if (route.path.startsWith(prefix)) {
      // /skus/:id belongs to the product section in the menu.
      return prefix === '/skus' ? '/products' : prefix
    }
  }
  return '/dashboard'
})

const roleText = computed(() => auth.roles.join(' / ') || '无角色')

async function onLogout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  await auth.logout()
  ElMessage.success('已退出')
  router.push({ name: 'login' })
}
</script>

<template>
  <el-container style="height: 100%">
    <el-header class="header">
      <div class="brand">OmniStock · 多渠道电商库存与采购协同平台</div>
      <div class="account">
        <span>{{ auth.displayName }}</span>
        <el-tag size="small" type="info">{{ roleText }}</el-tag>
        <el-button link type="primary" @click="onLogout">退出</el-button>
      </div>
    </el-header>
    <el-container>
      <el-aside width="200px" class="aside">
        <el-menu :default-active="activeMenu" router>
          <el-menu-item index="/dashboard">经营看板</el-menu-item>
          <el-menu-item index="/orders">订单管理</el-menu-item>
          <el-menu-item index="/order-import">订单导入</el-menu-item>
          <el-menu-item index="/order-exceptions">异常订单</el-menu-item>
          <el-menu-item index="/shipments">拣货发货</el-menu-item>
          <el-sub-menu index="purchase">
            <template #title>采购管理</template>
            <el-menu-item index="/purchase-orders">采购单与收货</el-menu-item>
            <el-menu-item index="/suppliers">供应商</el-menu-item>
          </el-sub-menu>
          <el-menu-item index="/transfers">仓库调拨</el-menu-item>
          <el-menu-item index="/products">商品管理</el-menu-item>
          <el-menu-item index="/inventory">库存总览</el-menu-item>
          <el-menu-item index="/bundles">组合商品</el-menu-item>
          <el-menu-item index="/warehouses">仓库与库位</el-menu-item>
          <el-sub-menu index="returns">
            <template #title>退货与盘点</template>
            <el-menu-item index="/returns">退货单</el-menu-item>
            <el-menu-item index="/stocktakes">盘点任务</el-menu-item>
          </el-sub-menu>
          <el-sub-menu index="alerts">
            <template #title>预警与补货</template>
            <el-menu-item index="/alerts">预警中心</el-menu-item>
            <el-menu-item index="/alert-rules">预警规则</el-menu-item>
            <el-menu-item index="/replenish">补货建议</el-menu-item>
          </el-sub-menu>
          <el-sub-menu index="channel">
            <template #title>渠道配置</template>
            <el-menu-item index="/channels">渠道与店铺</el-menu-item>
            <el-menu-item index="/channel-products">渠道商品映射</el-menu-item>
            <el-menu-item index="/channel-adapters">渠道适配器</el-menu-item>
          </el-sub-menu>
          <el-menu-item index="/reports">报表中心</el-menu-item>
          <el-menu-item index="/audit-logs">审计日志</el-menu-item>
          <el-menu-item index="/notifications">通知中心</el-menu-item>
        </el-menu>
        <div class="milestone">M8 · 全链路完成</div>
      </el-aside>
      <el-main>
        <slot />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border-bottom: 1px solid #e4e7ed;
}
.brand {
  font-size: 16px;
  font-weight: 600;
}
.account {
  display: flex;
  align-items: center;
  gap: 10px;
}
.aside {
  background: #ffffff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.milestone {
  padding: 12px 16px;
  font-size: 12px;
  color: #909399;
}
</style>
