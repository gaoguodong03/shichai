# 书童四九 · 前端

Vue 3 + TypeScript + Vite，与后端 `/api` 通信；登录后使用 `localStorage` 中的 token，通过全局 `fetch` 包装发送 `Authorization: Bearer`。

## 快速开始

```bash
npm install
npm run dev
```

默认开发地址：`http://localhost:5173`（API 由 Vite 代理到 `http://127.0.0.1:8000` 的后端，见 `vite.config.ts`）。

## 构建

```bash
npm run build
```

## 项目结构（节选）

```
frontend/
├── src/
│   ├── views/
│   ├── components/
│   ├── router/
│   └── main.ts          # 全局 fetch 附带 Bearer
├── package.json
└── vite.config.ts
```
