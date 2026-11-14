$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$port = 8765
$baseUrl = "http://localhost:$port"
$captureUrl = "$baseUrl/capturar.html?v=3"
$python = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Falta el Python del proyecto en .venv.' }
$adbOnPath = Get-Command adb.exe -ErrorAction SilentlyContinue
$adbCandidates = @(
    (Join-Path $PWD 'platform-tools\adb.exe'),
    (Join-Path $PWD 'tools\platform-tools\adb.exe'),
    (Join-Path $env:USERPROFILE 'Downloads\platform-tools-latest-windows\platform-tools\adb.exe'),
    (Join-Path $env:USERPROFILE 'Downloads\platform-tools\adb.exe')
)
if ($adbOnPath) { $adbCandidates += $adbOnPath.Source }
$adb = $adbCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $adb) { throw 'No encuentro adb.exe. Coloca Platform Tools en Descargas o dentro del proyecto.' }

function Test-CaptureServer {
    try {
        $status = Invoke-RestMethod -Uri "$baseUrl/subir/estado" -TimeoutSec 2
        return $status.version -eq 3
    } catch { return $false }
}

if (-not (Test-CaptureServer)) {
    $logDirectory = Join-Path $PWD 'captura\trabajos\_runtime'
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $outLog = Join-Path $logDirectory 'capturador.log'
    $errorLog = Join-Path $logDirectory 'capturador-error.log'
    $server = Start-Process -FilePath $python -ArgumentList '-u captura/servidor.py --port 8765' `
        -WorkingDirectory $PWD.Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errorLog
    $ready = $false
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        if ($server.HasExited) { break }
        if (Test-CaptureServer) { $ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        throw 'El capturador no pudo iniciar. Si esta abierta la consola anterior de INICIAR_CAPTURADOR, cierrala con Ctrl+C y abre este BAT de nuevo.'
    }
}

$devices = @(& $adb devices)
if ($LASTEXITCODE -ne 0) { throw 'ADB no pudo consultar el telefono.' }
$readyDevices = @($devices | Where-Object { $_ -match '^\S+\s+device\s*$' })
if ($readyDevices.Count -ne 1) { throw 'Conecta un solo Android, desbloquealo y permite la depuracion USB. Luego abre el BAT de nuevo.' }
$serial = ($readyDevices[0] -split '\s+')[0]
& $adb -s $serial reverse 'tcp:8765' 'tcp:8765'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo conectar el capturador por USB.' }
& $adb -s $serial shell am start -a android.intent.action.VIEW -d $captureUrl -p com.android.chrome
if ($LASTEXITCODE -ne 0) { Write-Host "Abre $captureUrl en Chrome del telefono." }
Write-Host 'Capturador listo. Espera el aviso Captura sin cable lista antes de desconectar.'
