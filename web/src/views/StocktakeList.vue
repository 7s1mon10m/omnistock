<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as stocktakeApi from '@/api/stocktake'
import * as warehouseApi from '@/api/warehouse'
import {
  STOCKTAKE_STATUS_LABELS,
  STOCKTAKE_STATUS_TAG,
  fmtDate,
  type StocktakeListItem,
  type StocktakeStatus,
  type Warehouse,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const rows = ref<StocktakeListItem[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])

const query = reactive({
  status: undefined as StocktakeStatus | undefined,
  warehouse_id: undefined as number | undefined,
  page: 1,
  page_size: 15,
})

const visible = ref(false)
const form = reactive({
  warehouse_id: undefined as number | undefined,
  scope: '全部',
  remark: '',
})

const STATUS_OPTIONS = Object.entries(STOCKTAKE_STATUS_LABELS) as [StocktakeStatus, string][]

async function load() {
  loading.value = true
  try {
    const page = await stocktakeApi.listStocktakes(query)
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.warehouse_id) {
    ElMessage.warning('请选择仓库')
    return
  }
  try {
    const created = await stocktakeApi.createStocktake({
      warehouse_id: form.warehouse_id,
      scope: form.scope,
      remark: form.remark,
    })
    ElMessage.success(`盘点单 ${created.stocktake_no} 已创建，共 ${created.items.length} 行`)
    visible.value = false
    router.push(`/stocktakes/${created.id}`)
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function cancel(row: StocktakeListItem) {
  try {
    await ElMessageBox.confirm(`取消盘点单 ${row.stocktake_no}？已审核的不能取消。`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await stocktakeApi.cancelStocktake(row.id, '人工取消')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

onMounted(async () => {
  warehouses.value = (await warehouseApi.listWarehouses({ page_size: 200 })).items
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">盘点任务</span>
      <el-button type="primary" @click="visible = true">发起盘点</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      盘盈盘亏会直接改写库存，而库存是所有下游决策的基础。所以差异必须
      <b>先提交、再审核</b>才落账 —— 未审核前盘点到什么程度都不会动库存。
    </el-alert>

    <el-form :inline="true" class="filters">
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 120px">
          <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库">
        <el-select v-model="query.warehouse_id" clearable placeholder="全部" style="width: 140px">
          <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </el-form-item>
      <el-form-item><el-button @click="load">查询</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="stocktake_no" label="盘点单号" width="130" />
      <el-table-column prop="warehouse_name" label="仓库" width="140" />
      <el-table-column prop="scope" label="范围" width="120" />
      <el-table-column label="进度" width="140">
        <template #default="{ row }">
          <el-progress
            :percentage="row.total_lines ? Math.round((row.counted_lines / row.total_lines) * 100) : 0"
            :stroke-width="14"
            :text-inside="true"
          />
        </template>
      </el-table-column>
      <el-table-column label="差异行" width="90" align="right">
        <template #default="{ row }">
          <span :class="{ danger: row.variance_lines > 0 }">{{ row.variance_lines }}</span>
        </template>
      </el-table-column>
      <el-table-column label="净差异" width="90" align="right">
        <template #default="{ row }">
          <span :class="{ danger: row.total_variance < 0, gain: row.total_variance > 0 }">
            {{ row.total_variance }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="STOCKTAKE_STATUS_TAG[row.status as StocktakeStatus] as never">
            {{ STOCKTAKE_STATUS_LABELS[row.status as StocktakeStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/stocktakes/${row.id}`)">
            {{ row.status === 'draft' ? '去盘点' : '详情' }}
          </el-button>
          <el-button
            v-if="row.status !== 'approved' && row.status !== 'cancelled'"
            link
            type="danger"
            @click="cancel(row)"
          >
            取消
          </el-button>
        </template>
      </el-table-column>
      <template #empty><span class="muted">暂无盘点任务</span></template>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />

    <el-dialog v-model="visible" title="发起盘点" width="460px">
      <el-form label-width="90px">
        <el-form-item label="仓库" required>
          <el-select v-model="form.warehouse_id" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="范围">
          <el-input v-model="form.scope" placeholder="例如：A 区 / 全部" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <p class="note">建单时会冻结当前账面数量作为快照，之后发生的出入库不影响这个快照。</p>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
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
.note { color: #909399; font-size: 12px; margin: 0; }
.danger { color: #f56c6c; }
.gain { color: #67c23a; }
</style>
