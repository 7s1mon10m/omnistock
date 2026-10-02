<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as reportApi from '@/api/report'
import * as channelApi from '@/api/channel'
import {
  fmtDate,
  type AdapterDescriptor,
  type AdapterSyncResult,
  type Channel,
  type ChannelAdapter,
} from '@/types'

const loading = ref(false)
const rows = ref<ChannelAdapter[]>([])
const channels = ref<Channel[]>([])
const descriptors = ref<AdapterDescriptor[]>([])

const visible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  channel_id: undefined as number | undefined,
  adapter_key: '',
  enabled: true,
  sync_interval_minutes: 30,
  remark: '',
})

// 手动同步：粘贴一段平台响应
const syncVisible = ref(false)
const syncTarget = ref<ChannelAdapter | null>(null)
const syncPayload = ref('')
const syncResult = ref<AdapterSyncResult | null>(null)

const SAMPLE = JSON.stringify(
  {
    orders: [
      {
        tid: 'TB-100001',
        pay_time: '2026-10-02 10:00:00',
        buyer_nick: '买家甲',
        orders: [{ outer_sku_id: 'SKU-DEMO', num: 2, price: '99.00' }],
      },
    ],
  },
  null,
  2,
)

async function load() {
  loading.value = true
  try {
    rows.value = await reportApi.listChannelAdapters()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.channel_id = undefined
  form.adapter_key = ''
  form.enabled = true
  form.sync_interval_minutes = 30
  form.remark = ''
  visible.value = true
}

function openEdit(row: ChannelAdapter) {
  editingId.value = row.id
  form.channel_id = row.channel_id
  form.adapter_key = row.adapter_key
  form.enabled = row.enabled
  form.sync_interval_minutes = row.sync_interval_minutes
  form.remark = row.remark
  visible.value = true
}

async function submit() {
  if (!form.channel_id || !form.adapter_key) {
    ElMessage.warning('请选择渠道与适配器')
    return
  }
  try {
    if (editingId.value) {
      await reportApi.updateChannelAdapter(editingId.value, {
        adapter_key: form.adapter_key,
        enabled: form.enabled,
        sync_interval_minutes: form.sync_interval_minutes,
        remark: form.remark,
      })
    } else {
      await reportApi.createChannelAdapter({
        channel_id: form.channel_id,
        adapter_key: form.adapter_key,
        enabled: form.enabled,
        sync_interval_minutes: form.sync_interval_minutes,
        remark: form.remark,
      })
    }
    ElMessage.success('已保存')
    visible.value = false
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

async function toggle(row: ChannelAdapter) {
  try {
    await reportApi.updateChannelAdapter(row.id, { enabled: !row.enabled })
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

function openSync(row: ChannelAdapter) {
  syncTarget.value = row
  syncPayload.value = SAMPLE
  syncResult.value = null
  syncVisible.value = true
}

async function runSync() {
  if (!syncTarget.value) return
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(syncPayload.value)
  } catch {
    ElMessage.warning('JSON 格式不正确')
    return
  }
  try {
    syncResult.value = await reportApi.syncChannelAdapter(syncTarget.value.id, payload)
    ElMessage.success('同步完成')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  }
}

const STATUS_TAG: Record<string, string> = {
  never: 'info',
  ok: 'success',
  partial: 'warning',
  failed: 'danger',
}

onMounted(async () => {
  descriptors.value = await reportApi.listDescriptors()
  channels.value = (await channelApi.listChannels({ page_size: 200 })).items
  await load()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span class="title">渠道适配器</span>
      <el-button type="primary" @click="openCreate">新增配置</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      适配器是代码，这里只配置<b>某个渠道用哪个适配器</b>。接一个新平台 = 加一个适配器类 + 建一条配置，
      下游的占用、去重、异常逻辑完全不需要改动。渠道身份由配置决定，平台响应里没有也不影响。
    </el-alert>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="channel_name" label="渠道" width="160" />
      <el-table-column prop="channel_code" label="渠道编码" width="120" />
      <el-table-column prop="adapter_key" label="适配器" width="110" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="上次同步" width="160">
        <template #default="{ row }">{{ fmtDate(row.last_sync_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_TAG[row.last_sync_status] as never">
            {{ row.last_sync_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_sync_message" label="结果" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openSync(row)">同步</el-button>
          <el-button link @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty><span class="muted">还没有配置任何渠道适配器</span></template>
    </el-table>

    <el-dialog v-model="visible" :title="editingId ? '编辑适配器' : '新增适配器'" width="480px">
      <el-form label-width="110px">
        <el-form-item label="渠道" required>
          <el-select v-model="form.channel_id" filterable style="width: 100%">
            <el-option v-for="c in channels" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="适配器" required>
          <el-select v-model="form.adapter_key" style="width: 100%">
            <el-option
              v-for="d in descriptors.filter((item) => item.kind === 'api')"
              :key="d.key"
              :label="d.key"
              :value="d.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="同步间隔(分)">
          <el-input-number v-model="form.sync_interval_minutes" :min="1" />
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

    <el-dialog v-model="syncVisible" :title="`手动同步 · ${syncTarget?.adapter_key ?? ''}`" width="620px">
      <p class="note">
        粘贴平台返回的原始响应。同一批订单重复推送不会重复占用库存。
      </p>
      <el-input v-model="syncPayload" type="textarea" :rows="10" spellcheck="false" />
      <el-alert
        v-if="syncResult"
        :type="syncResult.created_orders ? 'success' : 'info'"
        :closable="false"
        class="result"
      >
        新建 {{ syncResult.created_orders }} · 重复 {{ syncResult.duplicate_orders }} ·
        失败 {{ syncResult.failed_rows }}
      </el-alert>
      <template #footer>
        <el-button @click="syncVisible = false">关闭</el-button>
        <el-button type="primary" @click="runSync">开始同步</el-button>
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
.note { color: #909399; font-size: 12px; margin: 0 0 8px; }
.result { margin-top: 12px; }
</style>
