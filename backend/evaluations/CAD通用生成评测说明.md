# 通用自然语言 2D CAD 生成评测

## 目的

该评测用于比较不同云端大模型把复杂中文需求转换为
`cad.construction-plan.v1` 的能力。评测只执行隔离的内存试构造：

- 不创建项目；
- 不保存候选方案；
- 不修改现有图纸；
- 不恢复或执行待处理任务；
- 报告不包含 API Key。

它评估的是“自然语言 -> 结构化构造计划 -> 确定性试执行”链路，
不是小车路径执行测试。

## 评测集

默认评测集：`evaluations/cad_construction_model_benchmark.json`

当前包含 L 形轮廓、仓库通道、停车位阵列、圆形广场、阶梯基础和
不规则边界等复杂请求。每个用例声明实体数量范围、逻辑对象数量、
必需图元类型和可行性要求。

## 运行方式

在 PowerShell 中进入后端目录：

```powershell
cd D:\xikao\xikao1_-app\backend
```

评测本机已配置的全部云端供应商：

```powershell
python .\run_cad_construction_benchmark.py `
  --output .\evaluations\reports\cad-construction-report.json
```

只评测指定供应商：

```powershell
python .\run_cad_construction_benchmark.py `
  --providers qwen glm `
  --output .\evaluations\reports\qwen-glm.json
```

使用自定义评测集：

```powershell
python .\run_cad_construction_benchmark.py `
  --providers openai `
  --corpus .\evaluations\my-construction-cases.json `
  --output .\evaluations\reports\openai.json
```

没有配置 API Key 的供应商会被明确拒绝，不会静默改用其他模型。

## 核心指标

- `pass_rate`：状态、图元数量、类型、逻辑对象和可行性全部满足用例要求。
- `ready_rate`：模型成功给出可试执行的结构化构造计划。
- `schema_valid_rate`：实际返回了通过 Schema 校验的计划。
- `trial_success_rate`：计划实际通过确定性构造器试执行。
- `clarification_rate`：模型认为信息不足并要求澄清的比例。
- `structured_retry_rate`：首次返回无法解析的 JSON 后，使用唯一一次纠错请求的比例。
- `deterministic_repair_count`：不改变几何和尺寸的对象引用确定性修复次数。
- `average_latency_ms`：模型调用与试执行的平均耗时。

`pass_rate` 是主要比较指标；不能只看模型是否返回 JSON。

## 使用边界

当前评测不会把实验链路接入生产聊天，也不会代替 CAD 几何校验。
模型输出必须继续经过严格 Schema、预算、几何可行性和断言检查。
达到稳定阈值后，再选择是否把通用生成链路接到候选方案保存流程。

复杂构造计划使用独立的输出上限，默认 `4096 tokens`，可以通过
`XLINE_AGENT_CONSTRUCTION_MAX_TOKENS` 调整；普通意图路由仍使用较小上限。
格式纠错最多执行一次，网络错误、语义错误和几何断言失败不会无限重试。
