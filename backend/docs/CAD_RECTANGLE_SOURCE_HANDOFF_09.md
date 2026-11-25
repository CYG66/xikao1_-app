# 单矩形来源验收与圆角语义分流

本轮仅修改独立后端 `C:\Users\29924\Codes\codex-cad-agent\backend`。
没有修改原后端，没有增加图形生成器，没有替换历史模型计划或降低验收标准。

## A2：测量通过但来源覆盖不完整

原始需求为“新建图纸，画一个宽5米高3米的矩形”，历史补参为“宽度5米，高度3米，单位米。”。
原有标量验收能验证尺寸，但不能单独证明完整原文已覆盖，也不能仅凭包围盒证明矩形身份。因此历史计划原本返回 `ready / review_required`。

新增只读的 `cad_rectangle_acceptance.verify_single_rectangle`，复用实际执行输出和现有 `_points`、`_frame` 测量工具：

- 只覆盖明确的单个矩形/长方形及宽、高、单位、闭合描述；未消费的附加要求保持 partial。
- 同一来源内冲突尺寸、非正尺寸、缺失尺寸均不声明完整覆盖。
- 独立检查实际图元数量、闭合性、轮廓有效性、直边及矩形形状，再测量宽高；模型标签和模型断言不作为证明。
- 尺寸误差沿用现有 0.5mm 容差。错尺寸、多图元、开口、交叉、三角形、梯形、曲边等均拒绝。
- 接入解释器已有 source_acceptance 汇总，保存时将测量证据写入 construction_record.rectangle_acceptance 对应的来源验收记录，实际路径为 `construction_record.source_acceptance.rectangle_acceptance`。

原历史计划未经修改，经解释器、验收和候选保存后为 `ready / passed`，证据在保存后的候选中保留。没有要求增加模型断言来替代实际测量。

支持范围保持保守：位置、旋转、圆角、面积、额外对象等原文未被该测量器完整消费时，不能由此获得完整覆盖。

## C20：圆角描述被误读为四角放圆

原始需求为“画一个圆角矩形，宽3米高2米，圆角半径0.5米”，补参含“四角圆角半径0.5米，闭合”。
原组合正则允许“角”和“圆”之间出现任意文字，导致这段补参被判成 `corner_placement`，继而报“圆必须与矩形四个顶点一一对应，不能重叠或漏角”。

现在要求明确的放置/绘制动作和独立圆图元名词，且同一分句不能是否定放置指令。圆角、圆弧过渡、不要放圆等均不再走该组合验收；原先“四角各放一个圆”的正例仍由现有数量、尺寸及角点对应测量验证。

历史 C20 计划实际生成一个直角矩形和四个完整圆，圆心位于矩形内部。这不能证明闭合圆角轮廓。修复后的离线回放为 `ready / review_required`，没有将其计为通过。现有系统允许保存待复核草稿；回归测试验证该草稿不能成为 accepted 候选，也不会出现在 accepted_project_view 中。没有改动草稿策略。

本轮消除了错误契约和错误诊断；圆角实际几何的独立验收仍缺失，需后续复用通用轮廓/圆弧/相切测量能力处理，不能把四个完整圆认作已完成圆角。

## 验证与复现

固定历史来源及计划：`tests/fixtures/recorded_rectangle_handoff.json`，含原计划来源路径。
原始只读来源：`C:\Users\29924\Codes\cad-audit-20261118\frozen-inputs.json`。

新增回归文件 `tests/test_rectangle_source_handoff.py`，共 42 项，覆盖历史候选保存、来源消费、错误几何、圆角分流、否定指令、既有四角放圆，以及待复核草稿的可用性边界。

改动前先复现：选定的 7 项已有问题测试为 5 failed / 2 passed，包括 A2 待复核及错误组合识别。
修改后通过新环境入口执行 `dev.ps1 test`：315 passed，16.02秒。其中原有选择集 273 项及新增 42 项全部通过。

测试结果：`.local-dev/test-keor05zi/result.json`；逐项结果与失败诊断分别保存在同目录 `junit.xml`、`pytest.log`。调试期间的失败记录保留在 `.local-dev/test-h6txq13i/`，最终结果以上述通过记录为准。

历史计划回放入口：`evaluations/replay_rectangle_handoff.py`，需在 `scripts.local_dev.isolated_environment` 提供的隔离子进程环境中以模块形式运行。
本轮回放报告：`.local-dev/check-fq105p2f/rectangle-handoff/summary.json`；同目录有 A2、C20 完整记录及 A2 已保存项目。回放脚本只提交通过验收的结果，因此该报告中 C20 的 saved 为 false，不代表系统禁止保存待复核草稿。

上述均为离线验证，模型调用 0 次，不是新的 70 条真实语料通过率。
