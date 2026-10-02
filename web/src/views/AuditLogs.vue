<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as reportApi from '@/api/report'
import { fmtDate, type AuditLog } from '@/types'

const loading = ref(false)
const rows = ref<AuditLog[]>([])
const total = ref(0)

const query = reactive({
  actor: '',
  action: '',
  resource: '',
  resource_id: '',
  page: 1,
  page_size: 20,
})

const detailVisible = ref(false)
const current = ref<AuditLog | null>(null)

async function load() {
  loading.value = true
  try {
    const page = await reportApi.listAuditLogs({
      actor: query.actor || undefined,
      action: query.action || undefined,
      resource: query.resource || undefined,
      resource_id: query.resource_id || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = page.items
    total.value = page.total
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    loading.value = false
  }
}

function reset() {
  query.actor = ''
  query.action = ''
  query.resource = ''
  query.resource_id = ''
  query.page = 1
  void load()
}

function open(row: AuditLog) {
  current.value = row
  detailVisible.value = true
}

const STATUS_TAG = (code: number) => (code >= 400 ? 'danger' : 'success')

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">审计日志</span>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      只记录<b>成功的写操作</b>（POST / PUT / PATCH / DELETE 且返回 2xx）。被拒绝的操作什么都没改，
      不该污染审计流。登录与令牌刷新不进这里 —— 避免把凭据写进一张可查询的表。
      <b>审计表只读</b>，没有也不该有更新与删除接口。
    </el-alert>

    <el-form :inline="true" class="filters">
      <el-form-item label="操作人">
        <el-input v-model="query.actor" placeholder="用户名" clearable style="width: 140px" />
      </el-form-item>
      <el-form-item label="动作">
        <el-input v-model="query.action" placeholder="如 inventory" clearable style="width: 150px" />
      </el-form-item>
      <el-form-item label="资源">
        <el-input v-model="query.resource" placeholder="如 shipments" clearable style="width: 150px" />
      </el-form-item>
      <el-form-item label="资源 ID">
        <el-input v-model="query.resource_id" clearable style="width: 110px" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border @row-click="open">
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="actor_name" label="操作人" width="130" />
      <el-table-column prop="action" label="动作" width="160" />
      <el-table-column label="资源对象" width="180">
        <template #default="{ row }">
          <span v-if="row.resource_id">{{ row.resource_type }}#{{ row.resource_id }}</span>
          <span v-else>{{ row.resource_type }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="接口" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" width="90" align="right">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_TAG(row.status_code) as never">{{ row.status_code }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="来源 IP" width="130" />
      <template #empty><span class="muted">没有匹配的审计记录</span></template>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />

    <el-dialog v-model="detailVisible" title="审计详情" width="600px">
      <el-descriptions v-if="current" :column="2" border>
        <el-descriptions-item label="操作人">{{ current.actor_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="动作">{{ current.action }}</el-descriptions-item>
        <el-descriptions-item label="资源">{{ current.resource_type }}#{{ current.resource_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ current.status_code }}</el-descriptions-item>
        <el-descriptions-item label="接口" :span="2">{{ current.method }} {{ current.path }}</el-descriptions-item>
        <el-descriptions-item label="来源 IP">{{ current.ip || '-' }}</el-descriptions-item>
        <el-descriptions-item label="请求 ID">{{ current.request_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="时间" :span="2">{{ fmtDate(current.created_at) }}</el-descriptions-item>
      </el-descriptions>
      <el-divider content-position="left">摘要</el-divider>
      <p class="summary">{{ current?.summary }}</p>
      <el-divider content-position="left">请求体预览</el-divider>
      <pre class="preview">{{ current?.detail ? JSON.stringify(current.detail, null, 2) : '（无）' }}</pre>
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
.summary { color: #303133; margin: 0; }
.preview { background: #f5f7fa; padding: 10px; border-radius: 4px; font-size: 12px; margin: 0; overflow: auto; max-height: 240px; }
</style>
