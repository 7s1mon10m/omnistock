<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as stocktakeApi from '@/api/stocktake'
import {
  STOCKTAKE_STATUS_LABELS,
  STOCKTAKE_STATUS_TAG,
  fmtDate,
  type Stocktake,
  type StocktakeLine,
  type StocktakeStatus,
} from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const detail = ref<Stocktake | null>(null)

// 扫码录入
const barcode = ref('')
const scanQty = ref(0)
const scanning = ref(false)

const id = computed(() => Number(route.params.id))
const editable = computed(() => detail.value?.status === 'draft')

async function load() {
  loading.value = true
  try {
    detail.value = await stocktakeApi.getStocktake(id.value)
  } finally {
    loading.value = false
  }
}

async function countLine(row: StocktakeLine, qty: number) {
  if (!detail.value) return
  try {
    detail.value = await stocktakeApi.countStocktake(detail.value.id, {
      items: [{ stocktake_item_id: row.id, counted_qty: qty }],
    })
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function scan() {
  if (!detail.value || !barcode.value) return
  scanning.value = true
  try {
    detail.value = await stocktakeApi.scanStocktake(detail.value.id, {
      barcode: barcode.value,
      counted_qty: scanQty.value,
    })
    ElMessage.success(`已录入 ${barcode.value}`)
    barcode.value = ''
    scanQty.value = 0
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    scanning.value = false
  }
}

async function submit() {
  if (!detail.value) return
  saving.value = true
  try {
    detail.value = await stocktakeApi.submitStocktake(detail.value.id)
    ElMessage.success('已提交，等待审核')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}

async function approve() {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(
      `确认按实盘数调整库存？净差异 ${detail.value.total_variance} 件，此操作会生成盘点调整流水。`,
      '审核确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    detail.value = await stocktakeApi.approveStocktake(detail.value.id, '审核通过')
    ElMessage.success('已审核并落账')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page">
    <template v-if="detail">
      <div class="toolbar">
        <span class="title">
          盘点单 {{ detail.stocktake_no }}
          <el-tag size="small" :type="STOCKTAKE_STATUS_TAG[detail.status as StocktakeStatus] as never">
            {{ STOCKTAKE_STATUS_LABELS[detail.status as StocktakeStatus] }}
          </el-tag>
        </span>
        <el-button @click="router.push('/stocktakes')">返回列表</el-button>
      </div>

      <el-descriptions :column="5" border class="desc">
        <el-descriptions-item label="仓库">{{ detail.warehouse_name }}</el-descriptions-item>
        <el-descriptions-item label="范围">{{ detail.scope }}</el-descriptions-item>
        <el-descriptions-item label="总行数">{{ detail.total_lines }}</el-descriptions-item>
        <el-descriptions-item label="已盘">{{ detail.counted_lines }}</el-descriptions-item>
        <el-descriptions-item label="净差异">
          <span :class="{ danger: detail.total_variance < 0, gain: detail.total_variance > 0 }">
            {{ detail.total_variance }}
          </span>
        </el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="detail.status === 'draft'"
        type="info"
        :closable="false"
        show-icon
        class="hint"
      >
        录入阶段不会改动任何库存。盘完点「提交」，再由店主审核后才会落账。
      </el-alert>
      <el-alert
        v-if="detail.status === 'submitted'"
        type="warning"
        :closable="false"
        show-icon
        class="hint"
      >
        已提交，等待审核。此刻库存<b>尚未</b>变动。
      </el-alert>

      <div v-if="editable" class="scan">
        <el-input v-model="barcode" placeholder="扫描或输入条码" class="barcode" @keyup.enter="scan" />
        <el-input-number v-model="scanQty" :min="0" placeholder="实盘数" />
        <el-button type="primary" :loading="scanning" @click="scan">录入</el-button>
      </div>

      <el-table :data="detail.items" border>
        <el-table-column prop="sku_code" label="SKU" width="150" />
        <el-table-column prop="sku_name" label="商品" min-width="160" show-overflow-tooltip />
        <el-table-column prop="barcode" label="条码" width="120" />
        <el-table-column prop="book_qty" label="账面" width="90" align="right" />
        <el-table-column label="实盘" width="150">
          <template #default="{ row }">
            <el-input-number
              v-if="editable"
              :model-value="row.counted_qty ?? 0"
              :min="0"
              size="small"
              @change="(value: number) => countLine(row, value)"
            />
            <span v-else>{{ row.counted_qty ?? '未盘' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="差异" width="90" align="right">
          <template #default="{ row }">
            <span :class="{ danger: row.variance_qty < 0, gain: row.variance_qty > 0 }">
              {{ row.variance_qty }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip />
        <el-table-column label="已落账" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.adjusted" size="small" type="success">是</el-tag>
            <span v-else class="muted">否</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="actions">
        <el-button
          v-if="detail.status === 'draft'"
          type="primary"
          :loading="saving"
          :disabled="detail.counted_lines === 0"
          @click="submit"
        >
          提交盘点
        </el-button>
        <el-button
          v-if="detail.status === 'submitted'"
          type="success"
          :loading="saving"
          @click="approve"
        >
          审核并落账
        </el-button>
        <span v-if="detail.status === 'approved'" class="ok">
          已于 {{ fmtDate(detail.approved_at) }} 审核落账
        </span>
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
.scan { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.barcode { width: 260px; }
.actions { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.muted { color: #909399; }
.ok { color: #67c23a; font-size: 13px; }
.danger { color: #f56c6c; }
.gain { color: #67c23a; }
</style>
