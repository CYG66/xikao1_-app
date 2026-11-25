# 独立 CAD 后端本地开发环境

当前研发目录：`C:\Users\29924\Codes\codex-cad-agent\backend`。
原 `C:\Users\29924\Codes\xikao\backend` 未获授权不得修改。本说明中的入口根据自身文件位置确定后端根目录，不依赖终端当前目录。

## Python 和依赖

使用 Miniconda 独立环境 `test`，Python 3.11。
默认解释器为 `C:\Users\29924\Softwares\miniconda\envs\test\python.exe`。
运行时依赖见 `requirements.txt`，开发依赖见 `requirements-dev.txt`，无需使用系统 Python 或手动激活环境。

在新后端目录的 PowerShell 中运行：

```powershell
.\dev.ps1 setup    # 环境缺失时创建 test，安装依赖，执行检查
.\dev.ps1 check    # 依赖一致性、应用导入、HTTP 生命周期、health、OpenAPI
.\dev.ps1 test     # 当前选择的 CAD 离线回归集
.\dev.ps1 serve    # 前台启动本地虚拟后端，默认 127.0.0.1:8000
```

也可以从其他目录通过绝对路径调用 `dev.ps1`。
解释器位置不同时指定 `-PythonPath '完整的 python.exe 路径'`；端口冲突时指定 `-Port 8001`。
服务在前台运行，使用 Ctrl+C 停止；不会自动终止已有端口上的其他进程。

## 模型配置

默认启动使用 `local` 模式。`setup`、`check`、`test` 不使用真实 API 密钥。
需要真实自然语言模型时，在当前 PowerShell 会话设置 `DEEPSEEK_API_KEY` 环境变量，然后运行：

```powershell
.\dev.ps1 serve -Live
```

`-Live` 要求环境变量中有密钥，不从旧目录、复制来的凭据文件或用户全局配置自动读取。入口不将密钥写入文件。
基础模型、进阶模型和 CAD 规划模型统一设为 `deepseek-flash`。
本次基础配置只验证本地运行，没有发出真实模型请求。

## 数据和报告

所有通过新入口启动的进程均使用本后端 `.local-dev/` 下的独立配置和运行数据：

- `server/`：本地服务持久数据，包括 CAD、数据库、任务、会话、项目、版本和执行计划。
- `check-*/`：每次检查的独立数据。
- `test-*/`：每次回归的独立数据及 `pytest.log`、`junit.xml`、`result.json`。

HOME、USERPROFILE、临时目录及各存储路径只在子进程环境中隔离，不修改系统或当前终端的全局设置。禁用设备发现，使用 `virtual_sim`，仅监听本机。`.local-dev/` 已加入 Git 忽略规则。

回归测试失败时，`pytest.log` 保留失败断言和简短调用栈，`junit.xml` 保留逐项测试结果，`result.json` 记录解释器、目录、命令、起止时间和退出码。该回归集不是完整测试套件，也不代表 70 条真实语料的端到端通过率。

复制来的 `run_ai_test_backend.ps1` 和历史手工评测脚本保留原样。本地研发统一使用上述新入口；历史脚本在核对解释器、路径、凭据及数据隔离之前不要直接运行。
原生 CAD/DWG 等可选依赖尚未纳入本次基础安装，后续按实际调用需求处理。
