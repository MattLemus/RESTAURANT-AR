param(
    [string]$BindAddress = '127.0.0.1',
    [int]$Port = 8765,
    [string]$Certificate = '',
    [string]$PrivateKey = '',
    [string]$Adb = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$scanPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $scanPython)) { $scanPython = (Get-Command python -ErrorAction Stop).Source }
& $scanPython -c 'from PIL import Image'
if ($LASTEXITCODE -ne 0) { throw 'Falta Pillow. Instala requirements.txt en el Python elegido.' }
if ([bool]$Certificate -ne [bool]$PrivateKey) { throw 'Indica Certificate y PrivateKey juntos.' }
if ($Adb) {
    & $Adb reverse "tcp:$Port" "tcp:$Port"
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo conectar por USB. Autoriza depuración USB y revisa adb devices.' }
}
$scanArguments = @('captura/servidor.py', '--host', $BindAddress, '--port', "$Port")
if ($Certificate) { $scanArguments += @('--cert', $Certificate, '--key', $PrivateKey) }
Write-Host 'Capturador inteligente: /capturar.html (puerto distinto del estudio COLMAP)'
Write-Host "Android USB: abre http://localhost:$Port/capturar.html después de adb reverse."
Write-Host 'Wi-Fi: requiere HTTPS con certificado confiable para el celular.'
Write-Host 'No se publica ni se abre un túnel. Mantén esta consola abierta.'
& $scanPython @scanArguments
exit $LASTEXITCODE
