$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$cliArgs = @($args)
if (-not $cliArgs -or $cliArgs.Count -eq 0) {
    if ([Environment]::UserInteractive -and [Console]::IsOutputRedirected -eq $false) {
        Write-Host "=================================================================" -ForegroundColor Cyan
        Write-Host "  RaceProof v0.2.0 - Concurrency Verification Engine             " -ForegroundColor White
        Write-Host "  Native Rust Core: Online | 31 Labeled Ground-Truth Scenarios    " -ForegroundColor DarkCyan
        Write-Host "=================================================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  [1] Interactive Terminal Dashboard (TUI) [Default]" -ForegroundColor Green
        Write-Host "  [2] Run Benchmark Suite (31 Ground-Truth Scenarios)" -ForegroundColor Yellow
        Write-Host "  [3] Verify Attack Capture (verify -i ...)" -ForegroundColor Cyan
        Write-Host "  [4] Formal Concurrency Proof (prove -i ...)" -ForegroundColor Magenta
        Write-Host "  [5] Synthesize Reproduction PoC (hunt -t ...)" -ForegroundColor Yellow
        Write-Host "  [6] CLI Command Reference & Help" -ForegroundColor White
        Write-Host "  [Q] Exit" -ForegroundColor DarkGray
        Write-Host ""
        $choice = Read-Host "Select option [1-6, or press Enter for TUI]"
        if ($choice -eq "2") {
            $cliArgs = @("bench")
        } elseif ($choice -eq "3") {
            $f = Read-Host "Path to finding file [Default: race_proof_bench/fintech/bench_fin_001.json]"
            if (-not $f) { $f = "race_proof_bench/fintech/bench_fin_001.json" }
            $cliArgs = @("verify", "-i", $f)
        } elseif ($choice -eq "4") {
            $f = Read-Host "Path to session file [Default: race_proof_bench/fintech/bench_fin_001.json]"
            if (-not $f) { $f = "race_proof_bench/fintech/bench_fin_001.json" }
            $cliArgs = @("prove", "-i", $f)
        } elseif ($choice -eq "5") {
            $u = Read-Host "Target URL [Default: https://api.test/coupon]"
            if (-not $u) { $u = "https://api.test/coupon" }
            $cliArgs = @("hunt", "--target", $u)
        } elseif ($choice -eq "6") {
            $cliArgs = @()
        } elseif ($choice -eq "q" -or $choice -eq "Q") {
            exit 0
        } else {
            $cliArgs = @("tui")
        }
    } else {
        $cliArgs = @()
    }
}

# Set PYTHONPATH to include the race-proof package root
$env:PYTHONPATH = "$ScriptRoot;$env:PYTHONPATH"

# Locate Python 3.15 or current Python
$PythonExe = "python.exe"
$KnownPython = 'D:\program_software\sdks\Python315\python.exe'
if (Test-Path -LiteralPath $KnownPython -PathType Leaf) {
    $PythonExe = $KnownPython
}

# Set Vulkan SDK if present
if (-not $env:VULKAN_SDK) {
    $KnownSdk = 'D:\program_software\VulkanSDK\1.4.363.1'
    if (Test-Path -LiteralPath $KnownSdk -PathType Container) {
        $env:VULKAN_SDK = $KnownSdk
    }
}
if ($env:VULKAN_SDK) {
    $VulkanBin = Join-Path $env:VULKAN_SDK 'Bin'
    if (Test-Path -LiteralPath $VulkanBin -PathType Container) {
        $env:PATH = "$VulkanBin;$env:PATH"
    }
}

Write-Host "Launching RaceProof with: $PythonExe" -ForegroundColor Cyan
& $PythonExe -m race_proof.cli @cliArgs
exit $LASTEXITCODE
