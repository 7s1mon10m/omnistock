<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as productApi from '@/api/product'
import * as warehouseApi from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import type { Bundle, Sku, Spu, Warehouse } from '@/types'

const auth = useAuthStore()

const warehouses = ref<Warehouse[]>([])
const bundleSpus = ref<Spu[]>([])
const bundleSkus = ref<Sku[]>([])
const allSkus = ref<Sku[]>([])
const bundle = ref<Bundle | null>(null)

const selectedWarehouse = ref<number | undefined>(undefined)
const selectedSpu = ref<number | undefined>(undefined)
const selectedSku = ref<number | undefined>(undefined)
const loading = ref(false)

const editVisible = ref(false)
const editRows = ref<{ component_sku_id: number | undefined; quantity: number }[]>([])

/** Only plain SKUs may be a component — nesting is not allowed. */
const componentCandidates = computed(() => allSkus.value.filter((sku) => !sku.is_bundle))

async function bootstrap() {
  try {
    warehouses.value = (await warehouseApi.listWarehouses()).items
    selectedWarehouse.value = warehouses.value[0]?.id
    bundleSpus.value = (await productApi.listSpus({ type: 'bundle', page_size: 100 })).items
    allSkus.value = (await productApi.listSkus({ page_size: 200 })).items
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function onSpuChange() {
  selectedSku.value = undefined
  bundle.value = null
  if (!selectedSpu.value) {
    bundleSkus.value = []
    return
  }
  try {
    bundleSkus.value = (
      await productApi.listSkus({ spu_id: selectedSpu.value, page_size: 100 })
    ).items
    if (bundleSkus.value.length === 1) {
      selectedSku.value = bundleSkus.value[0].id
      await loadBundle()
    }
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function loadBundle() {
  if (!selectedSku.value) {
    bundle.value = null
    return
  }
  loading.value = true
  try {
    bundle.value = await productApi.getBundle(selectedSku.value, selectedWarehouse.value)
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

function openEdit() {
  if (!bundle.value) return
  editRows.value = bundle.value.components.length
    ? bundle.value.components.map((c) => ({
        component_sku_id: c.component_sku_id,
        quantity: c.quantity,
      }))
    : [{ component_sku_id: undefined, quantity: 1 }]
  editVisible.value = true
}

function addRow() {
  editRows.value.push({ component_sku_id: undefined, quantity: 1 })
}

function removeRow(index: number) {
  editRows.value.splice(index, 1)
}

async function saveComponents() {
  if (!selectedSku.value) return
  const payload = editRows.value
    .filter((row) => row.component_sku_id)
    .map((row) => ({ component_sku_id: row.component_sku_id as number, quantity: row.quantity }))

  if (!payload.length) {
    ElMessage.warning('至少配置一个子项')
    return
  }
  try {
    bundle.value = await productApi.setBundleComponents(
      selectedSku.value,
      payload,
      selectedWarehouse.value,
    )
    ElMessage.success('组合商品子项已保存')
    editVisible.value = false
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(bootstrap)
</script>

<template>
  <div>
    <el-card shadow="never" class="block">
      <template #header>
        <span>选择组合商品</span>
        <span class="hint">组合商品自身不持有库存，下单时拆解为子 SKU 占用</span>
      </template>
      <div class="filters">
        <el-select
          v-model="selectedSpu"
          placeholder="选择组合类型商品"
          style="width: 260px"
          @change="onSpuChange"
        >
          <el-option
            v-for="spu in bundleSpus"
            :key="spu.id"
            :label="`${spu.name}（${spu.code}）`"
            :value="spu.id"
          />
        </el-select>
        <el-select
          v-model="selectedSku"
          placeholder="选择 SKU"
          style="width: 220px"
          @change="loadBundle"
        >
          <el-option
            v-for="sku in bundleSkus"
            :key="sku.id"
            :label="sku.sku_code"
            :value="sku.id"
          />
        </el-select>
        <el-select
          v-model="selectedWarehouse"
          placeholder="仓库"
          style="width: 200px"
          @change="loadBundle"
        >
          <el-option
            v-for="w in warehouses"
            :key="w.id"
            :label="`${w.name}（${w.code}）`"
            :value="w.id"
          />
        </el-select>
        <el-button
          v-if="auth.canManageProducts() && bundle"
          type="primary"
          @click="openEdit"
        >
          配置子项
        </el-button>
      </div>
    </el-card>

    <el-card v-if="bundle" shadow="never" v-loading="loading" class="block">
      <template #header>
        <div class="card-header">
          <span>{{ bundle.bundle_name }}（{{ bundle.bundle_sku_code }}）</span>
          <el-tag type="warning">
            当前可组套数：{{ bundle.buildable_qty }}
          </el-tag>
        </div>
      </template>
      <el-table :data="bundle.components" border size="small">
        <el-table-column prop="component_sku_code" label="子 SKU 编码" width="200" />
        <el-table-column prop="component_name" label="子商品名称" min-width="200" />
        <el-table-column prop="quantity" label="每套用量" width="110" align="right" />
        <el-table-column prop="available_qty" label="该仓可售" width="120" align="right" />
      </el-table>
    </el-card>

    <el-empty v-else description="请选择组合商品以查看构成" />

    <el-dialog v-model="editVisible" title="配置组合商品子项" width="620px">
      <el-alert
        title="保存会整体替换子项列表；组合商品不能嵌套组合商品"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <div v-for="(row, index) in editRows" :key="index" class="edit-row">
        <el-select
          v-model="row.component_sku_id"
          placeholder="选择子 SKU"
          style="flex: 1"
          filterable
        >
          <el-option
            v-for="sku in componentCandidates"
            :key="sku.id"
            :label="`${sku.sku_code} — ${sku.display_name}`"
            :value="sku.id"
          />
        </el-select>
        <el-input-number v-model="row.quantity" :min="1" />
        <el-button link type="danger" @click="removeRow(index)">移除</el-button>
      </div>
      <el-button link type="primary" @click="addRow">+ 添加子项</el-button>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveComponents">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: 16px;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.edit-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
</style>
