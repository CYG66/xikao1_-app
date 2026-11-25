# 控制点曲线的来源与候选交付衔接

## 定位结果

历史C1已经保存了正确四控制点的Bezier计划，执行为原生spline（degree=控制点数-1、隐式夹持节点），但来源验收不识别控制点，导致coverage unknown/review_required。

历史C2的原三次周期样条曾因自相交失败；后续四次周期样条保留了全部五个源控制点，能通过原执行器，但仍因来源覆盖不足成为草稿。原文没有指定次数，不能把测试中“必须三次”的附加要求当作用户要求。本轮不自动改次数，不修改任何控制点，不为案例增加生成器。

## 改动

在cad_coordinate_requirements.py增加只读verify_control_point_curve，接入cad_construction_interpreter.py现有独立来源验收汇总。核对：

- 来源中唯一控制点序列及其顺序、明确坐标单位、可选明确次数、单曲线数量、闭合与平滑要求。
- 实际执行后的原生非有理曲线control_points（含Z不得偏离二维）、degree、closed/periodic；不依赖模型标签、断言或预览采样判断通过。
- Bezier以控制点数-1次数及隐式夹持节点证明基函数关系；不将周期B-spline冒充Bezier。
- 周期样条以隐式均匀周期节点的C^(degree-1)连续性证明接缝条件；平滑要求不允许一般一次折线通过。

只在要求文本全部被支持语法消费、实际曲线表示可确定且测量全通过时给出完整覆盖证据。未知附加要求、混合单位歧义、多个控制点块、其他表示、自定义节点/权重、fit_points/vertices预览覆盖仍不声明完整覆盖。既有自相交、可行性、闭合、约束及候选权限检查保持不变。

源坐标不擅自改作拟合点，不索要已经由控制点和单位确定的外包尺寸；缺单位仍在模型调用前澄清。没有新增生产控制点、图形生成器或公共模型输入字段。

## 测试与重放

测试环境Conda test / Python3.11.18。新增test_control_point_source_handoff.py以及来源标明的recorded_control_point_curves.json历史计划夹具。

```powershell
python -m pytest tests/test_control_point_source_handoff.py tests/test_single_primitive_source_handoff.py tests/test_cad_pipeline_handoff.py tests/test_template_acceptance_handoff.py tests/test_cad_construction_interpreter.py tests/test_cad_source_acceptance.py tests/test_cad_requirement_contract.py tests/test_cad_construction_commit.py tests/test_cad_construction.py tests/test_cad_template_plan.py tests/test_candidate_visibility_gate.py -q
```

结果243 passed，19.82秒。随后补充毫米/厘米换算及原自相交计划继续拒绝的测试，单独运行新文件：21 passed，1.41秒。未声称全仓库测试或70条真实模型评测通过。

负例覆盖：控制点改动、顺序反转、次数错误、额外图元、错误闭合/周期属性、非零Z、忽略附加需求、自定义权重/节点及预览覆盖、明确次数与实际不符、缺单位。保留原三次C2计划的drawing_infeasible拒绝，未关闭自相交检查。

历史计划离线交付：

`C:\Users\29924\Codes\cad-eval-20261117\curve_source_replay.py`

结果保存于同目录curve-source-replay/summary.json，各案例有独立projects.json：C1/C2均来源验收通过并保存原生spline候选及测量证据。使用历史保存计划与原始单位补充，真实模型调用0次，没有重写原70条基线。C2重放的是历史修复后的degree4计划，不冒充其degree3首轮成功。

## 尚未证明

未重跑实时模型/完整App，不能据离线重放上调全量成功率。任意文字曲线、多个曲线混合、显式非默认节点/权重、椭圆全轴/半轴表达等仍需继续核对。未覆盖要求保持partial/待复核。

改前文件在C:\Users\29924\Codes\cad-eval-20261117\curve-before；不推送、不合并。
