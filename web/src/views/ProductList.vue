<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as productApi from '@/api/product'
import { useAuthStore } from '@/stores/auth'
import type { Sku, Spu } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const spus = ref<Spu[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, page_size: 10 })

// The currently expanded SPU and its SKUs.
const expanded = ref<number | null>(null)
const skusBySpu = ref<Record<number, Sku[]>>({})
const skuLoading = ref(false)

const createVisible = ref(false)
const createForm = reactive({
  code: '',
  name: '',
  category: '',
  brand: '',
  type: 'single' as 'single' | 'bundle',
})
const skuVisible = ref(false)
const skuForm = reactive({
  spu_id: 0,
  sku_code: '',
  color: '',
  size: '',
  barcode: '',
  purchase_price_yuan: 0,
  safety_qty: 0,
})

async function loadSpus() {
  loading.value = true
  try {
    const data = await productApi.listSpus({
      keyword: query.keyword || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    spus.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function onExpand(row: Spu, expandedRows: Spu[]) {
  const isOpen = expandedRows.some((item) => item.id === row.id)
  expanded.value = isOpen ? row.id : null
  if (!isOpen) return

  skuLoading.value = true
  try {
    const data = await productApi.listSkus({ spu_id: row.id, page_size: 200 })
    skusBySpu.value = { ...skusBySpu.value, [row.id]: data.items }
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    skuLoading.value = false
  }
}

function onCreateSpu() {
  createForm.code = ''
  createForm.name = ''
  createForm.category = ''
  createForm.brand = ''
  createForm.type = 'single'
  createVisible.value = true
}

async function submitSpu() {
  if (!createForm.code || !createForm.name) {
    ElMessage.warning('请填写商品编码与名称')
    return
  }
  try {
    await productApi.createSpu({ ...createForm })
    ElMessage.success('商品已创建')
    createVisible.value = false
    await loadSpus()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function onCreateSku(row: Spu) {
  skuForm.spu_id = row.id
  skuForm.sku_code = ''
  skuForm.color = ''
  skuForm.size = ''
  skuForm.barcode = ''
  skuForm.purchase_price_yuan = 0
  skuForm.safety_qty = 0
  skuVisible.value = true
}

async function submitSku() {
  const spec: Record<string, string> = {}
  if (skuForm.color) spec.color = skuForm.color
  if (skuForm.size) spec.size = skuForm.size

  try {
    await productApi.createSku({
      spu_id: skuForm.spu_id,
      sku_code: skuForm.sku_code || undefined,
      spec_json: spec,
      barcode: skuForm.barcode || undefined,
      purchase_price_cents: Math.round(Number(skuForm.purchase_price_yuan) * 100),
      safety_qty: Number(skuForm.safety_qty),
    })
    ElMessage.success('SKU 已创建')
    skuVisible.value = false
    await loadSpus()
    if (expanded.value === skuForm.spu_id) {
      await onExpand({ id: skuForm.spu_id } as Spu, [{ id: skuForm.spu_id } as Spu])
    }
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function goSku(id: number) {
  router.push({ name: 'sku-detail', params: { id } })
}

onMounted(loadSpus)
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索商品编码或名称"
        clearable
        style="width: 240px"
        @keyup.enter="((query.page = 1), loadSpus())"
      />
      <el-button type="primary" @click="((query.page = 1), loadSpus())">查询</el-button>
      <div class="spacer" />
      <el-button v-if="auth.canManageProducts()" type="primary" @click="onCreateSpu">
        新建商品（SPU）
      </el-button>
    </div>

    <el-table
      :data="spus"
      v-loading="loading"
      border
      row-key="id"
      @expand-change="onExpand"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="sku-panel">
            <div class="sku-header">
              <span>SKU 列表（最小库存单元）</span>
              <el-button
                v-if="auth.canManageProducts()"
                size="small"
                type="primary"
                @click="onCreateSku(row)"
              >
                新增 SKU
              </el-button>
            </div>
            <el-table :data="skusBySpu[row.id] ?? []" v-loading="skuLoading" size="small" border>
              <el-table-column prop="sku_code" label="SKU 编码" width="200" />
              <el-table-column prop="display_name" label="完整名称" min-width="180" />
              <el-table-column prop="barcode" label="条码" width="150">
                <template #default="{ row: sku }">
                  <span v-if="sku.barcode">{{ sku.barcode }}</span>
                  <span v-else class="muted">未设置</span>
                </template>
              </el-table-column>
              <el-table-column label="规格" min-width="160">
                <template #default="{ row: sku }">
                  <el-tag
                    v-for="(value, key) in sku.spec_json"
                    :key="key"
                    size="small"
                    class="spec-tag"
                  >
                    {{ key }}: {{ value }}
                  </el-tag>
                  <span v-if="!Object.keys(sku.spec_json).length" class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="采购价" width="110" align="right">
                <template #default="{ row: sku }">
                  ¥{{ (sku.purchase_price_cents / 100).toFixed(2) }}
                </template>
              </el-table-column>
              <el-table-column prop="safety_qty" label="安全库存" width="100" align="right" />
              <el-table-column label="类型" width="90">
                <template #default="{ row: sku }">
                  <el-tag v-if="sku.is_bundle" size="small" type="warning">组合</el-tag>
                  <el-tag v-else size="small">普通</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="{ row: sku }">
                  <el-button link type="primary" @click="goSku(sku.id)">库存详情</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="code" label="商品编码" width="150" />
      <el-table-column prop="name" label="商品名称" min-width="180" />
      <el-table-column prop="category" label="分类" width="110">
        <template #default="{ row }">{{ row.category || '—' }}</template>
      </el-table-column>
      <el-table-column prop="brand" label="品牌" width="120">
        <template #default="{ row }">{{ row.brand || '—' }}</template>
      </el-table-column>
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.type === 'bundle'" type="warning" size="small">组合商品</el-tag>
          <el-tag v-else size="small">普通商品</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sku_count" label="SKU 数" width="90" align="right" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ row.status === 'active' ? '在售' : '已归档' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      :current-page="query.page"
      :page-size="query.page_size"
      @current-change="
        (page: number) => {
          query.page = page
          loadSpus()
        }
      "
    />

    <el-dialog v-model="createVisible" title="新建商品（SPU）" width="480px">
      <el-form label-width="90px">
        <el-form-item label="商品编码" required>
          <el-input v-model="createForm.code" placeholder="例如 TSHIRT" />
        </el-form-item>
        <el-form-item label="商品名称" required>
          <el-input v-model="createForm.name" placeholder="例如 纯棉短袖" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="createForm.type">
            <el-radio value="single">普通商品</el-radio>
            <el-radio value="bundle">组合商品</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="createForm.category" placeholder="例如 服饰" />
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="createForm.brand" placeholder="例如 示例品牌" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitSpu">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="skuVisible" title="新增 SKU" width="480px">
      <el-form label-width="110px">
        <el-form-item label="SKU 编码">
          <el-input v-model="skuForm.sku_code" placeholder="留空则自动生成" />
        </el-form-item>
        <el-form-item label="规格 - 颜色">
          <el-input v-model="skuForm.color" placeholder="例如 白" />
        </el-form-item>
        <el-form-item label="规格 - 尺码">
          <el-input v-model="skuForm.size" placeholder="例如 L" />
        </el-form-item>
        <el-form-item label="条码">
          <el-input v-model="skuForm.barcode" placeholder="条形码 / 二维码" />
        </el-form-item>
        <el-form-item label="采购价（元）">
          <el-input-number v-model="skuForm.purchase_price_yuan" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item label="安全库存">
          <el-input-number v-model="skuForm.safety_qty" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="skuVisible = false">取消</el-button>
        <el-button type="primary" @click="submitSku">创建</el-button>
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
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.sku-panel {
  padding: 8px 16px 16px;
}
.sku-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}
.spec-tag {
  margin-right: 4px;
}
.muted {
  color: #c0c4cc;
}
</style>
