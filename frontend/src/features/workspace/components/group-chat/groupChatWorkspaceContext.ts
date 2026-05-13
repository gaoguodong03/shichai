import { inject, provide } from 'vue'

export type GroupChatWorkspaceContext = Record<string, any>

const GROUP_CHAT_WORKSPACE_CONTEXT_KEY = Symbol('GroupChatWorkspaceContext')

export function provideGroupChatWorkspaceContext(ctx: GroupChatWorkspaceContext) {
  provide(GROUP_CHAT_WORKSPACE_CONTEXT_KEY, ctx)
}

export function useGroupChatWorkspaceContext(): GroupChatWorkspaceContext {
  const ctx = inject<GroupChatWorkspaceContext>(GROUP_CHAT_WORKSPACE_CONTEXT_KEY)
  if (!ctx) throw new Error('GroupChatWorkspaceContext is not provided')
  return ctx
}
