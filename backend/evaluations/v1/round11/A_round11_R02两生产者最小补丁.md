# Round11 R-02：Projection / Repetition 两生产者最小生产补丁

- 性质：授权范围内的最小生产补丁；零真实模型请求、零网络；S1 冻结；未重跑 A9；未合并、未推送、未 amend。
- 基线：`2fb2c6804efed81cdcd37315b6ef33f613e496b5`；独立分支 `r02-fix`，独立工作树 `worktrees\tmp\r02-fix`；归档树 `tmp/r04-fix` 未改动。
- 授权边界：仅两个生产者文件 + 本代理新增/修改的测试与探针；未改解释器、Stroke/Path、候选门禁、语义两模块、公共接口、计划契约。

## 1. 缺陷与修复规则

已证实缺陷（C/D/B 三方实证）：Projection / Repetition 在"来源明确要求 + 多对象"时短路返回 `not_checked`，被解释器存储门按 `status != 'not_checked'` 丢弃；被丢弃要求既不进通道报告也不进 `unknown_requirements`；`not_checked` 不在共享阻断集 `{failed, unverified, review_required, partial}` 内，即使保留也不阻断。当前端到端未出 `accepted=true` 是被独立源覆盖完整性门先行掩盖，不能据此判安全。

三条行为规则（与授权一致）：

- **A 无适用要求**：来源未命中本通道既有要求谓词 → 保持 `not_checked` 原行为，不制造额外阻断；对象数 >1 本身不产生要求。
- **B 有要求、多对象未 scope**：来源已命中本通道既有要求谓词，但创建对象数 >1 导致检查范围无法唯一确定 → `status=unverified`、`review_required=True`、`coverage=unscoped_multiple_objects`，并在 `unknown_requirements` 保留条款明细（要求标识、理由、来源证据片段、对象数）；不构造新来源要求，不凭几何反推要求。
- **C 要求可正常验证**：单对象测量、通过、检查失败抛 `StructureContractError` 机制全部保持原行为；不放宽阈值、不删断言。

## 2. 改动文件与逐 hunk 说明

### 2.1 `app/cad_projection_acceptance.py`（`verify_projection_requirements`）

- **hunk 1（规则 A/B 重排判定顺序）**：原实现把多对象守卫排在关键词判定之前，多对象与无要求共用同一个 `not_checked` 返回。改为先计算三个既有谓词（盒体 `立方体|正方体`、投影 `等轴|等距投影`、棱清单 `(?:12|十二)\s*条.*?(?:棱|边)`）与 `local_creation_objects(source)` 对象列表：
  - 三谓词未全命中 → A：`{'status':'not_checked','checks':[]}`，与原无要求返回一致；
  - 三谓词全命中且对象数 >1 → B：`unverified` + `review_required=True` + `coverage=unscoped_multiple_objects`，`unknown_requirements` 条目含 `source_requirement_id=projection_isometric_edges`、`reason=unscoped_multiple_objects`、`evidence`（三个命中片段）、`object_count`；
  - 三谓词全命中且对象数 =1 → 进入原单对象测量段（规则 C，未改）。
- **未改动**：12 条直线校验、退化棱线、三组平行棱线、棱长一致、等轴方向、棱长尺寸、端点连接复原等测量段与全部抛错分支。

### 2.2 `app/cad_repetition_acceptance.py`（`verify_repetition_requirements`）

- **hunk 1（规则 B 前置要求识别）**：在守卫前复用既有解析器/正则识别五类条款：齿形 `tooth_boundary_requirements`、平行条带 `parallel_strip_requirements`、台阶正则、六边形阵列正则（列/行 + 边长 + 六边形 + 无缝/共边）、分支条款正则（`N 条对称分支` + `每条分支带 N 个侧枝`）。识别结果落成 `recognized` 列表，每项含 kind 与来源证据片段。
- **hunk 2（规则 B 未 scope 阻断返回）**：`recognized` 非空且对象数 >1 → `unverified` + `review_required=True` + `coverage=unscoped_multiple_objects`，按 kind 逐条写 `unknown_requirements`（`repetition_tooth_boundary` / `repetition_parallel_strip` / `repetition_stair_step` / `repetition_hexagonal_tiling` / `repetition_branch_network`），条目含证据与对象数。
- **hunk 3（规则 A 保留原丢弃路径）**：`recognized` 为空 → 落入原测量流程；无 checks 时维持原兜底 `{'status':'partial' if checks else 'not_checked','coverage':'explicit_repetition_relations_only','checks':checks}`。
- **hunk 4（消除重复解析）**：测量段内原先重复调用的齿形/条带/台阶/阵列正则改为复用前置变量；分支测量仍走既有 `branch_structure_requirements` 辅助函数（其曲线拒绝、数量上下限、多对象返回 None 等过滤行为未改）。
- **未改动**：齿形边界/外径/齿顶数量/齿顶角宽/齿根半径/旋转重复、条带数量/长宽/对齐/间距、台阶交替数量与局部尺寸、阵列单元数量/六边形/边长/重叠/连通、分支主侧枝数量/长度/位置/夹角/镜面对称/旋转对应等全部测量与抛错分支。

### 2.3 测试与探针（本代理新增/修改，非生产代码）

- `tests/test_cad_projection_acceptance.py`：原"多对象 + 关键词仍 `not_checked`"断言编码了被修复的丢弃行为，改为专项断言 B（`unverified`/`review_required=True`/coverage/明细非空/对象数 2）；新增 A 对照（无要求 + 多对象仍 `not_checked`）。
- `tests/test_cad_repetition_acceptance.py`：新增 B 专项（齿形条款 + 多对象 → `unverified` + 明细非空）与 A 对照（无要求 + 多对象仍 `not_checked`、无 unknown 条目）。
- `evaluations/v1/round11/A_round11_R02_multobject_probe.py` 与同名 JSON：零模型端到端探针，覆盖 B/A/C 单对象成功与坏几何抛错。

## 3. 实测结果（探针直连生产者 + 解释器入口）

| 场景 | 规则 | 生产者 status | review_required | coverage | 明细 | 解释器保留 | 候选接受 |
|---|---|---|---|---|---|---|---|
| 投影：圆形+立方体，等轴 12 棱 | B | `unverified` | True | `unscoped_multiple_objects` | 1 条，证据 `立方体/等轴/12条棱`，对象数 2 | 保留 `projection_acceptance` | false |
| 重复：圆形+齿轮轮廓，8 齿 | B | `unverified` | True | `unscoped_multiple_objects` | 1 条，证据 `8个齿/外径2米`，对象数 2 | 保留 `repetition_acceptance` | false |
| 投影：圆形+矩形，无条款 | A | `not_checked` | 无 | 无 | 无 | 门丢弃 | （覆盖门 review_required，非本通道阻断） |
| 重复：圆形+矩形，无条款 | A | `not_checked` | 无 | `explicit_repetition_relations_only` | 无 | 门丢弃 | （同上） |
| 投影：单对象等轴棱线 | C | `passed` | 无 | `isometric_edge_incidence_and_projected_lengths` | — | — | — |
| 重复：单对象齿形轮廓 | C | `partial` | 无 | `explicit_repetition_relations_only` | checks 非空 | — | — |
| 投影：单对象坏几何 | C | 抛 `StructureContractError`（12 条直线） | — | — | — | 链路 invalid | false |
| 重复：单对象坏几何 | C | 抛 `StructureContractError`（主枝及侧枝总数量） | — | — | — | 链路 invalid | false |

## 4. 与 R-04 已验收契约的兼容

- **复用**：共享阻断状态集（`unverified` 属既有成员）、通用 `_report_blocks_review` 谓词、"可阻断报告必须被门保留"的模式、来源优先/几何不反推原则。
- **不复用**：未引入 R-04 星形词表、歧义消歧、`applicability_decision` 四值、`semantic_requirement_state` 或语义 kind 注册表；四通道无来源文本扫描层，通道报告由通用汇总循环按状态集判定，不回写语义三态。
- **三态词表未改**：`no_applicable_requirement` / `fully_verified` / `unverified_or_partial` 保持原样。

## 5. 测试计数与失败身份

- 两个生产者定向测试文件：21 passed（投影 7 + 重复 14，含新增 B/A 用例）。
- 相邻语义/通道/解释器定向子集（语义验收、R-04 保留接线、源验收、Stroke、Path、解释器）：228 passed，仅余 R-04 已知两项基线失败。
- 全量同口径回归（剔除 8 个因缺失录制数据/语料文件而无法收集的测试文件）：
  - 基线树 `2fb2c68`：48 failed / 1808 passed / 4 skipped / 62 subtests；
  - 补丁树：47 failed / 1813 passed / 4 skipped / 62 subtests；
  - 失败节点逐名对照：**补丁侧无任何独有失败（零新增）**；基线有、补丁侧消失的 2 例为状态/顺序相关的既有波动用例（`test_agent_drawings` 布局跟进预览、`test_stale_project_guard` 新项目隔离），与两个生产者改动无关。
  - R-04 已知两项基线失败（`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`）在两侧均失败，保持原状，未被本补丁触碰。
  - 失败清单：`a_r02_failures_baseline.txt`（基线）、`a_r02_failures_patched.txt`（补丁后）。

## 6. 边界与未决

- **顶层台账合并（Tier 2，未在本轮做）**：汇总只读顶层 `source_acceptance.unknown_requirements`，不合并子通道报告内清单。本轮 B 报告的未 scope 条目可见于保留下来的通道报告；若主控要求被短路关系进入摘要顶层 unknown 列表，需一处解释器合并步骤（C 接线范围）。不影响本轮阻断有效性：`unverified + review_required=True` 的保留报告已被通用循环阻断 PASS。
- **Stroke / Path 未动**：C/D 未实测到"要求命中 + 多对象 → `not_checked` 丢弃"形态，按纪律不扩口；后续需专门夹具取证。
- 未改：解释器四门条件、候选门禁、`cad_candidate_state.py`、语义两模块、H2/H3/H4、`max_repairs`、计划契约 v1、FEATURE-CONTRACT；未碰 R-01/R-03/QE。
