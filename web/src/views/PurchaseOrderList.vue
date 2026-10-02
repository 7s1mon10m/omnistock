<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as productApi from '@/api/product'
import * as purchaseApi from '@/api/purchase'
import * as warehouseApi from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import {
  PURCHASE_STATUS_LABELS,
  PURCHASE_STATUS_TAG,
  yuan,
  type PurchaseOrderListItem,
  type PurchaseOrderStatus,
  type Sku,
  type Supplier,
  type Warehouse,
} from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<PurchaseOrderListItem[]>([])
const total = ref(0)
const suppliers = ref<Supplier[]>([])
const warehouses = ref<Warehouse[]>([])
const query = reactive({
  status: undefined as PurchaseOrderStatus | undefined,
  keyword: '',
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(PURCHASE_STATUS_LABELS) as [PurchaseOrderStatus, string][]

const visible = ref(false)
const form = reactive({
  supplier_id: undefined as number | undefined,
  warehouse_id: undefined as number | undefined,
  remark: '',
  items: [{ sku_id: undefined as number | undefined, quantity: 1, unit_price_yuan: 0 }],
})

const skuOptions = ref<Sku[]>([])
const skuSearching = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await purchaseApi.listPurchaseOrders({
      status: query.status,
      keyword: query.keyword || undefined,
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

async function bootstrap() {
  try {
    suppliers.value = (await purchaseApi.listSuppliers()).items
    warehouses.value = (await warehouseApi.listWarehouses()).items
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function resetAndLoad() {
  query.page = 1
  load()
}

async function searchSkus(keyword: string) {
  skuSearching.value = true
  try {
    skuOptions.value = (await productApi.listSkus({ keyword: keyword || undefined, page_size: 50 }))
      .items
  } finally {
    skuSearching.value = false
  }
}

async function openCreate() {
  form.supplier_id = suppliers.value[0]?.id
  form.warehouse_id = warehouses.value[0]?.id
  form.remark = ''
  form.items = [{ sku_id: undefined, quantity: 1, unit_price_yuan: 0 }]
  await searchSkus('')
  visible.value = true
}

function addLine() {
  form.items.push({ sku_id: undefined, quantity: 1, unit_price_yuan: 0 })
}

function removeLine(index: number) {
  form.items.splice(index, 1)
}

async function submit() {
  if (!form.supplier_id || !form.warehouse_id) {
    ElMessage.warning('请选择供应商与收货仓')
    return
  }
  const items = form.items
    .filter((line) => line.sku_id)
    .map((line) => ({
      sku_id: line.sku_id as number,
      quantity: line.quantity,
      unit_price_cents: Math.round(Number(line.unit_price_yuan) * 100),
    }))
  if (!items.length) {
    ElMessage.warning('至少添加一个商品行')
    return
  }
  try {
    const order = await purchaseApi.createPurchaseOrder({
      supplier_id: form.supplier_id,
      warehouse_id: form.warehouse_id,
      remark: form.remark,
      items,
    })
    ElMessage.success(`采购单 ${order.po_no} 已创建（草稿），确认后记得下单`)
    visible.value = false
    await load()
    router.push({ name: 'purchase-detail', params: { id: order.id } })
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openDetail(row: PurchaseOrderListItem) {
  router.push({ name: 'purchase-detail', params: { id: row.id } })
}

onMounted(async () => {
  await bootstrap()
  await load()
})
</script>

<template>
  <div>
    <el-alert
      title="采购单本身不动库存 —— 只有到货登记才会入库，而且合格品与次品分开记账。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <div class="toolbar">
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
        placeholder="采购单号 / 备注"
        clearable
        style="width: 220px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button v-if="auth.hasRole('admin', 'owner', 'buyer')" type="primary" @click="openCreate">
        新建采购单
      </el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="po_no" label="采购单号" width="140" />
      <el-table-column prop="supplier_name" label="供应商" min-width="160" />
      <el-table-column prop="warehouse_code" label="收货仓" width="110" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="PURCHASE_STATUS_TAG[row.status as PurchaseOrderStatus]" size="small">
            {{ PURCHASE_STATUS_LABELS[row.status as PurchaseOrderStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="到货进度" width="160">
        <template #default="{ row }">
          <el-progress
            :percentage="row.total_quantity ? Math.round((row.received_quantity / row.total_quantity) * 100) : 0"
            :stroke-width="12"
            :text-inside="true"
            :status="row.received_quantity >= row.total_quantity ? 'success' : undefined"
          />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="110" align="right">
        <template #default="{ row }">{{ row.received_quantity }}/{{ row.total_quantity }}</template>
      </el-table-column>
      <el-table-column label="金额" width="120" align="right">
        <template #default="{ row }">{{ yuan(row.total_amount_cents) }}</template>
      </el-table-column>
      <el-table-column label="预计到货" width="120">
        <template #default="{ row }">
          {{ row.expected_at ? row.expected_at.slice(0, 10) : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
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

    <el-dialog v-model="visible" title="新建采购单" width="720px">
      <el-form label-width="100px">
        <el-form-item label="供应商" required>
          <el-select v-model="form.supplier_id" style="width: 100%" filterable>
            <el-option
              v-for="s in suppliers"
              :key="s.id"
              :label="`${s.name}（${s.code} · 交期 ${s.lead_time_days} 天）`"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="收货仓" required>
          <el-select v-model="form.warehouse_id" style="width: 100%">
            <el-option
              v-for="w in warehouses"
              :key="w.id"
              :label="`${w.name}（${w.code}）`"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
        </el-form-item>
      </el-form>

      <div class="lines-header">
        <span>采购明细</span>
        <el-button link type="primary" @click="addLine">+ 添加一行</el-button>
      </div>
      <div v-for="(line, index) in form.items" :key="index" class="line">
        <el-select
          v-model="line.sku_id"
          filterable
          remote
          reserve-keyword
          placeholder="搜索 SKU"
          :remote-method="searchSkus"
          :loading="skuSearching"
          style="flex: 1"
        >
          <el-option
            v-for="sku in skuOptions"
            :key="sku.id"
            :label="`${sku.sku_code} — ${sku.display_name}`"
            :value="sku.id"
          />
        </el-select>
        <el-input-number v-model="line.quantity" :min="1" placeholder="数量" />
        <el-input-number
          v-model="line.unit_price_yuan"
          :min="0"
          :precision="2"
          :controls="false"
          placeholder="单价(元)"
          style="width: 110px"
        />
        <el-button link type="danger" @click="removeLine(index)">移除</el-button>
      </div>

      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建草稿</el-button>
      </template>
    </el-dialog>
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
.lines-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px 0;
  font-weight: 600;
}
.line {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
