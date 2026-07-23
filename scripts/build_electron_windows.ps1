$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$clientRoot = Join-Path $projectRoot "electron-client"
$backendRoot = Join-Path $clientRoot "backend"
$uvPath = (Get-Command uv -ErrorAction Stop).Source

if (Test-Path $backendRoot) {
    Remove-Item -LiteralPath $backendRoot -Recurse -Force
}
New-Item -ItemType Directory -Force $backendRoot | Out-Null

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
    Copy-Item (Join-Path $projectRoot $dir) $backendRoot -Recurse -Force
}
foreach ($file in $includeFiles) {
    Copy-Item (Join-Path $projectRoot $file) $backendRoot -Force
}
New-Item -ItemType Directory -Force (Join-Path $backendRoot "runtime") | Out-Null
Copy-Item $uvPath (Join-Path $backendRoot "runtime\uv.exe") -Force
Copy-Item (Join-Path $projectRoot "overlay.js") (Join-Path $clientRoot "src\renderer\public\overlay.js") -Force

$env:npm_config_cache = Join-Path $clientRoot ".npm-cache"
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
Push-Location $clientRoot
try {
    cmd /c npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
    cmd /c npm run build:win
    if ($LASTEXITCODE -ne 0) { throw "Electron build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host "Electron installer created under: $clientRoot\release"
