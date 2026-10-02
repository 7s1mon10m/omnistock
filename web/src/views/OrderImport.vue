<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as channelApi from '@/api/channel'
import * as orderApi from '@/api/order'
import { useAuthStore } from '@/stores/auth'
import {
  SYNC_RESULT_LABELS,
  type Channel,
  type ImportBatch,
  type ImportResult,
  type SyncLog,
} from '@/types'

const router = useRouter()
const auth = useAuthStore()

const activeTab = ref('upload')

// ------------------------------------------------------------------- upload
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const result = ref<ImportResult | null>(null)

// --------------------------------------------------------------- paste JSON
const jsonText = ref('')
const jsonSubmitting = ref(false)
const jsonResult = ref<ImportResult | null>(null)
const jsonError = ref('')

// --------------------------------------------------------------- history
const batches = ref<ImportBatch[]>([])
const logs = ref<SyncLog[]>([])
const channels = ref<Channel[]>([])
const logQuery = reactive({ channel_order_no: '', result: '' })

const SAMPLE_JSON = computed(() =>
  JSON.stringify(
    [
      {
        channel_code: 'TB',
        shop_code: 'TB-SHOP-1',
        channel_order_no: 'TB202610020099',
        buyer_nick: '示例买家',
        items: [{ channel_product_code: 'TB-100238', quantity: 2, unit_price_cents: 9900 }],
      },
    ],
    null,
    2,
  ),
)

function pickFile(file: File | null) {
  selectedFile.value = file
  result.value = null
}

async function submitFile() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择 CSV 或 JSON 文件')
    return
  }
  uploading.value = true
  try {
    result.value = await orderApi.importOrdersFile(selectedFile.value)
    ElMessage.success(`导入完成：新增 ${result.value.created_orders} 笔`)
    await loadHistory()
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    uploading.value = false
  }
}

async function submitJson() {
  jsonError.value = ''
  jsonResult.value = null
  let parsed: unknown
  try {
    parsed = JSON.parse(jsonText.value)
  } catch {
    jsonError.value = 'JSON 格式不正确'
    return
  }
  const orders = Array.isArray(parsed) ? parsed : (parsed as { orders?: unknown[] }).orders
  if (!Array.isArray(orders) || !orders.length) {
    jsonError.value = '需要一个非空的订单数组，或用 {"orders": [...]} 包裹'
    return
  }
  jsonSubmitting.value = true
  try {
    jsonResult.value = await orderApi.importOrdersJson({
      filename: 'pasted.json',
      source: 'import_json',
      orders,
    })
    ElMessage.success(`导入完成：新增 ${jsonResult.value.created_orders} 笔`)
    await loadHistory()
  } catch (err) {
    jsonError.value = describeError(err)
  } finally {
    jsonSubmitting.value = false
  }
}

function fillSample() {
  jsonText.value = SAMPLE_JSON.value
}

async function loadHistory() {
  try {
    batches.value = (await orderApi.listImportBatches({ page_size: 10 })).items
    logs.value = (
      await orderApi.listSyncLogs({
        channel_order_no: logQuery.channel_order_no || undefined,
        result: logQuery.result || undefined,
        page_size: 15,
      })
    ).items
    channels.value = (await channelApi.listChannels()).items
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openOrder(orderId: number | null) {
  if (orderId) router.push({ name: 'order-detail', params: { id: orderId } })
}

onMounted(loadHistory)
</script>

<template>
  <div>
    <el-alert
      title="订单从这里进入系统：唯一约束 (渠道 + 渠道单号) 保证重复同步不会重复扣库存；缺货的订单会进入异常队列"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="activeTab">
      <!-- ------------------------------------------------------------ file -->
      <el-tab-pane label="上传文件" name="upload">
        <el-card shadow="never">
          <div class="upload-row">
            <input
              type="file"
              accept=".csv,.json,.txt"
              @change="
                (event: Event) => {
                  const target = event.target as HTMLInputElement
                  pickFile(target.files?.[0] ?? null)
                }
              "
            />
            <el-button
              v-if="auth.canManageProducts()"
              type="primary"
              :loading="uploading"
              @click="submitFile"
            >
              开始导入
            </el-button>
            <el-link :href="orderApi.TEMPLATE_URL" target="_blank" type="primary">
              下载 CSV 模板
            </el-link>
          </div>

          <el-descriptions :column="1" border size="small" class="tips">
            <el-descriptions-item label="CSV 列">
              channel_code, shop_code, channel_order_no, channel_product_code, quantity,
              unit_price, buyer_nick, warehouse_code, paid_at
            </el-descriptions-item>
            <el-descriptions-item label="说明">
              同一 (渠道, 店铺, 渠道单号) 的多行会合并成一张订单；
              unit_price 单位为元，paid_at 可留空（默认视为已付款并立即占用库存）
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card v-if="result" shadow="never" class="result">
          <template #header><span>导入结果</span></template>
          <div class="metrics">
            <div class="metric"><span>总行数</span><b>{{ result.total_rows }}</b></div>
            <div class="metric"><span>新增订单</span><b>{{ result.created_orders }}</b></div>
            <div class="metric"><span>重复同步</span><b>{{ result.duplicate_orders }}</b></div>
            <div class="metric"><span>失败</span><b class="bad">{{ result.failed_rows }}</b></div>
            <div class="metric"><span>已占用</span><b>{{ result.reserved_orders }}</b></div>
            <div class="metric"><span>异常</span><b class="warn">{{ result.exception_orders }}</b></div>
          </div>
          <el-table v-if="result.errors.length" :data="result.errors" size="small" border>
            <el-table-column prop="row" label="行/序号" width="90" />
            <el-table-column prop="code" label="错误码" width="100" />
            <el-table-column prop="channel_order_no" label="渠道单号" width="180" />
            <el-table-column prop="message" label="原因" min-width="240" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ------------------------------------------------------------ json -->
      <el-tab-pane label="粘贴 JSON" name="json">
        <el-card shadow="never">
          <div class="json-toolbar">
            <el-button size="small" @click="fillSample">填入示例</el-button>
            <el-button size="small" @click="jsonText = ''">清空</el-button>
            <div class="spacer" />
            <el-button
              v-if="auth.canManageProducts()"
              type="primary"
              :loading="jsonSubmitting"
              @click="submitJson"
            >
              导入
            </el-button>
          </div>
          <el-input v-model="jsonText" type="textarea" :rows="12" placeholder="粘贴订单 JSON 数组" />
          <el-alert v-if="jsonError" :title="jsonError" type="error" :closable="false" show-icon />
          <div v-if="jsonResult" class="metrics">
            <div class="metric"><span>新增订单</span><b>{{ jsonResult.created_orders }}</b></div>
            <div class="metric"><span>重复同步</span><b>{{ jsonResult.duplicate_orders }}</b></div>
            <div class="metric"><span>失败</span><b class="bad">{{ jsonResult.failed_rows }}</b></div>
            <div class="metric"><span>异常</span><b class="warn">{{ jsonResult.exception_orders }}</b></div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- --------------------------------------------------------- history -->
      <el-tab-pane label="导入记录与同步日志" name="history">
        <el-card shadow="never" class="result">
          <template #header><span>最近导入批次</span></template>
          <el-table :data="batches" size="small" border>
            <el-table-column prop="id" label="批次" width="70" />
            <el-table-column prop="filename" label="文件" min-width="180" />
            <el-table-column prop="total_rows" label="行数" width="80" align="right" />
            <el-table-column prop="created_orders" label="新增" width="80" align="right" />
            <el-table-column prop="duplicate_orders" label="重复" width="80" align="right" />
            <el-table-column prop="failed_rows" label="失败" width="80" align="right" />
            <el-table-column prop="created_at" label="时间" width="170">
              <template #default="{ row }">
                {{ row.created_at?.replace('T', ' ').slice(0, 19) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>订单同步日志</span>
              <div class="log-filter">
                <el-input
                  v-model="logQuery.channel_order_no"
                  size="small"
                  placeholder="渠道单号"
                  style="width: 180px"
                />
                <el-select v-model="logQuery.result" size="small" clearable placeholder="结果" style="width: 120px">
                  <el-option label="已创建" value="created" />
                  <el-option label="重复同步" value="duplicate" />
                  <el-option label="失败" value="failed" />
                </el-select>
                <el-button size="small" @click="loadHistory">查询</el-button>
              </div>
            </div>
          </template>
          <el-table :data="logs" size="small" border>
            <el-table-column prop="created_at" label="时间" width="170">
              <template #default="{ row }">
                {{ row.created_at?.replace('T', ' ').slice(0, 19) }}
              </template>
            </el-table-column>
            <el-table-column prop="channel_code" label="渠道" width="90" />
            <el-table-column prop="channel_order_no" label="渠道单号" width="180" />
            <el-table-column label="结果" width="110">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.result === 'created' ? 'success' : row.result === 'duplicate' ? 'info' : 'danger'"
                >
                  {{ SYNC_RESULT_LABELS[row.result] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="240" />
            <el-table-column label="订单" width="90">
              <template #default="{ row }">
                <el-button v-if="row.order_id" link type="primary" @click="openOrder(row.order_id)">
                  查看
                </el-button>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.tips {
  margin-top: 8px;
}
.result {
  margin-bottom: 16px;
}
.metrics {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric span {
  font-size: 12px;
  color: #909399;
}
.metric b {
  font-size: 20px;
}
.bad {
  color: #f56c6c;
}
.warn {
  color: #e6a23c;
}
.json-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.spacer {
  flex: 1;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.log-filter {
  display: flex;
  gap: 8px;
}
.muted {
  color: #c0c4cc;
}
</style>
