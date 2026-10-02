<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as inventoryApi from '@/api/inventory'
import * as warehouseApi from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import InventoryLedgerTable from '@/components/InventoryLedgerTable.vue'
import type { InventoryStock, InventoryTransaction, Warehouse } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<InventoryStock[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const query = reactive({
  keyword: '',
  warehouse_id: undefined as number | undefined,
  low_only: false,
  page: 1,
  page_size: 15,
})

// Ledger drawer, opened per SKU.
const drawerVisible = ref(false)
const ledgerRows = ref<InventoryTransaction[]>([])
const ledgerLoading = ref(false)
const ledgerTitle = ref('')

const adjustVisible = ref(false)
const adjustForm = reactive({
  sku_id: 0,
  warehouse_id: 0,
  direction: 1,
  quantity: 1,
  reason: '',
})

async function load() {
  loading.value = true
  try {
    const data = await inventoryApi.listInventory({
      keyword: query.keyword || undefined,
      warehouse_id: query.warehouse_id,
      low_only: query.low_only || undefined,
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

async function loadWarehouses() {
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

async function openLedger(row: InventoryStock) {
  ledgerTitle.value = `${row.sku_name} · ${row.warehouse_name}`
  drawerVisible.value = true
  ledgerLoading.value = true
  try {
    const page = await inventoryApi.listLedger({
      sku_id: row.sku_id,
      warehouse_id: row.warehouse_id,
      page_size: 100,
    })
    ledgerRows.value = page.items
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    ledgerLoading.value = false
  }
}

function openAdjust(row: InventoryStock) {
  adjustForm.sku_id = row.sku_id
  adjustForm.warehouse_id = row.warehouse_id
  adjustForm.direction = 1
  adjustForm.quantity = 1
  adjustForm.reason = ''
  adjustVisible.value = true
}

async function submitAdjust() {
  if (!adjustForm.reason.trim()) {
    ElMessage.warning('库存调整必须填写原因')
    return
  }
  try {
    await inventoryApi.adjustStock({
      sku_id: adjustForm.sku_id,
      warehouse_id: adjustForm.warehouse_id,
      qty_delta: adjustForm.direction * Math.abs(adjustForm.quantity),
      reason: adjustForm.reason.trim(),
    })
    ElMessage.success('库存已调整')
    adjustVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(async () => {
  await loadWarehouses()
  await load()
})
</script>

<template>
  <div>
    <div class="toolbar">
      <el-select
        v-model="query.warehouse_id"
        placeholder="全部仓库"
        clearable
        style="width: 180px"
        @change="resetAndLoad"
      >
        <el-option
          v-for="w in warehouses"
          :key="w.id"
          :label="`${w.name}（${w.code}）`"
          :value="w.id"
        />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="搜索 SKU 编码或条码"
        clearable
        style="width: 220px"
        @keyup.enter="resetAndLoad"
      />
      <el-checkbox v-model="query.low_only" @change="resetAndLoad">
        只看可售 ≤ 0
      </el-checkbox>
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="sku_code" label="SKU 编码" width="180" />
      <el-table-column prop="sku_name" label="商品" min-width="170" />
      <el-table-column prop="warehouse_name" label="仓库" width="120" />
      <el-table-column prop="on_hand_qty" label="实际" width="80" align="right" />
      <el-table-column prop="reserved_qty" label="已占用" width="85" align="right" />
      <el-table-column prop="safety_qty" label="安全" width="75" align="right" />
      <el-table-column prop="in_transit_qty" label="在途" width="75" align="right" />
      <el-table-column prop="defective_qty" label="次品" width="75" align="right" />
      <el-table-column label="可售" width="85" align="right">
        <template #default="{ row }">
          <strong :class="{ warn: row.available_qty <= 0 }">{{ row.available_qty }}</strong>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openLedger(row)">流水</el-button>
          <el-button link type="primary" @click="router.push({ name: 'sku-detail', params: { id: row.sku_id } })">
            SKU
          </el-button>
          <el-button v-if="auth.canAdjustStock()" link type="primary" @click="openAdjust(row)">
            调整
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

    <el-drawer v-model="drawerVisible" :title="`库存流水 · ${ledgerTitle}`" size="70%">
      <InventoryLedgerTable :rows="ledgerRows" :loading="ledgerLoading" :show-sku="false" />
    </el-drawer>

    <el-dialog v-model="adjustVisible" title="调整库存" width="440px">
      <el-form label-width="90px">
        <el-form-item label="方向">
          <el-radio-group v-model="adjustForm.direction">
            <el-radio :value="1">入库（+）</el-radio>
            <el-radio :value="-1">出库（−）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="adjustForm.quantity" :min="1" />
        </el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="adjustForm.reason" placeholder="例如 期初建账 / 破损报损" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAdjust">提交调整</el-button>
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
.warn {
  color: #e6a23c;
}
</style>
