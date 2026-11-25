# 顶点与阵列来源覆盖、重复断言绑定及完整覆盖边界

本轮只修改 `C:\Users\29924\Codes\codex-cad-agent\backend`，使用 Conda test / Python 3.11。
未修改原后端、原语料或历史几何计划，未增加生成器，未调用真实模型。

## 修复结果

| 问题 | 根因 | 本轮处理与边界 |
| --- | --- | --- |
| C4：明确三角形顶点仍待复核 | 现有曲线测量消费控制点，未覆盖闭合直线轮廓的顶点原文 | 新增通用顶点路径只读测量，核对坐标单位、顶点数量与顺序、闭合直边、简单非退化轮廓。历史计划通过并保存来源证据。 |
| C8：阵列补参导致完整覆盖失败 | 原文与补参中的“3行4列”“各矩形”“相邻中心行距”没有被完整消费 | 接到已有矩形阵列数量、单元尺寸和中心间距验证；所有重述行列数必须一致，冲突标量不再被最后一个值覆盖。历史计划通过并保存证据。 |
| A10、C6：已有计划重放时 Schema 错误 | bind_outline_requirements 再次追加 required-outline-count、required-outline-closure，产生重复 assertion_id | 复用语义等价的断言，正确区分全图数量和局部数量；标识碰撞但约束不同则保留原约束并为新增断言分配唯一标识。重复绑定保持幂等。两案可进入实际验收，但完整来源仍待复核。 |
| Bezier 需求被误报完整覆盖 | 只检查段数和连续性，就把整段原文标为 complete，甚至掩盖额外圆、指定经过点等要求 | 保留已有局部测量，取消这项无条件完整覆盖提升。尚未被来源测量器完整消费的曲线原文保持待复核。 |

顶点测量 `cad_vertex_acceptance.verify_vertex_path` 不构造坐标、不读取模型标签作为证明，支持三角形及明确给定顶点的通用闭合多边形/折线。闭合路径允许循环调整起点、反向遍历；不允许平移、旋转或改动原始坐标来伪装为匹配。位置、等边、圆角、面积、额外对象等未支持要求保持 partial。坐标单位不明/冲突、源顶点退化或自交、顶点数冲突均不声明完整覆盖。

阵列仍使用原有 explicit_composition / validate_explicit_composition，不改变阵列生成、布局或尺寸。仅在行距/列距之前消费“相邻中心”，不把未知位置语句当作已验证。相同字段出现不同数值保持 partial；本轮未实现复杂修订语义的自动消解。

轮廓绑定的防回退测试验证：原 equals=2 与新增 equals=1 冲突时，原断言仍保留，执行仍失败；不能通过重命名或覆盖断言来制造通过。既有 radial_pattern 绑定仍以用户明确的瓣数/星角数为依据。

## 验证

新增测试：

- `tests/test_vertex_array_source_handoff.py`：29 项，包括 C4/C8 的解释与持久化、错误顶点/图元/闭合/曲边、未消费附加要求、单位/数量冲突、阵列重述冲突，以及 Bezier 错误提升的反例。
- `tests/test_outline_binding_handoff.py`：5 项，包括 A10/C6 历史计划、序列化默认字段下的幂等性、标识碰撞时保留原约束，以及局部/全图数量作用域。

修改前选择性复现 C4/C8 与 Bezier 问题：6 failed；轮廓绑定问题：4 failed / 1 passed。
修改后 `dev.ps1 test`：359 passed，18.87 秒。原选择集 315 项、新增 34 项及纳入入口的验收边界/曲线质量 10 项全部通过。

测试报告：`.local-dev/test-1c6lqsfh/result.json`，同目录包含 `pytest.log`、`junit.xml`。

## 固定来源、固定计划的生产链路对照

通过新脚本 `evaluations/replay_fixed_plans.py` 调用当前后端解释器，默认保留规则优先、结构化计划后备的生产顺序。模板请求可以由既有规则处理，其余请求通过回调提供未修改的历史计划。没有启动旧后端或运行指向旧后端的历史启动脚本。

输入为只读的 `C:\Users\29924\Codes\cad-audit-20261118\frozen-inputs.json`，SHA256 为 `fe8f23282efca8c146c5c8231c3c4b438820b4bed062e0229ca2d9a588b85cf4`。

| 45 条固定历史生成案例 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 独立验收 passed | 10 | 12 |
| ready / review_required | 30 | 30 |
| invalid | 5 | 3 |

仅有四条状态变化：C4、C8 从待复核变为通过；A10、C6 从 invalid 变为可执行但待复核。其余状态未变。A10/C6 没有计为验收通过。

对照入口 `evaluations/summarize_fixed_replay.py` 会先核对输入哈希、执行链路及案例集合，然后比较已有记录，不重新执行或调用模型。

最终文件：

- 修改前：`.local-dev/audit-qmr9duzz/summary.json`。
- 修改后：`.local-dev/audit-cb4ae98t/summary.json`。
- 对照：`.local-dev/audit-cb4ae98t/comparison.json`。
- 剩余 33 条问题：`.local-dev/audit-cb4ae98t/failure-details.json`。逐项保留原文、状态、实际错误、来源覆盖状态、各测量器检查/未知要求及完整记录路径。

剩余 3 条明确执行失败的原错误继续保留：C17 单元没有通过完整公共边连通；C27 等轴投影未达到三组各四条平行棱线；C33 实际尺寸为 2×5，要求为 2×4。没有放松这些测量标准。

另有 30 条待复核，其统一阻塞项是来源未获得完整覆盖证据。报告中保留已有的局部几何测量，不能由此推断图形已经满足全部自然语言要求；各条未消费语句还需继续核查。这些数据仅覆盖 45 条生成案例，不含 25 条编辑案例，不能作为完整 70 条语料的实时模型通过率。

## 可重复运行

在新后端目录中执行：

```powershell
.\dev.ps1 test
& 'C:\Users\29924\Softwares\miniconda\envs\test\python.exe' -m evaluations.replay_fixed_plans --inputs 'C:\Users\29924\Codes\cad-audit-20261118\frozen-inputs.json'
```

回放入口自动建立新后端内部的独立环境及输出目录；默认不会强制绕过规则链路。`--force-structured` 仅供单独诊断，不能与默认链路结果混算。
