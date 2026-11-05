@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "TTS_ROOT=%~dp0"
cd /d "%TTS_ROOT%"
if not exist ".tools\uv.exe" (
  echo Installing uv from its official GitHub release...
  powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $d=Join-Path $env:TTS_ROOT '.tools'; New-Item -ItemType Directory -Force -Path $d | Out-Null; $z=Join-Path $d 'uv-windows.zip'; $s=Join-Path $d 'uv-windows.sha256'; $u='https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip'; Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $z; Invoke-WebRequest -UseBasicParsing -Uri ($u+'.sha256') -OutFile $s; $expected=(Get-Content -Raw $s).Trim().Substring(0,64); if((Get-FileHash $z -Algorithm SHA256).Hash -ne $expected){throw 'uv checksum mismatch'}; $unpack=Join-Path $d 'uv-windows'; Expand-Archive -Path $z -DestinationPath $unpack -Force; $exe=Get-ChildItem -Path $unpack -Recurse -Filter uv.exe | Select-Object -First 1; if(-not $exe){throw 'uv.exe missing'}; Copy-Item -LiteralPath $exe.FullName -Destination (Join-Path $d 'uv.exe') -Force"
  if errorlevel 1 goto fail
)
".tools\uv.exe" run --no-project --no-config --python 3.12 launcher.py %*
if errorlevel 1 goto fail
exit /b 0
:fail
echo Launch failed. See the message above.
pause
exit /b 1
