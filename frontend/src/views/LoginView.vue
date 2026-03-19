<template>
  <div class="min-h-screen flex items-center justify-center bg-page">
    <div class="w-full max-w-sm rounded-xl bg-card shadow-lg border border-border p-8">
      <h1 class="text-xl font-semibold text-primary text-center mb-6">
        {{ isRegister ? '创建账户' : '专家平台登录' }}
      </h1>
      <form @submit.prevent="isRegister ? onRegister() : onSubmit()" class="space-y-4">
        <div>
          <label for="username" class="block text-sm font-medium text-primary mb-1">用户名</label>
          <input
            id="username"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            class="w-full rounded-lg border border-input-border px-3 py-2 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            placeholder="请输入用户名"
          />
        </div>
        <div>
          <label for="password" class="block text-sm font-medium text-primary mb-1">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="w-full rounded-lg border border-input-border px-3 py-2 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            :placeholder="isRegister ? '请设置密码' : '请输入密码'"
          />
        </div>
        <div v-if="isRegister">
          <label for="passwordConfirm" class="block text-sm font-medium text-primary mb-1">确认密码</label>
          <input
            id="passwordConfirm"
            v-model="passwordConfirm"
            type="password"
            autocomplete="new-password"
            class="w-full rounded-lg border border-input-border px-3 py-2 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            placeholder="请再次输入密码"
          />
        </div>
        <p v-if="error" class="text-sm text-danger">{{ error }}</p>
        <button
          type="submit"
          :disabled="loading"
          class="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-text-inverse hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ loading ? (isRegister ? '创建中…' : '验证中…') : (isRegister ? '创建账户' : '登录') }}
        </button>
      </form>
      <p class="mt-4 text-center text-sm text-muted">
        <button
          type="button"
          class="text-accent hover:opacity-80 hover:underline"
          @click="toggleMode"
        >
          {{ isRegister ? '已有账号？去登录' : '没有账号？创建账户' }}
        </button>
      </p>
      <p class="mt-2 text-xs text-muted text-center">
        账密由后端文本文件校验，初始账号 123 / 密码 1。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const TOKEN_STORAGE_KEY = 'dha_token'

const router = useRouter()
const username = ref('')
const password = ref('')
const passwordConfirm = ref('')
const error = ref('')
const loading = ref(false)
const isRegister = ref(false)

function toggleMode() {
  isRegister.value = !isRegister.value
  error.value = ''
}

function parseError(j: { detail?: unknown }): string {
  const d = j.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return '操作失败'
}

async function onSubmit() {
  error.value = ''
  const name = username.value.trim()
  const pwd = password.value
  if (!name) {
    error.value = '请输入用户名'
    return
  }
  loading.value = true
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, password: pwd }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) {
      error.value = parseError(j)
      return
    }
    if (j.status !== 'ok' || !j.data?.access_token) {
      error.value = (j.detail as string) || '登录失败'
      return
    }
    localStorage.setItem(LOGIN_STORAGE_KEY, 'true')
    localStorage.setItem(USER_STORAGE_KEY, name)
    localStorage.setItem(TOKEN_STORAGE_KEY, j.data.access_token as string)
    router.replace('/')
  } catch (e) {
    error.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  error.value = ''
  const name = username.value.trim()
  const pwd = password.value
  const confirm = passwordConfirm.value
  if (!name) {
    error.value = '请输入用户名'
    return
  }
  if (!pwd) {
    error.value = '请设置密码'
    return
  }
  if (pwd !== confirm) {
    error.value = '两次密码不一致'
    return
  }
  loading.value = true
  try {
    const r = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, password: pwd }),
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) {
      error.value = parseError(j)
      return
    }
    if (j.status !== 'ok' || !j.data?.access_token) {
      error.value = (j.detail as string) || '创建失败'
      return
    }
    // 注册成功后直接视为已登录
    localStorage.setItem(LOGIN_STORAGE_KEY, 'true')
    localStorage.setItem(USER_STORAGE_KEY, name)
    localStorage.setItem(TOKEN_STORAGE_KEY, j.data.access_token as string)
    router.replace('/')
  } catch (e) {
    error.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
