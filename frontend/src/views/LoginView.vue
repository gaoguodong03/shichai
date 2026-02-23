<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-100">
    <div class="w-full max-w-sm rounded-xl bg-white shadow-lg border border-gray-200 p-8">
      <h1 class="text-xl font-semibold text-gray-800 text-center mb-6">DHA 登录</h1>
      <form @submit.prevent="onSubmit" class="space-y-4">
        <div>
          <label for="username" class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
          <input
            id="username"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-gray-800 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="请输入用户名"
          />
        </div>
        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 mb-1">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-gray-800 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="请输入密码（可选）"
          />
        </div>
        <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
        <button
          type="submit"
          class="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          登录
        </button>
      </form>
      <p class="mt-4 text-xs text-gray-500 text-center">
        当前为前端占位登录，仅做路由与展示；后续可接入后端认证。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')

function onSubmit() {
  error.value = ''
  const name = username.value.trim()
  if (!name) {
    error.value = '请输入用户名'
    return
  }
  try {
    localStorage.setItem(LOGIN_STORAGE_KEY, 'true')
    localStorage.setItem(USER_STORAGE_KEY, name)
  } catch (e) {
    error.value = '保存登录态失败'
    return
  }
  router.replace('/')
}
</script>
