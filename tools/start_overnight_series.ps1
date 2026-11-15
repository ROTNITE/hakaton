$ErrorActionPreference = 'Stop'
$runtime = 'D:\MetaRescue-output\releases\windows-verification-10-p0-ports-20261113\Распакованная сборка\MetaEvolution-Rescue'
$plan = 'D:\MetaRescue-output\series\competition-design-02-r3\plan.json'
$acceptance = 'D:\MetaRescue-output\checks\p0-release-followup-20261113-03\verification.json'
$python = Join-Path $runtime 'python\python.exe'
$runner = Join-Path $runtime 'tools\run_native_series.py'
$logDir = 'D:\MetaRescue-output\series\overnight-launch-logs'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    foreach ($path in @($python, $runner, $plan, $acceptance)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required file: $path. Wait for candidate09 verification to finish." }
    }
    $report = Get-Content -LiteralPath $acceptance -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($report.passed -ne $true) { throw "Candidate09 acceptance did not pass: $acceptance" }
    $hash = (Get-FileHash -LiteralPath $plan -Algorithm SHA256).Hash
    if ($hash -ne '92395633b0ed4a0d367e67415354f5a09bf4302861c5e85d5ea0c63e3be9567e') { throw 'The frozen series plan hash does not match.' }
    $active = Get-Process UnrealEditor, UnrealEditor-Cmd, MetaRescue -ErrorAction SilentlyContinue
    if ($active) { throw 'Unreal or MetaRescue is already running. Wait for the current work to finish.' }
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $log = Join-Path $logDir ("launch-{0}.log" -f [guid]::NewGuid().ToString('N'))
    Start-Transcript -LiteralPath $log | Out-Null
    Write-Host "Runtime: $runtime`nLog: $log"
    Set-Location -LiteralPath $runtime
    $env:METARESCUE_OUTPUT = 'D:\MetaRescue-output'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONPATH = ''
    Write-Host 'Pilot: first five cases.'
    & $python -B -X utf8 $runner $plan --limit 5
    if ($LASTEXITCODE -notin @(0, 2)) { throw "First pilot stage failed: exit $LASTEXITCODE" }
    Write-Host 'Pilot: heavy S6 case.'
    & $python -B -X utf8 $runner $plan --case S6-04-O1-dual-global-local
    if ($LASTEXITCODE -notin @(0, 2)) { throw "S6 pilot stage failed: exit $LASTEXITCODE" }
    $design = Get-Content -LiteralPath $plan -Raw -Encoding UTF8 | ConvertFrom-Json
    $ids = @($design.runs | Select-Object -First 5 | ForEach-Object { $_.id }) + @('S6-04-O1-dual-global-local')
    foreach ($id in $ids) {
        $attempts = Get-ChildItem -LiteralPath (Join-Path (Join-Path (Split-Path $plan) 'execution') $id) -Filter 'attempt-*.json'
        $complete = @($attempts | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } | Where-Object { $_.complete -eq $true })
        if ($complete.Count -eq 0) { throw "Pilot case did not complete: $id" }
    }
    Write-Host 'Pilot passed. Starting or resuming the full series.'
    & $python -B -X utf8 $runner $plan
    if ($LASTEXITCODE -ne 0) { throw "Series incomplete: runner exit $LASTEXITCODE. Review the log and retry after investigating." }
    Write-Host 'All 450 cases have verified archives.'
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
