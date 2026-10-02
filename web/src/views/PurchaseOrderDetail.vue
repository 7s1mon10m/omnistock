<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as purchaseApi from '@/api/purchase'
import { useAuthStore } from '@/stores/auth'
import {
  PURCHASE_STATUS_LABELS,
  PURCHASE_STATUS_TAG,
  yuan,
  type PurchaseOrder,
  type PurchaseOrderStatus,
} from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const order = ref<PurchaseOrder | null>(null)
const loading = ref(false)
const lastMessage = ref('')

const receiptVisible = ref(false)
const receiptForm = reactive({
  remark: '',
  lines: [] as { order_item_id: number; label: string; outstanding: number; quantity: number; defective_qty: number }[],
})

const orderId = computed(() => Number(props.id))
const canBuy = computed(() => auth.hasRole('admin', 'owner', 'buyer'))
const canReceive = computed(() => auth.hasRole('admin', 'owner', 'warehouse'))

async function load() {
  loading.value = true
  try {
    order.value = await purchaseApi.getPurchaseOrder(orderId.value)
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function submit() {
  try {
    order.value = await purchaseApi.submitPurchaseOrder(orderId.value)
    ElMessage.success('已下单，开始等到货')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function cancel() {
  const input = await ElMessageBox.prompt('取消原因', '取消采购单', { inputValue: '' })
  try {
    order.value = await purchaseApi.cancelPurchaseOrder(orderId.value, input.value ?? '')
    ElMessage.success('已取消')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openReceipt() {
  if (!order.value) return
  receiptForm.remark = ''
  receiptForm.lines = order.value.items
    .filter((item) => item.outstanding_qty > 0)
    .map((item) => ({
      order_item_id: item.id,
      label: `${item.sku_code}（剩余 ${item.outstanding_qty}）`,
      outstanding: item.outstanding_qty,
      quantity: item.outstanding_qty,
      defective_qty: 0,
    }))
  if (!receiptForm.lines.length) {
    ElMessage.info('这张采购单已经收齐了')
    return
  }
  receiptVisible.value = true
}

async function submitReceipt() {
  const items = receiptForm.lines
    .filter((line) => line.quantity > 0)
    .map((line) => ({
      order_item_id: line.order_item_id,
      quantity: line.quantity,
      defective_qty: line.defective_qty,
    }))
  if (!items.length) {
    ElMessage.warning('请填写本次到货数量')
    return
  }
  try {
    const result = await purchaseApi.createReceipt(orderId.value, {
      items,
      remark: receiptForm.remark,
    })
    order.value = result.order
    lastMessage.value = result.message
    receiptVisible.value = false
    ElMessage.success(result.message)
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

/** 到货总量里次品不能超过到货量 */
function lineDefectiveMax(line: { quantity: number }) {
  return line.quantity
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button link type="primary" @click="router.back()">← 返回采购单</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
      <template v-if="order">
        <el-button v-if="order.status === 'draft' && canBuy" type="primary" @click="submit">
          确认下单
        </el-button>
        <el-button
          v-if="['submitted', 'partial'].includes(order.status) && canReceive"
          type="success"
          @click="openReceipt"
        >
          登记到货
        </el-button>
        <el-button
          v-if="['draft', 'submitted', 'partial'].includes(order.status) && canBuy"
          type="danger"
          plain
          @click="cancel"
        >
          取消
        </el-button>
      </template>
    </div>

    <el-alert v-if="lastMessage" :title="lastMessage" type="success" :closable="false" show-icon class="block" />

    <el-card v-if="order" shadow="never" class="block">
      <template #header>
        <div class="card-header">
          <span>{{ order.po_no }} · {{ order.supplier_name }}</span>
          <el-tag :type="PURCHASE_STATUS_TAG[order.status as PurchaseOrderStatus]">
            {{ PURCHASE_STATUS_LABELS[order.status as PurchaseOrderStatus] }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="供应商">
          {{ order.supplier_name }}（{{ order.supplier_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="收货仓">
          {{ order.warehouse_name }}（{{ order.warehouse_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="采购员">{{ order.buyer_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="金额">{{ yuan(order.total_amount_cents) }}</el-descriptions-item>
        <el-descriptions-item label="下单时间">
          {{ order.ordered_at?.replace('T', ' ').slice(0, 19) || '未下单' }}
        </el-descriptions-item>
        <el-descriptions-item label="预计到货">
          {{ order.expected_at?.replace('T', ' ').slice(0, 10) || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="到货进度">
          {{ order.received_quantity }}/{{ order.total_quantity }}
        </el-descriptions-item>
        <el-descriptions-item label="备注">{{ order.remark || '—' }}</el-descriptions-item>
      </el-descriptions>

      <el-progress
        class="progress"
        :percentage="order.total_quantity ? Math.round((order.received_quantity / order.total_quantity) * 100) : 0"
        :status="order.is_fully_received ? 'success' : undefined"
      />
    </el-card>

    <el-card v-if="order" shadow="never" class="block">
      <template #header><span>采购明细</span></template>
      <el-table :data="order.items" size="small" border>
        <el-table-column prop="line_no" label="#" width="60" />
        <el-table-column label="SKU" min-width="220">
          <template #default="{ row }">
            <div>{{ row.sku_code }}</div>
            <div class="muted">{{ row.sku_name }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="下单量" width="90" align="right" />
        <el-table-column prop="received_qty" label="已到货" width="90" align="right" />
        <el-table-column label="其中次品" width="100" align="right">
          <template #default="{ row }">
            <span :class="{ warn: row.defective_qty > 0 }">{{ row.defective_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="未到" width="90" align="right">
          <template #default="{ row }">
            <b :class="{ warn: row.outstanding_qty > 0 }">{{ row.outstanding_qty }}</b>
          </template>
        </el-table-column>
        <el-table-column label="单价" width="110" align="right">
          <template #default="{ row }">{{ yuan(row.unit_price_cents) }}</template>
        </el-table-column>
      </el-table>
      <div class="note">次品进次品区，永远不计入可售库存。</div>
    </el-card>

    <el-card v-if="order" shadow="never" class="block">
      <template #header><span>到货记录（{{ order.receipts.length }} 次）</span></template>
      <el-table v-if="order.receipts.length" :data="order.receipts" size="small" border>
        <el-table-column prop="receipt_no" label="收货单号" width="140" />
        <el-table-column prop="total_quantity" label="到货" width="90" align="right" />
        <el-table-column label="次品" width="90" align="right">
          <template #default="{ row }">
            <span :class="{ warn: row.total_defective > 0 }">{{ row.total_defective }}</span>
          </template>
        </el-table-column>
        <el-table-column label="合格" width="90" align="right">
          <template #default="{ row }">{{ row.total_quantity - row.total_defective }}</template>
        </el-table-column>
        <el-table-column label="收货时间" min-width="170">
          <template #default="{ row }">
            {{ row.received_at?.replace('T', ' ').slice(0, 19) || '—' }}
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="还没有到货记录" :image-size="60" />
    </el-card>

    <el-dialog v-model="receiptVisible" title="登记到货" width="640px">
      <el-alert
        title="到货数量里可以拆出次品数：合格品进可售，次品只进次品区。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <div v-for="line in receiptForm.lines" :key="line.order_item_id" class="receipt-line">
        <span class="label">{{ line.label }}</span>
        <el-input-number v-model="line.quantity" :min="0" :max="line.outstanding" size="small" />
        <span class="sub">其中次品</span>
        <el-input-number
          v-model="line.defective_qty"
          :min="0"
          :max="lineDefectiveMax(line)"
          size="small"
        />
      </div>
      <el-form label-width="80px" class="receipt-remark">
        <el-form-item label="备注">
          <el-input v-model="receiptForm.remark" placeholder="例如 外箱有破损" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiptVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReceipt">确认收货</el-button>
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
.block {
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.progress {
  margin-top: 12px;
}
.note {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.warn {
  color: #e6a23c;
}
.receipt-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.receipt-line .label {
  flex: 1;
}
.receipt-line .sub {
  font-size: 12px;
  color: #909399;
}
.receipt-remark {
  margin-top: 12px;
}
</style>
