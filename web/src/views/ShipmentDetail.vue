<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as shipmentApi from '@/api/shipment'
import { useAuthStore } from '@/stores/auth'
import {
  SHIPMENT_STATUS_LABELS,
  SHIPMENT_STATUS_TAG,
  type PickRecord,
  type PickResult,
  type Shipment,
  type ShipmentItem,
  type ShipmentStatus,
} from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const shipment = ref<Shipment | null>(null)
const records = ref<PickRecord[]>([])
const loading = ref(false)

const ticket = reactive({ barcode: '', quantity: 1 })
const feedback = ref<PickResult | null>(null)
const barcodeInput = ref<HTMLInputElement | null>(null)
const busying = ref(false)

const packDialog = ref(false)
const packForm = reactive({ package_count: 1, weight_g: 0, remark: '' })
const shipDialog = ref(false)
const shipForm = reactive({ carrier: '顺丰', tracking_no: '', remark: '' })

const shipmentId = computed(() => Number(props.id))
const canWork = computed(() => auth.hasRole('admin', 'owner', 'warehouse'))
const progressPct = computed(() => {
  const s = shipment.value
  if (!s || !s.total_quantity) return 0
  return Math.round((s.picked_quantity / s.total_quantity) * 100)
})

/** 拣货清单按库位排序，与后端返回的 line_no 一致。 */
const pickList = computed<ShipmentItem[]>(() => shipment.value?.items ?? [])

async function load() {
  loading.value = true
  try {
    shipment.value = await shipmentApi.getShipment(shipmentId.value)
    records.value = (await shipmentApi.listPickRecords(shipmentId.value, { page_size: 30 })).items
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
    focusScanner()
  }
}

function focusScanner() {
  nextTick(() => barcodeInput.value?.focus())
}

async function submitScan() {
  const code = ticket.barcode.trim()
  if (!code || !shipment.value) return
  if (busying.value) return
  busying.value = true
  try {
    const result = await shipmentApi.pickBarcode(shipmentId.value, code, ticket.quantity)
    feedback.value = result
    ticket.barcode = ''
    ticket.quantity = 1
    // 只有被接受的扫码才需要重载（被拒的没有改变数据，但记录了一条日志）
    await load()
    if (!result.accepted) {
      // 扫描枪会连续输入，这里不要用弹窗打断操作，靠顶部横幅提示
      focusScanner()
    }
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    busying.value = false
  }
}

async function manualConfirm(item: ShipmentItem) {
  const left = item.quantity - item.picked_qty
  if (left <= 0) return
  try {
    await shipmentApi.pickManual(shipmentId.value, item.id, left)
    feedback.value = null
    ElMessage.success(`已确认 ${item.sku_code} × ${left}`)
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function claim() {
  try {
    shipment.value = await shipmentApi.claimShipment(shipmentId.value)
    ElMessage.success('已领取')
    focusScanner()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openPack() {
  packForm.package_count = 1
  packForm.weight_g = shipment.value?.weight_g ?? 0
  packForm.remark = ''
  packDialog.value = true
}

async function submitPack() {
  try {
    shipment.value = await shipmentApi.packShipment(shipmentId.value, { ...packForm })
    packDialog.value = false
    ElMessage.success('复核打包完成，可以出库了')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openShip() {
  shipForm.carrier = shipment.value?.carrier || '顺丰'
  shipForm.tracking_no = shipment.value?.tracking_no || ''
  shipForm.remark = ''
  shipDialog.value = true
}

async function submitShip() {
  try {
    const result = await shipmentApi.shipShipment(shipmentId.value, { ...shipForm })
    shipment.value = result.shipment
    shipDialog.value = false
    ElMessage.success(
      `${result.message}：${result.outbound.map((l) => `${l.sku_code}×${l.quantity}`).join('、')}`,
    )
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function cancel() {
  const input = await ElMessageBox.prompt('取消原因', '取消发货单', {
    inputPlaceholder: '取消后占用仍属于订单，可重新开单',
    inputValue: '',
  })
  try {
    shipment.value = await shipmentApi.cancelShipment(shipmentId.value, input.value ?? '')
    ElMessage.success('已取消')
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function lineState(item: ShipmentItem): 'success' | 'warning' | 'info' {
  if (item.picked_qty >= item.quantity) return 'success'
  if (item.picked_qty > 0) return 'warning'
  return 'info'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button link type="primary" @click="router.back()">← 返回发货单</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
      <template v-if="shipment && canWork">
        <el-button v-if="shipment.status === 'pending'" type="primary" @click="claim">
          领取任务
        </el-button>
        <el-button
          v-if="['picking', 'picked'].includes(shipment.status)"
          type="primary"
          @click="openPack"
        >
          复核打包
        </el-button>
        <el-button v-if="shipment.status === 'packed'" type="success" @click="openShip">
          出库发货
        </el-button>
        <el-button
          v-if="['pending', 'picking', 'picked', 'packed'].includes(shipment.status)"
          type="danger"
          plain
          @click="cancel"
        >
          取消
        </el-button>
      </template>
    </div>

    <el-card v-if="shipment" shadow="never" class="block">
      <template #header>
        <div class="card-header">
          <span>
            {{ shipment.shipment_no }} ·
            {{ shipment.channel_code }} {{ shipment.channel_order_no }}
          </span>
          <el-tag :type="SHIPMENT_STATUS_TAG[shipment.status as ShipmentStatus]">
            {{ SHIPMENT_STATUS_LABELS[shipment.status as ShipmentStatus] }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="内部单号">{{ shipment.order_no }}</el-descriptions-item>
        <el-descriptions-item label="买家">{{ shipment.buyer_nick || '—' }}</el-descriptions-item>
        <el-descriptions-item label="发货仓">
          {{ shipment.warehouse_name }}（{{ shipment.warehouse_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="拣货人">{{ shipment.picker_name || '未领取' }}</el-descriptions-item>
        <el-descriptions-item label="件数">
          {{ shipment.picked_quantity }}/{{ shipment.total_quantity }}
        </el-descriptions-item>
        <el-descriptions-item label="包裹">
          {{ shipment.package_count }} 件 / {{ shipment.weight_g }} g
        </el-descriptions-item>
        <el-descriptions-item label="物流">
          {{ shipment.tracking_no ? `${shipment.carrier} ${shipment.tracking_no}` : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="复核人">
          {{ shipment.packed_by_name || '—' }}
        </el-descriptions-item>
      </el-descriptions>

      <el-progress
        class="progress"
        :percentage="progressPct"
        :status="progressPct === 100 ? 'success' : undefined"
      />
    </el-card>

    <!-- 扫码区 -->
    <el-card v-if="shipment && canWork && ['pending', 'picking'].includes(shipment.status)" shadow="never" class="block scanner">
      <div class="scan-row">
        <span class="scan-label">扫码拣货</span>
        <el-input
          ref="barcodeInput"
          v-model="ticket.barcode"
          size="large"
          placeholder="用扫描枪扫商品条码，或手工输入后回车"
          clearable
          @keyup.enter="submitScan"
        />
        <el-input-number v-model="ticket.quantity" :min="1" size="large" controls-position="right" />
        <el-button size="large" type="primary" :loading="busying" @click="submitScan">
          确认
        </el-button>
      </div>

      <el-alert
        v-if="feedback"
        :type="feedback.accepted ? 'success' : 'error'"
        :closable="false"
        show-icon
        class="feedback"
      >
        <template #title>
          {{ feedback.accepted ? '✓ 已拣货' : '✕ 已拦截' }} —— {{ feedback.message }}
        </template>
        <template #default>
          <span v-if="feedback.accepted">
            进度 {{ feedback.progress }} · 状态
            {{ SHIPMENT_STATUS_LABELS[feedback.shipment_status as ShipmentStatus] }}
          </span>
        </template>
      </el-alert>
    </el-card>

    <!-- 拣货清单 -->
    <el-card v-if="shipment" shadow="never" class="block">
      <template #header>
        <span>拣货清单（按库位顺序）</span>
        <span class="hint">从上到下走一遍就是最短路线</span>
      </template>
      <el-table :data="pickList" size="small" border :row-class-name="() => ''">
        <el-table-column prop="line_no" label="序号" width="70" />
        <el-table-column label="库位" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.location_code" size="small" type="warning">
              {{ row.location_code }}
            </el-tag>
            <span v-else class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="商品" min-width="220">
          <template #default="{ row }">
            <div>{{ row.sku_code }}</div>
            <div class="muted">{{ row.sku_name }}</div>
          </template>
        </el-table-column>
        <el-table-column label="条码" width="150">
          <template #default="{ row }">
            <span v-if="row.barcode">{{ row.barcode }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_bundle_component" size="small" type="warning">套装配件</el-tag>
            <span v-else class="muted">普通</span>
          </template>
        </el-table-column>
        <el-table-column label="应拣 / 已拣" width="140" align="center">
          <template #default="{ row }">
            <el-tag :type="lineState(row)" size="small">
              {{ row.picked_qty }} / {{ row.quantity }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              v-if="canWork && row.picked_qty < row.quantity && ['pending', 'picking'].includes(shipment.status)"
              link
              type="primary"
              @click="manualConfirm(row)"
            >
              手工确认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 扫码记录 -->
    <el-card v-if="shipment" shadow="never" class="block">
      <template #header>
        <span>扫码记录</span>
        <span class="hint">被拦下的扫码也留痕，方便判断是不是货放错了位置</span>
      </template>
      <el-table :data="records" size="small" border>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column prop="barcode" label="条码" width="150" />
        <el-table-column prop="sku_code" label="识别到的 SKU" width="170">
          <template #default="{ row }">{{ row.sku_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="row.accepted ? 'success' : 'danger'" size="small">
              {{ row.accepted ? '通过' : '拦截' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="80" align="right" />
        <el-table-column prop="message" label="说明" min-width="220" />
        <el-table-column prop="operator_name" label="操作人" width="110" />
      </el-table>
    </el-card>

    <el-dialog v-model="packDialog" title="复核打包" width="440px">
      <el-alert
        title="复核通过才能真正出库。默认必须全部拣完才能复核。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="100px">
        <el-form-item label="包裹件数">
          <el-input-number v-model="packForm.package_count" :min="1" />
        </el-form-item>
        <el-form-item label="重量（g）">
          <el-input-number v-model="packForm.weight_g" :min="0" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="packForm.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packDialog = false">取消</el-button>
        <el-button type="primary" @click="submitPack">确认复核</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="shipDialog" title="出库发货" width="440px">
      <el-alert
        title="出库会扣减实际库存并释放占用，同时把订单推进到「已发货」。"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="100px">
        <el-form-item label="承运商">
          <el-input v-model="shipForm.carrier" placeholder="例如 顺丰" />
        </el-form-item>
        <el-form-item label="物流单号">
          <el-input v-model="shipForm.tracking_no" placeholder="例如 SF1234567890" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="shipForm.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="shipDialog = false">取消</el-button>
        <el-button type="success" @click="submitShip">确认出库</el-button>
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
.hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
.progress {
  margin-top: 12px;
}
.scanner {
  border-color: #409eff;
}
.scan-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.scan-label {
  font-weight: 600;
  white-space: nowrap;
}
.feedback {
  margin-top: 12px;
}
.muted {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
