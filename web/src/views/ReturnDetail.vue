<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as returnApi from '@/api/return'
import {
  DISPOSITION_LABELS,
  RETURN_REASON_LABELS,
  RETURN_STATUS_LABELS,
  RETURN_STATUS_TAG,
  fmtDate,
  type ReturnDisposition,
  type ReturnItem,
  type ReturnOrder,
  type ReturnReason,
  type ReturnStatus,
} from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const detail = ref<ReturnOrder | null>(null)

// 每行一个临时的分流录入
const splits = ref<Record<number, Record<string, number>>>({})

const id = computed(() => Number(route.params.id))

const DISPOSITION_OPTIONS = Object.entries(DISPOSITION_LABELS) as [ReturnDisposition, string][]

function splitOf(item: ReturnItem) {
  if (!splits.value[item.id]) {
    splits.value[item.id] = {
      resellable_qty: item.resellable_qty,
      defective_qty: item.defective_qty,
      repair_qty: item.repair_qty,
      scrap_qty: item.scrap_qty,
    }
  }
  return splits.value[item.id]
}

const allMatched = computed(() => {
  if (!detail.value) return false
  return detail.value.items.every((item) => {
    const split = splitOf(item)
    const total = split.resellable_qty + split.defective_qty + split.repair_qty + split.scrap_qty
    return total === item.quantity
  })
})

async function load() {
  loading.value = true
  try {
    detail.value = await returnApi.getReturn(id.value)
    splits.value = {}
  } finally {
    loading.value = false
  }
}

async function inspect() {
  if (!detail.value) return
  if (!allMatched.value) {
    ElMessage.warning('每一行的分流数量之和必须等于退货量')
    return
  }
  submitting.value = true
  try {
    detail.value = await returnApi.inspectReturn(id.value, {
      items: detail.value.items.map((item) => {
        const split = splitOf(item)
        // 结论取数量最大的那一档，仅用于展示；真正决定库存的是四个分流数
        const disposition = (Object.entries(split).sort((a, b) => b[1] - a[1])[0][0]
          .replace('_qty', '') + '') as ReturnDisposition
        return {
          return_item_id: item.id,
          disposition,
          resellable_qty: split.resellable_qty,
          defective_qty: split.defective_qty,
          repair_qty: split.repair_qty,
          scrap_qty: split.scrap_qty,
        }
      }),
    })
    ElMessage.success('质检已记录，库存尚未变动')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    submitting.value = false
  }
}

async function inbound() {
  submitting.value = true
  try {
    detail.value = await returnApi.inboundReturn(id.value)
    ElMessage.success('已入库，库存按质检结论更新')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page">
    <template v-if="detail">
      <div class="toolbar">
        <span class="title">
          退货单 {{ detail.return_no }}
          <el-tag size="small" :type="RETURN_STATUS_TAG[detail.status as ReturnStatus] as never">
            {{ RETURN_STATUS_LABELS[detail.status as ReturnStatus] }}
          </el-tag>
        </span>
        <el-button @click="router.push('/returns')">返回列表</el-button>
      </div>

      <el-descriptions :column="4" border class="desc">
        <el-descriptions-item label="原订单">{{ detail.channel_order_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="买家">{{ detail.buyer_nick || '-' }}</el-descriptions-item>
        <el-descriptions-item label="退货仓">{{ detail.warehouse_name }}</el-descriptions-item>
        <el-descriptions-item label="原因">
          {{ RETURN_REASON_LABELS[detail.reason as ReturnReason] }}
        </el-descriptions-item>
        <el-descriptions-item label="质检人">{{ detail.inspected_by_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="质检时间">{{ fmtDate(detail.inspected_at) }}</el-descriptions-item>
        <el-descriptions-item label="入库人">{{ detail.inbound_by_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="入库时间">{{ fmtDate(detail.inbound_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-alert type="warning" :closable="false" show-icon class="hint">
        四种结论对应四个去处：<b>可再售</b>回到可售库存；<b>次品</b>进次品区；
        <b>待维修</b>进维修区；<b>报损</b>直接出账。次品与维修品永远不参与可售。
      </el-alert>

      <el-table :data="detail.items" border>
        <el-table-column prop="sku_name" label="商品" min-width="160" show-overflow-tooltip />
        <el-table-column label="退货量" width="90" align="right">
          <template #default="{ row }"><b>{{ row.quantity }}</b></template>
        </el-table-column>
        <el-table-column label="已售" width="80" align="right">
          <template #default="{ row }">{{ row.sold_qty }}</template>
        </el-table-column>
        <el-table-column label="可退" width="80" align="right">
          <template #default="{ row }">{{ row.returnable_qty }}</template>
        </el-table-column>
        <el-table-column label="可再售" width="110">
          <template #default="{ row }">
            <el-input-number
              v-if="detail && detail.status === 'pending'"
              v-model="splitOf(row).resellable_qty"
              :min="0"
              :max="row.quantity"
              size="small"
            />
            <span v-else>{{ row.resellable_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="次品" width="110">
          <template #default="{ row }">
            <el-input-number
              v-if="detail && detail.status === 'pending'"
              v-model="splitOf(row).defective_qty"
              :min="0"
              :max="row.quantity"
              size="small"
            />
            <span v-else>{{ row.defective_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="待维修" width="110">
          <template #default="{ row }">
            <el-input-number
              v-if="detail && detail.status === 'pending'"
              v-model="splitOf(row).repair_qty"
              :min="0"
              :max="row.quantity"
              size="small"
            />
            <span v-else>{{ row.repair_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="报损" width="110">
          <template #default="{ row }">
            <el-input-number
              v-if="detail && detail.status === 'pending'"
              v-model="splitOf(row).scrap_qty"
              :min="0"
              :max="row.quantity"
              size="small"
            />
            <span v-else>{{ row.scrap_qty }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结论" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.disposition" size="small">
              {{ DISPOSITION_LABELS[row.disposition as ReturnDisposition] }}
            </el-tag>
            <span v-else class="muted">未质检</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="actions">
        <el-button
          v-if="detail.status === 'pending'"
          type="primary"
          :loading="submitting"
          :disabled="!allMatched"
          @click="inspect"
        >
          提交质检
        </el-button>
        <el-button
          v-if="detail.status === 'inspected'"
          type="success"
          :loading="submitting"
          @click="inbound"
        >
          确认入库
        </el-button>
        <span v-if="detail.status === 'pending' && !allMatched" class="warn">
          各分流数量之和必须等于退货量
        </span>
        <span v-if="detail.status === 'inbound'" class="ok">已入库，可按退货单号反查全部流水</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.desc { margin-bottom: 12px; }
.hint { margin-bottom: 12px; }
.actions { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.muted { color: #909399; }
.warn { color: #e6a23c; font-size: 13px; }
.ok { color: #67c23a; font-size: 13px; }
</style>
