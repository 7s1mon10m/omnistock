<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as channelApi from '@/api/channel'
import * as orderApi from '@/api/order'
import { useAuthStore } from '@/stores/auth'
import {
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TAG,
  yuan,
  type Channel,
  type OrderStatus,
  type OrderSummary,
} from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<OrderSummary[]>([])
const total = ref(0)
const channels = ref<Channel[]>([])
const query = reactive({
  channel_id: undefined as number | undefined,
  status: undefined as OrderStatus | undefined,
  keyword: '',
  only_exception: false,
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(ORDER_STATUS_LABELS) as [OrderStatus, string][]

async function load() {
  loading.value = true
  try {
    const data = await orderApi.listOrders({
      channel_id: query.channel_id,
      status: query.status,
      keyword: query.keyword || undefined,
      only_exception: query.only_exception || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function loadChannels() {
  try {
    channels.value = (await channelApi.listChannels()).items
  } catch {
    channels.value = []
  }
}

function resetAndLoad() {
  query.page = 1
  load()
}

function openDetail(row: OrderSummary) {
  router.push({ name: 'order-detail', params: { id: row.id } })
}

async function act(row: OrderSummary, action: 'pay' | 'cancel' | 'retry') {
  try {
    if (action === 'cancel') {
      await ElMessageBox.confirm('取消订单会释放已占用的库存，确认？', '提示', { type: 'warning' })
    }
    const result =
      action === 'pay'
        ? await orderApi.markPaid(row.id)
        : action === 'cancel'
          ? await orderApi.cancelOrder(row.id, '运营手动取消')
          : await orderApi.retryReserve(row.id)
    ElMessage.success(result.message || '操作完成')
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(async () => {
  await loadChannels()
  await load()
})
</script>

<template>
  <div>
    <div class="toolbar">
      <el-select
        v-model="query.channel_id"
        placeholder="全部渠道"
        clearable
        style="width: 160px"
        @change="resetAndLoad"
      >
        <el-option
          v-for="channel in channels"
          :key="channel.id"
          :label="channel.name"
          :value="channel.id"
        />
      </el-select>
      <el-select
        v-model="query.status"
        placeholder="全部状态"
        clearable
        style="width: 150px"
        @change="resetAndLoad"
      >
        <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="内部单号 / 渠道单号 / 买家"
        clearable
        style="width: 240px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <el-checkbox v-model="query.only_exception" @change="resetAndLoad">只看异常</el-checkbox>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="order_no" label="内部单号" width="140" />
      <el-table-column label="渠道" width="140">
        <template #default="{ row }">
          <div>{{ row.channel_code }}</div>
          <div class="muted">{{ row.shop_code || '—' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="channel_order_no" label="渠道单号" width="180" />
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-tag :type="ORDER_STATUS_TAG[row.status as OrderStatus]" size="small">
            {{ ORDER_STATUS_LABELS[row.status as OrderStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="buyer_nick" label="买家" width="110" />
      <el-table-column label="件数" width="80" align="right">
        <template #default="{ row }">{{ row.total_quantity }}</template>
      </el-table-column>
      <el-table-column label="金额" width="110" align="right">
        <template #default="{ row }">{{ yuan(row.total_amount_cents) }}</template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_bundle" size="small" type="warning">含套装</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="100">
        <template #default="{ row }">
          {{ row.source === 'import_csv' ? 'CSV 导入' : row.source === 'import_json' ? 'JSON 导入' : row.source }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <template v-if="auth.canManageProducts()">
            <el-button
              v-if="row.status === 'pending_payment'"
              link
              type="primary"
              @click="act(row, 'pay')"
            >
              标记付款
            </el-button>
            <el-button
              v-if="row.status === 'exception'"
              link
              type="warning"
              @click="act(row, 'retry')"
            >
              重新占用
            </el-button>
            <el-button
              v-if="['pending_payment', 'pending_fulfillment', 'reserved', 'exception'].includes(row.status)"
              link
              type="danger"
              @click="act(row, 'cancel')"
            >
              取消
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      :current-page="query.page"
      :page-size="query.page_size"
      @current-change="
        (page: number) => {
          query.page = page
          load()
        }
      "
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.muted {
  font-size: 12px;
  color: #909399;
}
</style>
