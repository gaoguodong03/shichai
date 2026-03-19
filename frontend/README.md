# 心像 EchoTwin Frontend

心像 EchoTwin 前端应用（专家协作平台，兼容历史 DHA 命名）

## 快速开始

### 1. 安装依赖

```bash
npm install
# 或
pnpm install
```

### 2. 运行开发服务器

```bash
npm run dev
```

应用将在 `http://localhost:5173` 启动

### 3. 构建生产版本

```bash
npm run build
```

## 项目结构

```
frontend/
├── src/
│   ├── views/           # 页面视图
│   ├── components/      # Vue 组件
│   ├── composables/      # Composables
│   ├── router/           # 路由配置
│   └── App.vue          # 根组件
├── package.json
└── vite.config.ts
```

## 功能

- ✅ Vue 3 + TypeScript
- ✅ 聊天界面
- ✅ SSE 流式接收
- ✅ 响应式设计
