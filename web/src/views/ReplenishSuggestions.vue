<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as alertApi from '@/api/alert'
import * as supplierApi from '@/api/purchase'
import {
  SUGGESTION_STATUS_LABELS,
  fmtDate,
  type ReplenishSuggestion,
  type SuggestionStatus,
  type Supplier,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const generating = ref(false)
const rows = ref<ReplenishSuggestion[]>([])
const total = ref(0)
const suppliers = ref<Supplier[]>([])

const query = reactive({
  status: undefined as SuggestionStatus | undefined,
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(SUGGESTION_STATUS_LABELS) as [SuggestionStatus, string][]

const visible = ref(false)
const target = ref<ReplenishSuggestion | null>(null)
const form = reactive({
  supplier_id: undefined as number | undefined,
  quantity: undefined as number | undefined,
  unit_price_cents: 0,
})

async function load() {
  loading.value = true
  try {
    const page = await alertApi.listSuggestions(query)
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  try {
    const created = await alertApi.generateSuggestions()
    ElMessage.success(created.length ? `生成 ${created.length} 条建议` : '当前没有需要补货的 SKU')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    generating.value = false
  }
}

function openConvert(row: ReplenishSuggestion) {
  target.value = row
  form.supplier_id = row.supplier_id ?? undefined
  form.quantity = row.suggested_qty
  form.unit_price_cents = 0
  visible.value = true
}

async function convert() {
  if (!target.value) return
  try {
    const result = await alertApi.suggestionToPurchaseOrder(target.value.id, {
      supplier_id: form.supplier_id,
      quantity: form.quantity,
      unit_price_cents: form.unit_price_cents || undefined,
    })
    ElMessage.success('已生成采购单草稿')
    visible.value = false
    const po = result.purchase_order as { id?: number }
    if (po?.id) {
      router.push({ name: 'purchase-detail', params: { id: po.id } })
      return
    }
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function dismiss(row: ReplenishSuggestion) {
  try {
    await ElMessageBox.confirm(`忽略「${row.sku_name || row.sku_code}」的补货建议？`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await alertApi.dismissSuggestion(row.id)
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

onMounted(async () => {
  suppliers.value = (await supplierApi.listSuppliers({ page_size: 200 })).items
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">补货建议</span>
      <el-button type="primary" :loading="generating" @click="generate">生成建议</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      公式：<b>建议采购量 = 预测销量 + 安全库存 − 可售库存 − 在途库存</b>。
      在途已下单的货会扣掉，避免重复采购；结果为负则不生成建议。
      生成的采购单是<b>草稿</b>——建议只是数字，下单仍要人来确认。
    </el-alert>

    <el-form :inline="true" class="filters">
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 140px">
          <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button @click="load">查询</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="suggestion_no" label="建议号" width="130" />
      <el-table-column prop="sku_name" label="商品" min-width="150" show-overflow-tooltip />
      <el-table-column prop="warehouse_name" label="仓库" width="110" />
      <el-table-column prop="supplier_name" label="建议供应商" width="130">
        <template #default="{ row }">
          <span v-if="row.supplier_name">{{ row.supplier_name }}</span>
          <span v-else class="muted">未指定</span>
        </template>
      </el-table-column>
      <el-table-column label="日均销量" width="90" align="right">
        <template #default="{ row }">{{ row.avg_daily_sales.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="forecast_qty" label="预测销量" width="90" align="right" />
      <el-table-column prop="safety_qty" label="安全库存" width="90" align="right" />
      <el-table-column prop="available_qty" label="可售" width="80" align="right" />
      <el-table-column prop="in_transit_qty" label="在途" width="80" align="right" />
      <el-table-column label="建议采购" width="100" align="right">
        <template #default="{ row }">
          <b class="strong">{{ row.suggested_qty }}</b>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'open' ? 'warning' : 'info'">
            {{ SUGGESTION_STATUS_LABELS[row.status as SuggestionStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="生成时间" width="150">
        <template #default="{ row }">{{ fmtDate(row.generated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'open'">
            <el-button link type="primary" @click="openConvert(row)">转采购单</el-button>
            <el-button link @click="dismiss(row)">忽略</el-button>
          </template>
          <span v-else class="muted">已处理</span>
        </template>
      </el-table-column>
      <template #empty>
        <span class="muted">暂无建议 —— 点「生成建议」按当前库存算一遍</span>
      </template>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />

    <el-dialog v-model="visible" title="转为采购单" width="460px">
      <el-form label-width="110px">
        <el-form-item label="供应商" required>
          <el-select v-model="form.supplier_id" style="width: 100%">
            <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="采购数量">
          <el-input-number v-model="form.quantity" :min="1" />
        </el-form-item>
        <el-form-item label="单价（分）">
          <el-input-number v-model="form.unit_price_cents" :min="0" />
        </el-form-item>
      </el-form>
      <p class="note">生成的是<b>草稿</b>采购单，仍需你确认后再下单。</p>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="convert">生成</el-button>
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
.strong { color: #409eff; font-size: 15px; }
.note { color: #606266; font-size: 13px; margin: 0; }
</style>
