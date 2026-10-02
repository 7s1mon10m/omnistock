<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as inventoryApi from '@/api/inventory'
import * as productApi from '@/api/product'
import { useAuthStore } from '@/stores/auth'
import InventoryLedgerTable from '@/components/InventoryLedgerTable.vue'
import type { Barcode, InventoryStock, InventoryTransaction, Sku } from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const sku = ref<Sku | null>(null)
const stocks = ref<InventoryStock[]>([])
const ledger = ref<InventoryTransaction[]>([])
const barcodes = ref<Barcode[]>([])
const loading = ref(false)
const ledgerLoading = ref(false)

const adjustVisible = ref(false)
const adjustForm = reactive({
  warehouse_id: 0,
  direction: 1,
  quantity: 1,
  reason: '',
})
const newBarcode = reactive({ barcode: '', remark: '' })

const skuId = computed(() => Number(props.id))

const totalOnHand = computed(() => stocks.value.reduce((sum, row) => sum + row.on_hand_qty, 0))
const totalReserved = computed(() => stocks.value.reduce((sum, row) => sum + row.reserved_qty, 0))
const totalAvailable = computed(() => stocks.value.reduce((sum, row) => sum + row.available_qty, 0))
const totalInTransit = computed(() =>
  stocks.value.reduce((sum, row) => sum + row.in_transit_qty, 0),
)

async function loadAll() {
  loading.value = true
  try {
    sku.value = await productApi.getSku(skuId.value)
    const stockPage = await inventoryApi.listInventory({ sku_id: skuId.value, page_size: 200 })
    stocks.value = stockPage.items
    barcodes.value = await productApi.listBarcodes(skuId.value)
    await loadLedger()
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function loadLedger() {
  ledgerLoading.value = true
  try {
    const page = await inventoryApi.listLedger({ sku_id: skuId.value, page_size: 50 })
    ledger.value = page.items
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    ledgerLoading.value = false
  }
}

function openAdjust(row: InventoryStock) {
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
      sku_id: skuId.value,
      warehouse_id: adjustForm.warehouse_id,
      qty_delta: adjustForm.direction * Math.abs(adjustForm.quantity),
      reason: adjustForm.reason.trim(),
    })
    ElMessage.success('库存已调整，并写入库存流水')
    adjustVisible.value = false
    await loadAll()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function submitBarcode() {
  if (!newBarcode.barcode.trim()) {
    ElMessage.warning('请填写条码')
    return
  }
  try {
    await productApi.addBarcode(skuId.value, {
      barcode: newBarcode.barcode.trim(),
      remark: newBarcode.remark,
    })
    ElMessage.success('条码已新增')
    newBarcode.barcode = ''
    newBarcode.remark = ''
    barcodes.value = await productApi.listBarcodes(skuId.value)
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function removeBarcode(row: Barcode) {
  await ElMessageBox.confirm(`确认删除条码 ${row.barcode}？`, '提示', { type: 'warning' })
  try {
    await productApi.deleteBarcode(skuId.value, row.id)
    ElMessage.success('已删除')
    barcodes.value = await productApi.listBarcodes(skuId.value)
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(loadAll)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button link type="primary" @click="router.back()">← 返回</el-button>
      <div class="spacer" />
      <el-button @click="loadAll">刷新</el-button>
    </div>

    <el-card v-if="sku" shadow="never" class="block">
      <template #header>
        <div class="card-header">
          <span>{{ sku.display_name }}</span>
          <div>
            <el-tag v-if="sku.is_bundle" type="warning" size="small">组合商品</el-tag>
            <el-tag v-else size="small">普通商品</el-tag>
          </div>
        </div>
      </template>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="SKU 编码">{{ sku.sku_code }}</el-descriptions-item>
        <el-descriptions-item label="条码">{{ sku.barcode || '—' }}</el-descriptions-item>
        <el-descriptions-item label="规格">
          <span v-if="Object.keys(sku.spec_json).length">
            {{ Object.entries(sku.spec_json).map(([k, v]) => `${k}: ${v}`).join(' / ') }}
          </span>
          <span v-else>—</span>
        </el-descriptions-item>
        <el-descriptions-item label="采购价">
          ¥{{ (sku.purchase_price_cents / 100).toFixed(2) }}
        </el-descriptions-item>
        <el-descriptions-item label="重量">{{ sku.weight_g }} g</el-descriptions-item>
        <el-descriptions-item label="包装规格">{{ sku.package_spec || '—' }}</el-descriptions-item>
        <el-descriptions-item label="安全库存">{{ sku.safety_qty }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          {{ sku.status === 'active' ? '在售' : '已归档' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <div class="summary">
      <el-card shadow="never" class="metric">
        <div class="metric-label">实际库存</div>
        <div class="metric-value">{{ totalOnHand }}</div>
      </el-card>
      <el-card shadow="never" class="metric">
        <div class="metric-label">已占用</div>
        <div class="metric-value">{{ totalReserved }}</div>
      </el-card>
      <el-card shadow="never" class="metric">
        <div class="metric-label">在途</div>
        <div class="metric-value">{{ totalInTransit }}</div>
      </el-card>
      <el-card shadow="never" class="metric">
        <div class="metric-label">可售</div>
        <div class="metric-value" :class="{ warn: totalAvailable <= 0 }">{{ totalAvailable }}</div>
      </el-card>
    </div>

    <el-card shadow="never" class="block">
      <template #header>
        <span>各仓库库存口径</span>
        <span class="hint">可售 = 实际 − 已占用 − 安全</span>
      </template>
      <el-table :data="stocks" border size="small">
        <el-table-column label="仓库" min-width="150">
          <template #default="{ row }">{{ row.warehouse_name }}（{{ row.warehouse_code }}）</template>
        </el-table-column>
        <el-table-column prop="on_hand_qty" label="实际" width="90" align="right" />
        <el-table-column prop="reserved_qty" label="已占用" width="90" align="right" />
        <el-table-column prop="safety_qty" label="安全" width="80" align="right" />
        <el-table-column prop="in_transit_qty" label="在途" width="80" align="right" />
        <el-table-column prop="defective_qty" label="次品" width="80" align="right" />
        <el-table-column prop="repair_qty" label="维修" width="80" align="right" />
        <el-table-column label="可售" width="90" align="right">
          <template #default="{ row }">
            <strong :class="{ warn: row.available_qty <= 0 }">{{ row.available_qty }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button
              v-if="auth.canAdjustStock()"
              link
              type="primary"
              @click="openAdjust(row)"
            >
              调整库存
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header><span>条码</span></template>
      <el-table :data="barcodes" border size="small">
        <el-table-column prop="barcode" label="条码" min-width="180" />
        <el-table-column prop="remark" label="备注" min-width="140" />
        <el-table-column label="主条码" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" size="small" type="success">是</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="auth.canManageProducts()"
              link
              type="danger"
              @click="removeBarcode(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="auth.canManageProducts()" class="barcode-form">
        <el-input v-model="newBarcode.barcode" placeholder="新条码" style="width: 200px" />
        <el-input v-model="newBarcode.remark" placeholder="备注（可选）" style="width: 180px" />
        <el-button type="primary" @click="submitBarcode">新增条码</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <span>库存流水</span>
        <span class="hint">只增不改，每一次变化都可追溯</span>
      </template>
      <InventoryLedgerTable :rows="ledger" :loading="ledgerLoading" :show-sku="false" />
    </el-card>

    <el-dialog v-model="adjustVisible" title="调整库存" width="440px">
      <el-alert
        title="库存不会被直接改写，调整会生成一条可追溯的库存流水"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
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
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
.block {
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
.summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.metric-label {
  font-size: 12px;
  color: #909399;
}
.metric-value {
  font-size: 24px;
  font-weight: 600;
  margin-top: 4px;
}
.warn {
  color: #e6a23c;
}
.barcode-form {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
