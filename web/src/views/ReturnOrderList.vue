<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as returnApi from '@/api/return'
import * as orderApi from '@/api/order'
import * as productApi from '@/api/product'
import * as warehouseApi from '@/api/warehouse'
import {
  RETURN_REASON_LABELS,
  RETURN_STATUS_LABELS,
  RETURN_STATUS_TAG,
  fmtDate,
  type ReturnListItem,
  type ReturnReason,
  type ReturnStatus,
  type Sku,
  type Warehouse,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const rows = ref<ReturnListItem[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const orders = ref<{ id: number; order_no: string; channel_order_no: string }[]>([])
const skuOptions = ref<Sku[]>([])

const query = reactive({
  status: undefined as ReturnStatus | undefined,
  warehouse_id: undefined as number | undefined,
  keyword: '',
  page: 1,
  page_size: 15,
})

const visible = ref(false)
const form = reactive({
  warehouse_id: undefined as number | undefined,
  order_id: undefined as number | undefined,
  buyer_nick: '',
  reason: 'other' as ReturnReason,
  items: [{ sku_id: undefined as number | undefined, quantity: 1 }],
})

const STATUS_OPTIONS = Object.entries(RETURN_STATUS_LABELS) as [ReturnStatus, string][]
const REASON_OPTIONS = Object.entries(RETURN_REASON_LABELS) as [ReturnReason, string][]

async function load() {
  loading.value = true
  try {
    const page = await returnApi.listReturns(query)
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function openCreate() {
  orders.value = (await orderApi.listOrders({ page_size: 100 })).items.map((row) => ({
    id: row.id,
    order_no: row.order_no,
    channel_order_no: row.channel_order_no,
  }))
  form.warehouse_id = undefined
  form.order_id = undefined
  form.buyer_nick = ''
  form.reason = 'other'
  form.items = [{ sku_id: undefined, quantity: 1 }]
  visible.value = true
}

async function submit() {
  if (!form.warehouse_id || !form.order_id) {
    ElMessage.warning('请选择仓库与原订单')
    return
  }
  const items = form.items.filter((line) => line.sku_id)
  if (!items.length) {
    ElMessage.warning('至少添加一个商品')
    return
  }
  try {
    const created = await returnApi.createReturn({
      warehouse_id: form.warehouse_id,
      order_id: form.order_id,
      buyer_nick: form.buyer_nick,
      reason: form.reason,
      items: items.map((line) => ({ sku_id: line.sku_id as number, quantity: line.quantity })),
    })
    ElMessage.success(`退货单 ${created.return_no} 已创建`)
    visible.value = false
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function cancel(row: ReturnListItem) {
  try {
    await ElMessageBox.confirm(`取消退货单 ${row.return_no}？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await returnApi.cancelReturn(row.id, '人工取消')
    ElMessage.success('已取消')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function searchSkus(keyword: string) {
  skuOptions.value = (await productApi.listSkus({ keyword: keyword || undefined, page_size: 50 })).items
}

function addLine() {
  form.items.push({ sku_id: undefined, quantity: 1 })
}

onMounted(async () => {
  warehouses.value = (await warehouseApi.listWarehouses({ page_size: 200 })).items
  await searchSkus('')
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">退货单</span>
      <el-button type="primary" @click="openCreate">新建退货单</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      退货分两步：<b>质检</b>只记录这批货分别该去哪，<b>入库</b>才真正改库存。
      分开是为了让质检结论可以反悔 —— 否则改一次结论就得先做一笔反向流水。
    </el-alert>

    <el-form :inline="true" class="filters">
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 120px">
          <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库">
        <el-select v-model="query.warehouse_id" clearable placeholder="全部" style="width: 140px">
          <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="关键字">
        <el-input v-model="query.keyword" placeholder="退货单号 / 渠道单号 / 买家" clearable />
      </el-form-item>
      <el-form-item><el-button @click="load">查询</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="return_no" label="退货单号" width="130" />
      <el-table-column prop="channel_order_no" label="原订单" width="160" />
      <el-table-column prop="buyer_nick" label="买家" width="120" />
      <el-table-column prop="warehouse_name" label="退货仓" width="120" />
      <el-table-column prop="total_quantity" label="数量" width="80" align="right" />
      <el-table-column label="原因" width="110">
        <template #default="{ row }">{{ RETURN_REASON_LABELS[row.reason as ReturnReason] }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="RETURN_STATUS_TAG[row.status as ReturnStatus] as never">
            {{ RETURN_STATUS_LABELS[row.status as ReturnStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/returns/${row.id}`)">
            {{ row.status === 'pending' ? '去质检' : '详情' }}
          </el-button>
          <el-button v-if="row.status !== 'inbound' && row.status !== 'cancelled'" link type="danger" @click="cancel(row)">
            取消
          </el-button>
        </template>
      </el-table-column>
      <template #empty><span class="muted">暂无退货单</span></template>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />

    <el-dialog v-model="visible" title="新建退货单" width="560px">
      <el-form label-width="100px">
        <el-form-item label="退货仓" required>
          <el-select v-model="form.warehouse_id" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="原订单" required>
          <el-select v-model="form.order_id" filterable style="width: 100%">
            <el-option
              v-for="o in orders"
              :key="o.id"
              :label="`${o.order_no} · ${o.channel_order_no}`"
              :value="o.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="买家">
          <el-input v-model="form.buyer_nick" />
        </el-form-item>
        <el-form-item label="原因">
          <el-select v-model="form.reason">
            <el-option v-for="[value, label] in REASON_OPTIONS" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="退货商品">
          <div v-for="(line, index) in form.items" :key="index" class="line">
            <el-select
              v-model="line.sku_id"
              filterable
              remote
              :remote-method="searchSkus"
              placeholder="选择 SKU"
              class="sku"
            >
              <el-option v-for="sku in skuOptions" :key="sku.id" :label="sku.sku_code" :value="sku.id" />
            </el-select>
            <el-input-number v-model="line.quantity" :min="1" />
            <el-button link type="danger" @click="form.items.splice(index, 1)">删除</el-button>
          </div>
          <el-button link type="primary" @click="addLine">+ 添加商品</el-button>
        </el-form-item>
      </el-form>
      <p class="note">退货数量不能超过「已售 − 已退」，否则会被拒绝。</p>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; }
.hint { margin-bottom: 12px; }
.filters { margin-bottom: 8px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.muted { color: #909399; }
.note { color: #909399; font-size: 12px; margin: 0; }
.line { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sku { flex: 1; }
</style>
