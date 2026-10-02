<script setup lang="ts">
import { computed } from 'vue'
import type { InventoryTransaction } from '@/types'
import { TRANSACTION_LABELS } from '@/types'

const props = defineProps<{
  rows: InventoryTransaction[]
  loading?: boolean
  showSku?: boolean
}>()

const visibleRows = computed(() => props.rows)

const TYPE_TAG: Record<string, string> = {
  purchase_inbound: 'success',
  order_reserve: 'warning',
  order_release: 'info',
  order_outbound: 'danger',
  return_inbound: 'success',
  return_defective: 'warning',
  return_repair: 'info',
  damage_scrap: 'danger',
  transfer_out: 'info',
  transfer_in: 'success',
  stocktake_adjust: 'warning',
  manual_adjust: 'info',
}

function tagType(type: string): string {
  return TYPE_TAG[type] ?? 'info'
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : `${value}`
}
</script>

<template>
  <el-table :data="visibleRows" v-loading="loading" size="small" border>
    <el-table-column prop="created_at" label="时间" width="170">
      <template #default="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
    </el-table-column>
    <el-table-column v-if="showSku !== false" prop="sku_code" label="SKU" width="170" />
    <el-table-column label="类型" width="110">
      <template #default="{ row }">
        <el-tag size="small" :type="tagType(row.type)">
          {{ TRANSACTION_LABELS[row.type as keyof typeof TRANSACTION_LABELS] ?? row.type }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="变动" width="90" align="right">
      <template #default="{ row }">
        <span :class="row.qty_delta > 0 ? 'up' : 'down'">{{ signed(row.qty_delta) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="实际库存 前→后" width="150" align="center">
      <template #default="{ row }">
        {{ row.on_hand_before }} → {{ row.on_hand_after }}
      </template>
    </el-table-column>
    <el-table-column label="已占用 前→后" width="150" align="center">
      <template #default="{ row }">
        {{ row.reserved_before }} → {{ row.reserved_after }}
      </template>
    </el-table-column>
    <el-table-column prop="warehouse_code" label="仓库" width="110" />
    <el-table-column prop="operator_name" label="操作人" width="110" />
    <el-table-column prop="remark" label="原因 / 备注" min-width="160" />
    <el-table-column label="来源单据" width="140">
      <template #default="{ row }">
        <span v-if="row.ref_type">{{ row.ref_type }}#{{ row.ref_id ?? '-' }}</span>
        <span v-else class="muted">—</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
/* Neutral colours on purpose: this is a quantity movement, not a price change,
   so the red-up/green-down stock market convention does not apply here. */
.up {
  color: #303133;
  font-weight: 600;
}
.down {
  color: #f56c6c;
  font-weight: 600;
}
.muted {
  color: #c0c4cc;
}
</style>
