param(
    [int]$Port = 8000,
    [string]$BindAddress = "0.0.0.0",
    [string]$DeepSeekApiKey = $env:DEEPSEEK_API_KEY,
    [switch]$KeepExisting,
    [switch]$VirtualTotalStation
)

$ErrorActionPreference = "Stop"
$backendRoot = $PSScriptRoot
$runtimeRoot = Join-Path $backendRoot ".local-ai-test"
$cadRoot = Join-Path $runtimeRoot "cad"
$credentialPath = Join-Path $runtimeRoot "deepseek-api-key.clixml"
$localDwgConverter = Join-Path $backendRoot "tools\libredwg-0.14-win64\dwg2dxf.exe"
New-Item -ItemType Directory -Force -Path $cadRoot | Out-Null

function Show-ConnectionAddresses {
    if ($BindAddress -eq "127.0.0.1") {
        Write-Host "Local API: http://127.0.0.1:$Port"
        Write-Host "Website access goes through Caddy; direct LAN access is disabled."
        return
    }
    $activeInterfaces = @(
        Get-NetConnectionProfile -ErrorAction SilentlyContinue |
            Where-Object { $_.IPv4Connectivity -ne "NoTraffic" } |
            Select-Object -ExpandProperty InterfaceIndex
    )
    $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $activeInterfaces -contains $_.InterfaceIndex -and
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.InterfaceAlias -notmatch "VMware|Loopback|本地连接"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
    foreach ($address in $addresses) {
        Write-Host "App API: http://${address}:$Port"
        Write-Host "App WebSocket: ws://${address}:$Port"
    }
    Write-Host "Local health check: http://127.0.0.1:$Port/health"
}

if ($DeepSeekApiKey) {
    ConvertTo-SecureString $DeepSeekApiKey -AsPlainText -Force |
        Export-Clixml -LiteralPath $credentialPath
}

if (Test-Path -LiteralPath $credentialPath) {
    $secureKey = Import-Clixml -LiteralPath $credentialPath
    $credential = [System.Net.NetworkCredential]::new("", $secureKey)
    $DeepSeekApiKey = $credential.Password
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.status.runtime_profile -eq "virtual_sim") {
            if ($KeepExisting) {
                Write-Host "Virtual rover backend is already running on port $Port."
                Write-Host "Keeping the existing process because -KeepExisting was supplied."
                Show-ConnectionAddresses
                exit 0
            }
            $processIds = @(
                $existing |
                    Select-Object -ExpandProperty OwningProcess -Unique |
                    Where-Object { $_ -gt 0 }
            )
            if (-not $processIds) {
                throw "Cannot identify the existing virtual backend process on port $Port."
            }
            Write-Host "Restarting the existing virtual backend to load current code."
            foreach ($processId in $processIds) {
                Stop-Process -Id $processId -Force -ErrorAction Stop
            }
            $deadline = (Get-Date).AddSeconds(5)
            do {
                Start-Sleep -Milliseconds 200
                $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            } while ($remaining -and (Get-Date) -lt $deadline)
            if ($remaining) {
                throw "The previous virtual backend did not release port $Port within 5 seconds."
            }
            $existing = $null
        }
    } catch {
        # A listener exists, but it is not this backend. Report the conflict below.
    }
    if ($existing) {
        throw "Port $Port is already in use by another process. Choose another port or stop that process first."
    }
}

$env:XLINE_RUNTIME_PROFILE = "virtual_sim"
$env:XLINE_VIRTUAL_TOTAL_STATION = if ($VirtualTotalStation) { "1" } else { "0" }
$env:XLINE_DEMO_MODE = "1"
$env:XLINE_DEVICE_ID = "dashes-local-virtual-rover"
$env:XLINE_VEHICLE_MODEL = "Dashes Virtual Rover"
$env:XLINE_SOFTWARE_VERSION = "local-ai-test"
$env:XLINE_CAD_DIR = $cadRoot
$env:DWG2DXF_BIN = if ($env:DWG2DXF_BIN) { $env:DWG2DXF_BIN } elseif (Test-Path -LiteralPath $localDwgConverter) { $localDwgConverter } else { "" }
$env:XLINE_DATABASE_PATH = Join-Path $runtimeRoot "xline-ai-test.db"
$env:XLINE_AGENT_AUDIT_STORE = Join-Path $runtimeRoot "agent-audit.jsonl"
$env:XLINE_EMBEDDED_DISCOVERY = "1"
$env:XLINE_AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_MODEL = if ($env:DEEPSEEK_MODEL) { $env:DEEPSEEK_MODEL } else { "deepseek-chat" }
if ($DeepSeekApiKey) {
    $env:DEEPSEEK_API_KEY = $DeepSeekApiKey
}

Write-Host "Starting isolated virtual rover backend on port $Port"
Write-Host "No ROS2 or real vehicle hardware will be initialized."
if ($env:DWG2DXF_BIN) {
    Write-Host "Local DWG converter: $env:DWG2DXF_BIN"
} else {
    Write-Host "Local DWG converter: unavailable (set DWG2DXF_BIN to enable DWG import)"
}
Show-ConnectionAddresses
Set-Location $backendRoot
& python -m uvicorn app.main:app --host $BindAddress --port $Port
