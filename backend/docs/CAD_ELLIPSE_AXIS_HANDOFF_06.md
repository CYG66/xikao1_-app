# 椭圆轴长表达与澄清交付衔接

## 根因及修复

A4原文“画一个长轴4米短轴2米的椭圆”已有有效尺寸，但旧parameterize_design先匹配“圆”而非“椭圆”，并把第一个数字当作圆半径；长轴/短轴又不在尺寸提取中。历史项目最终仍保留dimensions缺失状态。旧规则只支持中心+长半轴+短半轴的固定顺序。

本轮：

1. 修正形状识别优先级，保留椭圆/圆弧的具体类型，避免被通用圆别名吞掉；未增加旧形状生成器的支持枚举。
2. cad_axis_requirements.py从原文提取主轴要求，区分全轴/全长与半轴、独立单位、明确中心和旋转；整轴除以二，半轴不重复除以二，尺寸索引使用major_radius_m/minor_radius_m，不把主轴偷换成旋转后的外接框宽高。
3. 将已完整消费的单椭圆要求映射至已有add_ellipse构造原语，支持原文轴长在形状名称之前、后续完整轴长补充；未指定中心/方向时采用现有构造默认原点/零角度，不伪称这些是用户要求。
4. 独立测量执行后原生ellipse的主轴向量长度、ratio对应的短半轴、完整360度范围、平面属性、来源明确中心与主轴方向。不以模型自拟断言决定通过。未知附加对象、位置或面积不被忽略为完整覆盖。
5. 同轮全轴与半轴相互矛盾、长半轴小于短半轴、非正尺寸等先澄清，禁止通过交换轴标签或随意缩放通过。多对象要求不当作一个整体轴长契约。

修改：agent_skills.py、cad_project_candidates.py、cad_construction_interpreter.py；新增cad_axis_requirements.py与test_ellipse_axis_handoff.py。无专用图形生成器，无真实模型调用。

## 验证

Conda test / Python3.11.18、独立USERPROFILE。

```powershell
python -m pytest tests/test_ellipse_axis_handoff.py tests/test_control_point_source_handoff.py tests/test_single_primitive_source_handoff.py tests/test_cad_construction_interpreter.py tests/test_cad_source_acceptance.py tests/test_cad_requirement_contract.py tests/test_cad_construction_commit.py tests/test_cad_template_plan.py tests/test_candidate_visibility_gate.py tests/test_cad_pipeline_handoff.py tests/test_template_acceptance_handoff.py -q
```

227 passed，15.69秒。覆盖原A4、半轴、全长、混合长度单位换算、形状分类、中心/旋转、轴长翻倍、ratio错误、部分椭圆弧冒充完整椭圆、额外对象、冲突参数、补参后同项目确认保存。

额外运行test_design_requirement_followup.py时有3项失败：两个投影补参测试和一个双圆确认测试，其Mock仅返回trial_result、没有可保存plan，保存时严格计划校验失败。用本轮改前3份源码在内存中重放相同节点仍为3 failed；未修改旧测试输入或断言，也未放宽无plan的提交门槛。227项是列明范围的通过数，不声称全仓库全绿。

## 零费用生产方法验证

脚本：C:\Users\29924\Codes\cad-eval-20261117\ellipse_handoff_replay.py。

证据：同目录ellipse-handoff-replay/responses.json、projects.json。

- 直接使用原70条清单A4原文，保存原生ellipse，实际边界[-2000,-1000]至[2000,1000]mm，即4m×2m，acceptance passed。
- 从真实生产方法发出不完整“画一个椭圆”，补充全长4m/2m及单位，再确认；保持同一项目并保存通过验收的ellipse。
- 使用生产service方法及存储，模型回调禁止；不包含HTTP/App画布验证，不等同实时模型成功率。原70条基线不变。

## 仍需核对

单轴逐轮修订、部分轴长与其他约束混合的澄清、通用多对象绑定与整体/部件尺寸等仍需继续审计。当前完整覆盖只针对支持语法下的单椭圆请求，不扩大到任意含“长轴”的文本。

改前文件备份在C:\Users\29924\Codes\cad-eval-20261117\ellipse-before；不推送、不合并。
