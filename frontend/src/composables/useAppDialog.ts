import { reactive, readonly } from 'vue'

export type AppDialogVariant = 'info' | 'success' | 'warning' | 'danger'
export type AppDialogMode = 'alert' | 'confirm' | 'prompt'

export interface AppDialogOptions {
  title?: string
  message: string
  variant?: AppDialogVariant
  confirmText?: string
  cancelText?: string
}

export interface AppPromptOptions extends AppDialogOptions {
  label?: string
  defaultValue?: string
  placeholder?: string
  required?: boolean
}

interface AppDialogRequest extends AppPromptOptions {
  id: number
  mode: AppDialogMode
  resolve: (value: boolean | string | null) => void
}

const state = reactive<{
  active: AppDialogRequest | null
  queue: AppDialogRequest[]
}>({
  active: null,
  queue: [],
})

let nextId = 1

function normalizeMessage(options: string | AppDialogOptions): AppDialogOptions {
  return typeof options === 'string' ? { message: options } : options
}

function enqueue<T extends boolean | string | null>(
  mode: AppDialogMode,
  options: AppPromptOptions,
): Promise<T> {
  return new Promise<T>((resolve) => {
    const request: AppDialogRequest = {
      id: nextId++,
      mode,
      title: options.title,
      message: options.message,
      variant: options.variant || (mode === 'confirm' ? 'warning' : 'info'),
      confirmText: options.confirmText,
      cancelText: options.cancelText,
      label: options.label,
      defaultValue: options.defaultValue,
      placeholder: options.placeholder,
      required: options.required,
      resolve: resolve as (value: boolean | string | null) => void,
    }
    if (state.active) state.queue.push(request)
    else state.active = request
  })
}

function nextDialog() {
  state.active = state.queue.shift() || null
}

export function settleAppDialog(value: boolean | string | null) {
  const active = state.active
  if (!active) return
  active.resolve(value)
  nextDialog()
}

export function appAlert(options: string | AppDialogOptions): Promise<void> {
  const normalized = normalizeMessage(options)
  return enqueue<boolean>('alert', {
    title: normalized.title || '提示',
    message: normalized.message,
    variant: normalized.variant || 'info',
    confirmText: normalized.confirmText || '知道了',
  }).then(() => undefined)
}

export function appConfirm(options: string | AppDialogOptions): Promise<boolean> {
  const normalized = normalizeMessage(options)
  return enqueue<boolean>('confirm', {
    title: normalized.title || '请确认',
    message: normalized.message,
    variant: normalized.variant || 'warning',
    confirmText: normalized.confirmText || '确认',
    cancelText: normalized.cancelText || '取消',
  })
}

export function appPrompt(options: string | AppPromptOptions): Promise<string | null> {
  const normalized = typeof options === 'string' ? { message: options } : options
  return enqueue<string | null>('prompt', {
    title: normalized.title || '请输入',
    message: normalized.message,
    variant: normalized.variant || 'info',
    confirmText: normalized.confirmText || '确认',
    cancelText: normalized.cancelText || '取消',
    label: normalized.label,
    defaultValue: normalized.defaultValue || '',
    placeholder: normalized.placeholder,
    required: normalized.required,
  })
}

export function useAppDialogState() {
  return readonly(state)
}
