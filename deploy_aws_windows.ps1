# ==============================================================================
# AWS Windows VPS Automated Deployment Script for Gold & BTC Trading Bot
# ==============================================================================
$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  🚀 Deploying Institutional Gold & BTC Bot on AWS Windows VPS" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Identify Directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
Write-Host "[*] Working directory: $ScriptDir" -ForegroundColor Gray

# 2. Check for Python
Write-Host "`n[*] Checking Python installation..." -ForegroundColor Yellow
$PythonCmd = $null

if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        $ver = & py -3.11 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = "py -3.11"
            Write-Host "    Found Python via launcher: $ver" -ForegroundColor Green
        }
    } catch {}
}

if (-not $PythonCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        $ver = & python --version 2>&1
        $PythonCmd = "python"
        Write-Host "    Found Python on PATH: $ver" -ForegroundColor Green
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "[!] Python was not detected on this Windows VPS." -ForegroundColor Yellow
    Write-Host "[*] Attempting to install Python 3.11 using winget or direct official installer..." -ForegroundColor Cyan
    
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    Installing via winget..." -ForegroundColor Gray
        winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "    Downloading official Python 3.11 installer..." -ForegroundColor Gray
        $installerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        $installerPath = "$env:TEMP\python-3.11.9-amd64.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
        Write-Host "    Executing silent installation (Adding to PATH)..." -ForegroundColor Gray
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    }
    
    # Refresh PATH in current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $PythonCmd = "python"
}

# 3. Virtual Environment Setup
Write-Host "`n[*] Configuring Python virtual environment..." -ForegroundColor Yellow
$VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
$VenvPip = Join-Path $ScriptDir "venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "    Creating virtual environment (venv)..." -ForegroundColor Gray
    if ($PythonCmd -eq "py -3.11") {
        & py -3.11 -m venv venv
    } else {
        & python -m venv venv
    }
}

if (Test-Path $VenvPython) {
    Write-Host "    Upgrading pip in venv..." -ForegroundColor Gray
    & $VenvPython -m pip install --upgrade pip --quiet
    
    Write-Host "    Installing production dependencies (MetaTrader5, yfinance, pandas, matplotlib)..." -ForegroundColor Yellow
    & $VenvPip install -r requirements.txt
    Write-Host "    Dependencies installed successfully!" -ForegroundColor Green
} else {
    Write-Host "[!] Virtual environment creation failed. Installing globally with pip..." -ForegroundColor Yellow
    & $PythonCmd -m pip install --upgrade pip
    & $PythonCmd -m pip install -r requirements.txt
}

# 4. Check & Create .env Configuration
Write-Host "`n[*] Verifying configuration (.env)..." -ForegroundColor Yellow
$EnvFile = Join-Path $ScriptDir ".env"
$EnvExample = Join-Path $ScriptDir ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item -Path $EnvExample -Destination $EnvFile
        Write-Host "    Created .env file from .env.example." -ForegroundColor Green
        Write-Host "    --> Please edit .env with your Telegram Bot Token and Chat ID!" -ForegroundColor Magenta
    }
} else {
    Write-Host "    Found existing .env file." -ForegroundColor Green
}

# 5. Check MetaTrader 5 Setup
Write-Host "`n[*] Checking MetaTrader 5..." -ForegroundColor Yellow
$MT5Setup = Join-Path $ScriptDir "mt5setup.exe"
if (Test-Path $MT5Setup) {
    Write-Host "    MetaTrader 5 installer (mt5setup.exe) is present in the repository." -ForegroundColor Green
    Write-Host "    If not yet installed, you can run mt5setup.exe to install your broker terminal." -ForegroundColor Gray
}

# 6. Auto-Start Task on Windows Logon (Optional 24/7 persistence)
Write-Host "`n[*] Creating Windows Auto-Start Task for 24/7 Resilience..." -ForegroundColor Yellow
$TaskName = "InstitutionalTradingBot"
$BatPath = Join-Path $ScriptDir "run_bot.bat"

try {
    $Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ScriptDir
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365)
    
    # Unregister older task if present
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs Gold & BTC Quantitative Trading Bot 24/7 with auto-restart" -ErrorAction SilentlyContinue | Out-Null
    Write-Host "    Windows Scheduled Task '$TaskName' registered for 24/7 logon startup." -ForegroundColor Green
} catch {
    Write-Host "    Task scheduler registration skipped (run as Admin if you want auto-start on logon)." -ForegroundColor Gray
}

# Create Desktop Shortcut
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
    $Shortcut = $WshShell.CreateShortcut((Join-Path $DesktopPath "Start Trading Bot.lnk"))
    $Shortcut.TargetPath = $BatPath
    $Shortcut.WorkingDirectory = $ScriptDir
    $Shortcut.IconLocation = "$VenvPython,0"
    $Shortcut.Save()
    Write-Host "    Desktop shortcut 'Start Trading Bot' created!" -ForegroundColor Green
} catch {}

Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "  ✅ AWS Windows VPS Deployment Complete!" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Edit .env with your Telegram bot token: notepad .env" -ForegroundColor White
Write-Host "2. Double-click 'Start Trading Bot' on Desktop (or run .\run_bot.bat)" -ForegroundColor White
Write-Host "3. Open Telegram and send /start to launch your Omni-Cockpit!" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Cyan
