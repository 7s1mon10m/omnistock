<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as purchaseApi from '@/api/purchase'
import { useAuthStore } from '@/stores/auth'
import type { Supplier } from '@/types'

const auth = useAuthStore()

const loading = ref(false)
const rows = ref<Supplier[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, page_size: 15 })

const visible = ref(false)
const editing = ref<Supplier | null>(null)
const form = reactive({
  code: '',
  name: '',
  contact_name: '',
  contact_phone: '',
  email: '',
  address: '',
  payment_terms: '',
  lead_time_days: 7,
  remark: '',
})

async function load() {
  loading.value = true
  try {
    const data = await purchaseApi.listSuppliers({
      keyword: query.keyword || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  query.page = 1
  load()
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    code: '',
    name: '',
    contact_name: '',
    contact_phone: '',
    email: '',
    address: '',
    payment_terms: '',
    lead_time_days: 7,
    remark: '',
  })
  visible.value = true
}

function openEdit(row: Supplier) {
  editing.value = row
  Object.assign(form, {
    code: row.code,
    name: row.name,
    contact_name: row.contact_name,
    contact_phone: row.contact_phone,
    email: row.email,
    address: row.address,
    payment_terms: row.payment_terms,
    lead_time_days: row.lead_time_days,
    remark: row.remark,
  })
  visible.value = true
}

async function submit() {
  if (!form.name) {
    ElMessage.warning('请填写供应商名称')
    return
  }
  try {
    if (editing.value) {
      const { code, ...rest } = form
      await purchaseApi.updateSupplier(editing.value.id, rest)
      ElMessage.success('已更新')
    } else {
      await purchaseApi.createSupplier({ ...form, code: form.code || undefined })
      ElMessage.success('供应商已创建')
    }
    visible.value = false
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
      <el-input
        v-model="query.keyword"
        placeholder="编码 / 名称 / 联系人"
        clearable
        style="width: 240px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button v-if="auth.hasRole('admin', 'owner', 'buyer')" type="primary" @click="openCreate">
        新建供应商
      </el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="code" label="编码" width="110" />
      <el-table-column prop="name" label="供应商" min-width="180" />
      <el-table-column prop="contact_name" label="联系人" width="110">
        <template #default="{ row }">{{ row.contact_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="contact_phone" label="电话" width="140">
        <template #default="{ row }">{{ row.contact_phone || '—' }}</template>
      </el-table-column>
      <el-table-column prop="payment_terms" label="结算方式" width="130">
        <template #default="{ row }">{{ row.payment_terms || '—' }}</template>
      </el-table-column>
      <el-table-column label="交期" width="90" align="right">
        <template #default="{ row }">{{ row.lead_time_days }} 天</template>
      </el-table-column>
      <el-table-column label="在途采购单" width="110" align="right">
        <template #default="{ row }">
          <el-tag v-if="row.open_order_count" size="small" type="warning">
            {{ row.open_order_count }}
          </el-tag>
          <span v-else class="muted">0</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '合作中' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.hasRole('admin', 'owner', 'buyer')" label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
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
          load()
        }
      "
    />

    <el-dialog
      v-model="visible"
      :title="editing ? '编辑供应商' : '新建供应商'"
      width="520px"
    >
      <el-form label-width="100px">
        <el-form-item label="供应商编码">
          <el-input v-model="form.code" placeholder="留空自动生成，如 SUP001" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="供应商名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact_name" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="form.contact_phone" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" />
        </el-form-item>
        <el-form-item label="结算方式">
          <el-input v-model="form.payment_terms" placeholder="例如 月结 30 天" />
        </el-form-item>
        <el-form-item label="交期（天）">
          <el-input-number v-model="form.lead_time_days" :min="0" :max="365" />
          <span class="hint">新建采购单时用来推算预计到货日</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
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
.muted {
  color: #c0c4cc;
}
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
