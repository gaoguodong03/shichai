---
description: 使用规划 + 子代理的结构化 Web 调研工作流，生成带引用的研究报告。（目前无法使用）
enabled: false
name: web-research
---
# Web Research Skill

使用「研究规划 → 多子代理并行调研 → 系统化综合」三阶段流程，借助 `task` 工具创建研究子代理，并通过本地文件在代理之间传递信息，完成复杂 Web 调研与高质量研究报告撰写。

---

## 一、何时使用本 Skill

- 需要对一个**复杂主题**做系统性调研，而不是简单查一个事实。
- 需要**整合多个信息源**（搜索结果、网页内容等）的信息。
- 需要对多个对象做**对比分析**（如多款产品、多种方案、多家公司）。
- 需要输出**结构化、可引用**的研究结论或报告（含来源链接）。

---

## 二、核心理念与可用工具

本 Skill 依赖以下工具来实现「规划 → 调研 → 综合」的完整链路：

- **`write_file`**：将研究计划、子代理调研结果、最终报告写入本地文件。
- **`read_file`**：读取本地研究文件（计划、子代理结果等）。**不要**用来读取 URL。
- **`list_files`**：列出研究目录下已有的计划/结果/报告文件。
- **`fetch_url`**：从网络 URL 抓取网页内容并转换为 Markdown（用于深度阅读单个页面）。
- **`web_search`**：进行 Web 搜索获取多个候选信息源。
- **`task`**：为每个子主题创建独立的「研究子代理」，并行开展调研。子代理可使用 `web_search`、`write_file` 等工具。

> **重要约定：**
> - 所有研究相关文件统一放在 `research_[topic_name]` 目录下（相对当前工作目录）。
> - 与用户的最终交互由「主代理」完成；子代理**仅通过文件写入**与主代理通信，不直接回复用户。

---

## 三、步骤一：创建并保存研究计划（Research Plan）

在调用任何子代理之前，**必须先完成研究规划并落盘到本地文件**。

### 1. 创建研究目录

- 约定研究目录命名：`research_[topic_name]`
  - `topic_name`：将研究主题转为简短、可用作文件名的字符串（如 `llm-eval-frameworks`）。
- 实现方式：
  - 若环境支持 Shell，可执行类似 `mkdir research_[topic_name]`；
  - 若不支持，首次用 `write_file` 写入 `research_[topic_name]/research_plan.md` 时，确保自动创建上级目录。

### 2. 分解研究问题为子主题

对用户给出的研究问题进行分析，拆分为**2–5 个互不重叠的子主题**（Subtopics）：

- **简单事实查询**：通常 1–2 个子主题足够。
- **对比分析类问题**：以「被对比的对象」为粒度拆分，每个对象 1 个子主题，**总数不超过 3 个**。
- **复杂调研/综述类问题**：建议 3–5 个子主题，覆盖不同维度（背景、现状、方案、风险等）。

确保：

- 子主题之间**尽量不重叠**，避免不同子代理重复工作。
- 每个子主题都有**清晰、可回答的研究问题**。

### 3. 编写并保存 `research_plan.md`

使用 `write_file` 创建并写入：

- 文件路径：`research_[topic_name]/research_plan.md`
- 建议结构（Markdown）：

1. **Main Research Question（主研究问题）**
   - 用 1–3 句话明确用户希望解决的核心问题。
2. **Subtopics（子主题列表）**
   - 2–5 个小节，每个包含：
     - 子主题名称（唯一、简洁，可用于文件名片段）
     - 该子主题下的**具体研究问题**（自然语言）
     - 期望从该子主题获得的**关键信息类型**（如：定义、现状、优缺点、案例、指标、时间线等）
3. **Information Expectations（信息期望）**
   - 总结各子主题的预期输出，确保不同子主题的关注点不重叠。
4. **Synthesis Plan（综合与报告规划）**
   - 说明最终将如何结合各子主题的发现：
     - 报告的大致结构（章节标题）
     - 如何在报告中对比/串联不同子主题
     - 如何在报告中使用引用与链接

> **要求：** 每次使用本 Skill 调研新主题，都必须先写入/更新 `research_plan.md`，再进行子代理委派。

---

## 四、步骤二：为每个子主题创建研究子代理（Subagents）

在研究计划中确认好子主题后，对**每个子主题**使用 `task` 工具创建一个独立的研究子代理。

### 1. 子代理配置原则

对每个子主题：

- 使用 `task` 创建子代理，并在 prompt 中给出：
  - **清晰且不含歧义的研究问题**（尽量不要使用没有解释的缩写）。
  - 明确的输出要求：写入 `research_[topic_name]/findings_[subtopic].md`。
  - 最大搜索预算：**限制为 3–5 次 `web_search` 调用**。
  - 需要时可指示子代理对关键 URL 使用 `fetch_url` 进行深入阅读。
- 最多同时并行运行 **3 个子代理**，以平衡效率和资源使用。

### 2. 子代理通用指令模板

在通过 `task` 创建子代理时，可使用如下指令模板（根据具体子主题替换占位符）：

> **英文模板（推荐对子代理使用英文）**
>
> - **Task description**  
>   `Research [SPECIFIC_SUBTOPIC_QUESTION] as part of a broader research on [MAIN_TOPIC].`
>
> - **Tools**  
>   `Use the web_search tool as your primary way to discover information sources. Optionally use fetch_url when you need to deeply read a specific web page.`
>
> - **Output file**  
>   `After completing your research, use write_file to save your findings to: research_[topic_name]/findings_[subtopic].md`
>
> - **Output content requirements**  
>   - Key facts和结论（分点列出，注意与子主题问题强相关）  
>   - 关键引用（可包含原文短句或数据，使用 Markdown 引用格式）  
>   - 来源列表：每条信息尽量标注对应的 URL  
>   - 信息可信度或不确定性说明（如信息冲突、样本过少等）  
>
> - **Search budget**  
>   `Use at most 3–5 web_search calls. Prefer high-quality, recent, and authoritative sources.`

确保在 `task` 的参数中**显式指出输出文件路径**，并要求子代理使用 `write_file` 将结果保存到该路径，而不是直接通过返回值给主代理。

---

## 五、步骤三：汇总子代理结果并进行综合（Synthesis）

当所有子代理任务完成后，由主代理负责：

### 1. 收集本地结果文件

1. 使用 `list_files` 列出 `research_[topic_name]` 目录：
   - 确认是否存在：
     - `research_plan.md`
     - 若干 `findings_[subtopic].md`
     - 可能已经存在的 `research_report.md`（如果是增量更新场景）
2. 使用 `read_file` 读取所有 `findings_[subtopic].md` 文件的内容。

> **注意：**  
> - `read_file` **只用于本地文件**；若需要从网上获取页面内容，请使用 `fetch_url`。  
> - 如果发现某个子主题缺少 `findings_*.md` 文件，需视为该子代理任务失败或未完成，主代理可选择：  
>   - 重新为该子主题创建一个新的子代理；  
>   - 或在最终报告中明确说明该部分缺失。

### 2. 进行全局综合与分析

在充分阅读各个 `findings_[subtopic].md` 后，主代理应：

- 先给出对**主研究问题的直接回答**或结论性总结。
- 再结构化地整合各子主题的发现：
  - 明确每个结论来自哪个子主题、哪些来源。
  - 指出不同子主题之间的联系、对比与互相支持/矛盾的部分。
- 对重要观点、数据或结论**给出具体来源 URL 引用**：
  - 使用 Markdown 链接或引用形式，例如 `[来源 1](https://example.com/...)`。
  - 若子代理的 findings 中已列出来源，优先直接引用这些 URL。
- 指出当前研究的**局限性与信息空白**：
  - 如时间范围限制、样本不足、数据来源可信度有限等。

### 3. 可选：写入最终研究报告文件

如果用户希望在本地保留报告，主代理可以使用 `write_file` 创建：

- 路径：`research_[topic_name]/research_report.md`
- 建议结构：
  1. 标题：`# [主题] 研究报告`
  2. 简要摘要（1–3 段）
  3. 各子主题小节（可与 `Subtopics` 对应）
  4. 综合分析与结论
  5. 局限性与未来可能的补充研究方向
  6. 参考资料/来源列表（按 URL 或来源名称列出）

---

## 六、子代理可用工具说明（给子代理看的简要版本）

在为子代理撰写指令时，可简要说明其可用工具及用途：

- **`web_search`**：  
  - 用于根据查询词在互联网上搜索信息。  
  - 建议每个子主题搜索次数不超过 3–5 次。  
  - 优先选择权威、近期、与问题高度相关的结果。

- **`fetch_url`**：  
  - 当 `web_search` 得到的某个 URL 特别重要时，用 `fetch_url` 抓取并转为 Markdown，以便深入阅读和引用。

- **`write_file`**：  
  - 将研究结果以 Markdown 形式保存到 `research_[topic_name]/findings_[subtopic].md`。  
  - 文件内容必须包含：关键结论、引用、URL 列表和不确定性说明。

> 子代理**不需要**使用 `read_file` 或 `list_files`，这些通常由主代理在综合阶段使用。

---

## 七、最佳实践与注意事项

1. **先规划再调研**  
   - 始终先写 `research_plan.md`，再启动子代理。  
   - 不要跳过规划直接开始搜索，这会导致重复和遗漏。

2. **子主题要清晰、不重叠**  
   - 拆分时保证每个子主题有独立的问题和输出目标。  
   - 避免两个子代理研究范围几乎相同。

3. **文件是唯一的跨代理通信载体**  
   - 子代理**必须**将结果写入文件，而不是直接返回大段内容给主代理。  
   - 主代理通过 `read_file` 统一读取并综合。

4. **适度搜索，避免过度调研**  
   - 默认每个子主题 3–5 次 `web_search` 即可。  
   - 若在有限搜索内已得到足够一致且高质量的信息，不必继续增加搜索次数。

5. **严格区分本地文件与网络内容**  
   - 本地：使用 `read_file` / `write_file` / `list_files`。  
   - 网络：使用 `web_search` / `fetch_url`。  
   - 不要尝试用 `read_file` 直接读取 URL。

6. **清晰引用与可追溯性**  
   - 在 findings 和最终报告中尽量附上来源 URL。  
   - 对于关键信息，可以附上简短的引用原文或数据片段。

7. **适时停止**  
   - 当进一步搜索只能带来微小增益或重复信息时，应停止调研，转入综合阶段。  
   - 在报告中可以明确指出「在给定搜索预算内未发现更多高价值新信息」。

使用本 Skill 时，请始终遵循上述三阶段流程（规划 → 子代理调研 → 综合），确保每个阶段都有清晰的产物（plan 文件、findings 文件、最终答案/报告），从而让 Web 调研过程**可追溯、可复用、可维护**。

