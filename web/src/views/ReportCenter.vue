<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as reportApi from '@/api/report'
import type { Granularity } from '@/api/report'
import { fmtDate, yuan } from '@/types'

type ReportKey =
  | 'sku-stock'
  | 'turnover'
  | 'supplier-ontime'
  | 'channel-sales'
  | 'stockout'
  | 'return-rate'
  | 'slow-moving'
  | 'purchase-amount'
  | 'stocktake-variance'
  | 'low-stock'

interface ReportDef {
  key: ReportKey
  label: string
  columns: { prop: string; label: string; width?: number; align?: string }[]
  needsRange: boolean
}

const REPORTS: ReportDef[] = [
  {
    key: 'sku-stock',
    label: 'SKU 库存',
    needsRange: false,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'warehouse_name', label: '仓库', width: 120 },
      { prop: 'on_hand_qty', label: '实际', width: 80, align: 'right' },
      { prop: 'reserved_qty', label: '占用', width: 80, align: 'right' },
      { prop: 'in_transit_qty', label: '在途', width: 80, align: 'right' },
      { prop: 'safety_qty', label: '安全', width: 80, align: 'right' },
      { prop: 'available_qty', label: '可售', width: 80, align: 'right' },
      { prop: 'location_code', label: '库位', width: 100 },
    ],
  },
  {
    key: 'turnover',
    label: '库存周转',
    needsRange: true,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'sold_qty', label: '销量', width: 90, align: 'right' },
      { prop: 'avg_daily_sales', label: '日均', width: 90, align: 'right' },
      { prop: 'average_stock', label: '平均库存', width: 100, align: 'right' },
      { prop: 'turnover_days', label: '周转天数', width: 100, align: 'right' },
    ],
  },
  {
    key: 'supplier-ontime',
    label: '供应商及时率',
    needsRange: false,
    columns: [
      { prop: 'supplier_name', label: '供应商' },
      { prop: 'total_batches', label: '总批次', width: 100, align: 'right' },
      { prop: 'on_time_batches', label: '按期', width: 90, align: 'right' },
      { prop: 'late_batches', label: '延误', width: 90, align: 'right' },
      { prop: 'on_time_rate', label: '及时率', width: 100, align: 'right' },
      { prop: 'avg_delay_days', label: '平均延误', width: 110, align: 'right' },
    ],
  },
  {
    key: 'channel-sales',
    label: '渠道销量',
    needsRange: true,
    columns: [
      { prop: 'bucket', label: '时间', width: 130 },
      { prop: 'channel_name', label: '渠道' },
      { prop: 'order_count', label: '订单数', width: 90, align: 'right' },
      { prop: 'item_quantity', label: '件数', width: 90, align: 'right' },
      { prop: 'total_amount_cents', label: '金额', width: 120, align: 'right' },
    ],
  },
  {
    key: 'stockout',
    label: '缺货统计',
    needsRange: true,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'stockout_count', label: '缺货次数', width: 110, align: 'right' },
      { prop: 'shortage_qty', label: '缺口', width: 90, align: 'right' },
      { prop: 'last_stockout_at', label: '最近缺货', width: 160 },
    ],
  },
  {
    key: 'return-rate',
    label: '退货率',
    needsRange: true,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'sold_qty', label: '净销量', width: 100, align: 'right' },
      { prop: 'returned_qty', label: '退货量', width: 100, align: 'right' },
      { prop: 'return_rate', label: '退货率', width: 100, align: 'right' },
    ],
  },
  {
    key: 'slow-moving',
    label: '滞销商品',
    needsRange: true,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'warehouse_code', label: '仓库', width: 110 },
      { prop: 'on_hand_qty', label: '库存', width: 90, align: 'right' },
      { prop: 'idle_days', label: '闲置天数', width: 110, align: 'right' },
    ],
  },
  {
    key: 'purchase-amount',
    label: '采购金额',
    needsRange: true,
    columns: [
      { prop: 'bucket', label: '时间', width: 130 },
      { prop: 'supplier_name', label: '供应商' },
      { prop: 'order_count', label: '采购单数', width: 110, align: 'right' },
      { prop: 'total_amount_cents', label: '金额', width: 130, align: 'right' },
    ],
  },
  {
    key: 'stocktake-variance',
    label: '盘点差异',
    needsRange: false,
    columns: [
      { prop: 'warehouse_name', label: '仓库' },
      { prop: 'total_lines', label: '盘点行', width: 100, align: 'right' },
      { prop: 'variance_lines', label: '差异行', width: 100, align: 'right' },
      { prop: 'gain_qty', label: '盘盈', width: 90, align: 'right' },
      { prop: 'loss_qty', label: '盘亏', width: 90, align: 'right' },
      { prop: 'net_qty', label: '净差异', width: 90, align: 'right' },
    ],
  },
  {
    key: 'low-stock',
    label: '低库存清单',
    needsRange: false,
    columns: [
      { prop: 'sku_code', label: 'SKU', width: 150 },
      { prop: 'sku_name', label: '商品' },
      { prop: 'warehouse_name', label: '仓库', width: 120 },
      { prop: 'available_qty', label: '可售', width: 90, align: 'right' },
      { prop: 'in_transit_qty', label: '在途', width: 90, align: 'right' },
      { prop: 'safety_qty', label: '安全', width: 90, align: 'right' },
      { prop: 'gap_qty', label: '缺口', width: 90, align: 'right' },
    ],
  },
]

const active = ref<ReportKey>('sku-stock')
const loading = ref(false)
const rows = ref<Record<string, unknown>[]>([])
const days = ref(30)
const granularity = ref<Granularity>('day')

const current = computed(() => REPORTS.find((item) => item.key === active.value) as ReportDef)

const params = computed(() => ({
  days: days.value,
  granularity: granularity.value,
}))

async function load() {
  loading.value = true
  try {
    const opts = params.value
    let data: Record<string, unknown>[]
    switch (active.value) {
      case 'sku-stock':
        data = (await reportApi.skuStock()) as unknown as Record<string, unknown>[]
        break
      case 'turnover':
        data = (await reportApi.turnover({ days: days.value })) as unknown as Record<string, unknown>[]
        break
      case 'supplier-ontime':
        data = (await reportApi.supplierOnTime()) as unknown as Record<string, unknown>[]
        break
      case 'channel-sales':
        data = (await reportApi.channelSales(opts)) as unknown as Record<string, unknown>[]
        break
      case 'stockout':
        data = (await reportApi.stockout({ days: days.value })) as unknown as Record<string, unknown>[]
        break
      case 'return-rate':
        data = (await reportApi.returnRate({ days: days.value })) as unknown as Record<string, unknown>[]
        break
      case 'slow-moving':
        data = (await reportApi.slowMoving({ days: days.value })) as unknown as Record<string, unknown>[]
        break
      case 'purchase-amount':
        data = (await reportApi.purchaseAmount(opts)) as unknown as Record<string, unknown>[]
        break
      case 'stocktake-variance':
        data = (await reportApi.stocktakeVariance()) as unknown as Record<string, unknown>[]
        break
      default:
        data = (await reportApi.lowStock()) as unknown as Record<string, unknown>[]
    }
    rows.value = data
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    loading.value = false
  }
}

function cellText(row: Record<string, unknown>, prop: string): string {
  const value = row[prop]
  if (value === null || value === undefined) return '-'
  if (prop.endsWith('_cents')) return yuan(Number(value))
  if (prop === 'on_time_rate' || prop === 'return_rate') return `${(Number(value) * 100).toFixed(1)}%`
  if (prop === 'avg_daily_sales' || prop === 'average_stock') return Number(value).toFixed(2)
  if (prop === 'turnover_days') return value === null ? '无销量' : String(value)
  if (prop === 'last_stockout_at') return fmtDate(String(value))
  return String(value)
}

function exportCsv() {
  const url = reportApi.exportUrl(active.value, params.value)
  window.open(url, '_blank')
}

watch(active, load)
watch([days, granularity], load)
void load()
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">报表中心</span>
      <el-button type="primary" @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-tabs v-model="active">
      <el-tab-pane v-for="report in REPORTS" :key="report.key" :label="report.label" :name="report.key" />
    </el-tabs>

    <el-form :inline="true" class="filters">
      <el-form-item v-if="current.needsRange" label="回看">
        <el-select v-model="days" style="width: 120px">
          <el-option label="近 7 天" :value="7" />
          <el-option label="近 30 天" :value="30" />
          <el-option label="近 90 天" :value="90" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="active === 'channel-sales' || active === 'purchase-amount'" label="粒度">
        <el-select v-model="granularity" style="width: 110px">
          <el-option label="按天" value="day" />
          <el-option label="按周" value="week" />
          <el-option label="按月" value="month" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button @click="load">刷新</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border height="520">
      <el-table-column
        v-for="col in current.columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        :width="col.width"
        :align="(col.align as never) ?? 'left'"
        show-overflow-tooltip
      >
        <template #default="{ row }">{{ cellText(row, col.prop) }}</template>
      </el-table-column>
      <template #empty><span class="muted">该区间内没有数据</span></template>
    </el-table>

    <p class="note">
      导出文件带 UTF-8 BOM，Excel 双击打开不会乱码；金额按「元」导出。
    </p>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; }
.filters { margin: 8px 0; }
.muted { color: #909399; }
.note { color: #909399; font-size: 12px; margin-top: 8px; }
</style>
