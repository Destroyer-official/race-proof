[CmdletBinding()]
param(
    [switch]$AutoTune,
    [switch]$Diagnose,
    [string]$ModelPath,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppPath = Join-Path $ScriptRoot 'destroyer_ai_final.py'

if ($AutoTune -and $Diagnose) {
    throw 'Choose either -AutoTune or -Diagnose, not both.'
}
if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
    throw "Application file not found: $AppPath"
}

# This PC's known Vulkan SDK. An existing environment setting takes priority.
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

# Explicit -Python wins, then DESTROYER_PYTHON, then the known interpreter,
# then python.exe from PATH. Each candidate must import the exact runtime API.
$PythonCandidates = @()
if ($Python) { $PythonCandidates += $Python.Trim('"') }
if ($env:DESTROYER_PYTHON) { $PythonCandidates += $env:DESTROYER_PYTHON.Trim('"') }
$PythonCandidates += 'D:\program_software\sdks\Python315\python.exe'
$PathPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($PathPython) { $PythonCandidates += $PathPython.Source }

$ProbePath = Join-Path ([IO.Path]::GetTempPath()) (
    'destroyer_python_probe_{0}.py' -f [Guid]::NewGuid().ToString('N')
)
$ProbeSource = @'
import sys
try:
    import rich
    import jinja2
    import llama_cpp
    from llama_cpp import Llama
    from llama_cpp.llama_chat_format import Jinja2ChatFormatter
except Exception as exc:
    print("IMPORT_ERROR:", type(exc).__name__, str(exc))
    raise
print("PYTHON_OK", sys.version.split()[0])
print("LLAMA_CPP", getattr(llama_cpp, "__version__", "version-unknown"))
print("LLAMA_CPP_PATH", getattr(llama_cpp, "__file__", "unknown"))
print("RICH_PATH", getattr(rich, "__file__", "unknown"))
print("JINJA2_PATH", getattr(jinja2, "__file__", "unknown"))
'@
Set-Content -LiteralPath $ProbePath -Value $ProbeSource -Encoding UTF8

$PythonExe = $null
$ProbeFailures = @()
try {
    foreach ($Candidate in ($PythonCandidates | Select-Object -Unique)) {
        if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            continue
        }

        $ProbeOutput = @(& $Candidate $ProbePath 2>&1)
        $ProbeExitCode = $LASTEXITCODE
        if ($ProbeExitCode -eq 0) {
            $PythonExe = $Candidate
            Write-Host "Selected Python: $Candidate" -ForegroundColor Green
            $ProbeOutput | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
            break
        }

        $ProbeFailures += "Candidate: $Candidate"
        $ProbeFailures += ($ProbeOutput | Select-Object -Last 8 | ForEach-Object { [string]$_ })
    }
}
finally {
    Remove-Item -LiteralPath $ProbePath -Force -ErrorAction SilentlyContinue
}

if (-not $PythonExe) {
    Write-Host 'Python candidates failed the dependency/import probe:' -ForegroundColor Red
    $ProbeFailures | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    throw 'No usable Python interpreter found. Install rich and Jinja2 into the same Python environment as the Vulkan-enabled llama-cpp-python, or set DESTROYER_PYTHON.'
}

if ($ModelPath) {
    $ResolvedModel = Resolve-Path -LiteralPath $ModelPath -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $ResolvedModel.Path -PathType Leaf)) {
        throw "ModelPath is not a file: $ModelPath"
    }
    $env:DESTROYER_MODEL_PATH = $ResolvedModel.Path
}

$Arguments = @($AppPath)
if ($AutoTune) { $Arguments += '--autotune' }
if ($Diagnose) { $Arguments += '--diagnose' }

Write-Host "Launching Destroyer AI with: $PythonExe" -ForegroundColor Cyan
if ($env:VULKAN_SDK) { Write-Host "Vulkan SDK: $env:VULKAN_SDK" -ForegroundColor DarkGray }
& $PythonExe @Arguments
$AppExitCode = $LASTEXITCODE
exit $AppExitCode
