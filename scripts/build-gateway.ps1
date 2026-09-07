# Build the standalone CaberOS gateway executable for Windows.
#
# Mirrors scripts/build-gateway.sh. The one deliberate difference is the
# --add-data separator: PyInstaller uses ':' on POSIX and ';' on Windows.
# Keeping the colon here does not error — PyInstaller reads the whole string
# as a path, silently omits the bundled data, and the app then starts with no
# default agents and no MCP catalog, with nothing in the log pointing at the
# cause. gateway_entry.py asserts the data is present for that reason.

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"
$ResourceDir = Join-Path $RootDir "frontend\src-tauri\resources"
$GatewayOutputDir = Join-Path $ResourceDir "gateway"
$BuildDir = Join-Path $BackendDir "build\pyinstaller"

foreach ($dir in @($ResourceDir, $GatewayOutputDir, (Join-Path $BuildDir "work"), (Join-Path $BuildDir "spec"))) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

Set-Location $BackendDir

$defaultsSrc = Join-Path $BackendDir "src\agentos\defaults"
$catalogSrc = Join-Path $BackendDir "src\agentos\mcp\catalog.yaml"

uv run pyinstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name caberos-gateway `
    --paths src `
    --distpath "$GatewayOutputDir" `
    --workpath "$(Join-Path $BuildDir 'work')" `
    --specpath "$(Join-Path $BuildDir 'spec')" `
    --collect-submodules agentos `
    --collect-all aiosqlite `
    --collect-all litellm `
    --collect-all tiktoken `
    --collect-all ddgs `
    --collect-all primp `
    --collect-submodules tiktoken_ext `
    --add-data "$defaultsSrc;agentos/defaults" `
    --add-data "$catalogSrc;agentos/mcp" `
    src\agentos\gateway_entry.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exePath = Join-Path $GatewayOutputDir "caberos-gateway\caberos-gateway.exe"
if (-not (Test-Path $exePath)) { throw "Expected gateway executable not found at $exePath" }

# Fail here rather than shipping an app that boots with no agents.
$bundledDefaults = Join-Path $GatewayOutputDir "caberos-gateway\_internal\agentos\defaults"
if (-not (Test-Path $bundledDefaults)) {
    throw "Bundled defaults missing at $bundledDefaults - check the --add-data separator (Windows needs ';')"
}

Write-Output "Built $exePath"

# Copy system-level skills into the Tauri resources directory so they get
# bundled into the desktop app and AGENTOS_SKILLS_DIR can point at them.
$SkillsResourceDir = Join-Path $ResourceDir "skills"
$SkillsSrc = Join-Path $RootDir "skills"
if (Test-Path $SkillsSrc) {
    if (Test-Path $SkillsResourceDir) { Remove-Item -Recurse -Force $SkillsResourceDir }
    Copy-Item -Recurse -Force $SkillsSrc $SkillsResourceDir
    Write-Output "Copied skills to $SkillsResourceDir"
}
