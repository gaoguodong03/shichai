---
name: amap-maps
description: 高德地图位置服务。当用户需要地理编码、逆地理编码、天气查询、路线规划、距离计算、周边/关键词搜索 POI 时，使用 amap-maps 相关工具。
---

# 高德地图 Skill（基于 amap-maps MCP）

当用户提出与**地理位置、路线、天气、周边搜索**相关的问题时，请按以下原则工作：

1. **优先使用 amap-maps 工具**
   - 通过 MCP Manager 已接入：`amap-maps` Server
   - 工具在系统内的名称前缀为：`amap-maps_*`
   - 遇到地址转换、路线规划、天气、距离、POI 搜索等需求时，**必须**调用相应工具，而不是凭空猜测。

2. **工具调用规范（参数必须正确填写）**

   **经纬度格式**：高德使用 GCJ-02 坐标系，格式为 `经度,纬度`（如 `116.397428,39.90923`）。地址需先用 `maps_geo` 转为坐标后再参与路线/距离计算。

   | 工具名 | 必填参数 | 可选参数 | 说明 |
   |--------|----------|----------|------|
   | `amap-maps_maps_geo` | `address` | `city` | 地理编码：地址→坐标 |
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
   // 1. 地理编码取坐标
   { "address": "北京天安门", "city": "北京" }
   // 2. 步行路线
   { "origin": "116.397428,39.90923", "destination": "116.403119,39.924091" }
   ```

3. **典型工作流示例**

   - **「北京天安门到故宫怎么走？」**、**「从海淀北邮到天安门怎么去？」** → **必须**先用 `maps_geo` 分别查完**起点和终点**的坐标（一次可查多个，或分两次查），拿到两处经纬度后，再用 `maps_direction_walking` / `maps_direction_driving` / `maps_direction_transit` 查路线。**不要只查了一个点就停**，必须查完两点再查路线。
   - **「上海明天天气」** → `maps_weather` 传城市名
   - **「附近有什么好吃的」** → 需用户位置或地址，用 `maps_geo` 转坐标后 `maps_around_search`，或直接用 `maps_text_search` 配合地点
   - **「这两个地方相距多远」** → `maps_distance`
   - **「帮我查一下杭州西湖的详细地址」** → `maps_text_search` 或 `maps_geo`

4. **回答风格**
   - 先用自然语言确认用户需求（地址、城市、关键词等）。
   - 调用工具后，用简洁易懂的方式呈现结果（路线、距离、天气、POI 列表等）。
   - 若参数缺失（如出发地、目的地、城市名），先向用户确认再调用。

5. **不要做的事情**
   - 不要自造参数名（如 `from`/`to` 代替 `origin`/`destination`，`query` 代替 `keywords`）。
   - 不要在没有调用工具的情况下编造坐标、路线或天气数据。
   - 不要混淆经纬度顺序（高德使用 GCJ-02，格式为 `经度,纬度`）。
   - 不要在用户明确给出地址/地点时，仍用模糊描述代替实际查询。
   - **路线规划时**：不要只查完起点就停，必须查完起点和终点两个坐标后再查路线。

> 简单记忆：**有位置、路线、天气、周边，就找 amap-maps**，先查工具，再组织回答。
