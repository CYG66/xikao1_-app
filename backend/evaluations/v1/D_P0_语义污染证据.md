# D1 P0：A1 / A9 / C10 / C26 语义污染证据固化（爱心 vs 大写字母 A）

- 分支：`v1/d1-evaluation`；本轮为新增提交（不 amend、不推送、不合并）。
- 探针：`probes/d1_p0_semantic_forensic.py`；矩阵：`round7/d1_p0_semantic_matrix.json`；快照：`round7/d1_p0_snapshot.json`。
- 硬边界：本轮**未调用真实模型、未联网、未发起任何新请求、新增费用 0**；未重跑 A9、未启动 S1；未改冻结语料、未改公开 HTTP Schema、未改 `CadConstructionPlan v1`、未新增图形专用生成器；未写共享运行数据库。
- 取证对象：已落盘的 70 例语料复盘产物（只读）与第四轮冻结 A9 记录（只读）。所有中间过程凡落盘材料未记录者，一律标 `unverified`，不据最终报错反推。

---

## 0. 一句话结论

- **三例爱心/双对象（A1、A9、C10）在复盘运行中被大写字母 A 结构检查器误触发**；正向对照 **C26（真实字母 A）规则被正确选中并触发**，说明问题不是"字母 A 规则整体失效"，而是**规则选择/分发层把非字母 A 轮廓放进了字母 A 检查器**。
- **未发现 `case_id` 被拼进模型可见的消息/历史正文**；跨案例请求 ID 无串扰（143 个唯一请求 ID，`contamination=[]`，`blocked=false`）。同案历史中携带上一轮助手失败反馈，属会话内自反馈，不是跨案上下文污染。
- 两条 A9 记录**输入文本逐字相同、输入哈希相同**，但属不同实验、不同代码快照、不同 harness、不同失败现象，**已并列留证，未合并根因**。
- 代码级嫌疑（独立阅读 + 与 A 报告交叉核对，见 §8）：**选类层**在两套快照上都未把爱心文本判成字母 A kind；**分派层**修复前验收模块为 `if 房子 … else: 字母 A 检查器`，其余 profile（爱心/空/其他）全部兜底进字母检查器，与落盘字母 A 报错签名吻合；修复后改为显式 `elif straight_capital_a` 并对其他 profile 提前返回。运行时逐文件哈希未留存，该定性对运行时版本为**高置信但非逐字节证实**。

## 1. 附件版本与使用边界

| 附件 | 大小（字节） | SHA-256（本轮复算） | 使用边界 |
|---|---:|---|---|
| `文生文修CAD测试语料.md`（70 例语料） | 13,128 | `807F33A3C6ED5AAD05943258CF406D9D88014BD1E4B02EC6F369E5A88F8A742D` | 矩阵 `case_id` 与原始输入逐字取自该文件；本轮未修改语料文本。 |
| `CODEX_FEATURE_CONTRACT_PROPOSAL.md`（FC 提案 V1.1） | 29,056 | `670A6237A9F3989AC9D7EB10C4B1CDA316C86CFD0A041BB0B8B745ADF4B1E3B9` | 独立仓库 `codex-cad-agent`、分支 `codex/independent-cad-v1`、基线 `9bd105f`、提案提交 `bd8e43c`；自述未改生产代码、未运行测试。**该提案不构成任何已实现/已通过证据**；本轮审计、SHA 一致性核对、费用账本均未引用提案内容作为代码或测试依据。 |

语料构成：A1–A11（11）+ B1–B19（19）+ C1–C34（34）+ D1–D6（6）= 70。

## 2. 四例对照矩阵（逐行）

> 字段口径：`expected_semantic` 为语料原始语义；`actual_semantic` 为落盘证据中实际进入/命中的验收 profile；`rule_id` 取 profile kind 与检查项 ID；规则版本在落盘材料中无版本常量，统一标 `unverified`。完整机器可读矩阵见 `round7/d1_p0_semantic_matrix.json`。

| case_id | 原始输入（逐字） | expected_semantic | actual_semantic（落盘证据） | 最早错误层 | rule_id · version | case_id 泄漏 | 上下文污染 | FC binding | 证据状态 |
|---|---|---|---|---|---|---|---|---|---|
| A1 | `生成一个闭合爱心轮廓，宽度4米，高度4米` | heart_outline_features | 计划语义 `闭合爱心轮廓`（`heart.outline`，参数爱心曲线）；验收实际命中 `straight_capital_a` 上部三角区检查 | 结构/几何验收：attempt 1 `structure_requirement_failed`，检查 `大写A缺少由两斜笔与横笔围成的上部三角区域`，`observed_triangular_regions=[]` | 实际命中：`straight_capital_a` / `triangle_tip_above_horizontal_base`；应走：`heart_outline_features` / `heart_bilateral_lobes_notch_and_lower_tip`；**version=unverified** | 否：消息与历史正文无编号串；编号仅出现在 `conversation_id=user-corpus-A1` | 无跨案污染；同案历史含上一轮助手失败反馈（会话内自反馈） | 未持久化（`feature_contract_binding=not_persisted_in_evidence`） | 输入/历史/契约事实/计划标签/错误测量：有证据；system/developer 提示词、运行时逐文件哈希、规则版本：`unverified` |
| A9（语料版） | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | heart_outline_features | 计划语义 `左右对称、平滑闭合的爱心`；attempt 1 表达式非法，attempt 2/3 验收命中 `straight_capital_a` 上部三角区检查 | 最早：模型计划/表达式校验（attempt 1 `invalid_parametric_curve`，`heart-outer` 表达式未允许语法）；语义误触发在 attempt 2/3 | 误命中：`straight_capital_a` / `triangle_tip_above_horizontal_base`；**version=unverified** | 否：正文无编号串；`oracle_case=A10` 仅为别名映射元数据，未进正文 | 无跨案污染；同案自反馈 | 未持久化 | 输入/历史/契约事实/计划标签/两轮错误：有证据；system 提示词、运行时逐文件哈希、规则版本：`unverified` |
| C10 | `生成一个爱心和一个五角星，爱心在左，五角星在右` | heart + star 双对象 | 计划标签 `爱心`、`五角星`；验收命中 `straight_capital_a` 上部三角区检查 | 结构/几何验收：attempt 1 `structure_requirement_failed`，`observed_triangular_regions=[]` | 误命中：`straight_capital_a` / `triangle_tip_above_horizontal_base`；**version=unverified** | 否：正文无编号串 | 无跨案污染；同案自反馈 | 未持久化 | 输入/历史/契约事实（爱心宽高、五角星外接圆半径）/计划标签/错误测量：有证据；system 提示词、运行时逐文件哈希、规则版本：`unverified` |
| C26（正向对照） | `生成一个大写字母A的轮廓，高3米宽2米` | straight_capital_a | 计划标签均为 `大写字母A`（外轮廓/三角空隙/横笔）；字母 A 规则**正确选中并触发** | 结构/几何验收：attempt 1 `大写A的三角区域须属于同一笔画结构，不能用游离三角形代替`；attempt 2 `大写A底部须保留分离的左右支脚`；attempt 3 `assertion_failed`（尺寸 1.44×3 vs 2×3） | 正确命中：`straight_capital_a`（游离三角形 / 左右支脚检查）；**version=unverified** | 否：正文无编号串 | 无跨案污染；同案自反馈 | 未持久化 | 输入/历史/契约事实/计划标签/三轮错误：有证据；system 提示词、运行时逐文件哈希、规则版本：`unverified` |

**对照判读**：C26 证明字母 A 规则本身能在真实字母 A 上被触发；A1/A9/C10 的误触发不是规则"没跑"，而是**不该进字母 A 检查器的轮廓进了检查器**。两套快照本地回放（回放，非真实运行）：pre-fix（A 树快照，模块哈希 `423ed2ff…`）A1/A9/C10 → `heart_outline_features`、C26 → `straight_capital_a`；post-fix（当前后端，模块哈希 `164a7d89…`）A1/A9 → `heart_outline_features`、C10 → `[]`（双对象守卫收紧到 ≤1）、C26 → `straight_capital_a`。回放只证明选类层行为，不能反推运行时分派层。

## 3. 逐例调用链留痕

### 3.1 消息与历史（模型可见正文）

四例均为三轮：原始需求 → 补充参数（oracle 对应答案）→ `确认需求并生成CAD候选，只预览，不执行小车。`

- A1 历史：原始爱心需求 → 助手首轮失败（大写 A 三角区）→ 补充 `宽度4米，高度4米。` → 助手确认参数已合并 → 末轮再次失败。
- A9 历史：原始爱心需求（含中心坐标）→ 助手首轮失败 → 补充中心/宽高/单位 → 确认合并 → 末轮失败。
- C10 历史：原始爱心+五角星 → 助手首轮"已识别为爱心，请提供尺寸" → 补充双对象尺寸 → 确认合并 → 末轮被字母 A 规则拒绝。
- C26 历史：原始字母 A → 首轮尺寸/结构失败 → 补充高度 → 确认 → 末轮"CAD草稿待复核：未通过需求自动验收"。

`request-1/2/3.json` 留存了每轮 `message`、`history`、`conversation_id`；对正文做编号串扫描（正则 `\b[A-D]\d{1,2}\b`），**四例正文命中均为空**；编号仅出现在 `conversation_id` 元数据。`ui-fixture.json` 的 `id` 为 harness 本地夹具字段，不进入模型请求体。

### 3.2 Requirement Contract（事实/对象/作用域）

落盘 `requirement_ledger.requirement_contract.facts`（节选，完整见矩阵 JSON）：

- A1：对象 `闭合爱心轮廓`，事实 `width=4000mm`、`height=4000mm`，`user-2` 两条 `effective`；`requirements.shape=heart_outline`。
- A9：对象 `左右对称、平滑闭合的爱心`，宽高 `4000mm`；`requirements.shape=heart_outline`。
- C10：对象 `爱心`（宽高 4000mm）、`五角星`（外接圆半径 2000mm）；`requirements.shape=heart_outline`（修复前双对象阈值所致）。
- C26：对象 `大写字母A的轮廓`，高 3000mm、宽 2000mm；另有一条 `unresolved` 高度事实；`requirements.shape=generic_2d_cad`。

### 3.3 semantic_requirements 输入与输出

- **落盘侧**：留存了验收输入的来源文本（`requirement_ledger.sources`）与计划侧语义标签；但 `verify_semantic_requirements` 当次实际返回的 `requirements` 列表**未逐字段持久化**，运行时那一步的输出 `unverified`。
- **回放侧（本地回放，非真实运行）**：用当前工作树代码对落盘来源文本重放 `semantic_requirements`，结果见 §2 对照表"当前代码回放"列；回放只证明当前代码行为，不能反推运行时快照行为。

### 3.4 Feature Contract binding

四例落盘产物中均无 Feature Contract 绑定记录（`feature_contract` / `binding` 关键字在 step 记录与 agent-runs 中命中 0）。该项记 `not_persisted_in_evidence`，不做有无推定。

### 3.5 最终验收规则与错误测量

- A1、C10：`required_relation=triangle_tip_above_horizontal_base`，`observed_triangular_regions=[]`，权威 `backend_measured_geometry`。
- A9：attempt 1 为表达式校验失败；attempt 2/3 同上三角区测量。
- C26：游离三角形归属检查 → 底部两支脚检查 → 尺寸断言；测量细节见矩阵 JSON `attempts`。

## 4. 代码与环境快照

### 4.1 聚合 digest 与一致性

- 复盘运行清单留存聚合哈希 `backend_code_sha256=08eae81a3abab61bc9999f4c3327c0fdf6312883aa13d47c273deadfbc8e8e73`（算法：`app/**/*.py` 排序后，依次更新相对路径字节 + 文件原始字节，与 harness 清单生成逻辑一致）。
- 探针在当前工作树按同一算法复算：**聚合 digest 不匹配**；当前 `app` 下 127 个 Python 文件。运行后验收模块与 `agent_service.py` 等文件已有修改（文件 mtime 晚于复盘运行时间）。
- **运行时逐文件 SHA-256 未留存**（清单只存聚合值），除下述保留副本外，其余模块的运行时哈希 `unverified`；复盘后端目录在其版本控制下无提交记录，commit SHA `unverified`。

### 4.2 保留的修复前副本与当前模块对照

- 修复前保留副本：`before-fixes/cad_semantic_acceptance.py`，23,960 字节，SHA-256 `423ED2FF4D23D2090921C19542E2E8D9C8DCFECB49B196E3E619EB543C3A1D09`。
- 当前工作树：`app/cad_semantic_acceptance.py`，24,540 字节，SHA-256 `164A7D89E204D116275E31C50B8D55197F26BA620034954327B9FA9DE7345C32`。
- 两者 diff（4 处）：
  1. 爱心分支对象数阈值：`<= 2` → `<= 1`；
  2. 爱心几何检查门槛：文本正则 `爱心|心形` → 要求 requirements 中存在 `heart_outline_features`；
  3. 新增提前返回：非 `triangle_roof_house` / `straight_capital_a` 的 profile 不再落入结构检查器；
  4. 分发分支：`else:`（字母 A 检查器兜底）→ `elif kind == 'straight_capital_a':`。

### 4.3 代码级嫌疑（独立阅读，待 A 报告交叉核对）

修复前副本的分发结构为：`if kind == 'triangle_roof_house': … else: <字母 A 三角区/支脚/顶部收拢检查>`。即爱心、空 profile 及其他任何非房子轮廓，都会进入 `else` 字母 A 检查器；这与 A1/A9/C10 记录到的报错消息、测量字段（`triangle_tip_above_horizontal_base`、`observed_triangular_regions=[]`）吻合。当前代码已用显式 `elif` + 提前返回切断该兜底路径。

保留意见：修复前副本是否与运行时模块**逐字节相同**无法证实（逐文件哈希 `unverified`）；该根因定性为"与保留副本及落盘错误签名一致的高置信推断"，不等同于运行时文件级证实。

### 4.4 运行环境

- 模型：`deepseek-flash`（清单 `model_configuration.provider=deepseek`）；启动器重定向 `USERPROFILE/HOME` 到评测工作树 `home/`；预算上限 600 请求 / 20M 输入 / 2M 输出 / 5 USD；剥除 `P12_EVAL_MOCK_PROVIDER`。
- Python 版本：复盘产物未记录，`unverified`；探针本机解释器 3.11.18（仅作探针环境记录，不作为运行时版本）。
- 语义规则版本：模块内无规则版本常量，`unverified`；可追溯的 schema 版本为 `cad.construction-error.v1`、`cad.generation-recovery.v1`、`agent.checkpoint.v3`。

## 5. 两条 A9 永久并列（禁止合并）

| 对照项 | 记录① 第四轮独立真实评测 A9（冻结，未重跑） | 记录② 70 例语料 A9（本次复盘，未发起新请求） |
|---|---|---|
| 证据路径 | `round4/A9_case_record.json`、`round4/A9_raw_responses.jsonl`、`D1_round4_A9真实模型受控评测报告.md` | `run/A9/corpus-report.json`、`run/A9/step-1..3.json`、`run/A9/request-1..3.json`、`run/A9/model-usage.jsonl` |
| 输入文本 | `生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米` | 同左，**逐字相同** |
| 输入哈希 | `af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b` | `af12df04393e1da42acd9eae6e590f81fa8c66a4720c546c9d292fef89707d5b`（相同） |
| 代码快照 | 基线组合树 `f89bf41facfb7032cbb9647250cff6bbdcc6bbb7`；D 工作树 `4ad73eb038bbdf5a8ded8be5bc3a2feb0a2dcd70`；逐文件哈希 `unverified`，报告称评测期 `backend/app` 相对基线零改动 | 聚合 digest `08eae81a3abab61…e8e73`；逐文件哈希 `unverified`；保留修复前验收副本 `423ED2FF…A1D09` |
| 请求与真实调用 | 2 次 `deepseek-flash` 结构化请求；真实 usage 输入 31,554（命中 15,872 / 未命中 15,682）、输出 804；费用 0.005764632 USD | 6 条 usage 记录、结构化调用 3 次；输入 84,238、输出 2,093（缓存命中 77,824）；费用未在本轮重算（账本归第七轮统一处理，缺 usage 字段标 `unverified`） |
| 运行环境 | 隔离进程内运行；服务配置 deepseek / deepseek-flash；Python 版本 `unverified` | harness `tests/manual/run_user_cad_corpus.py` 经启动器执行；Python 版本 `unverified` |
| 语义规则版本 | `unverified` | `unverified` |
| 失败现象 | 爱心特征验收：`heart_bilateral_lobes_notch_and_lower_tip`，`lower_tip=false`（其余三特征 true） | attempt 1 参数表达式非法；attempt 2/3 命中字母 A 上部三角区检查 `observed_triangular_regions=[]` |
| 失败类别 | 几何特征验收（爱心下方尖点未检出） | 规则选择/结构验收串扰（爱心轮廓误入字母 A 检查器）；首轮另有模型计划表达式问题 |
| 项目读回 ID | `e089c984-dda0-4ad2-b84d-b6e008e2534c` | `47d6b245-7c58-4bab-bc04-2842f443f902` |
| 状态 | `failed`，未持久化候选 | `failed`，`has_candidate=False`，`app=not_run` |
| 是否发现可证明大写 A 误识别的证据 | **无**：失败为爱心几何尖点，无字母 A 报错记录 | **有（落盘验收报错签名）**：字母 A 上部三角区检查 `observed_triangular_regions=[]`；选类层来源归因 `unverified`（详见 §8.5） |

**并列结论**：两条记录输入文本与哈希相同，但代码快照、harness、请求规模、失败现象与失败类别均不同；**不得合成同一根因，不得用一条结论覆盖另一条**。记录①的爱心尖点几何问题与记录②的规则选择串扰是两类独立缺陷。

## 6. case_id 泄漏与上下文污染核查

- **泄漏核查**：四例 `request-N.json` 的 `message` / `history` 正文扫描无 `A1/A9/C10/C26` 编号串；`A9` 记录中的 `A10` 仅为 `oracle_case` 别名映射元数据。编号唯一出现位置是 `conversation_id`（`user-corpus-<case>`），属会话标识，不进入提示词正文。
- **跨案污染**：清单证据审计 `unique_request_ids=143`，`contamination=[]`，`blocked=false`；未发现同一请求 ID 被两个案例复用。
- **同案自反馈**：第二轮起历史携带上一轮助手失败反馈文本；该反馈在会话内回灌，是否反向影响后续规则选择，本轮无直接证据，记为待核事项，不归为跨案污染。

## 7. 证据覆盖率与 unverified 清单

- 矩阵 4 行 × 9 列：输入文本、历史轮次与内容、契约事实、计划语义标签、最早错误层、命中检查项与测量、请求 ID/模型/用量、会话标识——**有落盘证据**；
- 以下单元格 `unverified`（落盘材料未记录，未反推）：
  1. system / developer 提示词全文（`model-responses.jsonl` 仅存响应字符串，`agent-runs.json` 无 system 字段）；
  2. 运行时逐文件 SHA-256 与 commit SHA（清单仅存聚合 digest；后端目录无 git 提交）；
  3. 语义规则版本号（模块无版本常量）；
  4. `verify_semantic_requirements` 当次返回的 requirements 列表；
  5. Feature Contract binding（产物中无记录）；
  6. 复盘运行 Python 版本；
  7. 修复前副本与运行时模块是否逐字节相同。

## 8. 交叉核对 A 结论（D 独立复核，有异议并列，不和稀泥）

### 8.1 复核范围与方法

- A 报告：`A_P0_语义污染定位.md`，A 树 commit `91ff8fe`；其快照验收模块哈希 `423ed2ff4d23d2090921c19542e2e8d9c8dcfecb49b196e3e619eb543c3a1d09`（23,960 B，pre-fix）。
- D 在两套快照上独立跑纯函数规则回放（无模型、无网络、无新请求）：pre-fix = A 树只读工作树；post-fix = 当前后端（模块哈希 `164a7d89e204d116275e31c50b8d55197f26ba620034954327b9fa9de7345c32`，24,540 B）。
- 回放输入取落盘账本来源文本；回放只证明规则函数当前行为，**不证明运行时快照行为**。
- A 探针 trace 字段止于 `sidecar_shadow`（`entry_normalization / local_creation_objects / regex_matches / requirement_contract / semantic_requirements / parameterize_design / sidecar_shadow`），**不含分派（dispatch）与验收可达性回放**。

### 8.2 逐条核对

| # | A 的结论 | D 复核判定 | 证据与说明 |
|---|---|---|---|
| 1 | 选类层：A1/A9/C10 → `heart_outline_features`，C26 → `straight_capital_a`；爱心未在选类层被判成字母 A | **同意（限 pre-fix 快照）** | D 独立回放 pre-fix 与 A 取值完全一致：A1/A9/C10 heart、C26 letter。**快照差异注明**：post-fix 回放 C10 → `[]`（爱心对象数守卫由 ≤2 收紧到 ≤1）；A 表中"C10 = heart"是 pre-fix 行为，不能外推到 post-fix。 |
| 2 | 代码行角色：`:42` 爱心正则；`:173` cardioid 分支；`:275-319` 字母 A 几何检查 | **同意，行号角色属实** | 逐行 Read 核验（A 快照）：`:42` `re.search(r'爱心\|心形', text)` + 对象数 ≤2 守卫；`:173` `re.search(r'cardioid\|心形线', original)`；`:253` `kind=requirements[0]['kind']`；`:254` 仅分流 `triangle_roof_house`；`:275 else:` 起字母 A 检查（上部三角 `:290-294`、分离双支脚 `:312-317`、收拢斜笔 `:318-319`）。 |
| 3 | L8：按当前 kind 分派；**"爱心文本不进入字母 A 几何检查"**；规则不跨请求继承 | **异议（不同意 L8 前半句）** | A 自身快照代码与该结论矛盾：`:254` 只分流房子，`:275 else:` 兜底会让 `heart_outline_features` kind 穿透进入字母 A 几何检查器；`:199` 爱心特征检查通过后**不提前 return**，继续落到 `:253` 分派。A 探针未回放分派/验收可达性，L8 属未经验证的代码阅读结论。**D 侧 §8.6 执行回放已钉死**：pre-fix 上 A1/A9/C10 的 heart kind 经 `253→254(假)→276` 轨迹实际到达字母 A 检查器并抛出三角区签名。落盘真实运行的字母 A 报错（`:292` require 消息，`observed_triangular_regions=[]`）与该 `else` 兜底行为吻合。"规则不跨请求继承"一句：D 侧落盘证据同样未发现旧标签复用，此项同意。 |
| 4 | 上下文 / 多轮污染、对象绑定错误、验收规则跨请求继承错误，均被证据排除 | **部分同意** | 同意：D 侧落盘扫描未发现 case_id 进入模型可见正文，143 个唯一请求 ID 无跨案复用（`contamination=[]`）；C10 双对象无尺寸事实、绑定歧义拒绝。保留：A 对"验收规则继承错误被排除"的论证止于选类层与静态阅读，分派层 `else` 兜底（见 #3）未被其回放覆盖。 |
| 5 | 唯一实测规则层重叠：C19 `心形线（cardioid）` 被爱心子串 `心形` 先命中；是否误验收待验证 | **同意选类层重叠；验收定性补记** | 两套快照回放 C19 均 → `heart_outline_features`。**选类标签重叠真实存在**：落盘 C19 首轮澄清话术按爱心走（"还缺少生成候选方案所需的：爱心轮廓宽度和高度"），有选类层实害表现。**是否造成错误几何验收：`unverified`**。验收流顺序 cardioid `:173` 先于爱心 `:199`；cardioid 判过在 `:196` 提前 return，heart kind 分派不可达；cardioid 判败则抛 cardioid 错误。未跑几何回放前不下定论；当前口径偏"标签近似、验收层被 cardioid 分支先行拦截"。补充风险：pre-fix `else` 兜底下，若 cardioid 未拦截，heart kind 仍会落入字母检查器（与 P0 三例同一机制）。 |
| 6 | 语料 A9 在 A 仓库内无运行记录；"大写 A 验收错误"标 `unverified` | **范围分歧，并列保留** | A 的"无记录"仅适用于其 A 树仓库快照。D 侧在 persisted 70 例运行目录找到四例完整落盘（请求体/历史/计划标签/验收测量/用量），其中 A1/A9/C10 含字母 A 上部三角区报错签名（`observed_triangular_regions=[]`）。两处证据范围不同，互不覆盖；运行时逐文件哈希在两侧均 `unverified`。 |

### 8.3 两套快照选类回放对照（本地回放，非真实运行）

| case_id | 期望语义 | pre-fix（`423ed2ff…`） | post-fix（`164a7d89…`） | 与期望一致（pre-fix） |
|---|---|---|---|---|
| A1 | heart | `heart_outline_features` | `heart_outline_features` | 是 |
| A9 | heart | `heart_outline_features` | `heart_outline_features` | 是 |
| C10 | heart + star 双对象 | `heart_outline_features` | `[]` | 选类层未判字母 A；双对象未映射单一 profile |
| C26 | 大写字母 A | `straight_capital_a` | `straight_capital_a` | 是（正向对照） |
| C19（重叠对照，非 P0 四例） | cardioid | `heart_outline_features` | `heart_outline_features` | 子串重叠，两套快照均复现 |

混合两轮文本回放（pre-fix / post-fix 一致）：`heart_then_A`、`A_then_heart` 均命中 `heart_outline_features`——爱心正则在顺序上先于字母 A 正则，同段文本含两个形状词面时爱心子串占先。该结果为回放观察，未对应真实运行。

### 8.4 P0 前提的 D 独立判断

1. **选类层**：当前 post-fix 代码与 pre-fix 代码的选类函数上，都复现不出"爱心文本被规则识别为大写字母 A"。**P0 前提（爱心在文本规则层被误判为字母 A）未被当前代码证据支持**。
2. **分派层**：pre-fix `else` 兜底会把 heart kind 放入字母 A 几何检查器；§8.6 执行回放已证明该穿透在 pre-fix 快照上真实发生（heart kind 到达 `:275/:276` 字母检查器并抛出三角区签名）。但运行时快照逐字节哈希 `unverified`，"运行时确实走了该 `else` 分支"仍为与保留副本及报错签名一致的高置信推断，非文件级证实。
3. **模型侧**：模型计划几何 / 自报标签是否影响门禁，本轮零模型调用无法复核，记 `unverified`，不据最终报错反推中间过程。
4. **口径结论**：若问题确实存在，可定位到的代码侧嫌疑是 **pre-fix 分派层兜底**（结构有代码证据）；归因到模型侧、另一未留存快照或选类层误识别，目前均 `unverified`。A 报告"后端规则链内未找到爱心→字母 A 的第一次错误分类层"在**选类层**成立；其 L8"爱心不进字母检查器"在分派层与其自身快照代码矛盾，D 不同意该句。

### 8.5 两条 A9 并列（新增：大写 A 误识别证据列）

| 对照项 | 记录① 第四轮独立真实评测 A9 | 记录② 70 例语料 A9 |
|---|---|---|
| 输入哈希 | `af12df04393e1da…89707d5b` | 同左（逐字相同） |
| 代码快照 | 基线组合树 `f89bf41…`；D 工作树 `4ad73eb…`；逐文件哈希 `unverified` | 聚合 digest `08eae81a…`；保留 pre-fix 验收副本 `423ED2FF…`；逐文件哈希 `unverified` |
| 请求记录 | 2 次真实 `deepseek-flash`，usage/费用有落盘 | 6 条 usage、结构化调用 3 次；费用归第七轮账本 |
| 运行环境 | 隔离评测进程；Python 版本 `unverified` | harness 经启动器执行；Python 版本 `unverified` |
| 语义规则版本 | `unverified`（以文件哈希 + 行区间标识） | `unverified` |
| 失败现象 | 爱心几何：`heart_bilateral_lobes_notch_and_lower_tip`，`lower_tip=false` | attempt 1 参数表达式非法；attempt 2/3 命中字母 A 上部三角区检查 |
| **是否发现可证明大写 A 误识别的证据** | **无**：失败检查为爱心几何特征，无字母 A 验收报错记录 | **有（落盘验收报错签名）**：`required_relation=triangle_tip_above_horizontal_base`、`observed_triangular_regions=[]`；选类层来源归因与运行时逐文件哈希 `unverified` |
| 项目读回 ID | `e089c984-…2534c` | `47d6b245-…443f902` |
| 状态 | `failed`，未持久化候选 | `failed`，`has_candidate=False`，`app=not_run` |

**并列结论**：同一输入文本、相同输入哈希，但代码快照、harness、请求规模、失败现象、失败类别均不同；**不得合成同一根因，不得用一条结论覆盖另一条**。记录①是爱心尖点几何问题，记录②是分派/验收串扰线索，两类独立缺陷。

### 8.6 分派层执行回放（离线、零模型；把结构推断升级为执行证据）

**方法**：在两套快照上直接调用验收入口 `verify_semantic_requirements(source, geometries)`，不再停在选类层；夹具为一条合成的闭合爱心折线（4000 mm 包络，非落盘真实几何）。用行级 trace 记录实际执行到的验收分支；回放为纯函数执行，**不是真实端到端运行**，不能反推运行时快照逐字节行为。机器可读证据：`round7/d1_p0_dispatch_replay.json`，探针 `probes/d1_p0_dispatch_replay_probe.py`。

**pre-fix 快照（模块哈希 `423ed2ff…`，23,960 B）回放轨迹**

| case_id | 进入 kind | 爱心检查器 | 是否到达字母 A 检查器 | 执行轨迹与签名 | 最终规则 ID |
|---|---|---|---|---|---|
| A1 | `heart_outline_features` | 进入并通过爱心特征门 | **到达**（`:275 else` 兜底，首条执行语句 `:276`；trace `253→254(假)→276→292`） | 抛出 `大写A缺少由两斜笔与横笔围成的上部三角区域`；`required_relation=triangle_tip_above_horizontal_base`，`observed_triangular_regions=[]` | 实际进入 `straight_capital_a` 几何检查器；无通过规则 |
| A9 | `heart_outline_features` | 进入并通过爱心特征门 | **到达**（同上 `:275/:276`） | 同上三角区签名，`observed_triangular_regions=[]` | 同上 |
| C10 | `heart_outline_features` | 进入并通过爱心特征门 | **到达**（同上 `:275/:276`） | 同上三角区签名，`observed_triangular_regions=[]` | 同上 |
| C26（正向对照） | `straight_capital_a` | 未进入爱心块（门条件不成立） | **到达**（`else` 分支；`letter_triangle_check` 命中 `:292`） | 同上三角区签名（夹具为爱心折线，无三角形） | `straight_capital_a` 检查器被正确选中并执行 |

**post-fix 快照（模块哈希 `164a7d89…`，24,540 B）回放轨迹**

| case_id | 进入 kind | 爱心检查器 | 是否到达字母 A 检查器 | 执行轨迹与返回 | 最终规则 ID |
|---|---|---|---|---|---|
| A1 | `heart_outline_features` | 进入并通过爱心特征门 | **未到达**（`:239` 非目标 profile 提前返回；trace `238→239→240-243`） | 返回 `partial`，coverage `heart_outline_features_measured_features` | 爱心特征门；字母 A 规则不可达 |
| A9 | `heart_outline_features` | 进入并通过爱心特征门 | **未到达**（同上 `:239` 提前返回） | 同上 `heart_outline_features_measured_features` | 同上 |
| C10 | `[]`（无 profile） | 未进入爱心块 | **未到达** | `requirements` 为空，`:232` 返回 `not_checked` / `partial` | 无强制门禁规则 |
| C26（正向对照） | `straight_capital_a` | 未进入爱心块 | **到达**（`:283 elif straight_capital_a`，三角检查 `:300`） | 抛出上部三角区签名（夹具无三角形） | `straight_capital_a` 检查器被正确选中并执行 |

**逐例一句话结论（pre-fix）**：A1 → 到达字母 A 检查器；A9 → 到达字母 A 检查器；C10 → 到达字母 A 检查器；C26 → 到达字母 A 检查器（正向，应到达）。
**逐例一句话结论（post-fix）**：A1 → 未到达；A9 → 未到达；C10 → 未到达；C26 → 到达（正向，应到达）。

**对照结论**：
1. pre-fix 上，heart kind 在爱心特征门通过后**没有提前返回**，经 `:253` kind 取值、`:254` 房子分支不成立，穿透进 `:275 else` 字母 A 几何检查器——该穿透已由执行轨迹钉死，不再仅是代码阅读推断。
2. post-fix 上，`:239` 对非房子 / 非字母 profile 提前返回，heart kind 不再落入字母检查器；修复点在**分派层**，不是选类层（选类守卫收紧只影响 C10 空 profile，未改动爱心→字母的穿透路径）。
3. C26 在两套快照上都正确进入字母 A 检查器，正向对照成立：字母 A 规则本身可用，问题是 pre-fix 分派兜底把非字母轮廓放了进去。

**第一次错误层判定（D 独立口径）**：
- **选类层：无错误**。两套快照选类取值与期望一致（C10 post-fix 为空 profile 属多对象守卫，非误判为字母 A）；未发现爱心文本在规则层被识别成大写 A。
- **分派层：主因（pre-fix 快照，执行证据支持）**。`else` 兜底把 heart / 空 / 其他非房子 profile 一并送入字母 A 几何检查器；落盘报错签名与回放抛出的检查项、测量字段一致。
- **模型侧 / 运行时快照：`unverified`**。模型计划几何与自报标签是否影响门禁，本轮零模型调用无法复核；运行时逐文件哈希未留存，"运行时确实走了该 `else` 分支"仍属与保留副本及报错签名一致的高置信推断，非文件级证实。
- 主次：分派层兜底是代码侧可定位的主因；选类层不背锅；模型侧归因待后续真实运行落盘中间态再核。

**与 A 修订版报告的一致性**：A 修订版报告路径转来后，本节逐条回填"同意 / 仍异议"。基于 A 原版：选类层结论 D 同意；其 L8"爱心文本不进入字母 A 几何检查"在分派层与执行回放矛盾，D **仍持异议**——pre-fix 回放证明 heart kind 实际到达了字母 A 检查器。

## 9. 纪律复核

- 本轮新增真实模型请求 **0**、新增费用 **0.000000000 USD**；未联网；未重跑记录① A9；未启动 S1；冻结语料哈希复核一致；未改公开 HTTP Schema 与 `CadConstructionPlan v1`；未新增图形专用生成器；未写共享运行数据库；未 amend、未 push、未合并。
