# run_bot.ps1
# ==============================================================================
# Autonomous Live Bot Launcher for Windows (Hardened v3)
# ==============================================================================

$ProjectRoot = "C:\Users\Admin\ai-strategy-lab"
$BotScript = "$ProjectRoot\live_main.py"
$LogDir = "$ProjectRoot\logs"
$LockFile = "$ProjectRoot\bot.lock"
$LogRetentionDays = 7

# Named Mutex for race-condition protection
$MutexName = "Global\ai-strategy-lab-launcher-mutex"

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

# --- MUTEX ACQUISITION ---
Write-BotLog "Acquiring launcher mutex..."
$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$mutexAcquired = $false
try {
    # Attempt to acquire the mutex.
    # If the previous owner crashed, this will throw System.Threading.AbandonedMutexException.
    if ($Mutex.WaitOne(0)) {
        $mutexAcquired = $true
        Write-BotLog "Mutex acquired successfully."
    } else {
        Write-BotLog "ERROR: Another launcher instance is already owning the mutex. Refusing to launch." "ERROR"
        exit 1
    }
} catch [System.Threading.AbandonedMutexException] {
    $mutexAcquired = $true
    Write-BotLog "Detected abandoned mutex from a previous instance. Recovering ownership as the new authoritative launcher."
} catch {
    Write-BotLog "ERROR: Mutex acquisition failed: $($_.Exception.Message)" "ERROR"
    exit 1
}

# --- PROJECT-SCOPED CLEANUP ---
function Cleanup-ProjectProcesses {
    Write-BotLog "Performing project-scoped process cleanup..."

    # 1. Identify the authoritative pair if a lock exists
    $AuthLauncherPid = $null
    $AuthChildPid = $null
    if (Test-Path $LockFile) {
        $LockContent = Get-Content $LockFile -Raw
        if ($LockContent -match '^(\d+)\|(\d+)\|(.+)\|(.+)\|(.+)$') {
            $AuthLauncherPid = [int]$Matches[1]
            $AuthChildPid = [int]$Matches[2]
        }
    }

    # 2. Find all project-related processes
    # We look for processes whose CommandLine contains the ProjectRoot
    $AllProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$ProjectRoot*" }

    foreach ($Proc in $AllProcs) {
        $CurrentPid = $Proc.ProcessId
        $CmdLine = $Proc.CommandLine

        # Protection: Do not kill the current launcher
        if ($CurrentPid -eq $PID) { continue }

        # Protection: Do not kill the authoritative pair
        if ($AuthLauncherPid -and $CurrentPid -eq $AuthLauncherPid) {
            Write-BotLog "Protecting authoritative launcher (PID: $CurrentPid)."
            continue
        }
        if ($AuthChildPid -and $CurrentPid -eq $AuthChildPid) {
            Write-BotLog "Protecting authoritative child (PID: $CurrentPid)."
            continue
        }

        # Terminate Orphans/Duplicates
        Write-BotLog "Terminating orphan/duplicate project process (PID: $CurrentPid, Cmd: $CmdLine)" "WARN"
        Stop-Process -Id $CurrentPid -Force -ErrorAction SilentlyContinue
    }
}

Cleanup-ProjectProcesses
Rotate-Logs
Write-BotLog "Starting Autonomous Live Bot Launcher..."

# Launcher Identity
$LauncherPid = $PID
$SessionUuid = [guid]::NewGuid().ToString()
$RetryCount = 0
$MaxRetries = 10
$RetryDelay = 30 # seconds

Write-BotLog "Session UUID: $SessionUuid"
Write-BotLog "Launcher PID: $LauncherPid"

while ($true) {
    try {
        Write-BotLog "Launching bot process..."

        # Environment injection
        $env:BOT_MANAGED_BY_LAUNCHER = "true"
        $env:SESSION_UUID = $SessionUuid

        $Process = Start-Process 'C:\Users\Admin\AppData\Local\Python\bin\python.exe' -ArgumentList $BotScript -PassThru `
            -RedirectStandardOutput "$LogDir\bot_stdout_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" `
            -RedirectStandardError "$LogDir\bot_stderr_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" `
            -WindowStyle Hidden

        # Restore environment variable immediately after launch
        $env:BOT_MANAGED_BY_LAUNCHER = "false"

        $BotPid = $Process.Id
        $StartTime = Get-Date

        # ATOMIC LOCK WRITE
        # Format: launcher_pid|child_pid|started_at|project_path|session_uuid
        $LockData = "$LauncherPid|$BotPid|$($StartTime.ToString('o'))|$ProjectRoot|$SessionUuid"
        $TempLockFile = "$LockFile.tmp"
        Set-Content -Path $TempLockFile -Value $LockData
        Move-Item -Path $TempLockFile -Destination $LockFile -Force

        Write-BotLog "Bot launched successfully (PID: $BotPid). Monitoring..."
        Write-BotLog "Child PID: $BotPid"

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
    $RetryCount++
    if ($RetryCount -gt $MaxRetries) {
        Write-BotLog "Max retries ($MaxRetries) reached. Stopping launcher to prevent rapid crash loop." "ERROR"
        Remove-Item $LockFile -Force
        break
    }

    Write-BotLog "Restarting bot in $RetryDelay seconds... (Attempt $RetryCount/$MaxRetries)" "WARN"
    Start-Sleep -Seconds $RetryDelay
}

# Final Cleanup
if ($mutexAcquired) {
    $Mutex.ReleaseMutex()
}
$Mutex.Dispose()
Write-BotLog "Mutex released. Launcher exiting."
