param([string]$Python='python',[Parameter(Mandatory=$true)][string]$Results)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath $Results) { throw '结果目录已存在，请换新目录，保留旧日志。' }
New-Item -ItemType Directory -Path $Results | Out-Null
$resultRoot=(Resolve-Path -LiteralPath $Results).Path
$patterns=@('test_ctflab_supervisor_fault.py','test_ctflab_acceptance_session.py',
    'test_ctflab_guest_policy.py','test_ctflab_guest_agent.py','test_ctflab_guest_channel.py',
    'test_ctflab_guest_contract.py','test_ctflab_guest_kit.py','test_ctflab_mirror.py',
    'test_ctflab_desktop_bridge.py','test_ctflab_desktop_package.py','test_ctflab_content_cache.py',
    'test_ctflab_release_store.py','test_ctflab_release_update.py','test_ctflab_release_launcher.py',
    'test_ctflab_qemu_driver.py','test_ctflab_windows_recovery.py',
    'test_ctflab_generation_store.py','test_ctflab_scenario_v2.py','test_ctflab_runtime_inventory.py',
    'test_ctflab_linux_native.py','test_ctflab_network.py','test_ctflab_roadmap_offline.py',
    'test_ctflab_guest_routes.py','test_ctflab_policy_review.py','test_ctflab_oci.py',
    'test_ctflab_remote.py','test_ctflab_remote_assets.py','test_ctflab_remote_leases.py',
    'test_ctflab_remote_audit.py','test_ctflab_worker_audit.py','test_ctflab_audit_review.py',
    'test_ctflab_desktop_remote.py','test_ctflab_desktop_leases.py',
    'test_ctflab_client_store.py','test_ctflab_client_assets.py')
$summaries=@()
foreach ($pattern in $patterns) {
    $name=[IO.Path]::GetFileNameWithoutExtension($pattern)
    $stdout=Join-Path $resultRoot ($name+'.stdout.log')
    $stderr=Join-Path $resultRoot ($name+'.stderr.log')
    $process=Start-Process -FilePath $Python -ArgumentList @('-B','-m','unittest','discover','-s','tools/tests','-p',$pattern,'-v') -WorkingDirectory $sourceRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $text=Get-Content -LiteralPath $stderr -Raw
    $count=0; $skipped=0
    if ($text -match 'Ran (\d+) tests?') { $count=[int]$Matches[1] }
    if ($text -match 'skipped=(\d+)') { $skipped=[int]$Matches[1] }
    $state=if ($process.ExitCode -eq 0 -and $count -gt 0) {'passed'} else {'failed'}
    $summaries+=[ordered]@{suite=$pattern;exit_code=$process.ExitCode;count=$count;skipped=$skipped;result=$state}
    Write-Output ($name+': '+$state+' / '+$count+' 项，跳过 '+$skipped)
}
$report=[ordered]@{schema=1;scope='source-tests-not-guest-or-installer-acceptance';vm_operations=$false;g0_passed=$false;g1_passed=$false;suites=$summaries}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resultRoot 'summary.json') -Encoding UTF8
if (@($summaries | Where-Object {$_.result -ne 'passed'}).Count -gt 0) { throw '有专项失败；已完成全部可运行专项并保留日志，不继续VM操作。' }
Write-Output '源码专项完成；跳过和未测仍单列，不代表来宾、网络、课程或安装器验收通过。'
