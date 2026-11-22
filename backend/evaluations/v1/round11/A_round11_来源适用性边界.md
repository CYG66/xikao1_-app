# Round11 R-04：来源适用性边界核查与最小扩口说明

- 工作树：`tmp/r04-fix`（分支 `tmp/r04-fix`，父提交 `7c25d15…`）；本轮在其上**新提交**，不 amend / rebase / push / merge。
- 性质：零真实模型请求、零网络；未重跑 A9；未改冻结输入；未启动第六阶段。
- 改动范围：仅两个语义模块 + 语义单测 + 本轮评估产物；未改解释器、未改门禁谓词、未新增专用生成器或验收器。
- 核心判据：**"词表未命中"不得等同于"用户没有提出要求"**。系统必须能把"已存在但暂时无法验收的对象意图"与"真正没有适用语义要求"区分开。

## 1. 支持范围矩阵（实测，零模型）

### 1.1 语言范围

- 当前识别词表以**简体中文**为主；仅对英文 `star` / `draw a star` / `five-pointed star` 这一星形语族词面做有限识别。
- 未覆盖其他语言（如法语 `étoile`、德语 `Stern`）；未做英文整句语义理解，只做词面正则匹配。
- 中英混排可识别（如 `一个star`）；英文普通单词含子串 `star`（如 `start`）有负向前瞻保护，不误判。

### 1.2 明确支持：五角星轮廓（`star_profile`，已识别、无验收器）

| 表达 | 归类 | 通道 / 终态 |
|---|---|---|
| `五角星` | 显式可识别 | 适用但未验证；`not_checked` + `review_required=True`；第三态阻断 |
| `五芒星` | 显式可识别 | 同上 |
| `星形轮廓` | 显式可识别 | 同上 |
| `五角星形` | 显式可识别（子串命中） | 同上 |

正则位置：`UNVERIFIABLE_SHAPE_PATTERNS["star_profile"] = 五角星|五芒星|星形轮廓`；扫描函数 `recognized_unverifiable_kinds_from_text`。

### 1.3 歧义表达（来源信号不足以确立要求，保留不确定性）

| 表达 | 归类 | 终态 |
|---|---|---|
| `五角形` | 歧义（可能是五角星，也可能是凸五边形） | 无可佐证几何 → `ambiguous_unresolved` 阻断；几何为 star → `applicable` 阻断；几何为凸五边形 → `resolved_non_star` 放行 |
| `星形` | 歧义 | 同上 |
| `星星` | 歧义 | 同上 |
| `星型` | 歧义 | 同上 |

正则位置：`AMBIGUOUS_SHAPE_PATTERNS["star_profile"] = 五角形|星形|星星|星型`；扫描函数 `ambiguous_requirement_kinds_from_text`。

### 1.4 不支持但属星形语族：已识别、不可验收（本轮扩口重点）

| 表达 | 独立 kind 标识 | 终态 / 子原因 |
|---|---|---|
| `四角星` / `四角星形` | `four_pointed_star` | `unverified` + `coverage=unsupported_semantic_kind`；第三态阻断；`no_verifier` + `report_unverified` |
| `六角星` / `六角星形` | `six_pointed_star` | 同上 |
| `六芒星` | `six_pointed_star` | 同上 |
| `星号` | `asterisk` | 同上 |
| `draw a star` / `five-pointed star` / `star`（含中英混排 `一个star`） | `star_family_generic` | 同上 |

- 这些 kind **不绑定** `star_profile`：未来接入四尖 / 六尖验收器时可按 kind 单独注册，不与五角星轮廓冲突。
- 复用既有终态口径：`status=unverified`、`coverage=unsupported_semantic_kind`、`reason=no_verifier_for_kind`；未另起终态词表。
- 这是**来源侧意图记录**：用户措辞本身表达了星形语族意图，只是当前无验收能力；不是凭几何外观反向补造需求。

正则位置：`UNSUPPORTED_STAR_FAMILY_PATTERNS`；扫描函数 `recognized_star_family_unsupported_kinds_from_text`；kind 注册表 `UNVERIFIABLE_STAR_FAMILY_KINDS`。

### 1.5 非星形表达（不挂星形要求，正常放行或走既有专用通道）

| 表达 | 归类 | 终态 |
|---|---|---|
| 圆、矩形、正五边形、正六边形 | 无星形信号 | `no_signal`；第一态放行 |
| `星形线` / `astroid` | 既有专用通道 `astroid_identity` | 走既有曲线数学关系验收；显式 / 歧义 / 语族三类扫描均不命中 |
| `start` 等含 `star` 子串的英文普通词 | 负向前瞻排除 | `no_signal` 放行 |
| 爱心、房子轮廓、大写 A、嵌套框、cardioid、regular_polygon 等 | 既有已登记通道 | 按既有通道验收口径执行 |

## 2. 三分类处理判据

### 2.1 明确星形意图（含词表命中）

- 判据：来源命中显式词表，或报告已登记通道 / 专用验收通道。
- 即使无完整验收器，也必须 `applicable` → 未验证 + 第三态 + `review_required=True`，**不得**落 `no_signal` → accepted=true。
- 本轮实测 `五角星` / `五芒星` / `星形轮廓` 保持阻断，行为未被扩口破坏。

### 2.2 歧义表达

- 判据：来源命中歧义词，文本本身不足以确立要求。
- 无可佐证几何：`ambiguous_unresolved` → 第三态阻断（子原因 `ambiguous_requirement`）。
- 几何 profile 确认星形：`applicable` → 第三态阻断。
- 几何排除为非星形：`resolved_non_star` → 第一态放行。
- 本轮实测三种分支均保持既有行为。

### 2.3 不支持 / 星形语族外已识别但无验收器（本轮新增）

- 判据：来源命中 1.4 节语族词表，识别为既有注册表之外的星形语族意图。
- 必须落成一条可审计语义条目（`requirements` 含 kind、`unsupported_kind`、`recognized_unverifiable_kinds`），返回 `unverified` + `review_required=True`；不得伪装为完整验证，不得落 `no_signal` 放行。
- kind 与 `star_profile` 分离；不调用任何五角星验收器；不生成专用几何。

## 3. 落码位置（每条可追溯）

| 内容 | 位置 |
|---|---|
| 语族 kind 注册表 `four_pointed_star` / `six_pointed_star` / `asterisk` / `star_family_generic` | 调度模块 `UNVERIFIABLE_STAR_FAMILY_KINDS`；并入 `MANDATORY_REQUIREMENT_KINDS` |
| 语族词表正则 | 调度模块 `UNSUPPORTED_STAR_FAMILY_PATTERNS` |
| 语族文本扫描函数（astroid 守卫、显式优先排除） | 调度模块 `recognized_star_family_unsupported_kinds_from_text` |
| kind 分类（归入 `unverifiable_recognized`，不算 unknown） | 调度模块 `classify_requirement_kind` |
| 语族报告生成（`unverified` / `unsupported_semantic_kind` / 独立 kind） | 验收模块 `_verify_no_recognized_requirement` 语族分支 |
| 裁定挂载与三态消费 | 复用既有 `derive_applicability_decision` 与 `semantic_requirement_state`，未新增裁定取值 |

## 4. 实测真值表（探针：`A_round11_R04_family_scope_probe.py`；快照：`A_round11_R04_family_scope_probe.json`）

| 场景 | 来源 | decision | kind / 适用清单 | 合同状态 | 放行 |
|---|---|---|---|---|---|
| 显式 | 画一个五角星 / 五芒星 / 星形轮廓 | `applicable` | `star_profile` | `unverified_or_partial` | 否 |
| 歧义未解决 | 画一个星星 / 星形 | `ambiguous_unresolved` | 歧义 `star_profile` | `unverified_or_partial` | 否 |
| 歧义几何确认 | 画一个五角形 + 星形几何 | `applicable` | `star_profile` | `unverified_or_partial` | 否 |
| 歧义排除 | 生成一个五角形 + 凸五边形 | `resolved_non_star` | 空 | `no_applicable_requirement` | 是 |
| 语族 | 画一个四角星 | `applicable` | `four_pointed_star` | `unverified_or_partial` | 否 |
| 语族 | 画一个六角星 | `applicable` | `six_pointed_star` | `unverified_or_partial` | 否 |
| 语族 | 画一个六芒星 | `applicable` | `six_pointed_star` | `unverified_or_partial` | 否 |
| 语族 | 画一个星号 | `applicable` | `asterisk` | `unverified_or_partial` | 否 |
| 语族 | draw a star | `applicable` | `star_family_generic` | `unverified_or_partial` | 否 |
| 语族 | a five-pointed star | `applicable` | `star_family_generic` | `unverified_or_partial` | 否 |
| 语族 | 一个star（中英混排） | `applicable` | `star_family_generic` | `unverified_or_partial` | 否 |
| 普通 | 六边形 / 圆 / 矩形 / 五边形 | `no_signal` | 空 | `no_applicable_requirement` | 是 |
| W1 边界 | 画一个圆和一个矩形 + 星形几何 | `no_signal` | 空（未注入 star_profile） | `no_applicable_requirement` | 是 |
| 英文负例 | start here | `no_signal` | 空 | `no_applicable_requirement` | 是 |
| C10 | 爱心 + 五角星 | `applicable` | `heart_outline_features`, `star_profile` | `unverified_or_partial` | 否 |
| astroid | 星形线 astroid 四尖点 | 专用通道 | 显式 / 歧义 / 语族扫描均为空 | 既有行为保持 | — |

C10 对象级状态保持：爱心 `passed / heart_features_measured`；五角星 `not_checked / no_verifier_for_star_profile`；整体 `partial + review_required=True`。

## 5. 不得误伤核对

- 正五边形 / 正六边形：仅走 `regular_polygon` 既有口径，未挂任何星形要求；
- 星形线 astroid：仍走既有专用通道，未归入五角星或语族阻断；
- 圆 / 矩形（无星形文本，即使几何呈星形）：仍 `no_signal` 放行，上一轮 W1 边界未回退；
- `五角形` + 凸五边形：仍 `resolved_non_star` 放行；`五角形` + 星形几何：仍阻断；
- C10：爱心 passed、五角星 not_checked、整体 `partial / review_required=True`、accepted=false；
- 未通过无条件拦截所有图形提高通过率：放行项在探针中逐一实测仍放行。

## 6. 裁定词表核对

- 四值裁定仍是唯一出口：`applicable` / `resolved_non_star` / `no_signal` / `ambiguous_unresolved`；本轮**未新增**裁定取值。
- 三态词表未改：`no_applicable_requirement` / `fully_verified` / `unverified_or_partial`；既有终态词 `not_checked` / `unverified` / `partial` / `coverage=unsupported_semantic_kind` 含义不变。
- 语族 kind 属于"已识别、无验收器"的能力缺口登记，不是 unknown kind；`recognized_unknown_kinds` 为空。

## 7. 测试计数与回归

- 语义单测文件：**90 passed / 2 failed**；两项失败为基线既有失败（`test_structural_counter_schema_preserves_multiple_paths_without_coordinates`、`test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified`），同名同因，非本轮引入。
- 定向 12 文件回归：**287 passed / 2 failed**，失败项同上；C 侧保留接线 5 例全部通过。
- 本轮新增单测：语族七例参数化（四角星 / 六角星 / 六芒星 / 星号 / draw a star / five-pointed star / 一个star）、`start` 负例、普通形状与 W1 边界放行、歧义排除放行、歧义几何确认阻断、C10 回归。

## 8. 边界与禁区核对

- 未新增五角星 / 四角星 / 六角星专用生成器或验收器；复用既有 profile 分类与三态判据；
- 未改动 `cad_construction_interpreter.py`、`cad_candidate_state.py`（以 `git diff --name-only` 与 blob 哈希为准）；
- 未改 H2/H3/H4、`max_repairs`、`CadConstructionPlan v1`、FEATURE-CONTRACT；
- 未碰 R-01/R-02/R-03；未缩小既有检查范围、未删断言、未放宽阈值；
- 语族各 kind 仍是已识别但无完整验收器的能力缺口：本轮只关闭"语族意图被静默丢弃并放行"，不构成四尖 / 六尖 / 星号验收能力已解决。

## 9. 能力缺口表述

- 星形（五角星轮廓）、四角星、六角星、星号、英文泛称 star 当前均**无完整语义验收器**；探针中的 `unverified` / `not_checked` 只表示"已识别意图、尚未完成验收"，不得计为通过。
- 未来若接入四尖 / 六尖验收器，按各自 kind 注册通道即可，不影响现有 `star_profile` 与既有通道口径。
