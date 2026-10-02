<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as reportApi from '@/api/report'
import { yuan, type ChannelSalesRow, type DashboardSummary, type SupplierOnTimeRow } from '@/types'

const router = useRouter()
const loading = ref(false)
const days = ref(30)
const summary = ref<DashboardSummary | null>(null)
const channelRows = ref<ChannelSalesRow[]>([])
const onTime = ref<SupplierOnTimeRow[]>([])

const RANGE_OPTIONS = [
  { label: '近 7 天', value: 7 },
  { label: '近 30 天', value: 30 },
  { label: '近 90 天', value: 90 },
]

const cards = computed(() => {
  const data = summary.value
  if (!data) return []
  return [
    { label: '在库件数', value: String(data.total_on_hand), hint: '所有仓库实际库存合计' },
    { label: '可售件数', value: String(data.total_available), hint: '已扣除占用与安全库存' },
    { label: '库存金额', value: yuan(data.total_stock_value_cents), hint: '按采购价估算' },
    { label: '待处理订单', value: String(data.open_orders), hint: '未发货的订单数' },
    { label: '库存预警', value: String(data.open_alerts), hint: '未关闭的低库存预警', danger: data.open_alerts > 0 },
    { label: '异常订单', value: String(data.open_exceptions), hint: '缺货等异常，需处理', danger: data.open_exceptions > 0 },
    { label: '低库存 SKU', value: String(data.low_stock_count), hint: '可售 + 在途 < 安全库存', danger: data.low_stock_count > 0 },
    { label: '待审核盘点', value: String(data.pending_stocktakes), hint: '盘点中或待审核' },
  ]
})

// 渠道销量柱状图（纯 SVG，避免为一个图表引入整个图表库）
const bars = computed(() => {
  const rows = channelRows.value
  if (!rows.length) return []
  const max = Math.max(...rows.map((row) => row.total_amount_cents), 1)
  return rows.slice(0, 12).map((row) => ({
    label: row.channel_name || row.channel_code,
    amount: row.total_amount_cents,
    orders: row.order_count,
    // 最少留 4% 的高度，否则小额渠道会看不见
    height: Math.max(4, Math.round((row.total_amount_cents / max) * 100)),
  }))
})

const onTimeBars = computed(() =>
  onTime.value.map((row) => ({
    label: row.supplier_name,
    rate: row.on_time_rate,
    width: Math.round(row.on_time_rate * 100),
    total: row.total_batches,
  })),
)

async function load() {
  loading.value = true
  try {
    const params = { days: days.value }
    const [dash, sales, suppliers] = await Promise.all([
      reportApi.dashboard(params),
      reportApi.channelSales(params),
      reportApi.supplierOnTime(),
    ])
    summary.value = dash
    channelRows.value = sales
    onTime.value = suppliers
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page">
    <div class="toolbar">
      <span class="title">经营看板</span>
      <el-select v-model="days" style="width: 120px" @change="load">
        <el-option v-for="opt in RANGE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>

    <div class="cards">
      <el-card v-for="card in cards" :key="card.label" shadow="hover" class="card">
        <div class="card-label">{{ card.label }}</div>
        <div class="card-value" :class="{ danger: card.danger }">{{ card.value }}</div>
        <div class="card-hint">{{ card.hint }}</div>
      </el-card>
    </div>

    <div class="charts">
      <el-card shadow="never" class="chart">
        <template #header>
          <span class="chart-title">渠道销量对比</span>
          <el-button link type="primary" @click="router.push('/reports')">看报表</el-button>
        </template>
        <div v-if="bars.length" class="bars">
          <div v-for="bar in bars" :key="bar.label" class="bar-item">
            <div class="bar-track">
              <div class="bar-fill" :style="{ height: `${bar.height}%` }" />
            </div>
            <div class="bar-label">{{ bar.label }}</div>
            <div class="bar-value">{{ yuan(bar.amount) }}</div>
          </div>
        </div>
        <el-empty v-else description="所选区间内没有已付款订单" :image-size="60" />
      </el-card>

      <el-card shadow="never" class="chart">
        <template #header><span class="chart-title">供应商交付及时率</span></template>
        <div v-if="onTimeBars.length" class="rates">
          <div v-for="row in onTimeBars" :key="row.label" class="rate-row">
            <span class="rate-label">{{ row.label }}</span>
            <div class="rate-track">
              <div class="rate-fill" :class="{ low: row.rate < 0.8 }" :style="{ width: `${row.width}%` }" />
            </div>
            <span class="rate-value">{{ (row.rate * 100).toFixed(0) }}%</span>
            <span class="rate-total">{{ row.total }} 批</span>
          </div>
        </div>
        <el-empty v-else description="还没有已到货的采购批次" :image-size="60" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; }

.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.card-label { color: #909399; font-size: 13px; }
.card-value { font-size: 24px; font-weight: 600; margin: 4px 0; }
.card-value.danger { color: #f56c6c; }
.card-hint { color: #c0c4cc; font-size: 12px; }

.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.chart-title { font-weight: 600; }

.bars { display: flex; align-items: flex-end; gap: 12px; height: 220px; padding-top: 8px; }
.bar-item { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.bar-track { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
.bar-fill { width: 60%; background: #409eff; border-radius: 3px 3px 0 0; }
.bar-label { font-size: 12px; color: #606266; margin-top: 6px; text-align: center; }
.bar-value { font-size: 11px; color: #909399; }

.rates { display: flex; flex-direction: column; gap: 10px; min-height: 180px; }
.rate-row { display: flex; align-items: center; gap: 10px; }
.rate-label { width: 110px; font-size: 13px; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rate-track { flex: 1; background: #f0f2f5; border-radius: 4px; height: 12px; }
.rate-fill { height: 100%; background: #67c23a; border-radius: 4px; }
.rate-fill.low { background: #e6a23c; }
.rate-value { width: 44px; text-align: right; font-size: 13px; font-weight: 600; }
.rate-total { width: 50px; color: #909399; font-size: 12px; }

@media (max-width: 1200px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
  .charts { grid-template-columns: 1fr; }
}
</style>
