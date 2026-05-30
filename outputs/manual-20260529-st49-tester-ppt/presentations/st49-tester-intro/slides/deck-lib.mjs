const ROOT = "/Users/ggd/project/shichai";
const A = `${ROOT}/docs/architecture/system-architecture-imagegen.png`;
const IMG = {
  workspace: `${ROOT}/docs/user-manual/images/workspace-overview.png`,
  skill: `${ROOT}/docs/user-manual/images/resources-skill.png`,
  sandbox: `${ROOT}/docs/user-manual/images/settings-sandbox.png`,
  share: `${ROOT}/docs/user-manual/images/share-preview.png`,
  login: `${ROOT}/docs/user-manual/images/login-page.png`,
};

const C = {
  ink: "#172033",
  muted: "#64748B",
  faint: "#EEF2F7",
  paper: "#F8FAFC",
  white: "#FFFFFF",
  blue: "#2563EB",
  cyan: "#0891B2",
  green: "#059669",
  amber: "#D97706",
  red: "#DC2626",
  line: "#CBD5E1",
  dark: "#0F172A",
};

const deckTitle = "书童四九测试员介绍";

function bg(slide, ctx, fill = C.paper) {
  ctx.addShape(slide, { x: 0, y: 0, w: ctx.W, h: ctx.H, fill });
}

function text(slide, ctx, t, x, y, w, h, opts = {}) {
  const s = ctx.addText(slide, {
    text: t,
    x, y, w, h,
    fontSize: opts.size ?? 24,
    color: opts.color ?? C.ink,
    bold: opts.bold ?? false,
    typeface: opts.face ?? "Microsoft YaHei",
    align: opts.align ?? "left",
    valign: opts.valign ?? "top",
    fill: opts.fill ?? "#00000000",
    line: opts.line ?? { style: "solid", fill: "#00000000", width: 0 },
    insets: opts.insets ?? { left: 0, right: 0, top: 0, bottom: 0 },
  });
  if (opts.fit) s.text.autoFit = opts.fit;
  return s;
}

function title(slide, ctx, t, sub) {
  text(slide, ctx, t, 54, 36, 780, 50, { size: 31, bold: true });
  if (sub) text(slide, ctx, sub, 56, 89, 930, 28, { size: 14, color: C.muted });
}

function footer(slide, ctx, n) {
  text(slide, ctx, deckTitle, 54, 684, 360, 18, { size: 10, color: "#94A3B8" });
  text(slide, ctx, String(n).padStart(2, "0"), 1180, 681, 46, 20, { size: 11, color: "#94A3B8", align: "right" });
}

function box(slide, ctx, x, y, w, h, fill = C.white, line = C.line) {
  return ctx.addShape(slide, {
    x, y, w, h,
    fill,
    line: { style: "solid", fill: line, width: 1 },
  });
}

function metric(slide, ctx, x, y, w, v, label, color = C.blue) {
  box(slide, ctx, x, y, w, 88, C.white, "#E2E8F0");
  ctx.addShape(slide, { x, y, w: 6, h: 88, fill: color, line: { style: "solid", fill: color, width: 0 } });
  text(slide, ctx, v, x + 20, y + 15, w - 30, 32, { size: 28, bold: true, color });
  text(slide, ctx, label, x + 20, y + 51, w - 30, 26, { size: 12, color: C.muted });
}

function smallLabel(slide, ctx, t, x, y, w, color = C.blue) {
  text(slide, ctx, t, x, y, w, 20, { size: 11, bold: true, color });
}

function bulletList(slide, ctx, items, x, y, w, lineH = 34, opts = {}) {
  items.forEach((item, i) => {
    const color = opts.color ?? C.blue;
    ctx.addShape(slide, { x, y: y + i * lineH + 6, w: 7, h: 7, fill: color, line: { style: "solid", fill: color, width: 0 } });
    text(slide, ctx, item, x + 20, y + i * lineH, w - 20, lineH - 2, { size: opts.size ?? 15, color: opts.textColor ?? C.ink, fit: "shrinkText" });
  });
}

function stage(slide, ctx, x, y, w, h, head, body, color = C.blue) {
  box(slide, ctx, x, y, w, h, C.white, "#DCE6F2");
  ctx.addShape(slide, { x, y, w, h: 5, fill: color, line: { style: "solid", fill: color, width: 0 } });
  text(slide, ctx, head, x + 16, y + 18, w - 32, 28, { size: 18, bold: true, color });
  text(slide, ctx, body, x + 16, y + 52, w - 32, h - 62, { size: 13, color: C.muted, fit: "shrinkText" });
}

function arrow(slide, ctx, x1, y1, x2, y2, color = C.line) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ang = Math.atan2(dy, dx);
  const bodyX = x1;
  const bodyY = y1 - 1.5;
  const line = ctx.addShape(slide, { x: bodyX, y: bodyY, w: Math.max(len - 11, 1), h: 3, fill: color, line: { style: "solid", fill: color, width: 0 } });
  line.rotation = (ang * 180) / Math.PI;
  ctx.addShape(slide, { geometry: "triangle", x: x2 - 9, y: y2 - 6, w: 14, h: 12, fill: color, line: { style: "solid", fill: color, width: 0 } });
}

async function screenshot(slide, ctx, imagePath, x, y, w, h, fit = "cover") {
  box(slide, ctx, x - 1, y - 1, w + 2, h + 2, C.white, "#D8E1EC");
  await ctx.addImage(slide, { path: imagePath, x, y, w, h, fit, alt: "repository UI screenshot" });
}

function command(slide, ctx, t, x, y, w, h = 40) {
  box(slide, ctx, x, y, w, h, "#0B1120", "#0B1120");
  text(slide, ctx, t, x + 18, y + 10, w - 36, h - 14, { size: 14, color: "#E2E8F0", face: "Aptos Mono", fit: "shrinkText" });
}

function headerBand(slide, ctx, label, x, y, w, color) {
  ctx.addShape(slide, { x, y, w, h: 28, fill: color, line: { style: "solid", fill: color, width: 0 } });
  text(slide, ctx, label, x + 12, y + 6, w - 24, 16, { size: 10, bold: true, color: C.white });
}

async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, "#F7FAFC");
  text(slide, ctx, "书童四九", 60, 70, 530, 64, { size: 48, bold: true });
  text(slide, ctx, "面向测试员的项目介绍与 E2E 验收 PPT", 62, 145, 760, 38, { size: 24, color: C.blue, bold: true });
  text(slide, ctx, "目标：让测试员先理解系统边界、调用链与用户可见路径，再按统一证据标准执行验收。", 64, 204, 700, 48, { size: 17, color: C.muted });
  metric(slide, ctx, 64, 328, 214, "7", "当前 UI E2E spec 文件", C.blue);
  metric(slide, ctx, 304, 328, 214, "35", "可点击用户路径用例", C.green);
  metric(slide, ctx, 544, 328, 214, "3", "常用上线门禁命令", C.amber);
  box(slide, ctx, 816, 68, 390, 530, C.white, "#DEE8F4");
  await ctx.addImage(slide, { path: A, x: 830, y: 90, w: 362, h: 204, fit: "cover", alt: "system architecture overview" });
  smallLabel(slide, ctx, "本稿包含", 844, 328, 120, C.blue);
  bulletList(slide, ctx, [
    "系统定位与三块操作入口",
    "浏览器到 Agent Runtime 的调用关系",
    "平台使用路径与关键截图",
    "E2E 覆盖矩阵、命令与失败证据"
  ], 846, 360, 320, 39, { size: 15 });
  footer(slide, ctx, 1);
  return slide;
}

async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "测试员先看三块入口，不要先陷进实现细节", "书童四九 = 工作空间执行任务 + 资源中心配置能力 + 设置维护运行环境");
  stage(slide, ctx, 68, 156, 330, 250, "工作空间", "新建会话、发送消息、邀请专家、插入文件、选择场景。这里验证用户是否真的能完成任务。", C.blue);
  stage(slide, ctx, 474, 156, 330, 250, "资源中心", "维护场景、专家、Skills、MCP 工具、模型与文件。这里验证资源 CRUD、依赖、分享和导入。", C.green);
  stage(slide, ctx, 880, 156, 330, 250, "设置", "主持人、主题、密钥、账号安全和沙箱 requirements。这里验证用户级配置和敏感信息处理。", C.amber);
  arrow(slide, ctx, 405, 281, 466, 281);
  arrow(slide, ctx, 812, 281, 872, 281);
  box(slide, ctx, 68, 464, 1142, 116, "#EFF6FF", "#BBD7FF");
  text(slide, ctx, "测试口径", 92, 486, 130, 24, { size: 18, bold: true, color: C.blue });
  bulletList(slide, ctx, [
    "用户可见路径优先：能登录、能点、能保存、能刷新恢复、能看到错误",
    "用户隔离优先：A 用户的会话、文件、Skill、密钥、沙箱配置不能泄露给 B 用户",
    "证据优先：失败时必须带路径、截图/trace、请求响应、预期与实际差异"
  ], 228, 482, 900, 28, { size: 15, color: C.blue });
  footer(slide, ctx, 2);
  return slide;
}

async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, C.dark);
  text(slide, ctx, "系统架构总览", 54, 28, 380, 42, { size: 30, bold: true, color: C.white });
  text(slide, ctx, "读图顺序：UI 发起 REST/SSE，API 建立用户上下文，Agent 调度专家与 ReAct，Runtime 执行 MCP、Skill 与文件工具。", 56, 76, 1040, 28, { size: 14, color: "#CBD5E1" });
  await ctx.addImage(slide, { path: A, x: 54, y: 114, w: 1170, h: 548, fit: "contain", alt: "system architecture imagegen" });
  footer(slide, ctx, 3);
  return slide;
}

async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "一次用户操作的整体调用关系", "测试失败时先定位断在哪一层：UI、API、编排、工具运行、数据或外部服务");
  const y = 182;
  const nodes = [
    ["Vue SPA", "工作空间/资源中心/设置\n可见按钮、表单、路由守卫", C.blue],
    ["FastAPI /api", "/api/sessions/*\n/api/agents/*\n设置/文件/分享 API", C.cyan],
    ["会话与编排", "主持人调度\n专家配置装载\nSSE 事件输出", C.green],
    ["ReAct Runtime", "模型步 -> 工具步 -> 结束步\nSimpleAgent 统一循环", C.amber],
    ["工具与数据", "MCP / Skill 脚本 / 文件工具\nbackend/data/users/{user_id}", C.red],
  ];
  nodes.forEach((n, i) => {
    const x = 54 + i * 242;
    stage(slide, ctx, x, y, 196, 172, n[0], n[1], n[2]);
    if (i < nodes.length - 1) arrow(slide, ctx, x + 202, y + 86, x + 236, y + 86);
  });
  box(slide, ctx, 70, 438, 520, 132, C.white, "#DDE7F2");
  headerBand(slide, ctx, "测试要观察的返回", 70, 438, 520, C.blue);
  bulletList(slide, ctx, [
    "页面：按钮可见、状态反馈、表单保存、刷新恢复",
    "SSE：route/content/message/end 等事件被前端正确消费",
    "错误：无权限、缺依赖、沙箱不可达时给出可诊断提示"
  ], 94, 482, 450, 25, { size: 13 });
  box(slide, ctx, 660, 438, 520, 132, C.white, "#DDE7F2");
  headerBand(slide, ctx, "常见归因边界", 660, 438, 520, C.green);
  bulletList(slide, ctx, [
    "UI 失败：控件找不到、路由错误、状态未刷新",
    "API 失败：鉴权、用户上下文、数据读写、响应结构",
    "Runtime 失败：工具未加载、模型未发 tool_call、沙箱/依赖异常"
  ], 684, 482, 450, 25, { size: 13, color: C.green });
  footer(slide, ctx, 4);
  return slide;
}

async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "平台如何使用：测试员按真实用户路径走", "不要只从接口入手；先用页面建立完整路径，再用日志和 API 归因");
  await screenshot(slide, ctx, IMG.login, 58, 138, 258, 172);
  await screenshot(slide, ctx, IMG.workspace, 354, 138, 258, 172);
  await screenshot(slide, ctx, IMG.skill, 650, 138, 258, 172);
  await screenshot(slide, ctx, IMG.sandbox, 946, 138, 258, 172);
  [["登录/注册", 58], ["工作空间", 354], ["资源中心", 650], ["设置/沙箱", 946]].forEach(([label, x]) => {
    text(slide, ctx, label, x, 326, 258, 24, { size: 15, bold: true, color: C.ink, align: "center" });
  });
  arrow(slide, ctx, 325, 224, 347, 224);
  arrow(slide, ctx, 621, 224, 643, 224);
  arrow(slide, ctx, 917, 224, 939, 224);
  box(slide, ctx, 78, 414, 1120, 134, "#F0FDF4", "#BFE8D2");
  text(slide, ctx, "最小用户旅程", 104, 440, 160, 24, { size: 18, bold: true, color: C.green });
  bulletList(slide, ctx, [
    "登录后进入工作空间，创建会话并发送一条消息",
    "进入资源中心，确认场景/专家/Skill/工具/模型能查看、创建和保存",
    "进入设置，确认主持人、密钥、账号、安全和沙箱 requirements 是当前用户自己的",
    "打开分享链接，预览后确认导入，回到资源中心检查结果"
  ], 270, 432, 850, 24, { size: 13, color: C.green });
  footer(slide, ctx, 5);
  return slide;
}

async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "测试分层：每层回答不同问题", "上线前不要用一个命令替代所有判断；先确定本次风险属于哪一层");
  const rows = [
    ["UI 点击级自动化", "./scripts/test-ui-flow.sh", "真实 Vue 页面、路由、按钮、输入框、关键用户路径", "不验证真实 LLM、Docker、OpenSandbox"],
    ["第一层回归", "./scripts/test-layer1.sh", "后端核心链路 + 前端构建，适合最低上线门禁", "不覆盖所有 HTTP 路由和真实外部服务"],
    ["完整门禁", "./scripts/test-full-flow.sh", "后端全量测试 + 前端生产构建，适合提测/上线前", "仍需部署冒烟验证环境变量和容器"],
    ["部署冒烟", "docker compose -f docker-compose.1panel.yml up -d", "容器、健康检查、登录、基础对话、技能沙箱", "依赖目标机器、镜像和模型 Key"],
  ];
  const x = 58, y = 140, widths = [205, 352, 354, 253];
  ["层级", "命令", "覆盖什么", "不覆盖什么"].forEach((h, i) => {
    headerBand(slide, ctx, h, x + widths.slice(0, i).reduce((a, b) => a + b, 0), y, widths[i], i === 0 ? C.blue : C.dark);
  });
  rows.forEach((r, ri) => {
    const yy = y + 28 + ri * 88;
    let xx = x;
    r.forEach((cell, ci) => {
      box(slide, ctx, xx, yy, widths[ci], 88, ri % 2 ? "#F8FAFC" : C.white, "#E2E8F0");
      text(slide, ctx, cell, xx + 12, yy + 14, widths[ci] - 24, 62, { size: ci === 1 ? 12 : 13, bold: ci === 0, color: ci === 1 ? C.blue : C.ink, face: ci === 1 ? "Aptos Mono" : "Microsoft YaHei", fit: "shrinkText" });
      xx += widths[ci];
    });
  });
  command(slide, ctx, "FRONTEND_INSTALL=skip ./scripts/test-ui-flow.sh", 270, 622, 740, 42);
  footer(slide, ctx, 6);
  return slide;
}

async function slide07(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "当前 E2E 覆盖：7 个 spec，35 个用户路径用例", "这里是测试员最该先跑通的前端可见验收层");
  const data = [
    ["登录与账号入口", "auth.spec.ts", 3, C.blue],
    ["路由边界", "route-boundaries.spec.ts", 5, C.cyan],
    ["工作空间会话与文件", "workspace.spec.ts", 10, C.green],
    ["资源中心场景与专家", "resources-scenario-expert.spec.ts", 5, C.amber],
    ["资源中心技能/工具/模型", "resources-skill-mcp-llm.spec.ts", 5, C.red],
    ["设置中心", "settings.spec.ts", 5, "#7C3AED"],
    ["分享链接与公开场景", "share-routes.spec.ts", 2, "#0F766E"],
  ];
  data.forEach((d, i) => {
    const y = 146 + i * 60;
    text(slide, ctx, d[0], 70, y + 5, 230, 24, { size: 14, bold: true });
    text(slide, ctx, d[1], 310, y + 6, 300, 22, { size: 12, color: C.muted, face: "Aptos Mono" });
    ctx.addShape(slide, { x: 630, y: y + 6, w: d[2] * 20, h: 24, fill: d[3], line: { style: "solid", fill: d[3], width: 0 } });
    text(slide, ctx, `${d[2]} cases`, 630 + d[2] * 20 + 14, y + 5, 90, 24, { size: 13, color: C.muted });
  });
  box(slide, ctx, 938, 144, 250, 348, C.white, "#DCE6F2");
  text(slide, ctx, "读取方式", 962, 168, 150, 26, { size: 18, bold: true, color: C.blue });
  bulletList(slide, ctx, [
    "先看 describe 名称：对应验收 1/6 到 6/6",
    "再看 test 名称：就是用户需求表达",
    "定位控件优先 role、label、placeholder 和可见文本",
    "失败时看 Playwright trace，不只看终端红字"
  ], 964, 210, 190, 39, { size: 12 });
  command(slide, ctx, "./scripts/test-ui-flow.sh", 938, 536, 250, 42);
  footer(slide, ctx, 7);
  return slide;
}

async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "关键路径 1：工作空间会话、文件与场景入口", "这是最接近真实用户任务完成度的验收面");
  await screenshot(slide, ctx, IMG.workspace, 58, 132, 588, 392);
  box(slide, ctx, 694, 132, 492, 392, C.white, "#DCE6F2");
  headerBand(slide, ctx, "必须验证", 694, 132, 492, C.green);
  bulletList(slide, ctx, [
    "新建会话后能看到新对话标题和输入框",
    "发送消息后能看到专家回复或可诊断错误",
    "成员管理能显示主持人、当前成员和可邀请专家",
    "文件入口能插入已有文件或上传本地文件",
    "场景快捷入口不会把旧用户本地历史带给新账号",
    "运行中的会话状态、完成提示、刷新恢复都要一致"
  ], 724, 180, 410, 39, { size: 14, color: C.green });
  box(slide, ctx, 58, 560, 1128, 60, "#ECFEFF", "#BAE6FD");
  text(slide, ctx, "自动化锚点：frontend/e2e/workspace.spec.ts 覆盖 10 个用例，是当前 UI E2E 中最重的一组。", 82, 580, 1048, 22, { size: 15, bold: true, color: "#0E7490" });
  footer(slide, ctx, 8);
  return slide;
}

async function slide09(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "关键路径 2：资源中心决定 Agent 能力从哪里来", "场景、专家、Skill、MCP、模型不是配置页装饰，它们会进入会话编排和工具组装");
  await screenshot(slide, ctx, IMG.skill, 704, 128, 480, 320);
  const x = 72, y = 164;
  stage(slide, ctx, x, y, 142, 106, "场景", "组合主持人与协作专家", C.blue);
  stage(slide, ctx, x + 178, y, 142, 106, "专家", "绑定人设、模型、Skill", C.green);
  stage(slide, ctx, x + 356, y, 142, 106, "Skill", "策略、脚本、依赖声明", C.amber);
  stage(slide, ctx, x + 178, y + 170, 142, 106, "MCP 工具", "标准化执行能力", C.cyan);
  stage(slide, ctx, x + 356, y + 170, 142, 106, "模型", "Provider、参数、Key 引用", C.red);
  arrow(slide, ctx, x + 148, y + 53, x + 170, y + 53);
  arrow(slide, ctx, x + 326, y + 53, x + 348, y + 53);
  arrow(slide, ctx, x + 426, y + 112, x + 258, y + 166, "#94A3B8");
  arrow(slide, ctx, x + 320, y + 223, x + 348, y + 223);
  box(slide, ctx, 74, 520, 1110, 92, "#FFF7ED", "#FED7AA");
  text(slide, ctx, "资源中心测试结论必须回答：资源能否保存、能否被会话读取、缺依赖时是否提示清楚、分享/导入后是否影响当前用户自己的资源。", 104, 546, 1000, 30, { size: 16, bold: true, color: "#C2410C", fit: "shrinkText" });
  footer(slide, ctx, 9);
  return slide;
}

async function slide10(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "关键路径 3：设置、沙箱与分享是高风险验收区", "这里最容易出现用户隔离、敏感字段、运行依赖和导入冲突问题");
  await screenshot(slide, ctx, IMG.sandbox, 60, 128, 372, 248);
  await screenshot(slide, ctx, IMG.share, 456, 128, 372, 248);
  box(slide, ctx, 862, 128, 314, 248, C.white, "#DCE6F2");
  headerBand(slide, ctx, "风险点", 862, 128, 314, C.red);
  bulletList(slide, ctx, [
    "密钥不能明文回显",
    "主题和偏好不能影响登录页或其他用户",
    "沙箱版本和 requirements 是用户级配置",
    "分享导入要能预览、确认、处理冲突",
    "旧链接 /scenario/run 仍要兼容"
  ], 888, 178, 250, 33, { size: 13, color: C.red });
  box(slide, ctx, 60, 446, 1116, 92, "#F8FAFC", "#CBD5E1");
  text(slide, ctx, "测试员判断标准", 86, 470, 150, 24, { size: 18, bold: true });
  text(slide, ctx, "设置类页面不只看保存成功，还要刷新后复查、换账号复查、回到工作空间复查。分享类页面不只看导入成功，还要回到资源中心确认导入对象和依赖状态。", 248, 468, 848, 38, { size: 15, color: C.muted, fit: "shrinkText" });
  footer(slide, ctx, 10);
  return slide;
}

async function slide11(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx);
  title(slide, ctx, "失败证据：不要只报“测试失败”", "每个失败都要能让开发者定位到层级、路径、状态和复现条件");
  const cols = [
    ["1. 复现入口", "页面 URL、账号、前置资源、点击步骤、输入内容"],
    ["2. 可见证据", "截图、视频、Playwright trace、控制台错误、页面状态"],
    ["3. 请求证据", "相关 API、状态码、响应体、SSE 事件、request id"],
    ["4. 归因层级", "UI / API / 编排 / Runtime / 数据 / 外部服务"],
  ];
  cols.forEach((c, i) => {
    stage(slide, ctx, 64 + i * 294, 154, 246, 182, c[0], c[1], [C.blue, C.green, C.amber, C.red][i]);
  });
  box(slide, ctx, 94, 400, 500, 160, C.white, "#DCE6F2");
  headerBand(slide, ctx, "Playwright 失败先看", 94, 400, 500, C.blue);
  bulletList(slide, ctx, [
    "控件定位是否过宽或页面文案重复",
    "mock API 是否覆盖本次请求",
    "页面是否被路由守卫重定向",
    "等待条件是否绑定到真实可见状态"
  ], 120, 446, 420, 24, { size: 12 });
  box(slide, ctx, 684, 400, 500, 160, C.white, "#DCE6F2");
  headerBand(slide, ctx, "后端失败先看", 684, 400, 500, C.green);
  bulletList(slide, ctx, [
    "用户上下文是否正确",
    "资源路径是否在 backend/data/users/{user_id}",
    "模型是否真的发出 tool_call",
    "沙箱、MCP 或 requirements 是否是运行层问题"
  ], 710, 446, 420, 24, { size: 12, color: C.green });
  footer(slide, ctx, 11);
  return slide;
}

async function slide12(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(slide, ctx, "#F1F5F9");
  title(slide, ctx, "测试员执行 Runbook", "按这个顺序交付，结论会更稳定，也更容易复现");
  const steps = [
    ["准备", "确认代码版本、依赖、Chrome、测试账号、是否需要 Docker/模型 Key"],
    ["先跑 UI", "./scripts/test-ui-flow.sh\n确认 7 spec / 35 cases 全部通过"],
    ["跑门禁", "./scripts/test-layer1.sh\n高风险或提测时再跑 ./scripts/test-full-flow.sh"],
    ["手工复核", "登录、工作空间、资源中心、设置、分享导入各抽一条真实路径"],
    ["交付证据", "通过项给命令结果；失败项给截图/trace/API/归因层级"],
  ];
  steps.forEach((s, i) => {
    const y = 130 + i * 92;
    ctx.addShape(slide, { geometry: "ellipse", x: 76, y: y + 8, w: 42, h: 42, fill: i < 3 ? C.blue : C.green, line: { style: "solid", fill: "#00000000", width: 0 } });
    text(slide, ctx, String(i + 1), 76, y + 17, 42, 20, { size: 16, bold: true, color: C.white, align: "center" });
    box(slide, ctx, 146, y, 988, 62, C.white, "#DCE6F2");
    text(slide, ctx, s[0], 172, y + 18, 120, 22, { size: 16, bold: true, color: i < 3 ? C.blue : C.green });
    text(slide, ctx, s[1], 306, y + 13, 760, 34, { size: 13, color: C.ink, face: s[1].includes("./scripts") ? "Aptos Mono" : "Microsoft YaHei", fit: "shrinkText" });
  });
  box(slide, ctx, 146, 620, 988, 44, "#DBEAFE", "#BFDBFE");
  text(slide, ctx, "一句话目标：让每个测试结论都能落到“哪个用户、哪个入口、哪条调用链、哪份证据”。", 172, 633, 900, 20, { size: 15, bold: true, color: "#1D4ED8" });
  footer(slide, ctx, 12);
  return slide;
}

export async function makeSlide(presentation, ctx, index) {
  const slides = [slide01, slide02, slide03, slide04, slide05, slide06, slide07, slide08, slide09, slide10, slide11, slide12];
  return slides[index - 1](presentation, ctx);
}
