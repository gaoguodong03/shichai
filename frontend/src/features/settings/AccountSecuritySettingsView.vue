<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <div class="flex-1 overflow-y-auto p-4 themed-scrollbar">
      <div class="max-w-5xl w-full mx-auto space-y-6">
      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">
          修改账号
        </h2>
        <p class="text-xs text-muted">
          账号支持手机号或是电子邮箱。
        </p>
        <div class="rounded-xl border border-border bg-card p-4 space-y-3">
          <div>
            <label for="new-account" class="mb-1 block text-sm font-medium text-primary">账号</label>
            <input
              id="new-account"
              v-model.trim="newAccount"
              type="text"
              autocomplete="username"
              placeholder="请输入新账号"
              class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label for="account-password" class="mb-1 block text-sm font-medium text-primary">当前密码</label>
            <input
              id="account-password"
              v-model="accountCurrentPassword"
              type="password"
              autocomplete="current-password"
              placeholder="请输入当前密码"
              class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            />
          </div>
          <p v-if="accountError" class="text-sm text-danger">{{ accountError }}</p>
          <p v-if="accountSuccess" class="text-sm text-accent">{{ accountSuccess }}</p>
          <div class="flex items-center justify-start pt-3">
            <button
              type="button"
              :disabled="savingAccount"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              @click="onChangeAccount"
            >
              {{ savingAccount ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </section>

      <section class="space-y-4">
        <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">
          修改密码
        </h2>
        <div class="rounded-xl border border-border bg-card p-4 space-y-3">
          <div>
            <label for="current-password" class="mb-1 block text-sm font-medium text-primary">当前密码</label>
            <input
              id="current-password"
              v-model="passwordCurrent"
              type="password"
              autocomplete="current-password"
              placeholder="请输入当前密码"
              class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label for="new-password" class="mb-1 block text-sm font-medium text-primary">新密码</label>
            <input
              id="new-password"
              v-model="passwordNext"
              type="password"
              autocomplete="new-password"
              placeholder="请输入新密码（至少 6 位）"
              class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            />
          </div>
          <div>
            <label for="confirm-password" class="mb-1 block text-sm font-medium text-primary">确认新密码</label>
            <input
              id="confirm-password"
              v-model="passwordConfirm"
              type="password"
              autocomplete="new-password"
              placeholder="请再次输入新密码"
              class="w-full rounded-lg border border-input-border bg-accent-subtle px-3 py-2.5 text-primary placeholder-placeholder focus:border-input-focus-ring focus:outline-none focus:ring-1 focus:ring-input-focus-ring"
            />
          </div>
          <p v-if="passwordError" class="text-sm text-danger">{{ passwordError }}</p>
          <p v-if="passwordSuccess" class="text-sm text-accent">{{ passwordSuccess }}</p>
          <div class="flex items-center justify-start pt-3">
            <button
              type="button"
              :disabled="savingPassword"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              @click="onChangePassword"
            >
              {{ savingPassword ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const USER_STORAGE_KEY = 'dha_user'
const TOKEN_STORAGE_KEY = 'dha_token'

const newAccount = ref('')
const accountCurrentPassword = ref('')
const accountError = ref('')
const accountSuccess = ref('')
const savingAccount = ref(false)
const PHONE_REGEX = /^1[3-9]\d{9}$/
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const passwordCurrent = ref('')
const passwordNext = ref('')
const passwordConfirm = ref('')
const passwordError = ref('')
const passwordSuccess = ref('')
const savingPassword = ref(false)

function isValidAccount(value: string): boolean {
  return PHONE_REGEX.test(value) || EMAIL_REGEX.test(value)
}

function parseError(j: { detail?: unknown }): string {
  const d = j.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return '操作失败'
}

async function requestWithMethodFallback(path: string, payload: Record<string, string>) {
  const body = JSON.stringify(payload)
  const common = {
    headers: { 'Content-Type': 'application/json' },
    body,
  }
  let r = await fetch(path, { method: 'PUT', ...common })
  let j = await r.json().catch(() => ({}))
  if (r.status === 405) {
    r = await fetch(path, { method: 'POST', ...common })
    j = await r.json().catch(() => ({}))
  }
  return { r, j }
}

async function onChangeAccount() {
  accountError.value = ''
  accountSuccess.value = ''
  const account = newAccount.value.trim()
  const currentPwd = accountCurrentPassword.value
  if (!account) {
    accountError.value = '请输入新账号'
    return
  }
  if (!isValidAccount(account)) {
    accountError.value = '账号格式不正确，请输入手机号或电子邮箱'
    return
  }
  if (!currentPwd) {
    accountError.value = '请输入当前密码'
    return
  }
  savingAccount.value = true
  try {
    const { r, j } = await requestWithMethodFallback('/api/auth/account', {
      new_username: account,
      current_password: currentPwd,
    })
    if (!r.ok || j.status !== 'ok' || !j.data?.access_token) {
      accountError.value = parseError(j)
      return
    }
    localStorage.setItem(USER_STORAGE_KEY, j.data.username as string)
    localStorage.setItem(TOKEN_STORAGE_KEY, j.data.access_token as string)
    newAccount.value = ''
    accountCurrentPassword.value = ''
    accountSuccess.value = '账号已更新'
  } catch {
    accountError.value = '网络错误，请稍后重试'
  } finally {
    savingAccount.value = false
  }
}

async function onChangePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''
  const currentPwd = passwordCurrent.value
  const nextPwd = passwordNext.value
  const confirmPwd = passwordConfirm.value
  if (!currentPwd) {
    passwordError.value = '请输入当前密码'
    return
  }
  if (nextPwd.length < 6) {
    passwordError.value = '新密码至少 6 位'
    return
  }
  if (nextPwd !== confirmPwd) {
    passwordError.value = '两次新密码不一致'
    return
  }
  savingPassword.value = true
  try {
    const { r, j } = await requestWithMethodFallback('/api/auth/password', {
      current_password: currentPwd,
      new_password: nextPwd,
    })
    if (!r.ok || j.status !== 'ok' || !j.data?.access_token) {
      passwordError.value = parseError(j)
      return
    }
    localStorage.setItem(TOKEN_STORAGE_KEY, j.data.access_token as string)
    passwordCurrent.value = ''
    passwordNext.value = ''
    passwordConfirm.value = ''
    passwordSuccess.value = '密码已更新'
  } catch {
    passwordError.value = '网络错误，请稍后重试'
  } finally {
    savingPassword.value = false
  }
}
</script>
