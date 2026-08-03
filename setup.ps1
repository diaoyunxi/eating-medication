#requires -Version 5.1
<#
.SYNOPSIS
    eating-medication Windows 一键部署脚本（PowerShell）

.DESCRIPTION
    功能：检测系统 → 安装系统依赖 → 询问访问模式（cloudflared/DDNS/仅内网）
         → git clone（GitHub→Gitee 回退）→ 装依赖 → 生成 .env → 服务安装

    适用：Windows 10/11、Windows Server 2019+
    服务管理：NSSM（推荐）或 计划任务
    默认部署目录 C:\eating-medication

.NOTES
    用法：
        以管理员身份运行 PowerShell，执行：
        .\setup.ps1                          # 默认域名 my-website.ccwu.cc
        .\setup.ps1 -Domain "你的域名"        # 自定义域名
        .\setup.ps1 -ServiceMode nssm        # 指定服务模式
        .\setup.ps1 -AccessMode cloudflared  # 非交互式指定访问模式

    幂等：可重复执行（更新代码 + 重装依赖 + 重启服务）。
          .env 仅在不存在时生成，已存在则保留你的配置。
#>

param(
    # 部署目录
    [string]$DeployDir = "C:\eating-medication",
    # 公网域名
    [string]$Domain = "my-website.ccwu.cc",
    # 访问模式：cloudflared / ddns / local
    [string]$AccessMode = "",
    # 服务管理模式：nssm / task
    [string]$ServiceMode = "",
    # pip 镜像源
    [string]$PipMirror = "https://pypi.tuna.tsinghua.edu.cn/simple",
    # 跳过交互提示
    [switch]$NonInteractive
)

# ============================================================
# 常量
# ============================================================
$script:RepoGithub = "https://github.com/diaoyunxi/eating-medication.git"
$script:RepoGitee  = "https://gitee.com/diaoyunxi/eating-medication.git"
$script:ServerPrefix = "/eating-medication/server"
$script:FamilyPrefix = "/eating-medication/family"
$script:ServerPort   = 1059
$script:FamilyPort   = 4430
$script:NssmVersion  = "2.24"
$script:NssmUrl      = "https://nssm.cc/release/nssm-$($script:NssmVersion).zip"

# GitHub 镜像站列表
$script:Mirrors = @(
    "https://gh.llkk.cc",
    "https://gh-proxy.com"
)

# ============================================================
# 日志函数
# ============================================================
function Write-LogInfo  { param([string]$Msg) Write-Host "[INFO] $Msg" -ForegroundColor Green }
function Write-LogWarn  { param([string]$Msg) Write-Host "[WARN] $Msg" -ForegroundColor Yellow }
function Write-LogError { param([string]$Msg) Write-Host "[ERROR] $Msg" -ForegroundColor Red }
function Write-LogStep  { param([string]$Msg) Write-Host "`n==> $Msg" -ForegroundColor Cyan }

# ============================================================
# 检测管理员权限
# ============================================================
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    return $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ============================================================
# 检测系统信息
# ============================================================
function Detect-System {
    Write-LogStep "检测系统信息"

    # 检测架构
    $arch = $env:PROCESSOR_ARCHITECTURE
    switch ($arch) {
        "AMD64"  { $script:ArchNorm = "amd64" }
        "ARM64"  { $script:ArchNorm = "arm64" }
        default  { $script:ArchNorm = $arch.ToLower() }
    }
    Write-LogInfo "系统架构: $arch ($script:ArchNorm)"

    # Windows 版本
    $osInfo = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($osInfo) {
        Write-LogInfo "Windows 版本: $($osInfo.Caption) $($osInfo.Version)"
    }

    # 检测 PowerShell 版本
    Write-LogInfo "PowerShell 版本: $($PSVersionTable.PSVersion)"
}

# ============================================================
# 安装系统依赖（Git、Python）
# ============================================================
function Install-SystemDeps {
    Write-LogStep "[1/9] 检查并安装系统依赖"

    # 检查 Git
    $gitOk = $false
    try {
        $gitVer = git --version 2>$null
        if ($gitVer) {
            Write-LogInfo "Git 已安装: $gitVer"
            $gitOk = $true
        }
    } catch {}

    if (-not $gitOk) {
        Write-LogWarn "未检测到 Git，尝试通过 winget 安装..."
        try {
            winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements 2>$null
            # 刷新 PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
            $gitVer = git --version 2>$null
            if ($gitVer) {
                Write-LogInfo "Git 安装成功: $gitVer"
                $gitOk = $true
            }
        } catch {
            Write-LogError "winget 安装 Git 失败，请手动安装: https://git-scm.com/download/win"
        }
    }

    if (-not $gitOk) {
        Write-LogError "Git 未安装，无法继续"
        exit 1
    }

    # 检查 Python
    $pyOk = $false
    try {
        $pyVer = python --version 2>$null
        if ($pyVer) {
            Write-LogInfo "Python 已安装: $pyVer"
            $pyOk = $true
        }
    } catch {}

    if (-not $pyOk) {
        Write-LogWarn "未检测到 Python，尝试通过 winget 安装..."
        try {
            winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements 2>$null
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
            $pyVer = python --version 2>$null
            if ($pyVer) {
                Write-LogInfo "Python 安装成功: $pyVer"
                $pyOk = $true
            }
        } catch {
            Write-LogError "winget 安装 Python 失败，请手动安装: https://www.python.org/downloads/"
        }
    }

    if (-not $pyOk) {
        Write-LogError "Python 未安装，无法继续"
        exit 1
    }

    # 显示 Python 版本号
    $pyVerNum = python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    Write-LogInfo "Python 版本: $pyVerNum"
}

# ============================================================
# 询问访问模式
# ============================================================
function Ask-AccessMode {
    Write-LogStep "[2/9] 选择公网访问模式"

    if ($script:AccessMode -ne "") {
        Write-LogInfo "命令行指定访问模式: $script:AccessMode"
        return
    }

    if ($NonInteractive) {
        $script:AccessMode = "cloudflared"
        Write-LogInfo "非交互模式，使用默认: Cloudflare 隧道"
        return
    }

    Write-Host ""
    Write-Host "  1) Cloudflare 隧道（cloudflared）—— 推荐，本地无需公网IP"
    Write-Host "  2) 动态域名解析（DDNS + Caddy 自动 HTTPS）—— 需公网IP"
    Write-Host "  3) 仅内网访问 —— 不配置公网"
    Write-Host ""
    $choice = Read-Host "  请选择 [1/2/3] (默认 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" { $script:AccessMode = "cloudflared"; Write-LogInfo "已选择: Cloudflare 隧道" }
        "2" { $script:AccessMode = "ddns";        Write-LogInfo "已选择: DDNS + Caddy" }
        "3" { $script:AccessMode = "local";       Write-LogInfo "已选择: 仅内网访问" }
        default { $script:AccessMode = "cloudflared"; Write-LogWarn "无效选择，使用默认: Cloudflare 隧道" }
    }
}

# ============================================================
# 询问服务管理模式
# ============================================================
function Ask-ServiceMode {
    if ($script:ServiceMode -ne "") {
        Write-LogInfo "命令行指定服务模式: $script:ServiceMode"
        return
    }

    if ($NonInteractive) {
        $script:ServiceMode = "nssm"
        return
    }

    Write-Host ""
    Write-Host "  服务管理模式（将服务端和子女端注册为 Windows 服务）："
    Write-Host "  1) NSSM（推荐）—— 安装为 Windows 服务，开机自启、崩溃自动重启"
    Write-Host "  2) 计划任务 —— 通过 Windows 任务计划程序，开机时启动"
    Write-Host ""
    $choice = Read-Host "  请选择 [1/2] (默认 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" { $script:ServiceMode = "nssm"; Write-LogInfo "已选择: NSSM" }
        "2" { $script:ServiceMode = "task"; Write-LogInfo "已选择: 计划任务" }
        default { $script:ServiceMode = "nssm"; Write-LogWarn "无效选择，使用默认: NSSM" }
    }
}

# ============================================================
# 下载文件（支持镜像回退）
# ============================================================
function Download-FileWithFallback {
    param(
        [string]$Url,
        [string]$SavePath
    )

    # 构建下载源列表
    $urls = @($Url)
    foreach ($mirror in $script:Mirrors) {
        $urls += "$mirror/$Url"
    }

    foreach ($u in $urls) {
        Write-LogInfo "尝试下载: $u"
        try {
            Invoke-WebRequest -Uri $u -OutFile $SavePath -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop
            Write-LogInfo "下载成功"
            return $true
        } catch {
            Write-LogWarn "下载失败，尝试下一个源..."
        }
    }

    Write-LogError "所有下载源均失败: $Url"
    return $false
}

# ============================================================
# Cloudflared 安装与配置
# ============================================================
function Install-Cloudflared {
    Write-LogStep "[3/9] 安装与配置 Cloudflare 隧道"

    # 检查是否已安装
    $cfInstalled = $false
    try {
        $cfVer = cloudflared --version 2>$null
        if ($cfVer) {
            Write-LogInfo "cloudflared 已安装: $cfVer"
            $cfInstalled = $true
        }
    } catch {}

    if (-not $cfInstalled) {
        Write-LogInfo "下载 cloudflared..."

        # 下载 cloudflared Windows 二进制
        $cfUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-$script:ArchNorm.exe"
        $cfBinPath = "C:\Program Files\cloudflared\cloudflared.exe"

        # 创建目录
        $cfDir = Split-Path $cfBinPath -Parent
        if (-not (Test-Path $cfDir)) {
            New-Item -ItemType Directory -Path $cfDir -Force | Out-Null
        }

        $tempPath = "$env:TEMP\cloudflared.exe"
        if (Download-FileWithFallback -Url $cfUrl -SavePath $tempPath) {
            Move-Item -Path $tempPath -Destination $cfBinPath -Force
            # 添加到 PATH
            $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            if ($machinePath -notlike "*$cfDir*") {
                [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$cfDir", "Machine")
                $env:Path += ";$cfDir"
            }
            Write-LogInfo "cloudflared 已安装到 $cfBinPath"
            $cfInstalled = $true
        } else {
            Write-LogError "下载 cloudflared 失败，请手动安装: https://github.com/cloudflare/cloudflared/releases"
            return
        }
    }

    # 选择认证方式
    if (-not $NonInteractive) {
        Write-Host ""
        Write-Host "  Cloudflare 隧道认证方式:"
        Write-Host "  1) Token（推荐）—— 在 Zero Trust 控制台创建隧道后粘贴 token"
        Write-Host "  2) Login（交互式）—— 需浏览器授权"
        Write-Host ""
        $choice = Read-Host "  请选择 [1/2] (默认 1)"
        if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }
    } else {
        $choice = "1"
    }

    switch ($choice) {
        "1" {
            # Token 方式
            if ($NonInteractive) {
                $cfToken = ""
            } else {
                Write-Host "  请粘贴隧道 Token（从 Cloudflare Zero Trust 控制台复制）:" -NoNewline
                $cfToken = Read-Host " "
            }

            if ([string]::IsNullOrWhiteSpace($cfToken)) {
                Write-LogWarn "Token 为空，跳过 cloudflared 服务创建"
                return
            }

            # 注册为 Windows 服务
            $cfBin = "C:\Program Files\cloudflared\cloudflared.exe"
            if (Test-Path $cfBin) {
                # 先卸载旧服务（如果存在）
                try { & $cfBin service uninstall 2>$null } catch {}

                # 写入 token 环境变量
                $env:TUNNEL_TOKEN = $cfToken

                # 安装为服务
                & $cfBin service install 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-LogInfo "Cloudflare 隧道已注册为 Windows 服务（Token 模式）"
                } else {
                    Write-LogWarn "cloudflared service install 返回码: $LASTEXITCODE"
                    # 回退：直接用 sc 创建服务
                    try {
                        & sc.exe create cloudflared binPath= "\"$cfBin\" tunnel --no-autoupdate run --token $cfToken" start= auto 2>$null
                        & sc.exe description cloudflared "Cloudflare Tunnel (cloudflared)" 2>$null
                        & sc.exe start cloudflared 2>$null
                        Write-LogInfo "Cloudflare 隧道已通过 sc.exe 注册为 Windows 服务"
                    } catch {
                        Write-LogError "无法创建 cloudflared 服务，请手动配置"
                    }
                }
            }

            Write-LogInfo "请在 Zero Trust 控制台添加路由:"
            Write-LogInfo "  $script:ServerPrefix -> http://localhost:$script:ServerPort"
            Write-LogInfo "  $script:FamilyPrefix -> http://localhost:$script:FamilyPort"
        }
        "2" {
            # Login 方式
            Write-LogInfo "执行 cloudflared tunnel login（将打开浏览器授权）..."
            $cfBin = "C:\Program Files\cloudflared\cloudflared.exe"
            if (-not (Test-Path $cfBin)) {
                $cfBin = "cloudflared"
            }
            try {
                & $cfBin tunnel login
            } catch {
                Write-LogError "cloudflared tunnel login 失败"
                Write-LogError "请稍后手动执行: cloudflared tunnel login"
            }

            if (-not $NonInteractive) {
                $tunnelName = Read-Host "  请输入隧道名称 (默认 eating-medication)"
                if ([string]::IsNullOrWhiteSpace($tunnelName)) { $tunnelName = "eating-medication" }
            } else {
                $tunnelName = "eating-medication"
            }

            try {
                & $cfBin tunnel create $tunnelName 2>$null
                Write-LogInfo "隧道 $tunnelName 创建成功"
            } catch {
                Write-LogWarn "隧道创建失败，请手动执行: cloudflared tunnel create $tunnelName"
            }

            Write-LogInfo "请在 Zero Trust 控制台或 config.yml 中配置路由:"
            Write-LogInfo "  $script:ServerPrefix -> http://localhost:$script:ServerPort"
            Write-LogInfo "  $script:FamilyPrefix -> http://localhost:$script:FamilyPort"
        }
    }
}

# ============================================================
# DDNS 配置（Windows 下使用计划任务 + 脚本）
# ============================================================
function Setup-DDNS {
    Write-LogStep "[3/9] 配置 DDNS（动态域名解析）"

    # Windows 下 DDNS 仅配置脚本和计划任务，不安装 Caddy
    # HTTPS 反向代理建议在路由器或另装 Caddy/nginx
    Write-LogWarn "Windows 下 DDNS 模式仅创建 IP 更新脚本"
    Write-LogWarn "HTTPS 反向代理需在路由器或另装 Caddy/Nginx 处理"

    if (-not $NonInteractive) {
        $ddnsDomain = Read-Host "  请输入你的域名 (默认 $script:Domain)"
        if ([string]::IsNullOrWhiteSpace($ddnsDomain)) { $ddnsDomain = $script:Domain }
    } else {
        $ddnsDomain = $script:Domain
    }

    Write-Host ""
    Write-Host "  DDNS 更新方式:"
    Write-Host "  1) Cloudflare API（需 API Token + Zone ID）"
    Write-Host "  2) 自定义命令（支持 `$ip 占位符）"
    Write-Host ""

    if ($NonInteractive) {
        $ddnsChoice = "1"
    } else {
        $ddnsChoice = Read-Host "  请选择 [1/2] (默认 1)"
        if ([string]::IsNullOrWhiteSpace($ddnsChoice)) { $ddnsChoice = "1" }
    }

    $ddnsScriptPath = "$DeployDir\deploy\em-ddns-update.ps1"

    switch ($ddnsChoice) {
        "1" {
            if ($NonInteractive) {
                $cfApiToken = ""
                $cfZoneId = ""
                $cfDnsName = ""
            } else {
                $cfApiToken = Read-Host "  请输入 Cloudflare API Token"
                $cfZoneId = Read-Host "  请输入 Zone ID"
                $cfDnsName = Read-Host "  请输入 DNS 记录名 (如 eating.example.com)"
            }

            # 生成 DDNS 更新脚本
            $ddnsContent = @"
# DDNS 更新脚本 - Cloudflare API 方式
# 每 5 分钟检测公网 IP 并更新 Cloudflare DNS 记录

`$CF_API_TOKEN = '$cfApiToken'
`$CF_ZONE_ID = '$cfZoneId'
`$CF_DNS_NAME = '$cfDnsName'

# 获取当前公网 IP
try {
    `$currentIp = (Invoke-RestMethod -Uri 'https://ifconfig.me' -TimeoutSec 10).Trim()
} catch {
    try {
        `$currentIp = (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10).Trim()
    } catch {
        Write-Error '[DDNS] 无法获取公网 IP'
        exit 1
    }
}

# 读取上次记录的 IP
`$cacheFile = Join-Path `$env:LOCALAPPDATA 'em-ddns-last-ip.txt'
`$lastIp = ''
if (Test-Path `$cacheFile) {
    `$lastIp = Get-Content `$cacheFile -Raw 2>`$null
}

# IP 未变化则跳过
if (`$currentIp -eq `$lastIp) {
    exit 0
}

Write-Host "[DDNS] 公网 IP 变化: `$lastIp -> `$currentIp"

# 查询现有 DNS 记录
`$headers = @{
    'Authorization' = "Bearer `$CF_API_TOKEN"
    'Content-Type' = 'application/json'
}
`$apiBase = "https://api.cloudflare.com/client/v4/zones/`$CF_ZONE_ID/dns_records"

try {
    `$records = Invoke-RestMethod -Uri "`$apiBase?name=`$CF_DNS_NAME&type=A" -Headers `$headers -TimeoutSec 15
    `$recordId = ''
    if (`$records.result -and `$records.result.Count -gt 0) {
        `$recordId = `$records.result[0].id
    }
} catch {
    `$recordId = ''
}

`$body = @{ type = 'A'; name = `$CF_DNS_NAME; content = `$currentIp; ttl = 60; proxied = `$false } | ConvertTo-Json

if ([string]::IsNullOrEmpty(`$recordId)) {
    # 创建新记录
    try {
        Invoke-RestMethod -Uri `$apiBase -Method Post -Headers `$headers -Body `$body -TimeoutSec 15 | Out-Null
        Write-Host '[DDNS] 已创建 DNS 记录'
    } catch {
        Write-Error '[DDNS] 创建失败'
    }
} else {
    # 更新现有记录
    try {
        Invoke-RestMethod -Uri "`$apiBase/`$recordId" -Method Put -Headers `$headers -Body `$body -TimeoutSec 15 | Out-Null
        Write-Host '[DDNS] 已更新 DNS 记录'
    } catch {
        Write-Error '[DDNS] 更新失败'
    }
}

# 缓存当前 IP
`$currentIp | Out-File `$cacheFile -Encoding utf8 -NoNewline
"@

            Set-Content -Path $ddnsScriptPath -Value $ddnsContent -Encoding UTF8
        }
        "2" {
            if ($NonInteractive) {
                $customCmd = ""
            } else {
                Write-Host "  请输入自定义命令（用 `$ip 表示公网IP占位符）:" -NoNewline
                $customCmd = Read-Host " "
            }

            $ddnsContent = @"
# DDNS 更新脚本 - 自定义命令方式

`$CustomCmd = '$customCmd'

try {
    `$currentIp = (Invoke-RestMethod -Uri 'https://ifconfig.me' -TimeoutSec 10).Trim()
} catch {
    try {
        `$currentIp = (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10).Trim()
    } catch {
        Write-Error '[DDNS] 无法获取公网 IP'
        exit 1
    }
}

Write-Host "[DDNS] 当前公网 IP: `$currentIp"
`$cmd = `$CustomCmd -replace '\`$ip', `$currentIp
Invoke-Expression `$cmd
"@

            Set-Content -Path $ddnsScriptPath -Value $ddnsContent -Encoding UTF8
        }
    }

    # 创建计划任务（每 5 分钟执行）
    $taskName = "EatingMedication-DDNS"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ddnsScriptPath`""
    $trigger1 = New-ScheduledTaskTrigger -AtStartup
    $trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger1, $trigger2) -Settings $settings -Description "Eating Medication DDNS Update" -Force | Out-Null
        Write-LogInfo "DDNS 计划任务已创建（每 5 分钟执行）"
        # 立即执行一次
        Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    } catch {
        Write-LogWarn "创建 DDNS 计划任务失败: $_"
    }

    $script:Domain = $ddnsDomain
}

# ============================================================
# git clone（GitHub → Gitee 回退）
# ============================================================
function Clone-Repo {
    Write-LogStep "[4/9] 克隆仓库"

    if (Test-Path "$DeployDir\.git") {
        Write-LogInfo "仓库已存在，拉取最新代码..."
        try {
            git -C $DeployDir pull --ff-only 2>$null
        } catch {
            try {
                git -C $DeployDir pull 2>$null
            } catch {
                Write-LogWarn "git pull 失败，继续使用现有代码"
            }
        }
    } else {
        Write-LogInfo "尝试从 GitHub 克隆: $script:RepoGithub"
        $cloneOk = $false
        try {
            git clone --depth 1 $script:RepoGithub $DeployDir 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-LogInfo "GitHub 克隆成功"
                $cloneOk = $true
            }
        } catch {}

        if (-not $cloneOk) {
            Write-LogWarn "GitHub 克隆失败（超时或网络问题），尝试 Gitee 镜像..."
            Write-LogInfo "尝试从 Gitee 克隆: $script:RepoGitee"
            try {
                git clone --depth 1 $script:RepoGitee $DeployDir 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-LogInfo "Gitee 克隆成功"
                    $cloneOk = $true
                }
            } catch {}

            if (-not $cloneOk) {
                Write-LogError "GitHub 和 Gitee 均克隆失败"
                Write-LogError "请检查网络或手动克隆仓库到 $DeployDir"
                exit 1
            }
        }
    }
}

# ============================================================
# 创建 venv + Python 依赖
# ============================================================
function Setup-PythonEnv {
    Write-LogStep "[5/9] 创建虚拟环境并安装 Python 依赖"

    $venv = "$DeployDir\venv"
    $venvPython = "$venv\Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        Write-LogInfo "创建虚拟环境 $venv ..."
        python -m venv $venv
        if (-not (Test-Path $venvPython)) {
            Write-LogError "虚拟环境创建失败"
            exit 1
        }
    }

    $pipArgs = @()
    if ($PipMirror) {
        $pipArgs += @("-i", $PipMirror)
    }

    Write-LogInfo "升级 pip ..."
    & $venvPython -m pip install --upgrade pip @pipArgs 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install --upgrade pip
    }

    Write-LogInfo "安装 server 依赖 ..."
    & $venvPython -m pip install -r "$DeployDir\server\requirements.txt" @pipArgs 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install -r "$DeployDir\server\requirements.txt"
    }

    Write-LogInfo "安装 family_monitor 依赖 ..."
    & $venvPython -m pip install -r "$DeployDir\family_monitor\requirements.txt" @pipArgs 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install -r "$DeployDir\family_monitor\requirements.txt"
    }

    Write-LogInfo "Python 依赖安装完成"
    $script:VenvPython = $venvPython
}

# ============================================================
# 生成生产环境 .env
# ============================================================
function New-SecretKey {
    # 生成 32 字节 URL 安全的随机密钥
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Generate-EnvFiles {
    Write-LogStep "[6/9] 生成生产环境 .env（server / family_monitor）"

    $serverEnv = "$DeployDir\server\.env"
    $familyEnv = "$DeployDir\family_monitor\.env"

    # server/.env
    if (Test-Path $serverEnv) {
        Write-LogInfo "$serverEnv 已存在，保留原配置"
    } else {
        $sk = New-SecretKey
        $serverContent = @"
# 生产环境配置（由 setup.ps1 自动生成，请按需修改后重启服务）
APP_NAME=老年人用药管理系统
DEBUG=false
API_V1_PREFIX=/api/v1
PATH_PREFIX=$script:ServerPrefix
SERVER_HOST=0.0.0.0
SERVER_PORT=$script:ServerPort
DATABASE_URL=sqlite:///./data/elderly_care.db
SECRET_KEY=$sk
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
ALLOWED_ORIGINS=https://$script:Domain$script:FamilyPrefix
GITHUB_OAUTH_CALLBACK_URL=https://$script:Domain$script:ServerPrefix/api/v1/auth/oauth/github/callback
GITEE_OAUTH_CALLBACK_URL=https://$script:Domain$script:ServerPrefix/api/v1/auth/oauth/gitee/callback
FAMILY_WEB_URL=https://$script:Domain$script:FamilyPrefix
# 以下为可选服务，留空则自动降级（功能关闭）：
#   MAIL_*        邮件验证码登录/找回密码
#   OCR_*         图片 OCR 识别
#   TURNSTILE_SECRET_KEY  Cloudflare 人机验证
#   GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET  GitHub 登录
#   GITEE_CLIENT_ID / GITEE_CLIENT_SECRET    Gitee 登录
#   ZHIPUAI_API_KEY / ZHIPUAI_MODEL          服务端 AI 全局兜底
"@
        Set-Content -Path $serverEnv -Value $serverContent -Encoding UTF8
        Write-LogInfo "已生成 $serverEnv"
    }

    # family_monitor/.env
    if (Test-Path $familyEnv) {
        Write-LogInfo "$familyEnv 已存在，保留原配置"
    } else {
        $sk2 = New-SecretKey
        $familyContent = @"
# 生产环境配置（由 setup.ps1 自动生成，请按需修改后重启服务）
SERVER_HOST=0.0.0.0
SERVER_PORT=$script:FamilyPort
ELDERLY_SERVER_URL=https://$script:Domain$script:ServerPrefix
PATH_PREFIX=$script:FamilyPrefix
APP_NAME=子女守护中心
DEBUG=false
COOKIE_SECURE=true
PRODUCTION=true
SECRET_KEY=$sk2
DEVICE_SECRET=
TURNSTILE_SITE_KEY=
ALLOWED_ORIGINS=https://$script:Domain$script:FamilyPrefix
DISPLAY_THEME=light
DISPLAY_COLOR=purple
DISPLAY_LANGUAGE=zh-CN
DISPLAY_ANIMATIONS=True
DISPLAY_COMPACT=False
"@
        Set-Content -Path $familyEnv -Value $familyContent -Encoding UTF8
        Write-LogInfo "已生成 $familyEnv"
    }
}

# ============================================================
# 创建运行时目录
# ============================================================
function Setup-RuntimeDirs {
    Write-LogStep "[7/9] 创建运行时目录"

    $dirs = @(
        "$DeployDir\server\data",
        "$DeployDir\server\logs",
        "$DeployDir\family_monitor\data",
        "$DeployDir\family_monitor\logs"
    )

    foreach ($d in $dirs) {
        if (-not (Test-Path $d)) {
            New-Item -ItemType Directory -Path $d -Force | Out-Null
        }
    }

    Write-LogInfo "运行时目录已创建"
}

# ============================================================
# 安装 NSSM
# ============================================================
function Install-Nssm {
    $nssmDir = "C:\Program Files\nssm"
    $nssmExe = "$nssmDir\nssm.exe"

    if (Test-Path $nssmExe) {
        Write-LogInfo "NSSM 已安装: $nssmExe"
        $env:Path += ";$nssmDir"
        return $nssmExe
    }

    Write-LogInfo "下载并安装 NSSM..."
    $tempZip = "$env:TEMP\nssm.zip"
    if (-not (Download-FileWithFallback -Url $script:NssmUrl -SavePath $tempZip)) {
        Write-LogError "下载 NSSM 失败"
        return $null
    }

    $tempExtract = "$env:TEMP\nssm-extract"
    if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force }
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

    # 查找对应架构的 nssm.exe
    $archSubDir = if ($script:ArchNorm -eq "arm64") { "win64" } else { "win64" }
    $nssmSource = Get-ChildItem -Path $tempExtract -Recurse -Filter "nssm.exe" | Select-Object -First 1

    if ($nssmSource) {
        if (-not (Test-Path $nssmDir)) {
            New-Item -ItemType Directory -Path $nssmDir -Force | Out-Null
        }
        Copy-Item $nssmSource.FullName $nssmExe -Force

        # 添加到 PATH
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($machinePath -notlike "*$nssmDir*") {
            [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$nssmDir", "Machine")
            $env:Path += ";$nssmDir"
        }

        Write-LogInfo "NSSM 已安装到 $nssmExe"
        Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
        return $nssmExe
    }

    Write-LogError "未在压缩包中找到 nssm.exe"
    return $null
}

# ============================================================
# 通过 NSSM 安装 Windows 服务
# ============================================================
function Setup-NssmServices {
    Write-LogStep "[8/9] 安装 NSSM 服务并启动"

    $nssmExe = Install-Nssm
    if (-not $nssmExe) {
        Write-LogError "NSSM 安装失败，回退到计划任务模式"
        $script:ServiceMode = "task"
        Setup-TaskServices
        return
    }

    # server 服务
    $serverServiceName = "EatingMedication-Server"
    Write-LogInfo "安装服务: $serverServiceName"
    try { & $nssmExe remove $serverServiceName confirm 2>$null } catch {}
    & $nssmExe install $serverServiceName $script:VenvPython "main.py" 2>$null
    & $nssmExe set $serverServiceName AppDirectory "$DeployDir\server" 2>$null
    & $nssmExe set $serverServiceName AppEnvironmentExtra PYTHONUNBUFFERED=1 2>$null
    & $nssmExe set $serverServiceName Description "Eating Medication Server (FastAPI :$script:ServerPort)" 2>$null
    & $nssmExe set $serverServiceName Start SERVICE_AUTO_START 2>$null
    & $nssmExe set $serverServiceName AppStdout "$DeployDir\server\logs\service.log" 2>$null
    & $nssmExe set $serverServiceName AppStderr "$DeployDir\server\logs\service.err.log" 2>$null
    & $nssmExe set $serverServiceName AppRotateFiles 1 2>$null
    & $nssmExe set $serverServiceName AppRotateBytes 10485760 2>$null
    & $nssmExe set $serverServiceName AppExit Default Restart 2>$null
    & $nssmExe set $serverServiceName AppRestartDelay 5000 2>$null
    & $nssmExe start $serverServiceName 2>$null
    Write-LogInfo "服务 $serverServiceName 已启动"

    # family 服务
    $familyServiceName = "EatingMedication-Family"
    Write-LogInfo "安装服务: $familyServiceName"
    try { & $nssmExe remove $familyServiceName confirm 2>$null } catch {}
    & $nssmExe install $familyServiceName $script:VenvPython "main.py" 2>$null
    & $nssmExe set $familyServiceName AppDirectory "$DeployDir\family_monitor" 2>$null
    & $nssmExe set $familyServiceName AppEnvironmentExtra PYTHONUNBUFFERED=1 2>$null
    & $nssmExe set $familyServiceName Description "Eating Medication Family Monitor (FastAPI Web :$script:FamilyPort)" 2>$null
    & $nssmExe set $familyServiceName Start SERVICE_AUTO_START 2>$null
    & $nssmExe set $familyServiceName AppStdout "$DeployDir\family_monitor\logs\service.log" 2>$null
    & $nssmExe set $familyServiceName AppStderr "$DeployDir\family_monitor\logs\service.err.log" 2>$null
    & $nssmExe set $familyServiceName AppRotateFiles 1 2>$null
    & $nssmExe set $familyServiceName AppRotateBytes 10485760 2>$null
    & $nssmExe set $familyServiceName AppExit Default Restart 2>$null
    & $nssmExe set $familyServiceName AppRestartDelay 5000 2>$null
    & $nssmExe start $familyServiceName 2>$null
    Write-LogInfo "服务 $familyServiceName 已启动"

    $script:ServerServiceName = $serverServiceName
    $script:FamilyServiceName = $familyServiceName
}

# ============================================================
# 通过计划任务安装服务
# ============================================================
function Setup-TaskServices {
    Write-LogStep "[8/9] 创建计划任务并启动"

    # server 计划任务
    $serverTaskName = "EatingMedication-Server"
    $serverAction = New-ScheduledTaskAction -Execute $script:VenvPython -Argument "main.py" -WorkingDirectory "$DeployDir\server"
    $serverTrigger = New-ScheduledTaskTrigger -AtStartup
    $serverSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $serverPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    try {
        Unregister-ScheduledTask -TaskName $serverTaskName -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $serverTaskName -Action $serverAction -Trigger $serverTrigger -Settings $serverSettings -Principal $serverPrincipal -Description "Eating Medication Server (FastAPI :$script:ServerPort)" -Force | Out-Null
        Start-ScheduledTask -TaskName $serverTaskName -ErrorAction SilentlyContinue
        Write-LogInfo "计划任务 $serverTaskName 已创建并启动"
    } catch {
        Write-LogError "创建计划任务 $serverTaskName 失败: $_"
    }

    # family 计划任务
    $familyTaskName = "EatingMedication-Family"
    $familyAction = New-ScheduledTaskAction -Execute $script:VenvPython -Argument "main.py" -WorkingDirectory "$DeployDir\family_monitor"
    $familyTrigger = New-ScheduledTaskTrigger -AtStartup
    $familySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $familyPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    try {
        Unregister-ScheduledTask -TaskName $familyTaskName -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $familyTaskName -Action $familyAction -Trigger $familyTrigger -Settings $familySettings -Principal $familyPrincipal -Description "Eating Medication Family Monitor (FastAPI Web :$script:FamilyPort)" -Force | Out-Null
        Start-ScheduledTask -TaskName $familyTaskName -ErrorAction SilentlyContinue
        Write-LogInfo "计划任务 $familyTaskName 已创建并启动"
    } catch {
        Write-LogError "创建计划任务 $familyTaskName 失败: $_"
    }

    $script:ServerServiceName = $serverTaskName
    $script:FamilyServiceName = $familyTaskName
}

# ============================================================
# 提示编辑 .env
# ============================================================
function Prompt-EditEnv {
    Write-LogStep "[9/9] 提示编辑配置文件"

    Start-Sleep -Seconds 2
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  部署即将完成！请编辑以下配置文件后按 Enter 继续：" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  1) 服务端配置:"
    Write-Host "     notepad $DeployDir\server\.env"
    Write-Host "     关键项: SECRET_KEY(已自动生成)、TURNSTILE_SECRET_KEY、"
    Write-Host "             ZHIPUAI_API_KEY、GITHUB/GITEE OAuth 凭据"
    Write-Host ""
    Write-Host "  2) 子女端配置:"
    Write-Host "     notepad $DeployDir\family_monitor\.env"
    Write-Host "     关键项: SECRET_KEY(已自动生成)、TURNSTILE_SITE_KEY、"
    Write-Host "             ELDERLY_SERVER_URL(已自动填写)"
    Write-Host ""

    if ($NonInteractive) {
        Write-LogInfo "非交互模式，跳过等待，请稍后手动重启服务"
        return
    }

    Write-Host "  编辑完成后按 Enter 重启服务以加载新配置..."
    Write-Host "  （或按 Ctrl+C 跳过，稍后手动重启）"
    Read-Host

    # 重启服务
    Write-LogInfo "重启服务以加载新配置..."
    Restart-Services
}

# ============================================================
# 重启服务
# ============================================================
function Restart-Services {
    if ($script:ServiceMode -eq "nssm") {
        try {
            & nssm restart $script:ServerServiceName 2>$null
            & nssm restart $script:FamilyServiceName 2>$null
        } catch {
            Write-LogWarn "重启服务时出错: $_"
        }
    } elseif ($script:ServiceMode -eq "task") {
        try {
            Stop-ScheduledTask -TaskName $script:ServerServiceName -ErrorAction SilentlyContinue
            Stop-ScheduledTask -TaskName $script:FamilyServiceName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Start-ScheduledTask -TaskName $script:ServerServiceName -ErrorAction SilentlyContinue
            Start-ScheduledTask -TaskName $script:FamilyServiceName -ErrorAction SilentlyContinue
        } catch {
            Write-LogWarn "重启计划任务时出错: $_"
        }
    }
}

# ============================================================
# 主流程
# ============================================================
function Main {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  eating-medication Windows 一键部署" -ForegroundColor Cyan
    Write-Host "  部署目录: $DeployDir" -ForegroundColor Cyan
    Write-Host "  域名:     $script:Domain" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    # 检查管理员权限
    if (-not (Test-Administrator)) {
        Write-LogError "请以管理员身份运行 PowerShell"
        Write-LogError "右键 PowerShell -> 以管理员身份运行"
        exit 1
    }

    # 1. 检测系统
    Detect-System

    # 2. 安装系统依赖
    Install-SystemDeps

    # 3. 询问访问模式
    Ask-AccessMode

    # 4. 按选择配置网络访问
    switch ($script:AccessMode) {
        "cloudflared" { Install-Cloudflared }
        "ddns"        { Setup-DDNS }
        "local"       { Write-LogInfo "跳过公网访问配置" }
    }

    # 5. 克隆仓库
    Clone-Repo

    # 6. Python 环境
    Setup-PythonEnv

    # 7. 生成 .env
    Generate-EnvFiles

    # 8. 运行时目录
    Setup-RuntimeDirs

    # 9. 询问服务管理模式
    Ask-ServiceMode

    # 10. 安装服务
    switch ($script:ServiceMode) {
        "nssm" { Setup-NssmServices }
        "task" { Setup-TaskServices }
    }

    # 提示编辑 .env
    Prompt-EditEnv

    # 完成
    Start-Sleep -Seconds 2
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  部署完成！" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  后续步骤:"
    Write-Host "  1) 查看日志:"

    if ($script:ServiceMode -eq "nssm") {
        Write-Host "     Get-Content $DeployDir\server\logs\service.log -Tail 30 -Wait"
        Write-Host "     Get-Content $DeployDir\family_monitor\logs\service.log -Tail 30 -Wait"
        Write-Host "     或: nssm status $($script:ServerServiceName)"
        Write-Host "         nssm status $($script:FamilyServiceName)"
    } else {
        Write-Host "     Get-Content $DeployDir\server\logs\service.log -Tail 30 -Wait"
        Write-Host "     Get-Content $DeployDir\family_monitor\logs\service.log -Tail 30 -Wait"
    }

    Write-Host "  2) 更新代码: .\setup.ps1"
    Write-Host "  3) 服务管理:"
    if ($script:ServiceMode -eq "nssm") {
        Write-Host "     启动: nssm start $($script:ServerServiceName)"
        Write-Host "     停止: nssm stop $($script:ServerServiceName)"
        Write-Host "     重启: nssm restart $($script:ServerServiceName)"
    } else {
        Write-Host "     启动: Start-ScheduledTask -TaskName $($script:ServerServiceName)"
        Write-Host "     停止: Stop-ScheduledTask -TaskName $($script:ServerServiceName)"
    }

    switch ($script:AccessMode) {
        "cloudflared" {
            Write-Host "  4) Cloudflare 隧道路由:"
            Write-Host "     $script:ServerPrefix -> http://localhost:$script:ServerPort"
            Write-Host "     $script:FamilyPrefix -> http://localhost:$script:FamilyPort"
        }
        "ddns" {
            Write-Host "  4) DDNS 已配置，访问: https://$script:Domain"
        }
        "local" {
            Write-Host "  4) 内网访问:"
            Write-Host "     http://localhost:$script:ServerPort$script:ServerPrefix"
            Write-Host "     http://localhost:$script:FamilyPort$script:FamilyPrefix"
        }
    }

    Write-Host "------------------------------------------------------------"
}

# 执行主流程
Main
