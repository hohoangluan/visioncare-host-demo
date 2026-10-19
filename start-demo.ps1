<#
.SYNOPSIS
    Brings up the whole demo stack: PostgreSQL, App Communication Server (8001),
    the glasses server (8000), the glasses pairing, and the handset permissions.
    After this the glasses only have to POST /process — everything downstream to
    the phone runs on its own.

.EXAMPLE
    .\start-demo.ps1
    .\start-demo.ps1 -SkipGlasses     # backend only, when testing the local API
    .\start-demo.ps1 -SkipPhone       # when the handset is not on USB
#>
[CmdletBinding()]
param(
    [switch] $SkipGlasses,
    [switch] $SkipPhone
)

$ErrorActionPreference = 'Stop'

# Đường dẫn máy bạn đặt trong .env (xem .env.example); mặc định là thư mục
# anh em của repo này. Biến đã có trong môi trường thì không bị .env ghi đè.
$GlassesRoot = $PSScriptRoot
$EnvFile = Join-Path $GlassesRoot '.env'
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and -not $line.TrimStart().StartsWith('#')) {
            if (-not [Environment]::GetEnvironmentVariable($Matches[1])) {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'))
            }
        }
    }
}
$BackendRoot = if ($env:VISIONCARE_BACKEND_ROOT) { $env:VISIONCARE_BACKEND_ROOT } else { Join-Path (Split-Path $GlassesRoot -Parent) 'app-demo-backend' }
$AppServerUrl = 'http://127.0.0.1:8001'
$LogDir      = Join-Path $GlassesRoot 'logs'
$Adb         = if ($env:ADB_PATH) { $env:ADB_PATH } else { 'adb' }
$AppPackage  = 'com.youreyes.app'

# One ephemeral secret is inherited by both child processes. It is never
# written to source control or printed. The backend callback is loopback-only.
if (-not $env:VISIONCARE_CALLBACK_TOKEN) {
    $env:VISIONCARE_CALLBACK_TOKEN = [guid]::NewGuid().ToString('N')
}
$env:CALLBACK_URL = 'http://127.0.0.1:8000/internal/action-results'
$env:CALLBACK_TOKEN = $env:VISIONCARE_CALLBACK_TOKEN
$env:CALLBACK_ALLOWED_HOSTS = '127.0.0.1'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Wait-Until {
    param([scriptblock] $Check, [string] $What, [int] $TimeoutSeconds = 180)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Check) { Write-Host "  OK   $What" -ForegroundColor Green; return }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $What"
}

function Test-Http {
    param([string] $Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing `
            -Headers @{ 'User-Agent' = 'VisionCare-Glasses/1.0' }
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# 1. PostgreSQL -------------------------------------------------------------
Write-Host "`n[1/4] PostgreSQL" -ForegroundColor Cyan
docker start app-demo-postgres-1 2>&1 | Out-Null
Wait-Until -What 'postgres accepting connections on 5432' -Check {
    (Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 `
        -InformationLevel Quiet -WarningAction SilentlyContinue)
}

# 2. App Communication Server on 8001 ----------------------------------------
Write-Host "`n[2/4] App Communication Server -> 127.0.0.1:8001" -ForegroundColor Cyan
if (Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue) {
    Write-Host "  skip  something already listening on 8001" -ForegroundColor Yellow
} else {
    Start-Process -FilePath "$BackendRoot\apps\backend\.venv\Scripts\python.exe" `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--app-dir', 'src',
                      '--host', '0.0.0.0', '--port', '8001' `
        -WorkingDirectory "$BackendRoot\apps\backend" `
        -RedirectStandardOutput "$LogDir\backend8001.log" `
        -RedirectStandardError  "$LogDir\backend8001.err.log" `
        -WindowStyle Hidden
}
Wait-Until -What 'backend /health/ready' -Check { Test-Http 'http://127.0.0.1:8001/health/ready' }

# 3. Glasses server on 8000 -------------------------------------------------
if ($SkipGlasses) {
    Write-Host "`n[3/4] Glasses server skipped (-SkipGlasses)`n" -ForegroundColor Yellow
} else {
    Write-Host "`n[3/4] Glasses server -> 0.0.0.0:8000 (loads STT+TTS, ~20-30s)" -ForegroundColor Cyan
    if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
        Write-Host "  skip  something already listening on 8000" -ForegroundColor Yellow
    } else {
        Start-Process -FilePath "$GlassesRoot\.venv\Scripts\python.exe" `
            -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '0.0.0.0', '--port', '8000', '--ws-max-size', '2100000' `
            -WorkingDirectory $GlassesRoot `
            -RedirectStandardOutput "$LogDir\glasses8000.log" `
            -RedirectStandardError  "$LogDir\glasses8000.err.log" `
            -WindowStyle Hidden
    }
    Wait-Until -What 'glasses /health' -Check { Test-Http 'http://127.0.0.1:8000/health' } -TimeoutSeconds 300
}

# Pairing is idempotent, so re-asserting it every start costs nothing and
# removes "did anyone unlink the glasses?" from the list of demo-day unknowns.
if (-not $env:VISIONCARE_DEVICE_CLIENT_TOKEN) { throw 'Thiếu VISIONCARE_DEVICE_CLIENT_TOKEN trong .env' }
Write-Host "`n[pairing] glasses-123 -> user-100" -ForegroundColor Cyan
$pair = Invoke-RestMethod -Method Post -Uri "$AppServerUrl/api/v1/device/glasses/link" `
    -Headers @{
        Authorization = "Bearer $($env:VISIONCARE_DEVICE_CLIENT_TOKEN)"
        'User-Agent'  = 'VisionCare-Glasses/1.0'
    } `
    -ContentType 'application/json' `
    -Body '{"user_id":"user-100","device_id":"glasses-123"}'
Write-Host "  linked = $($pair.data.linked)" -ForegroundColor Green

# 4. Handset permissions ----------------------------------------------------
# HyperOS resets several of these on every app reinstall, and silently reverts
# USE_FULL_SCREEN_INTENT on its own after a few minutes. Without it the launcher
# notification loses its full-screen intent and nothing opens while the screen
# is off, so re-asserting them at every start is the difference between a demo
# that runs hands-free and one that needs someone tapping notifications.
if ($SkipPhone) {
    Write-Host "`n[4/4] Handset setup skipped (-SkipPhone)" -ForegroundColor Yellow
} elseif (-not (Test-Path $Adb)) {
    Write-Host "`n[4/4] adb not found at $Adb - skipping handset setup" -ForegroundColor Yellow
} else {
    Write-Host "`n[4/4] Handset permissions" -ForegroundColor Cyan
    $attached = (& $Adb devices | Select-String -Pattern "\sdevice$")
    if (-not $attached) {
        Write-Host "  warn  no device on USB; phone-side setup not applied" -ForegroundColor Yellow
    } else {
        # Lets the launcher notification carry a full-screen intent (targetSdk 36
        # no longer grants this to non-calling apps).
        & $Adb shell appops set $AppPackage USE_FULL_SCREEN_INTENT allow | Out-Null
        & $Adb shell appops set $AppPackage SYSTEM_ALERT_WINDOW allow | Out-Null
        # MIUI-private op guarding background activity starts.
        & $Adb shell appops set $AppPackage 10020 allow | Out-Null
        # Gate on MediaSessionManager.getActiveSessions(), which is how music_play
        # presses play on YouTube Music's own session.
        & $Adb shell cmd notification allow_listener `
            "$AppPackage/$AppPackage.service.MediaControlListenerService" | Out-Null
        & $Adb shell dumpsys deviceidle whitelist "+$AppPackage" | Out-Null

        $fsi = (& $Adb shell appops get $AppPackage | Select-String -Pattern 'USE_FULL_SCREEN_INTENT: allow')
        if ($fsi) {
            Write-Host "  OK   full-screen intent, overlay, media sessions, battery exemption" -ForegroundColor Green
        } else {
            Write-Host "  warn  USE_FULL_SCREEN_INTENT did not stick - MIUI may have reverted it" -ForegroundColor Yellow
        }
    }
}

Write-Host @"

Stack is up. The glasses connect to WS /v2/session (see docs/FIRMWARE_ENDPOINTS.md);
POST /process is kept as the legacy path. Every glasses endpoint needs the device token
(VISIONCARE_DEVICE_CLIENT_TOKEN in .env); an empty token makes them all answer 503.
Note: the Linux GPU server runs on port 18888 behind the Cloudflare tunnel; this script's
8000 is the Windows demo only.

  glasses server   ws://127.0.0.1:8000/v2/session  (turn + audio + live on one socket)
                   http://127.0.0.1:8000/process    (legacy, multipart: image + audio)
  app server       $AppServerUrl
  logs             $LogDir

  curl -X POST http://127.0.0.1:8000/process ``
    -H "Authorization: Bearer <VISIONCARE_DEVICE_CLIENT_TOKEN>" ``
    -F "image=@storage/request1.jpg" -F "audio=@command.wav" --output reply.mp3

Still manual on the phone, once per session:
  1. Open the app and tap Dang ky, so the FCM token is fresh. A stale token
     makes every action fail with DELIVERY_FAILED / NotRegistered.
  2. Leave the app running - do not force-stop it.
"@ -ForegroundColor Cyan
