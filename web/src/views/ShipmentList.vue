<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as shipmentApi from '@/api/shipment'
import { useAuthStore } from '@/stores/auth'
import {
  SHIPMENT_STATUS_LABELS,
  SHIPMENT_STATUS_TAG,
  type ShipmentListItem,
  type ShipmentStatus,
} from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const rows = ref<ShipmentListItem[]>([])
const total = ref(0)
const query = reactive({
  status: undefined as ShipmentStatus | undefined,
  keyword: '',
  page: 1,
  page_size: 15,
})

const STATUS_OPTIONS = Object.entries(SHIPMENT_STATUS_LABELS) as [ShipmentStatus, string][]

async function load() {
  loading.value = true
  try {
    const data = await shipmentApi.listShipments({
      status: query.status,
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

function openWorkbench(row: ShipmentListItem) {
  router.push({ name: 'shipment-detail', params: { id: row.id } })
}

async function claim(row: ShipmentListItem) {
  try {
    await shipmentApi.claimShipment(row.id)
    ElMessage.success('已领取，开始拣货')
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function cancel(row: ShipmentListItem) {
  const input = await ElMessageBox.prompt('取消原因', '取消发货单', {
    inputPlaceholder: '例如 库存数字不对，需要重新盘',
    inputValue: '',
  })
  try {
    await shipmentApi.cancelShipment(row.id, input.value ?? '')
    ElMessage.success('已取消，订单回到「已占用」')
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      title="拣货清单按库位编码排序 —— 从上到下走一遍就是最短路线。扫码对不上会当场拦截。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <div class="toolbar">
      <el-select
        v-model="query.status"
        placeholder="全部状态"
        clearable
        style="width: 160px"
        @change="resetAndLoad"
      >
        <el-option v-for="[value, label] in STATUS_OPTIONS" :key="value" :label="label" :value="value" />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="发货单号 / 订单号 / 渠道单号"
        clearable
        style="width: 260px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column prop="shipment_no" label="发货单号" width="140" />
      <el-table-column label="订单" width="200">
        <template #default="{ row }">
          <div>{{ row.order_no }}</div>
          <div class="muted">{{ row.channel_code }} · {{ row.channel_order_no }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="buyer_nick" label="买家" width="110" />
      <el-table-column prop="warehouse_code" label="仓库" width="110" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="SHIPMENT_STATUS_TAG[row.status as ShipmentStatus]" size="small">
            {{ SHIPMENT_STATUS_LABELS[row.status as ShipmentStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="拣货进度" width="150">
        <template #default="{ row }">
          <el-progress
            :percentage="
              row.total_quantity ? Math.round((row.picked_quantity / row.total_quantity) * 100) : 0
            "
            :stroke-width="12"
            :text-inside="true"
            :status="row.picked_quantity >= row.total_quantity ? 'success' : undefined"
          />
        </template>
      </el-table-column>
      <el-table-column label="件数" width="90" align="right">
        <template #default="{ row }">{{ row.picked_quantity }}/{{ row.total_quantity }}</template>
      </el-table-column>
      <el-table-column prop="picker_name" label="拣货人" width="110">
        <template #default="{ row }">{{ row.picker_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="物流" min-width="150">
        <template #default="{ row }">
          <span v-if="row.tracking_no">{{ row.carrier }} {{ row.tracking_no }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openWorkbench(row)">作业台</el-button>
          <el-button
            v-if="row.status === 'pending' && auth.hasRole('admin', 'owner', 'warehouse')"
            link
            type="primary"
            @click="claim(row)"
          >
            领取
          </el-button>
          <el-button
            v-if="['pending', 'picking', 'picked', 'packed'].includes(row.status) && auth.hasRole('admin', 'owner', 'warehouse')"
            link
            type="danger"
            @click="cancel(row)"
          >
            取消
          </el-button>
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
  font-size: 12px;
  color: #909399;
}
</style>
