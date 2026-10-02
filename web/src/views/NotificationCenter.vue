<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as alertApi from '@/api/alert'
import {
  DELIVERY_STATUS_LABELS,
  DELIVERY_STATUS_TAG,
  NOTIFICATION_LEVEL_TAG,
  fmtDate,
  type DeliveryStatus,
  type NotificationItem,
  type NotificationLevel,
  type NotificationSetting,
} from '@/types'

const activeTab = ref('all')
const loading = ref(false)
const rows = ref<NotificationItem[]>([])
const total = ref(0)
const unread = ref(0)
const settings = ref<NotificationSetting[]>([])

const query = reactive({ page: 1, page_size: 15 })

const detailVisible = ref(false)
const current = ref<NotificationItem | null>(null)

async function load() {
  loading.value = true
  try {
    const params: alertApi.AlertQuery & { is_read?: boolean } = { ...query }
    if (activeTab.value === 'unread') params.is_read = false
    if (activeTab.value === 'alert') params.status = undefined
    const page = await alertApi.listNotifications(
      activeTab.value === 'alert' ? { ...query, category: 'alert' } : params,
    )
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function refreshBadge() {
  unread.value = await alertApi.unreadCount()
}

async function open(row: NotificationItem) {
  current.value = row
  detailVisible.value = true
  if (!row.is_read) {
    await alertApi.markNotificationRead(row.id)
    row.is_read = true
    await refreshBadge()
  }
}

async function markAll() {
  await alertApi.markAllRead()
  ElMessage.success('已全部标记为已读')
  await refreshBadge()
  await load()
}

async function loadSettings() {
  settings.value = await alertApi.listNotificationSettings()
}

async function toggleSetting(row: NotificationSetting) {
  try {
    await alertApi.updateNotificationSetting(row.channel, { enabled: !row.enabled })
    await loadSettings()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

onMounted(async () => {
  await Promise.all([load(), refreshBadge(), loadSettings()])
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">
        通知中心
        <el-badge v-if="unread" :value="unread" type="danger" />
      </span>
      <el-button :disabled="!unread" @click="markAll">全部已读</el-button>
    </div>

    <el-tabs v-model="activeTab" @tab-change="load">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="未读" name="unread" />
      <el-tab-pane label="库存预警" name="alert" />
      <el-tab-pane label="通道配置" name="settings" />
    </el-tabs>

    <template v-if="activeTab !== 'settings'">
      <el-table v-loading="loading" :data="rows" border @row-click="open">
        <el-table-column label="" width="50">
          <template #default="{ row }">
            <el-badge v-if="!row.is_read" is-dot type="danger" />
          </template>
        </el-table-column>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="NOTIFICATION_LEVEL_TAG[row.level as NotificationLevel] as never">
              {{ row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="100" />
        <el-table-column label="投递" width="220">
          <template #default="{ row }">
            <el-tag
              v-for="d in row.deliveries"
              :key="d.id"
              size="small"
              class="delivery"
              :type="DELIVERY_STATUS_TAG[d.status as DeliveryStatus] as never"
            >
              {{ d.channel }}·{{ DELIVERY_STATUS_LABELS[d.status as DeliveryStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <template #empty><span class="muted">暂无通知</span></template>
      </el-table>

      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        layout="total, prev, pager, next"
        class="pager"
        @current-change="load"
      />
    </template>

    <template v-else>
      <el-alert type="info" :closable="false" show-icon class="hint">
        站内消息始终开启，不依赖任何外部配置 —— 一个坏掉的 Webhook 不能让人看不到低库存预警。
      </el-alert>
      <el-table :data="settings" border>
        <el-table-column prop="channel" label="通道" width="120" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleSetting(row)" />
          </template>
        </el-table-column>
        <el-table-column label="配置" min-width="240">
          <template #default="{ row }">
            <span v-if="Object.keys(row.config || {}).length">{{ JSON.stringify(row.config) }}</span>
            <span v-else class="muted">未配置（Webhook 需填 endpoint）</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ fmtDate(row.updated_at) }}</template>
        </el-table-column>
      </el-table>
    </template>

    <el-dialog v-model="detailVisible" :title="current?.title ?? ''" width="560px">
      <p class="body">{{ current?.body }}</p>
      <el-divider content-position="left">投递明细</el-divider>
      <el-table :data="current?.deliveries ?? []" size="small" border>
        <el-table-column prop="channel" label="通道" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="DELIVERY_STATUS_TAG[row.status as DeliveryStatus] as never">
              {{ DELIVERY_STATUS_LABELS[row.status as DeliveryStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="尝试次数" width="90" align="right" />
        <el-table-column prop="response_code" label="响应码" width="80" />
        <el-table-column prop="last_error" label="错误" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.hint { margin-bottom: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.muted { color: #909399; }
.delivery { margin-right: 4px; }
.body { white-space: pre-wrap; color: #303133; margin: 0 0 8px; }
</style>
