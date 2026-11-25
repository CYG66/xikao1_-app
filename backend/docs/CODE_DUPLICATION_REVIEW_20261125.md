# 当前源码全读审查：第一轮重复能力核对

本轮暂停功能开发，仅做代码审查、结构扫描和只读辅助函数诊断。生产Python源码SHA256前后完全一致，没有合并、删除、新增生产能力，没有模型调用或GitHub上传。

**范围说明：已完成全量结构扫描和下面核心链路的人工核对，尚未逐行深读全部源码，不能声称“完全了解项目”。下一项功能实现的最终决定暂缓，先完成能力与调用证据地图。**

## 覆盖与证据

- app有149个Python文件、63,602行、1,717个函数/异步函数定义（含方法和嵌套函数，不是1,717项独立能力）。
- app/scripts/tools/evaluations/tests共460个Python文件读取全文、AST解析，记录摘要、导入、定义、行号及函数内静态调用表达式；另扫描根目录11个Python入口。静态调用不是已执行调用，无法据此宣布动态入口无用。
- 机器清单`.local-dev/code-capability-audit-20261125/inventory.json`、`root-entrypoints.json`、`exact-body-duplicates.json`；只读差分证据`diagnostics.json`。模块索引见`CODE_MODULE_INDEX_20261125.md`，索引不代表人工逐行阅读完成。
- 人工重点核对主HTTP/编排、CAD构造/解释、编辑规则/模型解释/意图/目标、编辑计划/预览/断言/门禁、共享测量/验收、生成与步骤恢复、原生约束worker、目录/记忆和旧合并记录。其他模块仍需按索引继续深读；本轮不是安全审计或整个项目所有语言配置文件的逐行审计。
- 历史报告只作线索，当前代码重新核对；不把历史重复项自动算成当前重复项，也不把备份、测试fixture、独立oracle算作重复生产能力。

## 1. 已确认的重复实现

### R1：内置求解器与原生worker的几何基础函数

`cad_constraint_solver.py`和`native_constraint_worker.py`各自维护`_points`、`_size`、`_translate`、`_rotate`。其中前三个较长函数组（_points/_size/_rotate）的去文档AST函数体一致；_translate人工核对也相同，因扫描长度阈值未进入机器长函数组。

路径：内置求解/原生约束请求各调用本模块辅助函数；主求解器通过`python -m app.native_constraint_worker`启动独立进程。两条后端是真实不同的求解执行环境，不是可删除其中一条的重复求解器。

只读诊断对同一椭圆及0.37弧度执行两份_rotate，结果相同。这是一条差分输入，不代替全输入等价证明；AST一致则提供直接代码重复证据。

可评估提取无服务器依赖的纯几何辅助模块，由两后端导入；必须保留worker进程隔离、协议、单位和宿主独立残差验收。优先级中，当前不是名称绑定失败的根因。

### R2：数据库连接辅助样板

`agent_plan_sqlite_store._connect`与`database._connect`；`agent_plan_sqlite_store._connection`与`database._session`函数体一致。两套存储不是同一业务仓库，不能合并数据库或生命周期。

可以评估共用连接配置/关闭样板，优先级低；需保留事务、锁和文件路径所属关系。

### R3：正整数ID转换的小辅助函数

`agent_skills.as_id`、`cad_edit_gate._positive_id`、`drawing_commands._entity_id`、`geometry_catalog._geometry_id`函数体一致。它们是输入规范化重复，不是四套CAD执行器。

可考虑共用基础校验，需固定bool/字符串/小数/非法值的原合同。优先级低，不应为减少几行重复而大范围改调用。

## 2. 能力重叠，但不能直接合并

### O1：坐标、边界与变换的多份实现

涉及`incremental_cad`、`cad_target_resolver`、`geometry_catalog`、`cad_construction`、`drawing_store`、`logical_topology`、`agent_skills`与两个约束后端。

例如`cad_target_resolver._points/_bounds`与`incremental_cad._points/_bounds`遍历同类字段，但异常处理不同。只读反例中坏坐标被目标边界函数跳过，结果为(1,1,1,1)；编辑边界函数抛ValueError。不是可无条件替换的等价实现。

还必须区分精确圆弧/椭圆边界、选择器保守外包框、采样预览边界；旋转有弧度/角度、单图元中心/明确选区中心之分。先建立输入、精度、单位、异常与修改范围矩阵，再决定底层共享，禁止统一成“万能bounds/rotate”。

### O2：规则编辑和模型编辑的目标表达重叠、契约漂移

现有链路已经有：`incremental_cad.parse_incremental_edit`、`cad_edit_interpreter.StructuredCadTarget/_legacy_target`、`cad_edit_intent._target`、`cad_target_resolver.resolve_logical_object_target`、`agent_service._apply_cad_edit_commands`。

两种解释入口最终共用既有编辑执行器，**不是两套独立编辑引擎**。但目标表达不一致：规则链已能携带logical_object_selector的label/circle/rectangle；模型Target类型仍主要限制场地/房间，logical_object要求position，_legacy_target也不传名称。这是已有能力入口之间的契约不同步。

当前F2“支撑矩形”不是缺平移器或缺对象ID绑定。图中已有唯一confirmed标签，平移和唯一标签解析也已存在，缺的是原文名称通往现有目标字段的衔接。下一步不能再造名称解析器/目标仓库，应先核对并统一这一契约的完整调用范围。

### O3：构造引用与候选引用都叫“对象”，但不是同一个域

构造解释器已有output_ref、semantic.object_id、assembly及label别名归一；候选编辑使用project_id/variant_id/object_id/geometry_refs；会话记忆还管理project/variant/drawing/action指代。通用概念重叠，但作用域和生命周期不同，不能把构造别名表直接作为跨版本候选引用表。

可共享的只能先是明确的规范化/解析数据合同，不能去掉候选版本归属校验或用会话focus覆盖当前明确目标。

### O4：多处来源文本消费和尺寸验收

圆组、单原语、主体验收、布局、语义验收分别解析部分相同词汇与尺寸。不同入口承担匿名绑定、完整覆盖、来源事实ID、关系和对象身份等增量，不能因都检查半径就删除一个。

当前已存在共享几何事实、单次构造证据缓存、单位与预览意图分区；应先核对哪些入口未复用，不新增另一套语义事实/测量引擎。当前静态重叠不等于本轮已证明同一请求重复实测，性能重复需调用追踪另证。

## 3. 旧报告中已整合的项：不得重新合并

- `cad_assertions._fingerprint`、`cad_edit_preview._fingerprint`已委托同一个`cad_canonical_json.canonical_json_hash`。薄包装不是仍有两套SHA算法。
- `cad_structure_contract._points/_corners/_frame`已委托共享`cad_geometry_measurements`，不再是旧报告描述的独立矩形重测算法。
- `ConstructionEvidence`已在一次构造内按函数和完整输入摘要复用测量，几何改动重新计算，异常不缓存。看到多个上层入口不等于同一输入重复计算。
- `cad_plan_verifier`把已计算preflight传给`build_cad_machine_assertions`，后者`preflight or ...`复用；不能只数函数名出现次数宣布它重复预检。
- `length_factors`已成为多数来源单位表的公共入口。旧“27文件41张表”不能照抄成当前数量。

## 4. 明确不是重复，应保留的边界

- `cad_generation_recovery`管理模型规划的有界重试与尝试证据；`cad_plan_recovery`针对Agent步骤适配、调用既有确定性断言修复。输入、预算、错误域和输出不同，不能仅因都叫recovery合并。
- `cad_selected_operations`复用incremental_cad的变换函数，承担选区复制/阵列/镜像/偏移策略，不是完整重复编辑器。
- 构造执行器负责生成实际几何；来源验收必须独立核对，不能为“去重”改成相信模型/计划自身断言。
- geometry_diff、候选证据、语义指纹与构造去重采用不同ID/数值/NaN/Unicode规范；哈希同用SHA256不等于协议相同。
- task/run/plan/project及持久化事件各有生命周期，不因字段相似合并存储。

## 初步排序，不是实施决定

首先继续全读并完成能力地图：每项能力标明入口、输入合同、执行器、测量/验收、持久化、已有测试、当前未接入点；尤其核对所有目标类型与规则/模型适配器。之后才决定整合任务。

当前较值得优先研究的是目标合同漂移与已有能力接线，而非重复的六行ID函数。边界/变换辅助和原生/内置公共函数可进入后续整合候选；当前没有批准或实施任何合并。全文人工深读与运行时重复调用分析尚未完成，不以本报告冒充最终全面评定。
