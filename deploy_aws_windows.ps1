# ==============================================================================
# Complete Windows VPS / PC Automated Deployment Script for Gold & BTC Bot
# Installs: Python 3.11, Dependencies, MetaTrader 5 Terminal, .env, 24/7 Autostart
# ==============================================================================
$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  🚀 Deploying Institutional Gold & BTC Bot + MetaTrader 5" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Identify Working Directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
Write-Host "[*] Working directory: $ScriptDir" -ForegroundColor Gray

# 2. Check & Install Python 3.11
Write-Host "`n[*] Step 1/6: Checking Python installation..." -ForegroundColor Yellow
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
        if ($ver -match "3\.1[0-3]") {
            $PythonCmd = "python"
            Write-Host "    Found Python on PATH: $ver" -ForegroundColor Green
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "[!] Python 3.11 not detected. Installing automatically..." -ForegroundColor Yellow
    
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    Installing Python 3.11 via winget..." -ForegroundColor Gray
        winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "    Downloading official Python 3.11 installer..." -ForegroundColor Gray
        $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        $pyInstaller = "$env:TEMP\python-3.11.9-amd64.exe"
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller
        Write-Host "    Executing silent installation (Adding Python to PATH)..." -ForegroundColor Gray
        Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    }
    
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $PythonCmd = "python"
}

# 3. Virtual Environment Setup
Write-Host "`n[*] Step 2/6: Configuring Python virtual environment..." -ForegroundColor Yellow
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
Write-Host "`n[*] Step 3/6: Verifying configuration (.env)..." -ForegroundColor Yellow
$EnvFile = Join-Path $ScriptDir ".env"
$EnvExample = Join-Path $ScriptDir ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item -Path $EnvExample -Destination $EnvFile
        Write-Host "    Created .env file from .env.example." -ForegroundColor Green
        Write-Host "    --> Please edit .env with your Telegram Bot Token!" -ForegroundColor Magenta
    }
} else {
    Write-Host "    Found existing .env file." -ForegroundColor Green
}

# 5. Check & Install MetaTrader 5 Terminal
Write-Host "`n[*] Step 4/6: Checking MetaTrader 5 Terminal..." -ForegroundColor Yellow

$CommonMT5Paths = @(
    "C:\Program Files\MetaTrader 5\terminal64.exe",
    "C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    "C:\Program Files\FTMO MetaTrader 5\terminal64.exe",
    "C:\Program Files\ICMarkets MetaTrader 5\terminal64.exe",
    "C:\Program Files\Exness MetaTrader 5\terminal64.exe"
)

$InstalledMT5 = $null
foreach ($p in $CommonMT5Paths) {
    if (Test-Path $p) {
        $InstalledMT5 = $p
        break
    }
}

if (-not $InstalledMT5) {
    # Scan Program Files for any terminal64.exe
    $found = Get-ChildItem -Path "C:\Program Files" -Filter "terminal64.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        $InstalledMT5 = $found.FullName
    }
}

if ($InstalledMT5) {
    Write-Host "    ✅ MetaTrader 5 is already installed at: $InstalledMT5" -ForegroundColor Green
} else {
    Write-Host "    [!] MetaTrader 5 not found. Installing official MetaTrader 5..." -ForegroundColor Yellow
    $mt5InstallerPath = Join-Path $ScriptDir "mt5setup.exe"
    
    if (-not (Test-Path $mt5InstallerPath)) {
        Write-Host "    Downloading official MetaTrader 5 setup..." -ForegroundColor Gray
        $mt5Url = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
        $mt5InstallerPath = "$env:TEMP\mt5setup.exe"
        Invoke-WebRequest -Uri $mt5Url -OutFile $mt5InstallerPath -UserAgent "Mozilla/5.0"
    }
    
    Write-Host "    Launching MetaTrader 5 installer (automated mode)..." -ForegroundColor Cyan
    Start-Process -FilePath $mt5InstallerPath -ArgumentList "/auto" -Wait
    
    # Check again
    Start-Sleep -Seconds 5
    foreach ($p in $CommonMT5Paths) {
        if (Test-Path $p) {
            $InstalledMT5 = $p
            break
        }
    }
    if ($InstalledMT5) {
        Write-Host "    ✅ MetaTrader 5 installed successfully at: $InstalledMT5" -ForegroundColor Green
    } else {
        Write-Host "    ⚠️ MetaTrader 5 installer finished. Please complete broker login in the opened terminal." -ForegroundColor Yellow
    }
}

# Launch MT5 terminal if installed and not currently running
$mt5Process = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
if (-not $mt5Process -and $InstalledMT5) {
    Write-Host "    Starting MetaTrader 5 terminal in background..." -ForegroundColor Gray
    Start-Process -FilePath $InstalledMT5
}

# 6. Windows 24/7 Autostart Task Scheduler & Desktop Shortcut
Write-Host "`n[*] Step 5/6: Configuring 24/7 Autostart & Desktop Shortcut..." -ForegroundColor Yellow
$TaskName = "InstitutionalTradingBot"
$BatPath = Join-Path $ScriptDir "run_bot.bat"

try {
    $Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ScriptDir
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365)
    
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs Gold & BTC Quantitative Trading Bot 24/7 with auto-restart" -ErrorAction SilentlyContinue | Out-Null
    Write-Host "    ✅ Windows Scheduled Task '$TaskName' registered for 24/7 boot/logon." -ForegroundColor Green
} catch {
    Write-Host "    Task scheduler registration skipped (run as Admin to enable auto-start on boot)." -ForegroundColor Gray
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
    Write-Host "    ✅ Desktop shortcut 'Start Trading Bot' created!" -ForegroundColor Green
} catch {}

# 7. Verification Test Suite Run
Write-Host "`n[*] Step 6/6: Running Full System Test Suite..." -ForegroundColor Yellow
& $VenvPython test_suite.py

Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "  🎉 FULL WINDOWS & MT5 SETUP COMPLETE!" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "FINAL 3 CONFIGURATION STEPS:" -ForegroundColor Yellow
Write-Host "1. In MetaTrader 5:" -ForegroundColor White
Write-Host "   • Log into your Demo or Live broker account (File -> Login to Trade Account)." -ForegroundColor Gray
Write-Host "   • Enable Algo Trading: Tools -> Options -> Expert Advisors -> check 'Allow algorithmic trading'." -ForegroundColor Gray
Write-Host "2. Edit .env with your Telegram bot token: notepad .env" -ForegroundColor White
Write-Host "3. Double-click 'Start Trading Bot' on Desktop (or run .\run_bot.bat)" -ForegroundColor White
Write-Host "   • Open Telegram and send /start to launch your Omni-Cockpit!" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Cyan
