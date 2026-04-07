<template>
  <div class="max-w-4xl mx-auto text-primary">
    <!-- 标题和添加按钮 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-primary">Skills 配置</h2>
        <p class="text-sm text-muted mt-1">配置和管理 Skills，提供策略层指导</p>
      </div>
      <button
        @click="showAddModal = true"
        class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:bg-accent-hover transition-colors"
      >
        + 添加 Skill
      </button>
    </div>

    <!-- Skills 列表 -->
    <div v-if="loading" class="text-center py-8 text-muted">
      加载中...
    </div>
    <div v-else-if="skills.length === 0" class="text-center py-12 text-muted">
      <p class="mb-4">还没有配置 Skill</p>
      <button
        @click="showAddModal = true"
        class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:bg-accent-hover"
      >
        添加第一个 Skill
      </button>
    </div>
    <div v-else class="space-y-4">
      <div
        v-for="skill in skills"
        :key="skill.id"
        class="bg-card rounded-lg border border-border p-4 hover:shadow-md transition-shadow"
      >
        <div class="flex items-start justify-between">
          <div class="flex-1">
            <div class="flex items-center gap-3 mb-2">
              <h3 class="text-lg font-semibold text-primary">{{ skill.name }}</h3>
              <span
                :class="[
                  'px-2 py-1 text-xs rounded-full',
                  skill.enabled
                    ? 'bg-accent-subtle text-accent-subtle-text'
                    : 'bg-list-hover text-muted'
                ]"
              >
                {{ skill.enabled ? '已启用' : '已禁用' }}
              </span>
              <span
                :class="[
                  'px-2 py-1 text-xs rounded-full',
                  skill.source === 'local'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-purple-100 text-purple-700'
                ]"
              >
                {{ skill.source === 'local' ? '本地' : 'Git' }}
              </span>
            </div>
            <p v-if="skill.description" class="text-sm text-muted mb-2">
              {{ skill.description }}
            </p>
            <div class="text-sm text-muted">
              <span v-if="skill.source === 'local'">路径: {{ skill.path }}</span>
              <span v-else>URL: {{ skill.url }}</span>
            </div>
          </div>
          <div class="flex items-center gap-2 ml-4">
            <button
              @click="toggleSkill(skill.id, !skill.enabled)"
              :class="[
                'px-3 py-1 text-sm rounded',
                skill.enabled
                  ? 'bg-list-hover text-primary hover:opacity-90'
                  : 'bg-green-100 text-green-700 hover:bg-green-200'
              ]"
            >
              {{ skill.enabled ? '禁用' : '启用' }}
            </button>
            <button
              @click="editSkill(skill)"
              class="px-3 py-1 text-sm bg-list-hover text-primary rounded hover:opacity-90"
            >
              编辑
            </button>
            <button
              @click="deleteSkill(skill.id)"
              class="px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加/编辑 Modal -->
    <div
      v-if="showAddModal || editingSkill"
      class="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      @click.self="closeModal"
    >
      <div class="bg-card border border-border rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div class="p-6">
          <h3 class="text-xl font-semibold mb-4">
            {{ editingSkill ? '编辑 Skill' : '添加 Skill' }}
          </h3>
          
          <form @submit.prevent="saveSkill" class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-primary mb-1">
                名称 *
              </label>
              <input
                v-model="formData.name"
                type="text"
                required
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                placeholder="例如：数据分析"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-primary mb-1">
                来源 *
              </label>
              <select
                v-model="formData.source"
                @change="onSourceChange"
                required
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              >
                <option value="local">本地</option>
                <option value="git">Git URL</option>
              </select>
            </div>

            <!-- 本地路径 -->
            <div v-if="formData.source === 'local'">
              <label class="block text-sm font-medium text-primary mb-1">
                路径 *
              </label>
              <input
                v-model="formData.path"
                type="text"
                required
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                placeholder="例如：本机目录或 zip；技能落盘在 data/users/<邮箱>/skills/"
              />
            </div>

            <!-- Git URL -->
            <div v-if="formData.source === 'git'">
              <label class="block text-sm font-medium text-primary mb-1">
                URL *
              </label>
              <input
                v-model="formData.url"
                type="url"
                required
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                placeholder="例如：https://example.com/skills/data-analysis"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-primary mb-1">写入模式</label>
              <select
                v-model="formData.write_mode"
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              >
                <option value="readonly">readonly（只读）</option>
                <option value="workspace_all">workspace_all（可改会话工作区）</option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-primary mb-1">
                描述
              </label>
              <textarea
                v-model="formData.description"
                rows="3"
                class="w-full px-3 py-2 border border-input-border bg-input-bg text-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                placeholder="Skill 的功能描述"
              />
            </div>

            <div class="flex justify-end gap-3 pt-4">
              <button
                type="button"
                @click="closeModal"
                class="px-4 py-2 text-primary bg-list-hover rounded-lg hover:opacity-90"
              >
                取消
              </button>
              <button
                type="submit"
                class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
              >
                保存
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface Skill {
  id: string
  name: string
  description?: string
  enabled: boolean
  source: 'local' | 'git'
  path?: string
  url?: string
  write_mode?: 'readonly' | 'workspace_all'
}

const skills = ref<Skill[]>([])
const loading = ref(false)
const showAddModal = ref(false)
const editingSkill = ref<Skill | null>(null)

const formData = ref({
  name: '',
  description: '',
  source: 'local' as 'local' | 'git',
  path: '',
  url: '',
  write_mode: 'readonly' as 'readonly' | 'workspace_all',
})

const loadSkills = async () => {
  loading.value = true
  try {
    const { getSkillsList } = await import('@/api')
    const result = await getSkillsList()
    if (result.status === 'ok') {
      // 后端返回在类型上可能缺少 enabled/source 等字段；做一次归一化以满足 Skill 类型。
      const raw = (result.data?.skills || []) as any[]
      skills.value = raw.map((s: any): Skill => ({
        id: String(s?.id ?? ''),
        name: String(s?.name ?? s?.id ?? ''),
        description: s?.description,
        enabled: s?.enabled ?? true,
        source: s?.source === 'git' ? 'git' : 'local',
        path: s?.path,
        url: s?.url,
        write_mode: s?.write_mode,
      }))
    }
  } catch (error) {
    console.error('Failed to load skills:', error)
  } finally {
    loading.value = false
  }
}

const saveSkill = async () => {
  try {
    const { saveSkill: apiSaveSkill } = await import('@/api')
    const payload: any = {
      name: formData.value.name,
      description: formData.value.description,
      source: formData.value.source,
      write_mode: formData.value.write_mode,
      ...(editingSkill.value?.id ? { id: editingSkill.value.id } : {}),
    }
    if (formData.value.source === 'local') payload.path = formData.value.path
    else payload.url = formData.value.url
    const result = await apiSaveSkill(payload)
    if (result.status === 'ok') {
      await loadSkills()
      closeModal()
    } else {
      alert(result.error?.message || '保存失败')
    }
  } catch (error) {
    console.error('Failed to save skill:', error)
    alert('保存失败')
  }
}

const editSkill = (skill: Skill) => {
  editingSkill.value = skill
  formData.value = {
    name: skill.name,
    description: skill.description || '',
    source: skill.source,
    path: skill.path || '',
    url: skill.url || '',
    write_mode: skill.write_mode || 'readonly',
  }
  showAddModal.value = true
}

const deleteSkill = async (id: string) => {
  if (!confirm('确定要删除这个 Skill 吗？')) return
  try {
    const { deleteSkill: apiDeleteSkill } = await import('@/api')
    const result = await apiDeleteSkill(id)
    if (result.status === 'ok') await loadSkills()
    else alert(result.error?.message || '删除失败')
  } catch (error) {
    console.error('Failed to delete skill:', error)
    alert('删除失败')
  }
}

const toggleSkill = async (id: string, enabled: boolean) => {
  try {
    const { toggleSkill: apiToggleSkill } = await import('@/api')
    const result = await apiToggleSkill(id, enabled)
    if (result.status === 'ok') await loadSkills()
    else alert(result.error?.message || '操作失败')
  } catch (error) {
    console.error('Failed to toggle skill:', error)
    alert('操作失败')
  }
}

const closeModal = () => {
  showAddModal.value = false
  editingSkill.value = null
  formData.value = {
    name: '',
    description: '',
    source: 'local',
    path: '',
    url: '',
    write_mode: 'readonly',
  }
}

const onSourceChange = () => {
  if (formData.value.source === 'local') {
    formData.value.url = ''
  } else {
    formData.value.path = ''
  }
}

onMounted(() => {
  loadSkills()
})
</script>
