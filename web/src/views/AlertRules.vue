<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as alertApi from '@/api/alert'
import * as productApi from '@/api/product'
import * as warehouseApi from '@/api/warehouse'
import {
  ALERT_SCOPE_LABELS,
  type AlertRule,
  type AlertRuleScope,
  type Sku,
  type Warehouse,
} from '@/types'

const loading = ref(false)
const rows = ref<AlertRule[]>([])
const warehouses = ref<Warehouse[]>([])
const skuOptions = ref<Sku[]>([])

const visible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  name: '',
  scope: 'global' as AlertRuleScope,
  spu_id: undefined as number | undefined,
  sku_id: undefined as number | undefined,
  warehouse_id: undefined as number | undefined,
  threshold_qty: undefined as number | undefined,
  enabled: true,
  notify_channels: '',
  remark: '',
})

const SCOPE_OPTIONS = Object.entries(ALERT_SCOPE_LABELS) as [AlertRuleScope, string][]

async function load() {
  loading.value = true
  try {
    rows.value = await alertApi.listAlertRules()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    scope: 'global',
    spu_id: undefined,
    sku_id: undefined,
    warehouse_id: undefined,
    threshold_qty: undefined,
    enabled: true,
    notify_channels: '',
    remark: '',
  })
  visible.value = true
}

function openEdit(row: AlertRule) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    scope: row.scope,
    spu_id: row.spu_id ?? undefined,
    sku_id: row.sku_id ?? undefined,
    warehouse_id: row.warehouse_id ?? undefined,
    threshold_qty: row.threshold_qty ?? undefined,
    enabled: row.enabled,
    notify_channels: row.notify_channels,
    remark: row.remark,
  })
  visible.value = true
}

async function submit() {
  try {
    const payload: alertApi.AlertRuleIn = {
      name: form.name,
      scope: form.scope,
      spu_id: form.scope === 'category' ? form.spu_id : null,
      sku_id: form.scope === 'sku' ? form.sku_id : null,
      warehouse_id: form.scope === 'warehouse' ? form.warehouse_id : null,
      threshold_qty: form.threshold_qty ?? null,
      enabled: form.enabled,
      notify_channels: form.notify_channels,
      remark: form.remark,
    }
    if (editingId.value) {
      await alertApi.updateAlertRule(editingId.value, {
        name: payload.name,
        threshold_qty: payload.threshold_qty,
        enabled: payload.enabled,
        notify_channels: payload.notify_channels,
        remark: payload.remark,
      })
    } else {
      await alertApi.createAlertRule(payload)
    }
    ElMessage.success('已保存')
    visible.value = false
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function toggle(row: AlertRule) {
  try {
    await alertApi.updateAlertRule(row.id, { enabled: !row.enabled })
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function remove(row: AlertRule) {
  try {
    await ElMessageBox.confirm(`删除规则「${row.name}」？已产生的预警不受影响。`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await alertApi.deleteAlertRule(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function searchSkus(keyword: string) {
  skuOptions.value = (await productApi.listSkus({ keyword: keyword || undefined, page_size: 50 })).items
}

onMounted(async () => {
  warehouses.value = (await warehouseApi.listWarehouses({ page_size: 200 })).items
  await searchSkus('')
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">预警规则</span>
      <el-button type="primary" @click="openCreate">新建规则</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      规则按「范围越窄越优先」生效：按 SKU &gt; 按品类 &gt; 按仓库 &gt; 全局。
      没有给阈值时沿用 SKU 自己的安全库存；安全库存为 0 的 SKU 不会被判定为低库存。
    </el-alert>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="name" label="规则名称" min-width="140" />
      <el-table-column label="范围" width="100">
        <template #default="{ row }">
          <el-tag size="small">{{ ALERT_SCOPE_LABELS[row.scope as AlertRuleScope] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="目标" min-width="160">
        <template #default="{ row }">
          <span v-if="row.sku_code">{{ row.sku_code }}</span>
          <span v-else-if="row.spu_name">{{ row.spu_name }}</span>
          <span v-else-if="row.warehouse_name">{{ row.warehouse_name }}</span>
          <span v-else class="muted">全部 SKU</span>
        </template>
      </el-table-column>
      <el-table-column label="阈值" width="110">
        <template #default="{ row }">
          <span v-if="row.threshold_qty !== null">{{ row.threshold_qty }}</span>
          <span v-else class="muted">沿用 SKU</span>
        </template>
      </el-table-column>
      <el-table-column label="通知通道" width="140">
        <template #default="{ row }">
          <span v-if="row.notify_channels">{{ row.notify_channels }}</span>
          <span v-else class="muted">系统默认</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="visible" :title="editingId ? '编辑规则' : '新建规则'" width="520px">
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：核心 SKU 低库存" />
        </el-form-item>
        <el-form-item label="范围">
          <el-select v-model="form.scope">
            <el-option v-for="[value, label] in SCOPE_OPTIONS" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.scope === 'sku'" label="SKU" required>
          <el-select v-model="form.sku_id" filterable remote :remote-method="searchSkus" style="width: 100%">
            <el-option v-for="sku in skuOptions" :key="sku.id" :label="sku.sku_code" :value="sku.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.scope === 'warehouse'" label="仓库" required>
          <el-select v-model="form.warehouse_id" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="安全库存阈值">
          <el-input-number v-model="form.threshold_qty" :min="0" :controls="false" />
          <span class="muted inline">留空则沿用 SKU 自身的安全库存</span>
        </el-form-item>
        <el-form-item label="通知通道">
          <el-input v-model="form.notify_channels" placeholder="inapp,email,webhook（留空用系统默认）" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.title { font-size: 16px; font-weight: 600; }
.hint { margin-bottom: 12px; }
.muted { color: #909399; }
.inline { margin-left: 8px; font-size: 12px; }
</style>
