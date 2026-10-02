<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeError } from '@/api/client'
import * as channelApi from '@/api/channel'
import * as productApi from '@/api/product'
import { useAuthStore } from '@/stores/auth'
import type { Channel, ChannelProduct, ChannelShop, Page, Sku } from '@/types'

const auth = useAuthStore()

const loading = ref(false)
const rows = ref<ChannelProduct[]>([])
const total = ref(0)
const channels = ref<Channel[]>([])
const shops = ref<ChannelShop[]>([])
const query = reactive({
  channel_id: undefined as number | undefined,
  keyword: '',
  page: 1,
  page_size: 15,
})

const visible = ref(false)
const editing = ref<ChannelProduct | null>(null)
const form = reactive({
  channel_id: undefined as number | undefined,
  shop_id: undefined as number | undefined,
  channel_product_code: '',
  sku_id: undefined as number | undefined,
  channel_title: '',
  remark: '',
})

// SKU picker
const skuOptions = ref<Sku[]>([])
const skuSearching = ref(false)

async function load() {
  loading.value = true
  try {
    const data: Page<ChannelProduct> = await channelApi.listMappings({
      channel_id: query.channel_id,
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

async function loadChannels() {
  try {
    channels.value = (await channelApi.listChannels()).items
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function loadShops(channelId?: number) {
  if (!channelId) {
    shops.value = []
    return
  }
  try {
    shops.value = await channelApi.listShops(channelId)
  } catch {
    shops.value = []
  }
}

async function searchSkus(keyword: string) {
  skuSearching.value = true
  try {
    skuOptions.value = (await productApi.listSkus({ keyword: keyword || undefined, page_size: 50 }))
      .items
  } finally {
    skuSearching.value = false
  }
}

function resetAndLoad() {
  query.page = 1
  load()
}

async function openCreate() {
  editing.value = null
  form.channel_id = channels.value[0]?.id
  form.shop_id = undefined
  form.channel_product_code = ''
  form.sku_id = undefined
  form.channel_title = ''
  form.remark = ''
  await loadShops(form.channel_id)
  await searchSkus('')
  visible.value = true
}

async function openEdit(row: ChannelProduct) {
  editing.value = row
  form.channel_id = row.channel_id
  form.shop_id = row.shop_id ?? undefined
  form.channel_product_code = row.channel_product_code
  form.sku_id = row.sku_id
  form.channel_title = row.channel_title
  form.remark = row.remark
  await loadShops(row.channel_id)
  await searchSkus(row.sku_code)
  visible.value = true
}

async function submit() {
  if (!form.channel_id || !form.channel_product_code || !form.sku_id) {
    ElMessage.warning('渠道、渠道商品编码、内部 SKU 都是必填')
    return
  }
  try {
    if (editing.value) {
      await channelApi.updateMapping(editing.value.id, {
        shop_id: form.shop_id ?? null,
        sku_id: form.sku_id,
        channel_title: form.channel_title,
        remark: form.remark,
      })
      ElMessage.success('映射已更新')
    } else {
      await channelApi.createMapping({
        channel_id: form.channel_id,
        shop_id: form.shop_id ?? null,
        channel_product_code: form.channel_product_code.trim(),
        sku_id: form.sku_id,
        channel_title: form.channel_title,
        remark: form.remark,
      })
      ElMessage.success('映射已创建')
    }
    visible.value = false
    await load()
    await loadChannels()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

async function remove(row: ChannelProduct) {
  await ElMessageBox.confirm(
    `删除映射后，该渠道商品将无法导入订单：${row.channel_product_code}。确认删除？`,
    '提示',
    { type: 'warning' },
  )
  try {
    await channelApi.deleteMapping(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

onMounted(async () => {
  await loadChannels()
  await load()
})
</script>

<template>
  <div>
    <div class="toolbar">
      <el-select
        v-model="query.channel_id"
        placeholder="全部渠道"
        clearable
        style="width: 170px"
        @change="resetAndLoad"
      >
        <el-option
          v-for="channel in channels"
          :key="channel.id"
          :label="`${channel.name}（${channel.code}）`"
          :value="channel.id"
        />
      </el-select>
      <el-input
        v-model="query.keyword"
        placeholder="渠道商品编码或标题"
        clearable
        style="width: 220px"
        @keyup.enter="resetAndLoad"
      />
      <el-button type="primary" @click="resetAndLoad">查询</el-button>
      <div class="spacer" />
      <el-button v-if="auth.canManageProducts()" type="primary" @click="openCreate">
        新建映射
      </el-button>
    </div>

    <el-alert
      title="不同平台的商品编码不一致，通过映射统一到内部 SKU —— 这样多平台卖的是同一池库存"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <el-table :data="rows" v-loading="loading" border size="small">
      <el-table-column label="渠道" width="150">
        <template #default="{ row }">{{ row.channel_name }}（{{ row.channel_code }}）</template>
      </el-table-column>
      <el-table-column label="店铺" width="130">
        <template #default="{ row }">{{ row.shop_code || '全部店铺' }}</template>
      </el-table-column>
      <el-table-column prop="channel_product_code" label="渠道商品编码" width="180" />
      <el-table-column prop="channel_title" label="渠道商品标题" min-width="180">
        <template #default="{ row }">{{ row.channel_title || '—' }}</template>
      </el-table-column>
      <el-table-column label="内部 SKU" min-width="200">
        <template #default="{ row }">
          <div>{{ row.sku_code }}</div>
          <div class="muted">{{ row.sku_name }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="auth.canManageProducts()" label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
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
      :title="editing ? '编辑渠道商品映射' : '新建渠道商品映射'"
      width="520px"
    >
      <el-form label-width="130px">
        <el-form-item label="渠道" required>
          <el-select
            v-model="form.channel_id"
            style="width: 100%"
            :disabled="!!editing"
            @change="loadShops"
          >
            <el-option
              v-for="channel in channels"
              :key="channel.id"
              :label="`${channel.name}（${channel.code}）`"
              :value="channel.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="店铺（可选）">
          <el-select v-model="form.shop_id" clearable placeholder="不限定店铺" style="width: 100%">
            <el-option
              v-for="shop in shops"
              :key="shop.id"
              :label="`${shop.name || shop.code}`"
              :value="shop.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道商品编码" required>
          <el-input
            v-model="form.channel_product_code"
            placeholder="例如 TB-100238"
            :disabled="!!editing"
          />
        </el-form-item>
        <el-form-item label="内部 SKU" required>
          <el-select
            v-model="form.sku_id"
            filterable
            remote
            reserve-keyword
            placeholder="搜索 SKU 编码"
            :remote-method="searchSkus"
            :loading="skuSearching"
            style="width: 100%"
          >
            <el-option
              v-for="sku in skuOptions"
              :key="sku.id"
              :label="`${sku.sku_code} — ${sku.display_name}`"
              :value="sku.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道商品标题">
          <el-input v-model="form.channel_title" placeholder="平台上的商品名，便于核对" />
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
  font-size: 12px;
  color: #909399;
}
</style>
