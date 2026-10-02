<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as transferApi from '@/api/transfer'
import { useAuthStore } from '@/stores/auth'
import {
  TRANSFER_STATUS_LABELS,
  TRANSFER_STATUS_TAG,
  type StockTransfer,
  type TransferStatus,
} from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const transfer = ref<StockTransfer | null>(null)
const loading = ref(false)

const shipVisible = ref(false)
const shipForm = reactive({
  remark: '',
  lines: [] as { transfer_item_id: number; label: string; planned: number; quantity: number }[],
})

const receiveVisible = ref(false)
const receiveForm = reactive({
  remark: '',
  lines: [] as {
    transfer_item_id: number
    label: string
    outstanding: number
    quantity: number
    defective_qty: number
  }[],
})

const transferId = computed(() => Number(props.id))
const canApprove = computed(() => auth.hasRole('admin', 'owner'))
const canMove = computed(() => auth.hasRole('admin', 'owner', 'warehouse'))

/** 时间线：每一步谁在什么时候做的 */
const trail = computed(() => {
  const t = transfer.value
  if (!t) return []
  const rows = [
    { step: '提交申请', who: t.requested_by_name, at: t.requested_at, done: true },
    {
      step: t.status === 'rejected' ? '审批驳回' : '审批通过',
      who: t.approved_by_name,
      at: t.approved_at,
      done: !!t.approved_at,
    },
    { step: '调出仓发出', who: t.shipped_by_name, at: t.shipped_at, done: !!t.shipped_at },
    { step: '调入仓收货', who: t.received_by_name, at: t.received_at, done: !!t.received_at },
  ]
  return rows
})

async function load() {
  loading.value = true
  try {
    transfer.value = await transferApi.getTransfer(transferId.value)
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function approve() {
  try {
    transfer.value = await transferApi.approveTransfer(transferId.value)
    ElMessage.success('已批准，可以发出了')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function reject() {
  const input = await ElMessageBox.prompt('驳回原因', '驳回调拨申请', { inputValue: '' })
  try {
    transfer.value = await transferApi.rejectTransfer(transferId.value, input.value ?? '')
    ElMessage.success('已驳回')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openShip() {
  if (!transfer.value) return
  shipForm.remark = ''
  shipForm.lines = transfer.value.items.map((item) => ({
    transfer_item_id: item.id,
    label: `${item.sku_code}（申请 ${item.quantity}）`,
    planned: item.quantity,
    quantity: item.quantity,
  }))
  shipVisible.value = true
}

async function submitShip() {
  const items = shipForm.lines.map((line) => ({
    transfer_item_id: line.transfer_item_id,
    quantity: line.quantity,
  }))
  try {
    transfer.value = await transferApi.shipTransfer(transferId.value, items)
    shipVisible.value = false
    ElMessage.success('已发出，货物进入在途')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openReceive() {
  if (!transfer.value) return
  receiveForm.remark = ''
  receiveForm.lines = transfer.value.items
    .filter((item) => item.shipped_qty - item.received_qty > 0)
    .map((item) => ({
      transfer_item_id: item.id,
      label: `${item.sku_code}（在途 ${item.shipped_qty - item.received_qty}）`,
      outstanding: item.shipped_qty - item.received_qty,
      quantity: item.shipped_qty - item.received_qty,
      defective_qty: 0,
    }))
  if (!receiveForm.lines.length) {
    ElMessage.info('没有待收货的行')
    return
  }
  receiveVisible.value = true
}

async function submitReceive() {
  const items = receiveForm.lines
    .filter((line) => line.quantity > 0)
    .map((line) => ({
      transfer_item_id: line.transfer_item_id,
      quantity: line.quantity,
      defective_qty: line.defective_qty,
    }))
  if (!items.length) {
    ElMessage.warning('请填写实收数量')
    return
  }
  try {
    transfer.value = await transferApi.receiveTransfer(transferId.value, items)
    receiveVisible.value = false
    ElMessage.success('已收货，在途转为实际库存')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function cancel() {
  const input = await ElMessageBox.prompt('取消原因', '取消调拨', { inputValue: '' })
  try {
    transfer.value = await transferApi.cancelTransfer(transferId.value, input.value ?? '')
    ElMessage.success('已取消')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button link type="primary" @click="router.back()">← 返回调拨单</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
      <template v-if="transfer">
        <el-button v-if="transfer.status === 'pending' && canApprove" type="primary" @click="approve">
          审批通过
        </el-button>
        <el-button v-if="transfer.status === 'pending' && canApprove" type="danger" plain @click="reject">
          驳回
        </el-button>
        <el-button v-if="transfer.status === 'approved' && canMove" type="warning" @click="openShip">
          发出（进入在途）
        </el-button>
        <el-button v-if="transfer.status === 'in_transit' && canMove" type="success" @click="openReceive">
          收货
        </el-button>
        <el-button
          v-if="['pending', 'approved'].includes(transfer.status)"
          type="danger"
          plain
          @click="cancel"
        >
          取消
        </el-button>
      </template>
    </div>

    <el-card v-if="transfer" shadow="never" class="block">
      <template #header>
        <div class="card-header">
          <span>
            {{ transfer.transfer_no }} ·
            {{ transfer.from_warehouse_name }} → {{ transfer.to_warehouse_name }}
          </span>
          <el-tag :type="TRANSFER_STATUS_TAG[transfer.status as TransferStatus]">
            {{ TRANSFER_STATUS_LABELS[transfer.status as TransferStatus] }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="调出仓">
          {{ transfer.from_warehouse_name }}（{{ transfer.from_warehouse_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="调入仓">
          {{ transfer.to_warehouse_name }}（{{ transfer.to_warehouse_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="事由">{{ transfer.reason || '—' }}</el-descriptions-item>
        <el-descriptions-item label="数量">
          申请 {{ transfer.total_quantity }} · 发出 {{ transfer.shipped_quantity }} · 收货
          {{ transfer.received_quantity }}
        </el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="transfer.status === 'in_transit'"
        class="notice"
        type="warning"
        :closable="false"
        show-icon
        title="货物在途：已记入调入仓的在途数量，但两边都不算可售。收货后才会转为实际库存。"
      />
      <el-alert
        v-if="transfer.status === 'rejected'"
        class="notice"
        type="error"
        :closable="false"
        show-icon
        :title="`已驳回：${transfer.reject_reason || '未填原因'}`"
      />
    </el-card>

    <el-card v-if="transfer" shadow="never" class="block">
      <template #header><span>调拨明细</span></template>
      <el-table :data="transfer.items" size="small" border>
        <el-table-column prop="line_no" label="#" width="60" />
        <el-table-column label="SKU" min-width="220">
          <template #default="{ row }">
            <div>{{ row.sku_code }}</div>
            <div class="muted">{{ row.sku_name }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="申请" width="90" align="right" />
        <el-table-column prop="shipped_qty" label="发出" width="90" align="right" />
        <el-table-column prop="received_qty" label="实收" width="90" align="right" />
        <el-table-column label="其中次品" width="100" align="right">
          <template #default="{ row }">
            <span :class="{ warn: row.defective_qty > 0 }">{{ row.defective_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="合格入库" width="110" align="right">
          <template #default="{ row }">
            <b>{{ row.qualified_qty }}</b>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="transfer" shadow="never" class="block">
      <template #header><span>流转记录</span></template>
      <el-table :data="trail" size="small" border>
        <el-table-column prop="step" label="环节" width="140" />
        <el-table-column label="操作人" width="140">
          <template #default="{ row }">{{ row.done ? row.who || '—' : '待处理' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">
            {{ row.at ? row.at.replace('T', ' ').slice(0, 19) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.done ? 'success' : 'info'" size="small">
              {{ row.done ? '已完成' : '未开始' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="shipVisible" title="调出仓发出" width="560px">
      <el-alert
        title="发出后调出仓实际库存减少，调入仓在途增加。整单一起发，任何一行不够都会整单不发。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <div v-for="line in shipForm.lines" :key="line.transfer_item_id" class="dialog-line">
        <span class="label">{{ line.label }}</span>
        <el-input-number v-model="line.quantity" :min="1" :max="line.planned" size="small" />
      </div>
      <el-form label-width="70px" class="dialog-remark">
        <el-form-item label="备注">
          <el-input v-model="shipForm.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="shipVisible = false">取消</el-button>
        <el-button type="primary" @click="submitShip">确认发出</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="receiveVisible" title="调入仓收货" width="600px">
      <el-alert
        title="收货后在该仓内部把在途转为实际库存；破损的可以记成次品，次品不计入可售。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <div v-for="line in receiveForm.lines" :key="line.transfer_item_id" class="dialog-line">
        <span class="label">{{ line.label }}</span>
        <el-input-number v-model="line.quantity" :min="0" :max="line.outstanding" size="small" />
        <span class="sub">其中次品</span>
        <el-input-number
          v-model="line.defective_qty"
          :min="0"
          :max="line.quantity"
          size="small"
        />
      </div>
      <el-form label-width="70px" class="dialog-remark">
        <el-form-item label="备注">
          <el-input v-model="receiveForm.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReceive">确认收货</el-button>
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
.notice {
  margin-top: 12px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
.warn {
  color: #e6a23c;
}
.dialog-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.dialog-line .label {
  flex: 1;
}
.dialog-line .sub {
  font-size: 12px;
  color: #909399;
}
.dialog-remark {
  margin-top: 12px;
}
</style>
