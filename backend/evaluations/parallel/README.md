# 四主线并行研发工作台

本目录是「四个 Agent 并行开发 + 一个总控 Agent 统一集成」的执行入口。所有 Agent 开工前必须先读本目录，读完再动手。

## 一、组织与工作树

| 角色 | 工作树 | 分支 | 一句话职责 |
|---|---|---|---|
| A 自然语言与 CAD 规划 | `cad-worktrees/nlp-planning` | `parallel/nlp-planning` | 让模型第一次就产出可执行的 CAD 计划 |
| B CAD 几何与算法 | `cad-worktrees/geometry` | `parallel/geometry` | 让计划落成合法的几何，并能定位/修复缺陷 |
| C Agent 架构与产品链路 | `cad-worktrees/orchestration` | `parallel/orchestration` | 让多轮自然语言创建/修改真正跑通 |
| D 测试、评测与质量保障 | `cad-worktrees/evaluation` | `parallel/evaluation` | 用数据证明改动有效，且不污染生产代码 |
| 总控 | `cad-worktrees/integration` | `integration/p1.4-parallel` | 合并、回归、接口仲裁、最终合入 `cad` |

**最终合并目标：`cad`（已拍板）。`main` 是另一条独立开发线，本轮不动、不合并、不推送。** 四个 Agent 不得自行合并到 `cad`；只有总控在完成九项回归后才能执行合入。

主工作树（`D:\xikao\xikao1_-app`，分支 `cad`）只做三件事：冻结基线、维护本目录文档、作为历史评测产物的只读仓库。**Agent 不得在主工作树提交。**

## 二、基线

- 代码基线提交：`211cacd chore(baseline): 冻结 cad/ -> backend/app 重构现状作为并行研发基线`
- 该提交把 `cad/` 旧包删除与 `backend/app/` 新增模块一并固定下来（352 个文件），并补齐 `.gitignore`。
- 本目录文档随后单独提交，再同步到四个业务分支；各分支的起点以 `git log -1 --oneline` 显示的文档提交为准。

## 三、开工顺序

1. 把 Codex 会话的根目录设成**自己那条工作树的根**，不要停在 `backend/` 子目录（原因见「环境注意」第 3 条）。
2. 依次读：`00-四主线任务书.md` → `01-文件所有权与公共接口冻结.md` → `02-研发纪律与交付模板.md`。
3. 涉及真实模型调用读 `04`；涉及合并/验收读 `03`；涉及指标口径读 `05`。
4. 第一阶段只做诊断与只读调查，产出证据后再改代码（见 00 的三阶段节奏）。

## 四、启动检查清单

| # | 检查项 | 验证方式 | 期望结果 |
|---|---|---|---|
| 1 | 基线已冻结 | 各树 `git log -1 --format="%h %s"` | HEAD 为 `a8a8cb6`（制度文档最后一次提交），工作区干净 |
| 2 | 五条工作树就绪 | `git -C D:\xikao\xikao1_-app worktree list` | 主工作树 + 4 条业务 + 1 条集成，共 6 条 |
| 3 | A 分支正确 | 在 `nlp-planning` 内 `git branch --show-current` | `parallel/nlp-planning` |
| 4 | B 分支正确 | 在 `geometry` 内 `git branch --show-current` | `parallel/geometry` |
| 5 | C 分支正确 | 在 `orchestration` 内 `git branch --show-current` | `parallel/orchestration` |
| 6 | D 分支正确 | 在 `evaluation` 内 `git branch --show-current` | `parallel/evaluation` |
| 7 | 文件所有权已确认 | 各 Agent 首次汇报 | 明确列出自己的独占文件与禁改清单（对齐 `01`） |
| 8 | 集成分支就绪 | 在 `integration` 内 `git branch --show-current` | `integration/p1.4-parallel` |
| 9 | 每日集成已开始 | `06-每日集成记录.md` 有当日条目 | 至少一条「合并/回归/结论」记录 |
| 10 | 工作树根正确 | 各树 `git rev-parse --show-toplevel` | 输出的是该树自身根目录，不是上一层仓库 |
| 11 | 简报文件真的在 | 各树 `Test-Path .\AGENTS.md` | 五棵树全部为 `True`（不入库，不会自动同步） |
| 12 | 真实模型开关已关 | `Test-Path Env:CAD_PARALLEL_REAL_MODEL` | `False` 或空值；有值必须先清掉 |

## 五、已确认的现状事实（不要重复论证）

- A9 的真实自相交发生在第 1 段与第 6 段 Bezier，不是采样误差。
- A9 的 `junction_constraints` 为空，缺失环节已定位，证据见 `P1.4-A9控制点级自相交与junction_constraints缺失链路诊断报告.md`。
- S1 的确定性路由已修复，具备进入真实模型规划入口的条件。
- H3.3/H3.4 的多轮来源继承与规划传递已实现；H3-R3 候选上下文传递已完成。
- 现阶段不应继续大规模改基础设施；四条主线只在各自所有权范围内推进。

## 六、环境注意（踩到会浪费一整天）

1. **依赖用树外共享 venv，不要每棵树各装一遍**：全局 Python 3.13 缺 `fastapi`，但四棵树各自建 venv 会重复下载几百 MB。
   - 路径：`_parallel_setup_20261108\.venv`（与 2026-11-08 基线同名，便于归档）。
   - 每个终端启动前先激活同一环境：`& ..\..\_parallel_setup_20261108\.venv\Scripts\Activate.ps1`，并验证 `python -c "import fastapi; print(fastapi.__version__)"` 有输出。
   - **共享的只有 Python 依赖**。测试数据目录、临时目录、运行日志、端口一律各线独立，不许共用。
2. **`backend/wheelhouse/` 不能用**：里面是 linux/aarch64 轮子（`pydantic_core`、`websockets` 均为 manylinux aarch64），Windows 上装不上，不要拿它当离线源。
3. **`backend/.git` 是残留仓库**：主工作树里存在一个无任何提交的 `backend/.git`。在该目录内跑 `git status` 会得到「no commits yet」的假象。**所有 git 命令只在工作树根执行**，不要 `cd backend` 后再操作 git。
4. **历史评测产物未入库**：`backend/evaluations/reports/`（约 645MB、1 万余文件）刻意不入库，只存在于主工作树，供 D 只读引用；不要试图 `git add` 它们。
5. **前端不在本轮范围**：工作树里的 `xikao1_-app/` 是 gitlink，checkout 后是空目录。Flutter 与 FastAPI 的联调结论以 C 的 HTTP 层证据为准。
6. **不要 `git add -A`**：每个提交都用显式路径，或 `git add -u` + 明确的新文件清单。
7. **真实模型开关必须先清掉**：每个终端开跑前执行 `Remove-Item Env:CAD_PARALLEL_REAL_MODEL -ErrorAction SilentlyContinue`，否则一旦跑到评测入口就会产生真实计费调用。第一阶段零费用是硬约束。
8. **端口不共用**：A、B、总控不启动服务；C 用 8011、D 用 8012，避开可能被占用的 8000。
9. **`AGENTS.md` 不入库，不会随工作树同步**：五份简报是本地文件，被 `.gitignore` 排除。必须逐树 `Test-Path .\AGENTS.md` 确认存在，不能只看主工作树里有五份。

## 七、目录内容

| 文件 | 用途 |
|---|---|
| `00-四主线任务书.md` | 四个 Agent 的职责、任务、禁止项、交付物 |
| `01-文件所有权与公共接口冻结.md` | 谁能改哪些文件；五类公共接口的冻结定义与变更审批 |
| `02-研发纪律与交付模板.md` | 共同纪律、提交规范、阶段汇报模板 |
| `03-集成分支与回归流程.md` | 合并顺序、逐步回归、冲突处理、最终验收 |
| `04-真实模型调用与预算管理.md` | 唯一调用入口、账本字段、准入检查、熔断规则 |
| `05-考核指标口径.md` | 三个结果指标的计算口径与基线记录要求 |
| `06-每日集成记录.md` | 每日集成日志模板与当前记录 |

## 八、附录：五个会话的开工指令（可直接粘贴）

### A

> 你是 Agent A（自然语言与 CAD 规划）。工作树 `D:\xikao\cad-worktrees\nlp-planning`，分支 `parallel/nlp-planning`。先读工作树根的 `AGENTS.md`，再读 `backend/evaluations/parallel/` 下的 `README.md`、`00`、`01`、`02`。本轮只做第一阶段只读诊断：定位 A9 的 `junction_constraints` 第一次消失的位置（提示词 / 模型输出 / 解析 / 校验 / 落库），给出的每条结论都要带源码位置（文件:行）与原始请求/响应片段，写进 `backend/evaluations/Parallel-A-NLP-CAD规划报告.md`。不要修改 `backend/app` 任何文件，不要调用真实模型。

### B

> 你是 Agent B（CAD 几何与算法）。工作树 `D:\xikao\cad-worktrees\geometry`，分支 `parallel/geometry`。先读工作树根的 `AGENTS.md`，再读 `backend/evaluations/parallel/` 下的 `README.md`、`00`、`01`、`02`。本轮只做第一阶段只读诊断：复算 A9 第 1 段与第 6 段 Bezier 的交点，给出参数区间、交点坐标、采样误差上界，并判定回穿成因（控制点越界 / 切线反向 / 闭合端点约束缺失），结论必须能一键复现，写进 `backend/evaluations/Parallel-B-CAD几何算法报告.md`。不要修改 `backend/app` 任何文件，不要改冻结几何。

### C

> 你是 Agent C（Agent 架构与产品链路）。工作树 `D:\xikao\cad-worktrees\orchestration`，分支 `parallel/orchestration`。先读工作树根的 `AGENTS.md`，再读 `backend/evaluations/parallel/` 下的 `README.md`、`00`、`01`、`02`。本轮只做第一阶段只读验证：用隔离测试数据跑通「生成候选 → 正式保存 → 第二轮自然语言编辑」两轮链路，保存候选 id、来源 id、落库版本号与完整调用链，写进 `backend/evaluations/Parallel-C-Agent生产链路报告.md`。不要修改 `backend/app` 任何生产代码。

### D

> 你是 Agent D（测试、评测与质量保障）。工作树 `D:\xikao\cad-worktrees\evaluation`，分支 `parallel/evaluation`。先读工作树根的 `AGENTS.md`，再读 `backend/evaluations/parallel/` 下的 `README.md`、`00`、`04`、`05`。本轮只做第一阶段**只读审计**：盘点现有评测工具链（`run_cad_construction_benchmark.py`、`run_extended_deepseek_benchmark.py`、`run_extended_rule_benchmark.py` 与 `backend/evaluations/` 顶层资产），核对冻结案例 A9/S1/M1 的输入文件是否完整一致、账本字段（`04` 第二节）还缺什么、Mock 路径能否在不写文件的前提下跑通，产出「现有能力 / 缺口 / 第二阶段该建什么」三张清单，写进 `backend/evaluations/Parallel-D-Evaluation质量保障报告.md`。**不要新建 `bench/` 目录、不要创建账本文件、不要修改 `backend/app`、不要调用真实 DeepSeek。**

### 总控

> 你是总控。工作树 `D:\xikao\cad-worktrees\integration`，分支 `integration/p1.4-parallel`。先读工作树根的 `AGENTS.md`，再读 `backend/evaluations/parallel/03-集成分支与回归流程.md`。当前阶段只做两件事：盯四条线的第一阶段证据是否达标（`02` 第八节），以及维护 `06-每日集成记录.md`。没有你的批准，任何线不得进入第二阶段；最终合入目标是 `cad`，`main` 保持独立。
