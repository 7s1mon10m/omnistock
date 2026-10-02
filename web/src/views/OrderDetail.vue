<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as orderApi from '@/api/order'
import { useAuthStore } from '@/stores/auth'
import {
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TAG,
  yuan,
  type OrderActionResult,
  type OrderDetail,
  type OrderStatus,
} from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const order = ref<OrderDetail | null>(null)
const loading = ref(false)
const lastAction = ref<OrderActionResult | null>(null)

const canCancel = computed(() =>
  ['pending_payment', 'pending_fulfillment', 'reserved', 'exception'].includes(
    order.value?.status ?? '',
  ),
)

async function load() {
  loading.value = true
  try {
    order.value = await orderApi.getOrder(Number(props.id))
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function act(action: 'pay' | 'cancel' | 'retry') {
  if (!order.value) return
  try {
    let reason = ''
    if (action === 'cancel') {
      const input = await ElMessageBox.prompt('取消原因', '取消订单', {
        inputPlaceholder: '例如 客户改主意',
        inputValue: '',
      })
      reason = input.value ?? ''
    }
    const result =
      action === 'pay'
        ? await orderApi.markPaid(order.value.id)
        : action === 'cancel'
          ? await orderApi.cancelOrder(order.value.id, reason)
          : await orderApi.retryReserve(order.value.id)
    lastAction.value = result
    order.value = result.order
    ElMessage.success(result.message || '操作完成')
  } catch (err) {
    if (err === 'cancel') return
    ElMessage.error(describeError(err))
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button link type="primary" @click="router.back()">← 返回订单列表</el-button>
      <div class="spacer" />
      <el-button @click="load">刷新</el-button>
      <template v-if="order && auth.canManageProducts()">
        <el-button v-if="order.status === 'pending_payment'" type="primary" @click="act('pay')">
          标记付款并占用库存
        </el-button>
        <el-button v-if="order.status === 'exception'" type="warning" @click="act('retry')">
          重新占用
        </el-button>
        <el-button v-if="canCancel" type="danger" plain @click="act('cancel')">取消订单</el-button>
      </template>
    </div>

    <el-card v-if="order" shadow="never" class="block">
      <template #header>
        <div class="card-header">
          <span>{{ order.order_no }} · {{ order.channel_code }} {{ order.channel_order_no }}</span>
          <el-tag :type="ORDER_STATUS_TAG[order.status as OrderStatus]">
            {{ ORDER_STATUS_LABELS[order.status as OrderStatus] }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="渠道">{{ order.channel_name }}</el-descriptions-item>
        <el-descriptions-item label="店铺">{{ order.shop_code || '—' }}</el-descriptions-item>
        <el-descriptions-item label="买家">{{ order.buyer_nick || '—' }}</el-descriptions-item>
        <el-descriptions-item label="发货仓">
          {{ order.warehouse_code || '未确定' }}
        </el-descriptions-item>
        <el-descriptions-item label="件数">{{ order.total_quantity }}</el-descriptions-item>
        <el-descriptions-item label="金额">{{ yuan(order.total_amount_cents) }}</el-descriptions-item>
        <el-descriptions-item label="付款时间">
          {{ order.paid_at?.replace('T', ' ').slice(0, 19) || '未付款' }}
        </el-descriptions-item>
        <el-descriptions-item label="导入方式">{{ order.source }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="order.status === 'exception'"
        class="exception-alert"
        type="warning"
        :closable="false"
        show-icon
        :title="`该订单有 ${order.open_exceptions} 条未处理的异常，库存不足时整单不占用`"
      />
    </el-card>

    <el-card v-if="order" shadow="never" class="block">
      <template #header><span>商品行</span></template>
      <el-table :data="order.items" size="small" border>
        <el-table-column prop="line_no" label="#" width="60" />
        <el-table-column prop="channel_product_code" label="渠道商品编码" width="180" />
        <el-table-column label="内部 SKU" min-width="220">
          <template #default="{ row }">
            <div>{{ row.sku_code }}</div>
            <div class="muted">{{ row.sku_name }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="90" align="right" />
        <el-table-column label="单价" width="110" align="right">
          <template #default="{ row }">{{ yuan(row.unit_price_cents) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_bundle" size="small" type="warning">组合商品</el-tag>
            <span v-else class="muted">普通</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="note">
        组合商品自身不持有库存，占用时按下单数量拆解为子 SKU。
      </div>
    </el-card>

    <el-card v-if="order" shadow="never" class="block">
      <template #header><span>当前库存占用（来自库存流水）</span></template>
      <el-table v-if="order.reservations.length" :data="order.reservations" size="small" border>
        <el-table-column prop="sku_code" label="SKU" width="200" />
        <el-table-column prop="warehouse_code" label="仓库" width="130" />
        <el-table-column prop="quantity" label="已占用" width="110" align="right" />
      </el-table>
      <el-empty v-else description="当前没有占用任何库存" :image-size="60" />
    </el-card>

    <el-card v-if="lastAction" shadow="never" class="block">
      <template #header><span>最近一次操作</span></template>
      <el-alert :title="lastAction.message" type="success" :closable="false" show-icon />
      <div v-if="lastAction.released.length" class="lines">
        <span class="label">已释放：</span>
        <el-tag v-for="line in lastAction.released" :key="`${line.sku_id}-${line.warehouse_id}`" class="line-tag">
          {{ line.sku_code }} × {{ line.quantity }}（{{ line.warehouse_code }}）
        </el-tag>
      </div>
      <div v-if="lastAction.reserved.length" class="lines">
        <span class="label">已占用：</span>
        <el-tag v-for="line in lastAction.reserved" :key="`r-${line.sku_id}`" type="success" class="line-tag">
          {{ line.sku_code }} × {{ line.quantity }}（{{ line.warehouse_code }}）
        </el-tag>
      </div>
      <el-table v-if="lastAction.exceptions.length" :data="lastAction.exceptions" size="small" border class="exception-table">
        <el-table-column prop="sku_code" label="SKU" width="200" />
        <el-table-column prop="required_qty" label="需要" width="90" align="right" />
        <el-table-column prop="available_qty" label="可售" width="90" align="right" />
        <el-table-column prop="shortage_qty" label="缺口" width="90" align="right" />
        <el-table-column prop="message" label="说明" min-width="220" />
      </el-table>
    </el-card>
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
.block {
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.exception-alert {
  margin-top: 12px;
}
.note {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.lines {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.label {
  font-size: 13px;
  color: #606266;
}
.line-tag {
  margin-right: 4px;
}
.exception-table {
  margin-top: 12px;
}
.muted {
  font-size: 12px;
  color: #909399;
}
</style>
