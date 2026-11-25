# 调用与交付流程整理：第一批修复

修改范围：agent_service.py、agent_http_service.py、cad_template_plan.py；新增 tests/test_cad_pipeline_handoff.py。不新增生成器、模型协议或几何原语，不修改原始70条语料与通过率结果。

1. 非模板项目的确认操作不再进入旧形状生成分支，包括已有待复核草稿的项目；继续走正式构造及来源验收。此举避免原生circle被确认流程重建为64点polyline。待复核不因此升级为通过，正式流程仍可能重新规划。
2. 已有模板的length_m/width_m输入归一为IR二维轴尺寸，兼容旧摘要把width同时复制到height的情况；明显不一致的三轴输入报告冲突。来源项目不被原地修改。用户另有方向要求仍由既有旋转/布局处理。
3. 流式聊天在实际迭代服务生成器期间绑定与同步入口相同的execution_context，并在完成、异常、关闭时恢复，支持后续待确认任务保存原始上下文。

验证环境：Conda test / Python 3.11.18；独立USERPROFILE、未提供真实模型密钥。新增8项测试全部通过。

```powershell
python -m pytest tests/test_cad_pipeline_handoff.py tests/test_cad_template_plan.py tests/test_standard_template_geometry.py tests/test_candidate_visibility_gate.py tests/test_task_store.py -q
```

56 passed，1 failed：test_template_chat_and_toolbar_commit_same_project_once。修改前的代码在内存中重放同项测试也失败；当前原因是首次正式构造候选因来源覆盖不足成为草稿，后续模板确认没有复用而新存版本。该项尚未解决，未修改断言或将草稿放行。

```powershell
python -m pytest tests/test_conversation_memory.py -k stream -q
python -m pytest tests/test_cad_construction_commit.py tests/test_cad_source_acceptance.py tests/test_cad_requirement_contract.py tests/test_cad_plan_component_repair.py -q
```

前组2 passed、1 failed（上游流式异常后未回退模板）；后组48 passed。两组及上组共106 passed、2 failed。这是相关回归结果，不是70条自然语言通过率。未重新付费运行全量语料。

未完成：统一模板/通用构造的来源覆盖证明与确认保存幂等性；同步/流式业务异常回退一致性；真实B11/D4跨进程确认的完整链路复测。不能用直接改coverage=complete或解除前置版本验收来处理这些问题。

改动前文件在 C:\Users\29924\Codes\cad-eval-20261117\pipeline-before。原backend没有Git HEAD，不把当前源码冒充公开基线；本轮不推送、不合并。
