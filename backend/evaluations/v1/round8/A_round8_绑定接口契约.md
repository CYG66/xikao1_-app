# Round8 A-line 语义验收绑定接口契约

- 基线提交：`7567f7bb32d9571048f1d66deb8124df3bcf9d02`
- 既有 P0 补丁提交（保持原样，不 amend / 不 rebase）：`e7831921ef904deaa893573da8cc793056a9cf41`
- 本契约配套机器可读草案：`A_round8_binding_contract.schema.json`
- 适用入口：`verify_semantic_requirements(source, geometries, logical_objects=None, topology=None)`
- 纪律：本轮零真实模型请求、零网络；不新增五角星专用验收器、不新增图形专用识别器；分类只允许通用轮廓度量。

## 1. 范围与身份边界

本契约只固化"语义模块 ↔ 生产调用方"之间的目标绑定接口与载荷护栏，不扩展几何算法、不做 M3 快照、不改动 FEATURE-CONTRACT 公共接口。

身份依据优先级（后端侧解析，语义层不反推身份）：

1. **主要依据**：后端构造结果 `logical_objects[*].geometry_refs` 在本次 `geometries` 中解析到的真实几何集合；
2. **有限辅助证据**：由活动线网重建的后端连通分量（共享顶点或容差内接触），仅在载荷缺失时使用；
3. 包围盒仅用于重叠诊断与排序，**从来不是身份判据**；
4. 模型自报的 `object_id` / `label` / `assembly_id` 只作记录与展示，**不得被提升为身份**。

## 2. 入参形状

### 2.1 `geometries`（必传）

本次验收的后端几何列表。活动几何过滤口径与既有验收器一致：`selected != false` 且 `role` 不属于 `annotation / reference / ignored`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | 正整数 | 几何唯一标识，`geometry_refs` 必须命中该值 |
| `type` | string | `line / polyline / circle / arc / ellipse` |
| `role` | string | 可选；`annotation/reference/ignored` 视为非活动 |
| `selected` | bool | 可选；`false` 视为非活动 |

### 2.2 `logical_objects`（可选列表）

后端已生成、已经来源/执行结果/几何引用验证的逻辑对象数组。缺省 `null` 或空列表时回退连通分量辅助证据。

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `object_id` | string | 建议 | 声明性标识；同一载荷内非空且不得重复；不作身份依据 |
| `assembly_id` | string | 可缺省 | 整体归属标识 |
| `assembly_label` | string | 可缺省 | 整体归属名称 |
| `object_type` | string | 可缺省 | 对象类型声明 |
| `label` | string | 可缺省 | 声明性标签，不作身份依据 |
| `geometry_refs` | 正整数数组 | **必需** | 命中本次活动几何 id；非空、对象内不重复；一个对象可含多段不连通几何 |
| `bounds` | object | 可缺省 | `min_x/min_y/max_x/max_y`，仅诊断用 |
| `confirmed` | bool | 可缺省 | 后端确认标记 |
| `confidence` | number 0–1 | 可缺省 | 后端置信度，缺省按 1.0 记录 |

兼容旧字段：`geometry_ids` 作为 `geometry_refs` 的别名被读取；新接线应统一使用 `geometry_refs`。

### 2.3 `topology`（可选对象）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 可缺省 |
| `shared_geometries` | array | `{geometry_id, object_ids:[...]}`；多对象共用几何必须在此声明，且归属与引用一致 |
| `relations` | array | `{source_object_id, target_object_id, relation}`；语义层仅信息性消费，不据此定身份 |

## 3. 校验规则（模块侧强制）

1. **来源可信**：仅接受后端构造结果携带的 `geometry_refs`；模型在几何图元上自报的标签/对象 id 不参与身份判定。
2. **成员完整**：每个对象的 `geometry_refs` 必须是非空列表，元素可解析为正整数；不得为空、不得缺字段。
3. **归属一致**：每个引用必须在本次活动几何中一一命中；引用集合与真实几何引用一致。
4. **重复 / 缺失 / 过期绑定**：
   - 对象内重复引用 → 拒绝；
   - 引用不存在（悬空）id → 拒绝，不得模糊匹配到近似 id；
   - 活动几何未被任何对象引用 → 登记 `unowned_geometry_ids`，不静默并入相邻对象；
   - 多对象共用几何而拓扑未声明共享，或声明归属与引用不一致 → 拒绝。
5. **object_id 边界**：`object_id` 缺失、空白或重复按载荷缺陷处理；解析出的身份始终是后端几何集合，声明 id 仅记录在 `target_ref.object_id`。**模型自报的 `object_id` / `label` / `assembly_id` 只作声明性记录，语义层不将其提升为身份依据**（`target_ref.model_declared_object_id_trusted_as_identity=False`）。
6. **角色排除对账**：被 `annotation / reference / ignored` 角色或 `selected=False` 排除的几何，必须进入诊断字段 `excluded_geometry_ids` 与 `excluded_geometries`（含角色与选中状态），以区分"目标被角色排除"与"目标从未生成"。引用到被排除几何判 `excluded_geometry_ref`；若诊断字段缺失该清单，此种情形只能判 `unresolved`。
7. **不拆分 / 不合并**：
   - 一个逻辑对象含多段不连通几何 → 保持为**一个**验收对象，记 `disconnected_members` 诊断警告（含分量数），不按连通性拆分；
   - 两个逻辑对象几何接触、重叠、共享结点或边 → 保持为**两个**独立对象，接触/重叠关系仅记 `contact_or_overlap_between_distinct_objects` 诊断警告，连通分量不得覆盖可信 `geometry_refs`。

### 3.1 机器可读错误码

| 错误码 | 触发条件 |
|---|---|
| `invalid_logical_objects_payload` | `logical_objects` 不是列表 |
| `invalid_logical_object_entry` | 数组条目不是字典 |
| `invalid_object_id` | `object_id` 缺失或空白 |
| `duplicate_object_id` | `object_id` 在载荷内重复 |
| `missing_geometry_refs` | 引用列表缺失、非列表或为空 |
| `invalid_geometry_refs` | 引用含非正整数 |
| `duplicate_geometry_refs` | 同一对象内引用重复 |
| `dangling_geometry_refs` | 引用不存在的几何 id（本次几何列表中从未出现） |
| `excluded_geometry_ref` | 引用的几何存在于本次列表，但被角色/选中状态排除在活动几何之外 |
| `undeclared_shared_geometry` | 多对象共用几何但拓扑未声明共享 |
| `shared_ownership_mismatch` | 共享拓扑声明归属与对象引用不一致 |

### 3.2 诊断警告（非致命，不改变身份）

| 警告码 | 含义 |
|---|---|
| `binding_fallback_components` | 载荷缺失，身份回退连通分量辅助证据 |
| `contact_or_overlap_between_distinct_objects` | 不同绑定对象接触/重叠/共享结点；保持独立，未合并；附 `relation`（`intersects/touching/bounds_overlap`） |
| `disconnected_members` | 同一逻辑对象含多段不连通几何；保持一个对象，附 `component_count` |

## 4. 降级规则与终态口径

- **载荷缺失**（`null` / `[]`）：回退后端连通分量分组；`binding_source=connected_components`、`binding_auxiliary=true`，并带 `binding_fallback_components` 警告；该身份仅为有限辅助证据，结果不得整体 PASS。
- **载荷畸形 / 引用对不上 / 归属不唯一**：`status=unresolved`、`coverage=target_unresolved`、`review_required=True`，携带错误码与明细；不得整体 PASS。
- 既有终态词汇（主控已正式接受，不得改词）：
  - `unverified + coverage=unsupported_semantic_kind`：识别到需求但无法可靠完成语义验收；
  - `not_checked`：该对象未执行相应检查；
  - `partial + review_required=True`：部分对象完成检查，整体需求尚未全部验证；
  - 任何包含未完成强制语义验收的组合对象，不能因其他对象通过而整体 PASS；五角星本轮无完整验收器，登记为能力缺口，不计 PASS。

## 5. 给生产调用方（Agent C）的接线要点

1. 传入**后端已生成并通过图元/归属验证**的 `logical_objects`（含 `geometry_refs`）与 `topology`；不得只传整图几何列表。
2. 正常执行路径与诊断回放路径使用同一绑定入口；回放夹具必须明确标记"重建夹具"，不得冒充历史回放。
3. 模块返回中的 `binding_source` / `binding_auxiliary` / `unowned_geometry_ids` / `binding_warnings` / `binding_validation.errors` 必须进入验收证据账本。
4. 绑定不确定时，调用方不得把 `unresolved` / `review_required=True` 的结果改写为 PASS。
5. 不修改 H2/H3/H4、`max_repairs`、候选保存的原有授权条件；房屋与字母 A 通道既有 `review_required=False` 设计本轮不动，留待 D 测、C 报。

## 6. 校验矩阵（模块级，零模型）

| 输入 | 绑定判定 | 终态 / review_required | 不整体 PASS |
|---|---|---|---|
| 单对象 `geometry_refs` 命中 | `bound`，来源 `logical_objects.geometry_refs` | 爱心通道 `partial / True` | 是 |
| 多对象 `geometry_refs` 分别命中 | `bound`，两组独立 | `partial / True`，无验收器对象 `not_checked` | 是 |
| 引用不存在 id | `unresolved`，`dangling_geometry_refs` | `unresolved / True` | 是 |
| 引用被角色排除的几何 | `unresolved`，`excluded_geometry_ref`，附排除角色 | `unresolved / True` | 是 |
| 对象内重复引用 | `unresolved`，`duplicate_geometry_refs` | `unresolved / True` | 是 |
| 空引用列表 | `unresolved`，`missing_geometry_refs` | `unresolved / True` | 是 |
| 引用非正整数 | `unresolved`，`invalid_geometry_refs` | `unresolved / True` | 是 |
| `logical_objects` 非列表 | `unresolved`，`invalid_logical_objects_payload` | `unresolved / True` | 是 |
| 重复 `object_id` | `unresolved`，`duplicate_object_id` | `unresolved / True` | 是 |
| 多对象共用几何未声明 | `unresolved`，`undeclared_shared_geometry` | `unresolved / True` | 是 |
| 共享声明归属不一致 | `unresolved`，`shared_ownership_mismatch` | `unresolved / True` | 是 |
| 一对象多段不连通几何 | `bound`，单目标含全部段，`disconnected_members` 警告 | 按一个对象验收 | 是 |
| 两对象接触/共享顶点 | `bound`，两组独立，接触警告 | 不合并 | 是 |
| 两对象重叠 | `bound`，两组独立，重叠警告 | 不合并 | 是 |
| `logical_objects` 缺失 | 回退连通分量，`auxiliary=true` | `partial/unresolved / True` | 是 |
| 活动几何未被引用 | `bound`，登记 `unowned_geometry_ids` | 未归属对象 `unresolved` | 是 |
