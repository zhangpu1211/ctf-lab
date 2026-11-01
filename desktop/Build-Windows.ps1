param(
    [Parameter(Mandatory=$true)][string]$PythonRoot,
    [Parameter(Mandatory=$true)][string]$QemuRoot,
    [Parameter(Mandatory=$true)][string]$QemuInventory,
    [Parameter(Mandatory=$true)][string]$BuildRoot
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw '此入口只在 Windows 原生环境构建安装包。' }
$BuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
$sourceRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $PythonRoot 'python.exe'
$packageTool = Join-Path $sourceRoot 'tools\ctflab_desktop_package.py'
if (Test-Path -LiteralPath $BuildRoot) { throw '构建目录已存在；请使用新目录，原目录不会覆盖。' }
function Run-Python {
    & $pythonExe -I -B $packageTool @args
    if ($LASTEXITCODE -ne 0) { throw '运行时准备失败；保留现场，请检查本轮输出。' }
}
Run-Python workspace --destination $BuildRoot
$pythonInventory = Join-Path $BuildRoot 'python-inventory.json'
$staging = Join-Path $BuildRoot 'payload'
Run-Python python-inventory --root $PythonRoot --output $pythonInventory
$stageResult = Run-Python stage --destination $staging --python-root $PythonRoot --python-inventory $pythonInventory --qemu-root $QemuRoot --qemu-inventory $QemuInventory --inspect-imports | ConvertFrom-Json
$manifestSha = $stageResult.manifest_sha256
if ($stageResult.state -ne 'staged' -or $manifestSha -notmatch '^[0-9a-f]{64}$') { throw '未取得本轮暂存清单摘要，停止构建。' }
$stageResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $BuildRoot 'stage-result.json') -Encoding UTF8
Run-Python probe --destination $staging --manifest-sha256 $manifestSha
# 每次使用独立编译目录，不能把以前留下的安装器当成本轮产物。
$previousTarget = $env:CARGO_TARGET_DIR
$env:CARGO_TARGET_DIR = Join-Path $BuildRoot 'target'
Push-Location $PSScriptRoot
try {
    & npm ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw '前端依赖未准备完成。' }
    & npm test
    if ($LASTEXITCODE -ne 0) { throw '桌面模型测试失败。' }
    & node (Join-Path $PSScriptRoot 'node_modules/@tauri-apps/cli/tauri.js') build --config (Join-Path $staging 'tauri.bundle.json')
    if ($LASTEXITCODE -ne 0) { throw '原生安装包构建失败；日志和暂存目录保留。' }
    $installers = @(Get-ChildItem -LiteralPath (Join-Path $env:CARGO_TARGET_DIR 'release\bundle\nsis') -Filter '*.exe')
    if ($installers.Count -eq 0) { throw '没有生成NSIS安装资产，不能记为构建成功。' }
    Run-Python verify --destination $staging --manifest-sha256 $manifestSha
    $artifactRoot = Join-Path $BuildRoot 'installers'
    New-Item -ItemType Directory -Path $artifactRoot | Out-Null
    $results = @($installers | ForEach-Object {
        $target = Join-Path $artifactRoot $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $target -ErrorAction Stop
        $signature = Get-AuthenticodeSignature -LiteralPath $target
        [ordered]@{ name=$_.Name; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(); signature_status=[string]$signature.Status; clean_machine_tested=$false }
    })
    $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $BuildRoot 'installer-results.json') -Encoding UTF8
    Write-Output '构建步骤完成。未签名资产仅用于封闭测试；干净机离线、更新回退和课程验收另列。实验数据不会被构建脚本清理。'
} finally { Pop-Location; $env:CARGO_TARGET_DIR = $previousTarget }
