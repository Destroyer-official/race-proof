$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$cliArgs = @($args)
if (-not $cliArgs -or $cliArgs.Count -eq 0) {
    $cliArgs = @("tui")
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
