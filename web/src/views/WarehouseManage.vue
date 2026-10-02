<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as warehouseApi from '@/api/warehouse'
import { useAuthStore } from '@/stores/auth'
import { WAREHOUSE_TYPE_LABELS, type Warehouse, type WarehouseLocation } from '@/types'

const auth = useAuthStore()

const loading = ref(false)
const warehouses = ref<Warehouse[]>([])
const locationsByWarehouse = ref<Record<number, WarehouseLocation[]>>({})
const locationLoading = ref(false)

const createVisible = ref(false)
const createForm = reactive({
  code: '',
  name: '',
  type: 'main' as Warehouse['type'],
  address: '',
  contact_name: '',
  contact_phone: '',
})

const locationVisible = ref(false)
const locationForm = reactive({ warehouse_id: 0, code: '', name: '', zone: '' })

async function load() {
  loading.value = true
  try {
    warehouses.value = (await warehouseApi.listWarehouses()).items
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function onExpand(row: Warehouse, expandedRows: Warehouse[]) {
  if (!expandedRows.some((item) => item.id === row.id)) return
  locationLoading.value = true
  try {
    const list = await warehouseApi.listLocations(row.id)
    locationsByWarehouse.value = { ...locationsByWarehouse.value, [row.id]: list }
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    locationLoading.value = false
  }
}

function openCreate() {
  createForm.code = ''
  createForm.name = ''
  createForm.type = 'main'
  createForm.address = ''
  createForm.contact_name = ''
  createForm.contact_phone = ''
  createVisible.value = true
}

async function submitCreate() {
  if (!createForm.name) {
    ElMessage.warning('请填写仓库名称')
    return
  }
  try {
    await warehouseApi.createWarehouse({
      code: createForm.code || undefined,
      name: createForm.name,
      type: createForm.type,
      address: createForm.address,
      contact_name: createForm.contact_name,
      contact_phone: createForm.contact_phone,
    } as Partial<Warehouse>)
    ElMessage.success('仓库已创建')
    createVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openLocation(row: Warehouse) {
  locationForm.warehouse_id = row.id
  locationForm.code = ''
  locationForm.name = ''
  locationForm.zone = ''
  locationVisible.value = true
}

async function submitLocation() {
  if (!locationForm.code) {
    ElMessage.warning('请填写库位编码')
    return
  }
  try {
    await warehouseApi.createLocation(locationForm.warehouse_id, {
      code: locationForm.code,
      name: locationForm.name,
      zone: locationForm.zone,
    })
    ElMessage.success('库位已创建')
    locationVisible.value = false
    const list = await warehouseApi.listLocations(locationForm.warehouse_id)
    locationsByWarehouse.value = {
      ...locationsByWarehouse.value,
      [locationForm.warehouse_id]: list,
    }
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <span class="hint">总仓 / 直播间仓 / 退货仓，各自独立维护库存</span>
      <div class="spacer" />
      <el-button v-if="auth.canManageWarehouse()" type="primary" @click="openCreate">
        新建仓库
      </el-button>
    </div>

    <el-table :data="warehouses" v-loading="loading" border row-key="id" @expand-change="onExpand">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="location-panel">
            <div class="location-header">
              <span>库位</span>
              <el-button
                v-if="auth.canManageWarehouse()"
                size="small"
                type="primary"
                @click="openLocation(row)"
              >
                新增库位
              </el-button>
            </div>
            <el-table
              :data="locationsByWarehouse[row.id] ?? []"
              v-loading="locationLoading"
              size="small"
              border
            >
              <el-table-column prop="code" label="库位编码" width="160" />
              <el-table-column prop="name" label="库位名称" min-width="160" />
              <el-table-column prop="zone" label="分区" width="140" />
              <el-table-column label="状态" width="90">
                <template #default="{ row: loc }">
                  <el-tag :type="loc.is_active ? 'success' : 'info'" size="small">
                    {{ loc.is_active ? '启用' : '停用' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="code" label="仓库编码" width="140" />
      <el-table-column prop="name" label="仓库名称" min-width="150" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small">{{ WAREHOUSE_TYPE_LABELS[row.type as Warehouse['type']] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="address" label="地址" min-width="160">
        <template #default="{ row }">{{ row.address || '—' }}</template>
      </el-table-column>
      <el-table-column prop="contact_name" label="联系人" width="110">
        <template #default="{ row }">{{ row.contact_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="location_count" label="库位数" width="90" align="right" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="新建仓库" width="480px">
      <el-form label-width="90px">
        <el-form-item label="仓库编码">
          <el-input v-model="createForm.code" placeholder="留空自动生成，如 WH-001" />
        </el-form-item>
        <el-form-item label="仓库名称" required>
          <el-input v-model="createForm.name" placeholder="例如 总仓" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.type" style="width: 100%">
            <el-option label="总仓" value="main" />
            <el-option label="直播间仓" value="live" />
            <el-option label="退货仓" value="return" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="createForm.address" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="createForm.contact_name" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="createForm.contact_phone" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="locationVisible" title="新增库位" width="440px">
      <el-form label-width="90px">
        <el-form-item label="库位编码" required>
          <el-input v-model="locationForm.code" placeholder="例如 A-01" />
        </el-form-item>
        <el-form-item label="库位名称">
          <el-input v-model="locationForm.name" />
        </el-form-item>
        <el-form-item label="分区">
          <el-input v-model="locationForm.zone" placeholder="例如 A" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="locationVisible = false">取消</el-button>
        <el-button type="primary" @click="submitLocation">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
.hint {
  font-size: 13px;
  color: #909399;
}
.location-panel {
  padding: 8px 16px 16px;
}
.location-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}
</style>
