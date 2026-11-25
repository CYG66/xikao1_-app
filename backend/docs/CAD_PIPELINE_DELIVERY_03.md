# 调用与交付流程：模板验收统一及跨上下文确认修复

## 已完成

1. 注册模板首次聊天生成与项目确认共用 template_trial_acceptance。四项必要证据（断言、可行性、约束求解、对象图）及非空几何均需通过；只适用于后端模板编译器已经覆盖的请求。标明 registered_template_scope，不把通用 source_acceptance.partial 改成 complete。来源目标歧义、额外对象或其他独立检查不确定仍阻止通过。
2. 模板的已验收版本能被后续确认识别并复用。篮球场、羽毛球场、两个并排车位均通过生成后连续确认两次的测试：尺寸正确、候选ID不变、项目中仅一个版本、模型回调未调用。
3. 修正上一轮流式上下文包装器的跨Context缺陷。StreamingResponse可能在不同工作线程/Context中推进同步生成器，旧包装把token跨yield保留导致reset时报错。现在每次创建/推进/关闭生成器时独立绑定和恢复，返回事件前不保留token；新增copy_context分轮推进回归。

没有新增图形生成器，没有放宽自相交、连续性或通用来源覆盖门槛。未改变原70条基线结果。

## 流式异常回退的测试冲突

现有 test_conversation_memory.py 中一项旧测试要求上游异常后回退模板；test_candidate_visibility_gate.py::test_stream_failure_never_falls_back_to_local_template_cad 明确要求异常后失败且不回退。曾验证过回退方案，但它违反后一项约束，已撤回，未修改任何旧断言。当前保持异常时显式失败，模板通过正常模板路由处理。旧回退测试仍是已知不兼容项，不声称全仓库测试已绿。

## 测试

Conda test / Python 3.11.18，独立USERPROFILE、禁用字节码写入：

```powershell
python -m pytest tests/test_template_acceptance_handoff.py tests/test_cad_pipeline_handoff.py tests/test_cad_template_plan.py tests/test_standard_template_geometry.py tests/test_candidate_visibility_gate.py tests/test_task_store.py tests/test_cad_construction_commit.py tests/test_cad_source_acceptance.py tests/test_cad_requirement_contract.py -q
```

结果：112 passed / 0 failed，14.50秒。包含此前模板重复保存的失败测试，目前通过。此为选定回归范围，不是全仓库或70条真实模型结果。

## B11 / D4 跨进程离线重放

目录：C:\Users\29924\Codes\cad-eval-20261117\confirmation-replay-v2。

沿用历史A3/C3已存版本作为编辑输入，逐轮仍运行实际HTTP流式handler，确认请求由新进程恢复任务。仅本机loopback用于Windows asyncio内部socketpair，禁止外部socket连接；预算账本为0请求、0 tokens、0费用。没有调用真实模型，也没有用Mock伪造CAD或确认结果。

- B11通过：保存新版本、非目标保持、12实例、项目一致，待确认任务completed且含execution_context。因历史源圆为64点polyline，另用独立逐顶点对照验证3行4列、列距1500mm、行距1000mm：12实例均一一匹配；证据在B11/array-translation-proof.json。
- D4通过：保存新版本、非目标保持、6实例、每个实例的全部几何与2m/3m间距、项目一致，任务completed且含execution_context。

第一次离线尝试过强的网络屏蔽拦截了Windows asyncio的内部socketpair；随后允许loopback、继续禁止外网。第二轮实际重放暴露上一轮token跨Context错误，记录在confirmation-replay；修复后的成功记录单独保存为confirmation-replay-v2，未覆盖原始70条数据。

## 范围与后续

当前证明的是模板交付幂等性、相应编辑确认流程恢复。不能据此改写10%或历史68.6%，也不能把使用历史版本的编辑成功当成新生成端到端成功。普通图元/曲线的来源覆盖、完整语料的路由与澄清仍需继续逐项核对。没有解除未验收版本的编辑限制。

改动前文件备份在C:\Users\29924\Codes\cad-eval-20261117\delivery-before；本轮修改cad_template_plan.py、cad_construction_interpreter.py、agent_http_service.py及两个针对性测试文件。不推送、不合并。
