<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import * as channelApi from '@/api/channel'
import { useAuthStore } from '@/stores/auth'
import {
  CHANNEL_PLATFORM_LABELS,
  type Channel,
  type ChannelPlatform,
  type ChannelShop,
} from '@/types'

const auth = useAuthStore()

const loading = ref(false)
const channels = ref<Channel[]>([])
const shopsByChannel = ref<Record<number, ChannelShop[]>>({})
const shopLoading = ref(false)

const createVisible = ref(false)
const createForm = reactive({
  code: '',
  name: '',
  platform: 'taobao' as ChannelPlatform,
  remark: '',
})

const shopVisible = ref(false)
const shopForm = reactive({ channel_id: 0, code: '', name: '' })

async function load() {
  loading.value = true
  try {
    channels.value = (await channelApi.listChannels()).items
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    loading.value = false
  }
}

async function onExpand(row: Channel, expandedRows: Channel[]) {
  if (!expandedRows.some((item) => item.id === row.id)) return
  shopLoading.value = true
  try {
    const shops = await channelApi.listShops(row.id)
    shopsByChannel.value = { ...shopsByChannel.value, [row.id]: shops }
  } catch (err) {
    ElMessage.error(describeError(err))
  } finally {
    shopLoading.value = false
  }
}

function openCreate() {
  createForm.code = ''
  createForm.name = ''
  createForm.platform = 'taobao'
  createForm.remark = ''
  createVisible.value = true
}

async function submitCreate() {
  if (!createForm.code || !createForm.name) {
    ElMessage.warning('请填写渠道编码与名称')
    return
  }
  try {
    await channelApi.createChannel({ ...createForm })
    ElMessage.success('渠道已创建')
    createVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(describeError(err))
  }
}

function openShop(row: Channel) {
  shopForm.channel_id = row.id
  shopForm.code = ''
  shopForm.name = ''
  shopVisible.value = true
}

async function submitShop() {
  if (!shopForm.code) {
    ElMessage.warning('请填写店铺编码')
    return
  }
  try {
    await channelApi.createShop(shopForm.channel_id, {
      code: shopForm.code,
      name: shopForm.name,
    })
    ElMessage.success('店铺已创建')
    shopVisible.value = false
    const shops = await channelApi.listShops(shopForm.channel_id)
    shopsByChannel.value = { ...shopsByChannel.value, [shopForm.channel_id]: shops }
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
      <span class="hint">渠道 = 卖货的平台；店铺 = 平台上的一个店面。订单同步时按渠道编码归类。</span>
      <div class="spacer" />
      <el-button v-if="auth.canManageProducts()" type="primary" @click="openCreate">
        新建渠道
      </el-button>
    </div>

    <el-table :data="channels" v-loading="loading" border row-key="id" @expand-change="onExpand">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="shop-panel">
            <div class="shop-header">
              <span>店铺</span>
              <el-button
                v-if="auth.canManageProducts()"
                size="small"
                type="primary"
                @click="openShop(row)"
              >
                新增店铺
              </el-button>
            </div>
            <el-table
              :data="shopsByChannel[row.id] ?? []"
              v-loading="shopLoading"
              size="small"
              border
            >
              <el-table-column prop="code" label="店铺编码" width="180" />
              <el-table-column prop="name" label="店铺名称" min-width="180" />
              <el-table-column label="状态" width="90">
                <template #default="{ row: shop }">
                  <el-tag :type="shop.is_active ? 'success' : 'info'" size="small">
                    {{ shop.is_active ? '启用' : '停用' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="code" label="渠道编码" width="140" />
      <el-table-column prop="name" label="渠道名称" min-width="160" />
      <el-table-column label="平台" width="120">
        <template #default="{ row }">
          <el-tag size="small">
            {{ CHANNEL_PLATFORM_LABELS[row.platform as ChannelPlatform] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="shop_count" label="店铺数" width="90" align="right" />
      <el-table-column label="渠道商品映射" width="130" align="right">
        <template #default="{ row }">{{ row.product_count }} 条</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="140" />
    </el-table>

    <el-dialog v-model="createVisible" title="新建渠道" width="460px">
      <el-form label-width="90px">
        <el-form-item label="渠道编码" required>
          <el-input v-model="createForm.code" placeholder="例如 TB" />
        </el-form-item>
        <el-form-item label="渠道名称" required>
          <el-input v-model="createForm.name" placeholder="例如 淘宝" />
        </el-form-item>
        <el-form-item label="平台">
          <el-select v-model="createForm.platform" style="width: 100%">
            <el-option
              v-for="(label, value) in CHANNEL_PLATFORM_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="shopVisible" title="新增店铺" width="440px">
      <el-form label-width="90px">
        <el-form-item label="店铺编码" required>
          <el-input v-model="shopForm.code" placeholder="例如 TB-SHOP-1" />
        </el-form-item>
        <el-form-item label="店铺名称">
          <el-input v-model="shopForm.name" placeholder="例如 淘宝旗舰店" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="shopVisible = false">取消</el-button>
        <el-button type="primary" @click="submitShop">创建</el-button>
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
.shop-panel {
  padding: 8px 16px 16px;
}
.shop-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}
</style>
