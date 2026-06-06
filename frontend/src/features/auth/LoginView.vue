<template>
  <div class="min-h-screen flex items-center justify-center bg-page px-4 py-8">
    <div
      class="w-full max-w-5xl overflow-hidden rounded-xl border border-border bg-card shadow-lg flex flex-col md:flex-row min-h-[min(560px,90vh)]"
    >
      <!-- 左栏：书童四九主题插画 -->
      <div
        class="relative flex min-h-[280px] shrink-0 flex-col items-center justify-center bg-accent-subtle md:min-h-0 md:w-[60%] md:rounded-l-xl md:rounded-r-none rounded-t-xl md:rounded-t-none p-8 md:p-10"
      >
        <div
          class="pointer-events-none absolute inset-0 bg-gradient-to-b from-accent-subtle/55 to-page/18 md:rounded-l-xl rounded-t-xl md:rounded-t-none"
        />
        <img
          :src="landingImageUrl"
          alt="书童四九"
          class="relative z-[1] w-full max-w-[min(100%,500px)] select-none"
          width="630"
          height="490"
          decoding="async"
        />
      </div>

      <!-- 右栏：表单 -->
      <div class="flex flex-col justify-center px-8 py-10 md:w-[40%] md:flex-none md:px-10 md:py-12">
        <div class="mx-auto w-full max-w-sm">
          <div class="mb-8 flex flex-col items-center text-center">
            <div class="mb-4 flex items-center justify-center">
              <img
                :src="logoUrl"
                alt="书童四九 logo"
                class="h-20 w-20 rounded-full object-cover"
                width="80"
                height="80"
                decoding="async"
              />
            </div>
            <h1 class="mt-5 text-xl font-semibold text-primary">
              书童四九
            </h1>
            <p class="mt-1 text-sm text-muted">
              你的AI专家助理
            </p>
          </div>

          <form @submit.prevent="onSubmit()" class="space-y-4">
            <div>
              <label for="username" class="mb-1 block text-sm font-medium text-primary">账号</label>
              <input
                id="username"
                v-model="username"
                type="text"
                required
                autocomplete="username"
                class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
                placeholder="请输入手机号或电子邮箱"
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
                placeholder="请输入密码"
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
import { useRouter, useRoute } from 'vue-router'
import landingImageUrl from '@/assets/landing.png'
import logoUrl from '@/assets/49logo.png'
import { THEME_AUTH_CHANGED_EVENT } from '@/composables/useTheme'
import { apiRequest } from '@/api/base'

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const USER_ID_STORAGE_KEY = 'dha_user_id'
const TOKEN_STORAGE_KEY = 'dha_token'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const passwordConfirm = ref('')
const error = ref('')
const loading = ref(false)
const isRegister = ref(false)
const PHONE_REGEX = /^1[3-9]\d{9}$/
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function isValidAccount(value: string): boolean {
  return PHONE_REGEX.test(value) || EMAIL_REGEX.test(value)
}

function toggleMode() {
  isRegister.value = !isRegister.value
  error.value = ''
  passwordConfirm.value = ''
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
    error.value = '请输入账号'
    return
  }
  if (!isValidAccount(name)) {
    error.value = '账号格式不正确，请输入手机号或电子邮箱'
    return
  }
  if (!pwd) {
    error.value = '请输入密码'
    return
  }
  if (isRegister.value) {
    if (pwd.length < 6) {
      error.value = '密码至少 6 位'
      return
    }
    if (pwd !== passwordConfirm.value) {
      error.value = '两次密码不一致'
      return
    }
  }
  loading.value = true
  try {
    const endpoint = isRegister.value ? '/auth/register' : '/auth/login'
    const r = await apiRequest(endpoint, {
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
    if (typeof j.data.user_id === 'string' && j.data.user_id) {
      localStorage.setItem(USER_ID_STORAGE_KEY, j.data.user_id)
    } else {
      localStorage.removeItem(USER_ID_STORAGE_KEY)
    }
    localStorage.setItem(TOKEN_STORAGE_KEY, j.data.access_token as string)
    window.dispatchEvent(new Event(THEME_AUTH_CHANGED_EVENT))
    const redir = route.query.redirect
    if (typeof redir === 'string' && redir.startsWith('/') && !redir.startsWith('//')) {
      router.replace(redir)
    } else {
      router.replace('/')
    }
  } catch (e) {
    error.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
