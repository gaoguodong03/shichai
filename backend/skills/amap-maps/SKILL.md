---
description: 高德地图位置服务。当用户需要地理编码、逆地理编码、天气查询、路线规划、距离计算、周边/关键词搜索 POI 时，使用 amap-maps 相关工具。
enabled: true
name: 高德地图
---
# 高德地图 Skill（只使用 amap-maps MCP）

当用户提出与**地理位置、路线、天气、周边搜索**相关的问题时，请按以下原则工作：

1. **只使用 amap-maps MCP 处理地图相关任务**
   - 通过 MCP Manager 已接入：`amap-maps` Server。
   - 工具在系统内的名称前缀为：`amap-maps_*`。
   - 遇到地址转换、经纬度查询、路线规划（驾车/步行/骑行/公交）、距离计算、天气、周边/关键词 POI 搜索时，**必须调用 `amap-maps_*` 工具**。
   - **不要为了这些任务调用 linkup、exa、data-report 等其它 MCP/技能。** 这些仅用于通用网页搜索和数据报告，不负责具体导航与地图能力。

2. **工具调用规范（参数必须正确填写）**

   **经纬度格式**：高德使用 GCJ-02 坐标系，格式为 `经度,纬度`（如 `116.397428,39.90923`）。地址需先用 `maps_geo` 转为坐标后再参与路线/距离计算。

   | 工具名 | 必填参数 | 可选参数 | 说明 |
   |--------|----------|----------|------|
   | `amap-maps_maps_geo` | `address` | `city` | 地理编码：地址→坐标。**必须传 city**（城市名如「北京」），否则全国检索会误匹配到其他省份 |
   | `amap-maps_maps_regeocode` | `location` | - | 逆地理编码：坐标→省市区地址 |
   | `amap-maps_maps_ip_location` | `ip` | - | IP 定位 |
   | `amap-maps_maps_weather` | `city` | - | 天气：城市名或 adcode |
   | `amap-maps_maps_direction_walking` | `origin`, `destination` | - | 步行路线（100km 内） |
   | `amap-maps_maps_direction_driving` | `origin`, `destination` | - | 驾车路线 |
   | `amap-maps_maps_bicycling` | `origin`, `destination` | - | 骑行路线（500km 内） |
   | `amap-maps_maps_direction_transit` | `origin`, `destination`, `city`, `cityd` | - | 公交路线：跨城需传起点/终点城市 |
   | `amap-maps_maps_distance` | `origin`, `destination` | `type` | 距离测量 |
   | `amap-maps_maps_text_search` | `keywords` | `city` | 关键词搜索 POI |
   | `amap-maps_maps_around_search` | `keywords`, `location` | `radius` | 周边搜索：中心点坐标 + 半径 |
   | `amap-maps_maps_search_detail` | `id` | - | POI 详情：id 来自关键词搜/周边搜 |

   **注意**：`origin`、`destination`、`location` 均为经纬度字符串（`经度,纬度`）。若用户只给地址，先用 `maps_geo` 转坐标。

   **调用示例**（地址→坐标→路线）：
   ```json
   // 1. 地理编码取坐标（city 必填，否则会误匹配到贵州、广州等错误城市）
   { "address": "北京天安门", "city": "北京" }
   { "address": "北京邮电大学", "city": "北京" }
   { "address": "北邮海淀", "city": "北京" }
   // 2. 步行路线
   { "origin": "116.397428,39.90923", "destination": "116.403119,39.924091" }
   ```

3. **路线规划标准流程**（必须严格按此调用，否则会返回错误城市）

   用户问「从 A 到 B 怎么走」时，**必须**依次执行：
   - **第 1 次**：工具 `amap-maps_maps_geo`，参数 `{"address": "起点地址", "city": "城市名"}` → 取返回的 location 作为 origin
   - **第 2 次**：工具 `amap-maps_maps_geo`，参数 `{"address": "终点地址", "city": "城市名"}` → 取返回的 location 作为 destination
   - **第 3 次**：工具 `amap-maps_maps_direction_driving` 或 `amap-maps_maps_direction_walking`，参数 `{"origin": "经度,纬度", "destination": "经度,纬度"}`

   **「从北邮海淀到天安门怎么走」标准参数**（直接照抄，不要改动）：
   ```
   第1次：amap-maps_maps_geo  →  {"address": "北京邮电大学", "city": "北京"}
   第2次：amap-maps_maps_geo  →  {"address": "天安门", "city": "北京"}
   第3次：amap-maps_maps_direction_driving  →  {"origin": "<第1次返回的location>", "destination": "<第2次返回的location>"}
   ```

4. **典型工作流示例**

   - **「北京天安门到故宫怎么走？」**、**「从海淀北邮到天安门怎么去？」** → 按上述**标准流程**执行，必须查完两点再查路线。
   - **地址解析**：用户说「北邮海淀」→ address="北京邮电大学"，city="北京"；「天安门」→ address="天安门"，city="北京"。**city 必须为城市名（北京、上海等），不能为区名（海淀、朝阳等）**。不传 city 会全国检索，返回贵州、广州等错误结果。
   - **「上海明天天气」** → 工具 `amap-maps_maps_weather`，参数 `{"city": "上海"}`
   - **「附近有什么好吃的」** → 需用户位置或地址，用 `maps_geo` 转坐标后 `maps_around_search`，或直接用 `maps_text_search` 配合 `city`
   - **「这两个地方相距多远」** → 工具 `amap-maps_maps_distance`，参数 `{"origin": "经度,纬度", "destination": "经度,纬度"}`
   - **「帮我查一下杭州西湖的详细地址」** → 工具 `amap-maps_maps_geo`，参数 `{"address": "西湖", "city": "杭州"}`

5. **回答风格**
   - 先用自然语言确认用户需求（地址、城市、关键词等）。
   - 调用工具后，用简洁易懂的方式呈现结果（路线、距离、天气、POI 列表等）。
   - 若参数缺失（如出发地、目的地、城市名），先向用户确认再调用。

6. **不要做的事情**
   - 不要自造参数名（如 `from`/`to` 代替 `origin`/`destination`，`query` 代替 `keywords`）。
   - 不要在没有调用工具的情况下编造坐标、路线或天气数据。
   - 不要混淆经纬度顺序（高德使用 GCJ-02，格式为 `经度,纬度`）。
   - 不要在用户明确给出地址/地点时，仍用模糊描述代替实际查询。
   - **路线规划时**：不要只查完起点就停，必须查完起点和终点两个坐标后再查路线。
   - **maps_geo 时**：不要漏传 `city`，不要用区名（海淀、朝阳）当 city，必须用城市名（北京、上海）。否则会全国检索，返回兴义、越秀等错误城市。

> 简单记忆：**有位置、路线、天气、周边，就找 amap-maps**，先查工具，再组织回答。
