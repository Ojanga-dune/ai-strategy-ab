# run_bot.ps1
# ==============================================================================
# Autonomous Live Bot Launcher for Windows
# ==============================================================================

$ProjectRoot = "C:\Users\Admin\ai-strategy-lab"
$BotScript = "$ProjectRoot\live_main.py"
$LogDir = "$ProjectRoot\logs"
$LockFile = "$ProjectRoot\bot.lock"
$LogRetentionDays = 7

# Ensure Log Directory exists
if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-BotLog {
    param([string]$Message, [string]$Level = "INFO")
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogEntry = "[$Timestamp] [$Level] $Message"
    Write-Host $LogEntry
    $LogFile = "$LogDir\bot_launcher_$(Get-Date -Format 'yyyy-MM-dd').log"
    Add-Content -Path $LogFile -Value $LogEntry
}

function Rotate-Logs {
    Write-BotLog "Performing log rotation (Retention: $LogRetentionDays days)..."
    $LimitDate = (Get-Date).AddDays(-$LogRetentionDays)
    $Files = Get-ChildItem -Path $LogDir -Filter "*.log"
    foreach ($File in $Files) {
        if ($File.LastWriteTime -lt $LimitDate) {
            Remove-Item $File.FullName -Force
            Write-BotLog "Deleted old log: $($File.Name)"
        }
    }
}

# 1. Launcher-Owned Locking Design
if (Test-Path $LockFile) {
    $LockContent = Get-Content $LockFile -Raw
    # Expected format: launcher_pid|child_pid|started_at
    if ($LockContent -match '^(\d+)\|(\d+)\|(.+)$') {
        $StoredLauncherPid = [int]$Matches[1]
        $Proc = Get-Process -Id $StoredLauncherPid -ErrorAction SilentlyContinue

        if ($Proc) {
            Write-BotLog "ERROR: Another launcher instance is already running (PID: $StoredLauncherPid). Refusing to launch." "ERROR"
            exit 1
        } else {
            Write-BotLog "Found stale launcher lock (PID $StoredLauncherPid is gone). Cleaning up..." "WARN"
            Remove-Item $LockFile -Force
        }
    } else {
        Write-BotLog "Found malformed lock file. Cleaning up..." "WARN"
        Remove-Item $LockFile -Force
    }
}

Rotate-Logs
Write-BotLog "Starting Autonomous Live Bot Launcher..."

# Launcher Identity
$LauncherPid = $PID
$RetryCount = 0
$MaxRetries = 10
$RetryDelay = 30 # seconds

while ($true) {
    try {
        Write-BotLog "Launching bot process..."

        # PS 5.1 compatible environment variable injection
        $env:BOT_MANAGED_BY_LAUNCHER = "true"

        $Process = Start-Process python -ArgumentList $BotScript -PassThru `
            -RedirectStandardOutput "$LogDir\bot_stdout_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" `
            -RedirectStandardError "$LogDir\bot_stderr_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" `
            -WindowStyle Hidden

        # Restore environment variable immediately after launch
        $env:BOT_MANAGED_BY_LAUNCHER = "false"

        $BotPid = $Process.Id
        $StartTime = Get-Date

        # Update lock with Launcher ownership and Child identity
        $LockData = "$LauncherPid|$BotPid|$($StartTime.ToString('o'))"
        Set-Content -Path $LockFile -Value $LockData

        Write-BotLog "Bot launched successfully (PID: $BotPid). Monitoring..."

        # Wait for the process to exit
        $Process.WaitForExit()

        # Capture actual exit code reliably
        $ExitCodeValue = $Process.ExitCode
        $FormattedExitCode = if ($null -eq $ExitCodeValue) { "UNKNOWN" } else { $ExitCodeValue }
        Write-BotLog "Bot process (PID: $BotPid) exited with code $FormattedExitCode." "WARN"

    } catch {
        Write-BotLog "Failed to launch bot: $($_.Exception.Message)" "ERROR"
        $ExitCodeValue = -1
    }

    # 2. Health Check and Counter Reset
    if ($StartTime) {
        $Duration = (Get-Date) - $StartTime
        if ($Duration.TotalSeconds -gt 300) { # 5 min threshold
            $RetryCount = 0
            Write-BotLog "Bot ran healthily for $($Duration.TotalMinutes) mins. Resetting crash counter."
        }
    }

    # 3. Crash Recovery & Rapid Loop Prevention
    # Note: We KEEP the lock file during recovery delay to prevent duplicate launchers
    $RetryCount++
    if ($RetryCount -gt $MaxRetries) {
        Write-BotLog "Max retries ($MaxRetries) reached. Stopping launcher to prevent rapid crash loop." "ERROR"
        Remove-Item $LockFile -Force
        break
    }

    Write-BotLog "Restarting bot in $RetryDelay seconds... (Attempt $RetryCount/$MaxRetries)" "WARN"
    Start-Sleep -Seconds $RetryDelay
}
