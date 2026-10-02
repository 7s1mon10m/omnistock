<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'

const route = useRoute()
// The login screen is the only page without the shell around it.
const isBlank = computed(() => route.meta.public === true)
</script>

<template>
  <AppLayout v-if="!isBlank">
    <router-view />
  </AppLayout>
  <router-view v-else />
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei',
    sans-serif;
  background: #f5f7fa;
  color: #303133;
}
</style>
