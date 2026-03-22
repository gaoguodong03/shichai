<template>
  <div class="min-h-screen flex items-center justify-center bg-page px-4 py-8">
    <div
      class="w-full max-w-5xl overflow-hidden rounded-xl border border-border bg-card shadow-lg flex flex-col md:flex-row min-h-[min(560px,90vh)]"
    >
      <!-- 左栏：书童四九主题插画 -->
      <div
        class="relative flex min-h-[200px] shrink-0 flex-col items-center justify-center bg-accent-subtle md:min-h-0 md:w-[46%] md:rounded-l-xl md:rounded-r-none rounded-t-xl md:rounded-t-none p-8 md:p-10"
      >
        <div
          class="pointer-events-none absolute inset-0 bg-gradient-to-b from-accent-subtle/80 to-page/30 md:rounded-l-xl rounded-t-xl md:rounded-t-none"
        />
        <img
          :src="loginHeroUrl"
          alt="书童四九"
          class="relative z-[1] w-full max-w-[min(100%,380px)] select-none drop-shadow-sm"
          width="480"
          height="360"
          decoding="async"
        />
      </div>

      <!-- 右栏：表单 -->
      <div class="flex flex-1 flex-col justify-center px-8 py-10 md:px-12 md:py-12">
        <div class="mx-auto w-full max-w-sm">
          <div class="mb-8 flex flex-col items-center text-center">
            <div
              class="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent-subtle shadow-sm ring-1 ring-border-light"
              aria-hidden="true"
            >
              <svg class="h-8 w-8" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M16 4c-2 4-1 8 2 11-1-4 1-8 4-10-1 5 2 9 6 11-2-4-1-9 2-12 4 5 5 12 2 18-3 6-9 10-16 10-4 0-7-2-9-5 5 1 10-2 12-6-4 2-9 1-12-2 3-3 8-4 12-2-3-4-2-9 2-12 2 2 5 3 8 3 2 0 4-1 5-2z"
                  fill="var(--color-accent)"
                />
                <path
                  d="M8 26h16v2H8v-2zm2-4h4v3h-4v-3zm8 0h4v3h-4v-3z"
                  fill="var(--color-dha-box-3)"
                />
              </svg>
            </div>
            <h1 class="text-xl font-semibold text-primary tracking-tight">书童四九</h1>
            <p class="mt-1 text-xs text-muted tracking-[0.12em]">多数字人 ReAct Agent 工作台</p>
            <p class="mt-5 text-base font-semibold text-primary">
              {{ isRegister ? '创建账户' : '登录' }}
            </p>
          </div>

          <form @submit.prevent="isRegister ? onRegister() : onSubmit()" class="space-y-4">
            <div>
              <label for="username" class="mb-1 block text-sm font-medium text-primary">用户名</label>
              <input
                id="username"
                v-model="username"
                type="text"
                required
                autocomplete="username"
                class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
                placeholder="请输入用户名"
              />
            </div>
            <div>
              <label for="password" class="mb-1 block text-sm font-medium text-primary">密码</label>
              <input
                id="password"
                v-model="password"
                type="password"
                autocomplete="current-password"
                class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
                :placeholder="isRegister ? '请设置密码' : '请输入密码'"
              />
            </div>
            <div v-if="isRegister">
              <label for="passwordConfirm" class="mb-1 block text-sm font-medium text-primary">确认密码</label>
              <input
                id="passwordConfirm"
                v-model="passwordConfirm"
                type="password"
                autocomplete="new-password"
                class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
                placeholder="请再次输入密码"
              />
            </div>
            <p v-if="error" class="text-sm text-danger">{{ error }}</p>
            <button
              type="submit"
              :disabled="loading"
              class="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-text-inverse hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {{ loading ? (isRegister ? '创建中…' : '验证中…') : (isRegister ? '创建账户' : '登录') }}
            </button>
          </form>
          <p class="mt-6 text-center text-sm text-muted">
            <button
              type="button"
              class="text-accent hover:opacity-80 hover:underline"
              @click="toggleMode"
            >
              {{ isRegister ? '已有账号？去登录' : '没有账号？创建账户' }}
            </button>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import loginHeroUrl from '@/assets/login-hero.svg'

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
