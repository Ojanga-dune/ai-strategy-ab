# tests/test_launcher_recovery.ps1
# Hardened Regression Test for Launcher Mutex Abandonment Recovery

$ProjectRoot = "C:\Users\Admin\ai-strategy-lab"
$LauncherScript = "$ProjectRoot\run_bot.ps1"
$LockFile = "$ProjectRoot\bot.lock"
$LogDir = "$ProjectRoot\logs"

function Get-BotProcesses {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$ProjectRoot*" }
}

function Cleanup-ProjectProcesses {
    Write-Host "[CLEANUP] Terminating project launcher and child processes..." -ForegroundColor Gray
    $Procs = Get-BotProcesses
    foreach ($P in $Procs) {
        $CurrentPid = $P.ProcessId
        $CmdLine = $P.CommandLine
        
        # Protection: Exclude the current test process
        if ($CurrentPid -eq $PID) { continue }

        # Restrict to specific script execution to avoid killing unrelated project tools
        if ($CmdLine -match "run_bot\.ps1" -or $CmdLine -match "live_main\.py") {
            Stop-Process -Id $CurrentPid -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path $LockFile) { Remove-Item $LockFile -Force }
}

Write-Host "--- STARTING HARDENED LAUNCHER RECOVERY TEST ---" -ForegroundColor Cyan

try {
    # 1. Start Launcher A
    Write-Host "[STEP 1] Starting Launcher A..."
    $ProcA = Start-Process powershell -ArgumentList "-File $LauncherScript" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5

    $ProcsA = Get-BotProcesses
    $LaunchersA = $ProcsA | Where-Object { $_.CommandLine -match "run_bot\.ps1" }
    $ChildrenA = $ProcsA | Where-Object { $_.CommandLine -match "live_main\.py" }

    if ($LaunchersA.Count -ne 1 -or $ChildrenA.Count -ne 1) {
        throw "Baseline failed: Expected 1 launcher and 1 child, found $($LaunchersA.Count) launchers and $($ChildrenA.Count) children."
    }
    $LauncherAPid = $LaunchersA[0].ProcessId
    $ChildAPid = $ChildrenA[0].ProcessId
    
    # Capture Launcher A's Session UUID
    if (!(Test-Path $LockFile)) { throw "Lock file missing after Launcher A start." }
    $LockA = Get-Content $LockFile -Raw
    $PartsA = $LockA.Split('|')
    if ($PartsA.Count -lt 5) { throw "Invalid lock file format for Launcher A." }
    $SessionUuidA = $PartsA[4]
    
    # Capture Log Baseline (Path and Byte Length)
    $LogBaselineFile = Get-ChildItem $LogDir -Filter "bot_launcher_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $LogBaselineFile) { throw "No launcher log found for baseline." }
    $LogBaselinePath = $LogBaselineFile.FullName
    $LogBaselineLength = (Get-Item $LogBaselinePath).Length
    
    Write-Host "Baseline established: LauncherA($LauncherAPid), ChildA($ChildAPid), UUID($SessionUuidA)"

    # 2. Force-kill Launcher A (create abandoned mutex)
    Write-Host "[STEP 2] Force-killing Launcher A to create abandoned mutex..."
    Stop-Process -Id $LauncherAPid -Force
    Start-Sleep -Seconds 2

    # Verify Child A state
    $ProcsAfterKill = Get-BotProcesses
    $OrphanA = $ProcsAfterKill | Where-Object { $_.ProcessId -eq $ChildAPid }
    if ($null -ne $OrphanA) {
        Write-Host "Child A survived as orphan (PID: $ChildAPid)."
    } else {
        Write-Host "Child A terminated with launcher."
    }

    # 3. Start Launcher B
    Write-Host "[STEP 3] Starting Launcher B (should recover abandoned mutex)..."
    $ProcB = Start-Process powershell -ArgumentList "-File $LauncherScript" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5

    $ProcsB = Get-BotProcesses
    $LaunchersB = $ProcsB | Where-Object { $_.CommandLine -match "run_bot\.ps1" }
    $ChildrenB = $ProcsB | Where-Object { $_.CommandLine -match "live_main\.py" }

    if ($LaunchersB.Count -ne 1 -or $ChildrenB.Count -ne 1) {
        throw "Recovery failed: Expected 1 launcher and 1 child, found $($LaunchersB.Count) launchers and $($ChildrenB.Count) children."
    }
    $LauncherBPid = $LaunchersB[0].ProcessId
    $ChildBPid = $ChildrenB[0].ProcessId
    Write-Host "Recovery successful: LauncherB($LauncherBPid), ChildB($ChildBPid)"

    # 4. Verify Child A is gone
    $ProcsFinal = Get-BotProcesses
    if ($ProcsFinal | Where-Object { $_.ProcessId -eq $ChildAPid }) {
        throw "Orphan Child A (PID: $ChildAPid) was NOT terminated by Launcher B."
    }
    Write-Host "Verified: Orphan Child A terminated."

    # 5. Verify Child B is distinct
    if ($ChildBPid -eq $ChildAPid) {
        throw "Child B PID is identical to Child A PID."
    }

    # 6. Strict Lock Validation
    $LockB = Get-Content $LockFile -Raw
    $PartsB = $LockB.Split('|')
    if ($PartsB.Count -lt 5) { throw "Invalid lock file format for Launcher B." }
    
    $LockLauncherPid = [int]$PartsB[0]
    $LockChildPid = [int]$PartsB[1]
    $SessionUuidB = $PartsB[4]

    if ($LockLauncherPid -ne $LauncherBPid) { throw "Lock Launcher PID ($LockLauncherPid) != Actual ($LauncherBPid)" }
    if ($LockChildPid -ne $ChildBPid) { throw "Lock Child PID ($LockChildPid) != Actual ($ChildBPid)" }
    if ($SessionUuidB -eq $SessionUuidA) { throw "Session UUID did not change between A and B." }
    Write-Host "Verified: bot.lock is internally consistent and updated."

    # 7. Verify Log Recovery Message (Appended Content Only)
    $LatestLog = Get-ChildItem $LogDir -Filter "bot_launcher_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $LatestLog) { throw "No launcher log found after recovery." }
    
    if ($LatestLog.FullName -eq $LogBaselinePath) {
        $Reader = $null
        try {
            $Reader = [System.IO.File]::OpenText($LatestLog.FullName)
            $Reader.BaseStream.Seek($LogBaselineLength, [System.IO.SeekOrigin]::Begin)
            $Reader.DiscardBufferedData()
            $NewContent = $Reader.ReadToEnd()
        } finally {
            if ($null -ne $Reader) { $Reader.Dispose() }
        }
    } else {
        $NewContent = Get-Content $LatestLog.FullName -Raw
    }

    if ($NewContent -notmatch "Detected abandoned mutex from a previous instance") {
        throw "Recovery message not found in appended launcher log content."
    }
    Write-Host "Verified: Abandoned mutex recovery logged in new content."

    # 8. Verify Launcher C is rejected (bounded timeout)
    Write-Host "[STEP 8] Verifying Launcher C is rejected..."
    $ProcC = Start-Process powershell -ArgumentList "-File $LauncherScript" -PassThru -WindowStyle Hidden
    
    $timeout = 10
    $elapsed = 0
    while ($true) {
        if ($ProcC.HasExited) { break }
        if ($elapsed -ge $timeout) { 
            Stop-Process -Id $ProcC.Id -Force
            throw "Launcher C did not exit within $timeout seconds."
        }
        Start-Sleep -Seconds 1
        $elapsed++
    }

    if ($ProcC.ExitCode -eq 0) {
        throw "Launcher C was incorrectly allowed to start (Exit Code 0)."
    }
    Write-Host "Launcher C correctly rejected (Exit Code: $($ProcC.ExitCode))."

    Write-Host "--- ALL RECOVERY TESTS PASSED ---" -ForegroundColor Green

} catch {
    Write-Host "TEST FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Cleanup-ProjectProcesses
}
