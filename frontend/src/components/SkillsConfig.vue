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
            </div>
            <p v-if="skill.description" class="text-sm text-muted mb-2">
              {{ skill.description }}
            </p>
          </div>
          <div class="flex items-center gap-2 ml-4">
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
}

const skills = ref<Skill[]>([])
const loading = ref(false)
const showAddModal = ref(false)
const editingSkill = ref<Skill | null>(null)

const formData = ref({
  name: '',
  description: '',
})

const loadSkills = async () => {
  loading.value = true
  try {
    const { getSkillsList } = await import('@/api')
    const result = await getSkillsList()
    if (result.status === 'ok') {
      // 后端返回字段做一次归一化。
      const raw = (result.data?.skills || []) as any[]
      skills.value = raw.map((s: any): Skill => ({
        id: String(s?.id ?? ''),
        name: String(s?.name ?? s?.id ?? ''),
        description: s?.description,
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
      ...(editingSkill.value?.id ? { id: editingSkill.value.id } : {}),
    }
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

const closeModal = () => {
  showAddModal.value = false
  editingSkill.value = null
  formData.value = {
    name: '',
    description: '',
  }
}

onMounted(() => {
  loadSkills()
})
</script>
