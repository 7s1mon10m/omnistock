<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as productApi from '@/api/product'
import * as transferApi from '@/api/transfer'
import * as warehouseApi from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import {
  TRANSFER_STATUS_LABELS,
  TRANSFER_STATUS_TAG,
  type Sku,
  type TransferListItem,
  type TransferStatus,
  type Warehouse,
} from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<TransferListItem[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const query = reactive({
  status: undefined as TransferStatus | undefined,
  keyword: '',
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(TRANSFER_STATUS_LABELS) as [TransferStatus, string][]

const visible = ref(false)
const form = reactive({
  from_warehouse_id: undefined as number | undefined,
  to_warehouse_id: undefined as number | undefined,
  reason: '',
  items: [{ sku_id: undefined as number | undefined, quantity: 1 }],
})
const skuOptions = ref<Sku[]>([])
const skuSearching = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await transferApi.listTransfers({
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
  form.from_warehouse_id = warehouses.value[0]?.id
  form.to_warehouse_id = warehouses.value[1]?.id
  form.reason = ''
  form.items = [{ sku_id: undefined, quantity: 1 }]
  await searchSkus('')
  visible.value = true
}

function addLine() {
  form.items.push({ sku_id: undefined, quantity: 1 })
}

function removeLine(index: number) {
  form.items.splice(index, 1)
}

async function submit() {
  if (!form.from_warehouse_id || !form.to_warehouse_id) {
    ElMessage.warning('请选择调出仓与调入仓')
    return
  }
  if (form.from_warehouse_id === form.to_warehouse_id) {
    ElMessage.warning('调出仓与调入仓不能相同')
    return
  }
  const items = form.items
    .filter((line) => line.sku_id)
    .map((line) => ({ sku_id: line.sku_id as number, quantity: line.quantity }))
  if (!items.length) {
    ElMessage.warning('至少添加一个商品行')
    return
  }
  try {
    const transfer = await transferApi.createTransfer({
      from_warehouse_id: form.from_warehouse_id,
      to_warehouse_id: form.to_warehouse_id,
      reason: form.reason,
      items,
    })
    ElMessage.success(`调拨单 ${transfer.transfer_no} 已提交，等待审批`)
    visible.value = false
    await load()
    router.push({ name: 'transfer-detail', params: { id: transfer.id } })
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openDetail(row: TransferListItem) {
  router.push({ name: 'transfer-detail', params: { id: row.id } })
}

onMounted(async () => {
  await bootstrap()
  await load()
})
</script>

<template>
  <div>
    <el-alert
      title="调拨要经过「申请 → 审批 → 发出 → 收货」四步。货在路上时记在调入仓的在途里，两边都不算可售。"
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
        placeholder="调拨单号 / 事由"
        clearable
        style="width: 220px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button
        v-if="auth.hasRole('admin', 'owner', 'operator', 'warehouse')"
        type="primary"
        @click="openCreate"
      >
        发起调拨
      </el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="transfer_no" label="调拨单号" width="140" />
      <el-table-column label="调拨方向" min-width="220">
        <template #default="{ row }">
          <el-tag size="small">{{ row.from_warehouse_code }}</el-tag>
          <span class="arrow">→</span>
          <el-tag size="small" type="success">{{ row.to_warehouse_code }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="事由" min-width="140">
        <template #default="{ row }">{{ row.reason || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="TRANSFER_STATUS_TAG[row.status as TransferStatus]" size="small">
            {{ TRANSFER_STATUS_LABELS[row.status as TransferStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="申请 / 发出 / 收货" width="160" align="right">
        <template #default="{ row }">
          {{ row.total_quantity }} / {{ row.shipped_quantity }} / {{ row.received_quantity }}
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

    <el-dialog v-model="visible" title="发起调拨申请" width="720px">
      <el-form label-width="100px">
        <el-form-item label="调出仓" required>
          <el-select v-model="form.from_warehouse_id" style="width: 100%">
            <el-option
              v-for="w in warehouses"
              :key="w.id"
              :label="`${w.name}（${w.code}）`"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调入仓" required>
          <el-select v-model="form.to_warehouse_id" style="width: 100%">
            <el-option
              v-for="w in warehouses"
              :key="w.id"
              :label="`${w.name}（${w.code}）`"
              :value="w.id"
              :disabled="w.id === form.from_warehouse_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="事由">
          <el-input v-model="form.reason" placeholder="例如 直播备货" />
        </el-form-item>
      </el-form>

      <div class="lines-header">
        <span>调拨明细</span>
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
        <el-input-number v-model="line.quantity" :min="1" />
        <el-button link type="danger" @click="removeLine(index)">移除</el-button>
      </div>

      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="submit">提交申请</el-button>
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
.arrow {
  margin: 0 6px;
  color: #909399;
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
