import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')

const iconAssets = [
  'src/assets/icons/workspace/new-file.svg',
  'src/assets/icons/workspace/new-folder.svg',
  'src/assets/icons/workspace/file.svg',
  'src/assets/icons/workspace/folder.svg',
  'src/assets/icons/workspace/delete.svg',
  'src/assets/icons/workspace/download.svg',
  'src/assets/icons/workspace/preview.svg',
  'src/assets/icons/workspace/refresh.svg',
  'src/assets/icons/workspace/rename.svg',
  'src/assets/icons/workspace/scenario-open.svg',
  'src/assets/icons/workspace/more.svg',
  'src/assets/icons/workspace/upload.svg',
]

for (const relativePath of iconAssets) {
  const absolutePath = resolve(frontendRoot, relativePath)
  if (!existsSync(absolutePath)) {
    throw new Error(`Missing workspace icon asset: ${relativePath}`)
  }
}

const sourceChecks = [
  {
    file: 'src/features/workspace/components/group-chat/GroupChatHeader.vue',
    required: [
      "folderIconUrl from '@/assets/icons/workspace/folder.svg'",
      'workspaceIconStyle(folderIconUrl)',
    ],
    forbidden: ['M22 19a2 2 0 0 1-2 2H4'],
  },
  {
    file: 'src/features/workspace/components/group-chat/GroupWorkspacePanel.vue',
    required: [
      "newFileIconUrl from '@/assets/icons/workspace/new-file.svg'",
      "newFolderIconUrl from '@/assets/icons/workspace/new-folder.svg'",
      "deleteIconUrl from '@/assets/icons/workspace/delete.svg'",
      "downloadIconUrl from '@/assets/icons/workspace/download.svg'",
      "fileIconUrl from '@/assets/icons/workspace/file.svg'",
      "folderIconUrl from '@/assets/icons/workspace/folder.svg'",
      "previewIconUrl from '@/assets/icons/workspace/preview.svg'",
      "refreshIconUrl from '@/assets/icons/workspace/refresh.svg'",
      "renameIconUrl from '@/assets/icons/workspace/rename.svg'",
      "uploadIconUrl from '@/assets/icons/workspace/upload.svg'",
      'workspaceIconStyle(deleteIconUrl)',
      'workspaceIconStyle(downloadIconUrl)',
      'workspaceIconStyle(refreshIconUrl)',
      'workspaceIconStyle(renameIconUrl)',
      'workspaceIconStyle(newFolderIconUrl)',
      'workspaceIconStyle(newFileIconUrl)',
      'workspaceIconStyle(fileIconUrl)',
      'workspaceIconStyle(folderIconUrl)',
      'workspaceIconStyle(previewIconUrl)',
      'workspaceIconStyle(uploadIconUrl)',
    ],
    forbidden: [
      'M21 12a9 9 0 0 1-15.1 6.6',
      'M4 7h4l2 3h10v8',
      'M14 2H6a2 2 0 0 0-2 2v16',
      '>↓</button>',
      '>R</button>',
      '>×</button>',
    ],
  },
  {
    file: 'src/features/workspace/FileDetailView.vue',
    required: [
      "deleteIconUrl from '@/assets/icons/workspace/delete.svg'",
      "downloadIconUrl from '@/assets/icons/workspace/download.svg'",
      "renameIconUrl from '@/assets/icons/workspace/rename.svg'",
      'workspaceIconStyle(deleteIconUrl)',
      'workspaceIconStyle(downloadIconUrl)',
      'workspaceIconStyle(renameIconUrl)',
    ],
    forbidden: [],
  },
  {
    file: 'src/features/workspace/WorkspaceFilesView.vue',
    required: [
      "newFileIconUrl from '@/assets/icons/workspace/new-file.svg'",
      "newFolderIconUrl from '@/assets/icons/workspace/new-folder.svg'",
      "fileIconUrl from '@/assets/icons/workspace/file.svg'",
      "folderIconUrl from '@/assets/icons/workspace/folder.svg'",
      "refreshIconUrl from '@/assets/icons/workspace/refresh.svg'",
      "uploadIconUrl from '@/assets/icons/workspace/upload.svg'",
    ],
    forbidden: ['[DIR]', '[FILE]'],
  },
  {
    file: 'src/features/workspace/components/group-chat/GroupChatComposer.vue',
    required: [
      "fileIconUrl from '@/assets/icons/workspace/file.svg'",
      "folderIconUrl from '@/assets/icons/workspace/folder.svg'",
      "moreIconUrl from '@/assets/icons/workspace/more.svg'",
      "scenarioOpenIconUrl from '@/assets/icons/workspace/scenario-open.svg'",
      "uploadIconUrl from '@/assets/icons/workspace/upload.svg'",
      'workspaceIconStyle(fileIconUrl)',
      'workspaceIconStyle(moreIconUrl)',
      'workspaceIconStyle(scenarioOpenIconUrl)',
      'folderIconUrl : fileIconUrl',
      'workspaceIconStyle(uploadIconUrl)',
    ],
    forbidden: ['M12 13v4', '<rect x="4" y="4" width="7" height="7" rx="1.3"', '<circle cx="5" cy="12" r="1.5"'],
  },
]

for (const check of sourceChecks) {
  const source = readFileSync(resolve(frontendRoot, check.file), 'utf8')
  for (const expected of check.required) {
    if (!source.includes(expected)) {
      throw new Error(`${check.file} does not contain expected icon usage: ${expected}`)
    }
  }
  for (const oldShape of check.forbidden) {
    if (source.includes(oldShape)) {
      throw new Error(`${check.file} still contains old icon marker: ${oldShape}`)
    }
  }
}

const groupWorkspacePanelSource = readFileSync(
  resolve(frontendRoot, 'src/features/workspace/components/group-chat/GroupWorkspacePanel.vue'),
  'utf8',
)
const previewDownloadTextIndex = groupWorkspacePanelSource.indexOf('下载', groupWorkspacePanelSource.indexOf('group-chat-workspace-preview-actions'))
if (previewDownloadTextIndex === -1) {
  throw new Error('GroupWorkspacePanel.vue is missing the workspace preview download button text')
}
const previewDownloadButtonStart = groupWorkspacePanelSource.lastIndexOf('<button', previewDownloadTextIndex)
const previewDownloadButtonEnd = groupWorkspacePanelSource.indexOf('</button>', previewDownloadTextIndex)
const previewDownloadButtonMarkup = groupWorkspacePanelSource.slice(previewDownloadButtonStart, previewDownloadButtonEnd)
if (previewDownloadButtonMarkup.includes('workspaceIconStyle(downloadIconUrl)')) {
  throw new Error('Workspace preview download button should not render a leading icon')
}

console.log('Workspace file icons use replaceable SVG assets.')
