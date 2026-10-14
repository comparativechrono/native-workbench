# Windows PowerShell 5.1 / PowerShell 7. No policy changes or downloads.
param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Run this harness on Windows.' }
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root 'bin\windows\bwfastq.exe'
$Seqtk = Join-Path $Root 'bin\portable\seqtk.exe'
$Minimap = Join-Path $Root 'bin\portable\minimap2.exe'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $Root ('results\windows-' + [Guid]::NewGuid().ToString('N'))
}
$Work = New-Item -ItemType Directory -Path $OutputDirectory
$Checks = New-Object System.Collections.Generic.List[object]
function Quote-Argument([string]$Value) {
    if ($Value.Contains([char]0)) { throw 'NUL in argument' }
    $Escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $Escaped = [regex]::Replace($Escaped, '(\\+)$', '$1$1')
    return '"' + $Escaped + '"'
}
function Invoke-Tool([string]$Exe, [string[]]$Arguments) {
    $Start = New-Object System.Diagnostics.ProcessStartInfo
    $Start.FileName = $Exe
    $Start.Arguments = ($Arguments | ForEach-Object { Quote-Argument $_ }) -join ' '
    $Start.UseShellExecute = $false
    $Start.CreateNoWindow = $true
    $Start.RedirectStandardOutput = $true
    $Start.RedirectStandardError = $true
    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $Start
    [void]$Process.Start()
    $OutTask = $Process.StandardOutput.ReadToEndAsync()
    $ErrTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit(60000)) {
        $Process.Kill(); $Process.WaitForExit(); throw "Timeout: $Exe"
    }
    $Result = @{ Code=$Process.ExitCode; Stdout=$OutTask.Result; Stderr=$ErrTask.Result }
    $Process.Dispose()
    return $Result
}
function Check([string]$Name, [scriptblock]$Action) {
    try { & $Action; $Checks.Add(@{name=$Name;passed=$true}); Write-Host "PASS $Name" }
    catch { $Checks.Add(@{name=$Name;passed=$false;error=$_.Exception.Message}); Write-Host "FAIL $Name : $_" }
}
function Require([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
# Verify published executable bytes before running any tests.
$Manifest = Get-Content -Raw (Join-Path $Root 'manifest.json') | ConvertFrom-Json
foreach ($File in $Manifest.files) {
    if ($File.path -like 'bin/*.exe' -or $File.path -like 'bin/*/*.exe') {
        $Actual = (Get-FileHash -Algorithm SHA256 (Join-Path $Root $File.path)).Hash.ToLowerInvariant()
        if ($Actual -ne $File.sha256) { throw "Executable checksum mismatch: $($File.path)" }
    }
}
$InputFile = Join-Path $Work ('reads with spaces ' + [char]0x00e9 + [char]0x0394 + '.fastq')
Copy-Item (Join-Path $Root 'examples\tiny.fastq') $InputFile
$InputHash = (Get-FileHash $InputFile).Hash
$StatsFile = Join-Path $Work 'stats.json'
Check 'native version' {
    $R=Invoke-Tool $Bin @('--version'); Require ($R.Code -eq 0) $R.Stderr
}
Check 'statistics and Unicode paths' {
    $R=Invoke-Tool $Bin @('stats','--input',$InputFile,'--output',$StatsFile,'--threads','4')
    Require ($R.Code -eq 0) $R.Stderr
    $Actual=Get-Content -Raw $StatsFile | ConvertFrom-Json
    $Expected=Get-Content -Raw (Join-Path $Root 'examples\tiny.expected.json') | ConvertFrom-Json
    foreach($Key in @('records','bases','gc_bases','n_bases','min_length','max_length','phred33_sum')) {
        Require ($Actual.$Key -eq $Expected.$Key) "Statistic mismatch: $Key"
    }
}
Check 'existing outputs protected' {
    $Before=(Get-FileHash $StatsFile).Hash
    $R=Invoke-Tool $Bin @('stats','--input',$InputFile,'--output',$StatsFile)
    Require ($R.Code -ne 0) 'Existing output was accepted'
    Require ((Get-FileHash $StatsFile).Hash -eq $Before) 'Existing output changed'
}
Check 'malformed input rejected without output' {
    $Bad=Join-Path $Work 'bad.fastq'; $BadOut=Join-Path $Work 'bad.json'
    [IO.File]::WriteAllText($Bad,"@bad`nAC`n+`nI`n",[Text.Encoding]::ASCII)
    $R=Invoke-Tool $Bin @('stats','--input',$Bad,'--output',$BadOut)
    Require ($R.Code -eq 2) 'Wrong failure status'
    Require (-not (Test-Path $BadOut)) 'Failed result published'
    Require (@(Get-ChildItem $Work -Filter '*.partial.*').Count -eq 0) 'Temporary output leaked'
}
Check 'long read on four native workers' {
    $Long=Join-Path $Work 'long.fastq'; $LongOut=Join-Path $Work 'long.json'
    [IO.File]::WriteAllText($Long,"@long`n"+('ACGTN'*20000)+"`n+`n"+('I'*100000)+"`n",[Text.Encoding]::ASCII)
    $R=Invoke-Tool $Bin @('stats','--input',$Long,'--output',$LongOut,'--threads','4')
    Require ($R.Code -eq 0) $R.Stderr
    $S=Get-Content -Raw $LongOut | ConvertFrom-Json
    Require ($S.bases -eq 100000 -and $S.gc_bases -eq 40000 -and $S.phred33_sum -eq 4000000) 'Parallel statistics mismatch'
}
Check 'reverse complement twice' {
    $One=Join-Path $Work 'reverse.fastq';$Two=Join-Path $Work 'restored.fastq'
    $R=Invoke-Tool $Bin @('revcomp','--input',$InputFile,'--output',$One);Require ($R.Code -eq 0) $R.Stderr
    $R=Invoke-Tool $Bin @('revcomp','--input',$One,'--output',$Two);Require ($R.Code -eq 0) $R.Stderr
    Require ((Get-FileHash $Two).Hash -eq $InputHash) 'Round trip changed input'
}
Check 'portable seqtk matches custom module' {
    $R=Invoke-Tool $Seqtk @('seq','-r',$InputFile);Require ($R.Code -eq 0) $R.Stderr
    $Expected=[IO.File]::ReadAllText((Join-Path $Work 'reverse.fastq'))
    Require ($R.Stdout -eq $Expected) 'seqtk result differs'
}
Check 'portable minimap2 runs threaded alignment' {
    $R=Invoke-Tool $Minimap @('-a','-x','sr','-t','2',(Join-Path $Root 'examples\reference.fa'),(Join-Path $Root 'examples\reads.fastq'))
    Require ($R.Code -eq 0) $R.Stderr
    $Lines=@($R.Stdout -split "`n" | Where-Object { $_ -and -not $_.StartsWith('@') })
    Require ($Lines.Count -eq 20) 'Expected 20 alignment records'
    foreach($L in $Lines) { $F=$L.TrimEnd("`r").Split("`t"); Require (([int]$F[1] -band 4) -eq 0) 'Unexpected unmapped read' }
    [IO.File]::WriteAllText((Join-Path $Work 'alignment.sam'),$R.Stdout,[Text.Encoding]::ASCII)
}
Check 'input unchanged' { Require ((Get-FileHash $InputFile).Hash -eq $InputHash) 'Input changed' }
$Report=@{kind='native Windows smoke validation';utc=[DateTime]::UtcNow.ToString('o');os=[Environment]::OSVersion.VersionString;is64bit=[Environment]::Is64BitOperatingSystem;architecture=$env:PROCESSOR_ARCHITECTURE;powershell=$PSVersionTable.PSVersion.ToString();checks=$Checks.ToArray();passed=@($Checks|Where-Object{$_.passed}).Count;failed=@($Checks|Where-Object{-not $_.passed}).Count}
$Report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Work 'windows-validation.json')
Write-Host "Report: $(Join-Path $Work 'windows-validation.json')"
if($Report.failed -gt 0){exit 1}
