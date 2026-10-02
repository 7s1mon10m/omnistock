<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as orderApi from '@/api/order'
import { useAuthStore } from '@/stores/auth'
import type { OrderException } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<OrderException[]>([])
const total = ref(0)
const query = reactive({
  status: 'open' as string,
  type: '' as string,
  page: 1,
  page_size: 15,
})

const TYPE_LABELS: Record<string, string> = {
  stock_shortage: '库存不足',
  mapping_missing: '缺少映射',
  other: '其他',
}

async function load() {
  loading.value = true
  try {
    const data = await orderApi.listExceptions({
      status: query.status || undefined,
      type: query.type || undefined,
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

function resetAndLoad() {
  query.page = 1
  load()
}

async function retry(row: OrderException) {
  try {
    const result = await orderApi.retryReserve(row.order_id)
    ElMessage.success(result.message || '已重试')
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openOrder(orderId: number) {
  router.push({ name: 'order-detail', params: { id: orderId } })
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      title="缺货、映射缺失等导致无法履约的订单会出现在这里。补货后点「重新占用」即可续上，不必重新导入订单。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <div class="toolbar">
      <el-select v-model="query.status" style="width: 140px" @change="resetAndLoad">
        <el-option label="待处理" value="open" />
        <el-option label="已解决" value="resolved" />
        <el-option label="已忽略" value="ignored" />
        <el-option label="全部" value="" />
      </el-select>
      <el-select v-model="query.type" clearable placeholder="全部类型" style="width: 150px" @change="resetAndLoad">
        <el-option label="库存不足" value="stock_shortage" />
        <el-option label="缺少映射" value="mapping_missing" />
        <el-option label="其他" value="other" />
      </el-select>
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="created_at" label="时间" width="170">
        <template #default="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
      </el-table-column>
      <el-table-column label="订单" width="150">
        <template #default="{ row }">
          <el-button link type="primary" @click="openOrder(row.order_id)">
            {{ row.order_no || row.order_id }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="channel_order_no" label="渠道单号" width="180" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" type="warning">{{ TYPE_LABELS[row.type] ?? row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="SKU" min-width="200">
        <template #default="{ row }">
          <div>{{ row.sku_code || '—' }}</div>
          <div class="muted">{{ row.sku_name }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="required_qty" label="需要" width="80" align="right" />
      <el-table-column prop="available_qty" label="可售" width="80" align="right" />
      <el-table-column label="缺口" width="80" align="right">
        <template #default="{ row }">
          <b class="bad">{{ row.shortage_qty }}</b>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="说明" min-width="200" />
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="auth.canManageProducts() && row.status === 'open'"
            link
            type="primary"
            @click="retry(row)"
          >
            重新占用
          </el-button>
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
.bad {
  color: #f56c6c;
}
.muted {
  font-size: 12px;
  color: #909399;
}
</style>
