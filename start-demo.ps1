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
    .\start-demo.ps1 -Stop            # tear the whole stack back down
#>
[CmdletBinding()]
param(
    [switch] $SkipGlasses,
    [switch] $SkipPhone,
    [switch] $Stop
)

$ErrorActionPreference = 'Stop'

$BackendRoot = 'D:\Study\innostar\app_demo_backend'
$GlassesRoot = 'D:\Study\innostar\Sever_test'
$AppServerUrl = 'http://127.0.0.1:8001'
$LogDir      = Join-Path $GlassesRoot 'logs'
$Adb         = 'D:\tmp\app-demo-android-toolchain\android-sdk\platform-tools\adb.exe'
$AppPackage  = 'com.youreyes.app'
$ComposeFile = Join-Path $BackendRoot 'infra\compose.yaml'

# The running container was created with this password, and `docker compose up`
# recreates the container whenever the resolved environment differs from what it
# was created with. infra/compose.yaml has no .env next to it, so without this
# the default (app_demo_dev_only) would churn the container on every start.
# Postgres only reads POSTGRES_PASSWORD at initdb time, so the value that
# matters is the one already inside the volume: apps/backend/.env's.
if (-not $env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD = 'app_demo_password' }

function Stop-Listener {
    param([int] $Port, [string] $What)

    $owners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $owners) { Write-Host "  skip  nothing on $Port ($What)" -ForegroundColor Yellow; return }
    foreach ($processId in $owners) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Host "  OK   stopped PID $processId on $Port ($What)" -ForegroundColor Green
    }
}

if ($Stop) {
    Write-Host "`nStopping the demo stack" -ForegroundColor Cyan
    Stop-Listener -Port 8000 -What 'glasses server'
    Stop-Listener -Port 8001 -What 'app communication server'
    docker compose -f $ComposeFile stop postgres 2>&1 | Out-Null
    Write-Host "  OK   postgres container stopped" -ForegroundColor Green
    Write-Host "`nStack is down.`n" -ForegroundColor Cyan
    return
}

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
# `compose up` rather than `docker start`: it recreates the container if someone
# removed it, and `--wait` blocks on the compose healthcheck (pg_isready), not on
# the TCP port. Docker publishes port 5432 the moment the container starts, so a
# port check returns true seconds before Postgres can answer a query -- that race
# is exactly how the backend ends up serving 500s on its first request.
Write-Host "`n[1/4] PostgreSQL" -ForegroundColor Cyan
docker compose -f $ComposeFile up -d --wait postgres
if ($LASTEXITCODE -ne 0) {
    throw "docker compose could not bring postgres up healthy (is Docker Desktop running?)"
}
Write-Host "  OK   postgres healthy on 5432" -ForegroundColor Green

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
            -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '0.0.0.0', '--port', '8000' `
            -WorkingDirectory $GlassesRoot `
            -RedirectStandardOutput "$LogDir\glasses8000.log" `
            -RedirectStandardError  "$LogDir\glasses8000.err.log" `
            -WindowStyle Hidden
    }
    Wait-Until -What 'glasses /health' -Check { Test-Http 'http://127.0.0.1:8000/health' } -TimeoutSeconds 300
}

# Pairing is idempotent, so re-asserting it every start costs nothing and
# removes "did anyone unlink the glasses?" from the list of demo-day unknowns.
Write-Host "`n[pairing] glasses-123 -> user-100" -ForegroundColor Cyan
$pair = Invoke-RestMethod -Method Post -Uri "$AppServerUrl/api/v1/device/glasses/link" `
    -Headers @{
        Authorization = 'Bearer _W7kNZRwdQC9jawhJr7ji_TJ6JzUI5igkHQrE6oAQKE'
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

Stack is up. The glasses only need to POST /process from here.

  glasses server   http://127.0.0.1:8000/process   (multipart: image + audio)
  app server       $AppServerUrl
  logs             $LogDir

  curl -X POST http://127.0.0.1:8000/process ``
    -F "image=@storage/request1.jpg" -F "audio=@command.wav" --output reply.mp3

Still manual on the phone, once per session:
  1. Open the app and tap Dang ky, so the FCM token is fresh. A stale token
     makes every action fail with DELIVERY_FAILED / NotRegistered.
  2. Leave the app running - do not force-stop it.
"@ -ForegroundColor Cyan
