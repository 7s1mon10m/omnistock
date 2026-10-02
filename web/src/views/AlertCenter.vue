<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as alertApi from '@/api/alert'
import * as warehouseApi from '@/api/warehouse'
import {
  ALERT_STATUS_LABELS,
  ALERT_STATUS_TAG,
  ALERT_TYPE_LABELS,
  ALERT_TYPE_TAG,
  fmtDate,
  type AlertItem,
  type AlertStatus,
  type AlertType,
  type ScanResult,
  type Warehouse,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const rows = ref<AlertItem[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const scanning = ref(false)
const lastScan = ref<ScanResult | null>(null)

const query = reactive({
  status: undefined as AlertStatus | undefined,
  type: undefined as AlertType | undefined,
  warehouse_id: undefined as number | undefined,
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(ALERT_STATUS_LABELS) as [AlertStatus, string][]
const TYPE_OPTIONS = Object.entries(ALERT_TYPE_LABELS) as [AlertType, string][]

const openCount = computed(() => rows.value.filter((row) => row.status === 'open').length)

async function load() {
  loading.value = true
  try {
    const page = await alertApi.listAlerts(query)
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    lastScan.value = await alertApi.scanAlerts(query.warehouse_id)
    await load()
    const { alerts_created: created, resolved } = lastScan.value
    ElMessage.success(`扫描完成：新增 ${created} 条预警，自动关闭 ${resolved} 条`)
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    scanning.value = false
  }
}

async function ack(row: AlertItem) {
  try {
    await alertApi.ackAlert(row.id, '已确认')
    ElMessage.success('已确认')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function resolve(row: AlertItem) {
  try {
    await alertApi.resolveAlert(row.id)
    ElMessage.success('已关闭')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

function goSku(row: AlertItem) {
  router.push({ name: 'sku-detail', params: { id: row.sku_id } })
}

function reset() {
  query.status = undefined
  query.type = undefined
  query.warehouse_id = undefined
  query.page = 1
  void load()
}

onMounted(async () => {
  warehouses.value = (await warehouseApi.listWarehouses({ page_size: 200 })).items
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">
        预警中心
        <el-tag v-if="openCount" type="danger" size="small">{{ openCount }} 条待处理</el-tag>
      </span>
      <el-button type="primary" :loading="scanning" @click="scan">立即扫描</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      判定口径：<b>可售库存 + 在途库存 &lt; 安全库存</b>。在途已下单的货算作覆盖，
      所以「货在路上」不会误报。同一 SKU 未解决前只保留一条预警，补货到位后会自动关闭。
    </el-alert>

    <el-form :inline="true" class="filters">
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 120px">
          <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="query.type" clearable placeholder="全部" style="width: 120px">
          <el-option v-for="[value, label] in TYPE_OPTIONS" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库">
        <el-select v-model="query.warehouse_id" clearable placeholder="全部" style="width: 150px">
          <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="alert_no" label="预警号" width="130" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="ALERT_TYPE_TAG[row.type as AlertType] as never">
            {{ ALERT_TYPE_LABELS[row.type as AlertType] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="ALERT_STATUS_TAG[row.status as AlertStatus] as never">
            {{ ALERT_STATUS_LABELS[row.status as AlertStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sku_name" label="商品" min-width="160" show-overflow-tooltip />
      <el-table-column prop="warehouse_name" label="仓库" width="120" />
      <el-table-column label="可售" width="80" align="right">
        <template #default="{ row }">
          <span :class="{ danger: row.available_qty <= 0 }">{{ row.available_qty }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="in_transit_qty" label="在途" width="80" align="right" />
      <el-table-column prop="safety_qty" label="安全库存" width="90" align="right" />
      <el-table-column label="缺口" width="80" align="right">
        <template #default="{ row }">
          <b class="danger">{{ row.gap_qty }}</b>
        </template>
      </el-table-column>
      <el-table-column label="发现时间" width="150">
        <template #default="{ row }">{{ fmtDate(row.detected_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="goSku(row)">查看库存</el-button>
          <el-button v-if="row.status === 'open'" link type="warning" @click="ack(row)">确认</el-button>
          <el-button v-if="row.status !== 'resolved'" link @click="resolve(row)">关闭</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <span class="muted">暂无预警 —— 点「立即扫描」按当前安全库存检查一遍</span>
      </template>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.hint { margin-bottom: 12px; }
.filters { margin-bottom: 8px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.muted { color: #909399; }
.danger { color: #f56c6c; }
</style>
