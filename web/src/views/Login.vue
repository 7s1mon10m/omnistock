<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { describeError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const form = reactive({ username: '', password: '' })
const error = ref('')
const submitting = ref(false)

const DEMO_ACCOUNTS = [
  { username: 'admin', password: 'admin123', label: '店主 / 管理员' },
  { username: 'operator', password: 'operator123', label: '运营人员' },
  { username: 'buyer', password: 'buyer123', label: '采购人员' },
  { username: 'warehouse', password: 'warehouse123', label: '仓库人员' },
]

function fill(account: { username: string; password: string }) {
  form.username = account.username
  form.password = account.password
}

async function onSubmit() {
  error.value = ''
  if (!form.username || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success(`欢迎，${auth.displayName}`)
    const redirect = (route.query.redirect as string) || '/products'
    router.push(redirect)
  } catch (err) {
    error.value = describeError(err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <h1 class="title">OmniStock</h1>
      <p class="subtitle">多渠道电商库存与采购协同平台</p>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
        <el-button
          class="submit"
          type="primary"
          :loading="submitting"
          style="width: 100%; margin-top: 12px"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>

      <el-divider>演示账号（种子数据）</el-divider>
      <div class="demo">
        <el-button
          v-for="account in DEMO_ACCOUNTS"
          :key="account.username"
          size="small"
          @click="fill(account)"
        >
          {{ account.label }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}
.login-card {
  width: 400px;
}
.title {
  margin: 0;
  font-size: 22px;
  text-align: center;
}
.subtitle {
  margin: 6px 0 20px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
.demo {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
</style>
