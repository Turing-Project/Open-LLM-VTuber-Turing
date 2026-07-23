$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot "release\Open-LLM-VTuber-Windows"
$python = (Get-Command python -ErrorAction Stop).Source
$toolPath = Join-Path $projectRoot ".packaging-tools"
$uvPath = (Get-Command uv -ErrorAction Stop).Source

if (-not (Test-Path (Join-Path $toolPath "PyInstaller"))) {
    & $python -m pip install --target $toolPath "pyinstaller==6.14.2"
}

$env:PYTHONPATH = $toolPath
& $python -m PyInstaller --noconfirm --clean (Join-Path $projectRoot "open-llm-vtuber-desktop.spec") --distpath (Join-Path $projectRoot "release\launcher") --workpath (Join-Path $projectRoot "build\desktop")

if (Test-Path $outputRoot) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}
New-Item -ItemType Directory -Force $outputRoot | Out-Null
$includeDirs = @(
    "avatars", "backgrounds", "characters", "config_templates", "emoji",
    "frontend", "gifs", "live2d-models", "models_code", "prompts", "src",
    "upgrade_codes", "web_tool"
)
$includeFiles = @(
    "conf.yaml", "LICENSE", "LICENSE-Live2D.md", "mcp_servers.json",
    "model_dict.json", "pyproject.toml", "run_server.py", "uv.lock"
)

foreach ($dir in $includeDirs) {
    Copy-Item (Join-Path $projectRoot $dir) $outputRoot -Recurse -Force
}
foreach ($file in $includeFiles) {
    Copy-Item (Join-Path $projectRoot $file) $outputRoot -Force
}
Copy-Item (Join-Path $projectRoot "release\launcher\Open-LLM-VTuber.exe") $outputRoot -Force
New-Item -ItemType Directory -Force (Join-Path $outputRoot "runtime") | Out-Null
Copy-Item $uvPath (Join-Path $outputRoot "runtime\uv.exe") -Force

$readme = @"
Open-LLM-VTuber Windows 桌面版

双击 Open-LLM-VTuber.exe 启动。
首次启动会自动准备 Python 环境和依赖，耗时取决于网络速度。
配置文件为 conf.yaml；运行日志位于：
%LOCALAPPDATA%\Open-LLM-VTuber\desktop-backend.log
"@
Set-Content (Join-Path $outputRoot "使用说明.txt") $readme -Encoding UTF8

$archive = Join-Path $projectRoot "release\Open-LLM-VTuber-Windows.zip"
if (Test-Path $archive) { Remove-Item $archive -Force }
Compress-Archive -Path (Join-Path $outputRoot "*") -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Desktop package created: $archive"
