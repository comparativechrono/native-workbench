param([string]$Output = "blast-native-build")
$ErrorActionPreference = 'Stop'
$Output = [IO.Path]::GetFullPath($Output)
$Root = Split-Path $PSScriptRoot -Parent
New-Item -ItemType Directory -Force $Output | Out-Null
function Checked-Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
function Download-Pinned([string]$Url, [string]$Name, [string]$Sha) {
    $Path = Join-Path $Output $Name
    if (!(Test-Path $Path)) { Invoke-WebRequest $Url -OutFile $Path }
    if ((Get-FileHash $Path -Algorithm SHA256).Hash.ToLower() -ne $Sha) { throw "Hash mismatch: $Name" }
    return $Path
}
$SourceHash = '502057a88e9990e34e62758be21ea474cc0ad68d6a63a2e37b2372af1e5ea147'
$SqliteHash = '1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032'
$Source = Download-Pinned 'https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-src.tar.gz' 'source.tar.gz' $SourceHash
$Sqlite = Download-Pinned 'https://www.sqlite.org/2025/sqlite-amalgamation-3500400.zip' 'sqlite.zip' $SqliteHash
$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$Vs = & $VsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$Vs) { throw 'A licensed Visual Studio build environment with C++ x64 tools is required.' }
$DevCmd = Join-Path $Vs 'Common7\Tools\VsDevCmd.bat'
cmd /c "`"$DevCmd`" -arch=x64 -host_arch=x64 >nul && set" | ForEach-Object {
    $Pair = $_ -split '=',2
    if ($Pair.Count -eq 2 -and $Pair[0]) { [Environment]::SetEnvironmentVariable($Pair[0],$Pair[1],'Process') }
}
$Extracted = Join-Path $Output 'source'
New-Item -ItemType Directory -Force $Extracted | Out-Null
Checked-Run 'tar' @('-xzf',$Source,'-C',$Extracted,'--strip-components=1')
$MakeDbSource = Join-Path $Extracted 'c++\src\app\blastdb\makeblastdb.cpp'
$BeforePatch = (Get-FileHash $MakeDbSource -Algorithm SHA256).Hash.ToLower()
if ($BeforePatch -ne 'b555dc444f7da23b4ee2566908e7cf9922644e8f8bac87a1f6a0c5a298e78ab4') { throw 'Unexpected makeblastdb source before patch' }
$MakeDbText = [IO.File]::ReadAllText($MakeDbSource)
$Original = 'CSeqDB sdb(new_db, t);'
$Replacement = 'CSeqDB sdb("\"" + new_db + "\"", t);'
if (($MakeDbText.Split($Original).Count - 1) -ne 1) { throw 'BLAST space-path patch context changed' }
[IO.File]::WriteAllText($MakeDbSource,$MakeDbText.Replace($Original,$Replacement),[Text.UTF8Encoding]::new($false))
$AfterPatch = (Get-FileHash $MakeDbSource -Algorithm SHA256).Hash.ToLower()
if ($AfterPatch -ne 'c65d73d28f92eda26d20efd658e409990d23531e719284ef3dce60688231d4a4') { throw 'Unexpected makeblastdb source after patch' }
Checked-Run 'python' @((Join-Path $Root 'tools\blast\apply_local_only_patch.py'),'--source-root',$Extracted,'--report',(Join-Path $Output 'offline-patch-record.json'))
$OfflinePatches = Get-Content -Raw (Join-Path $Output 'offline-patch-record.json') | ConvertFrom-Json
$SqliteRoot = Join-Path $Output 'sqlite'
Expand-Archive -Path $Sqlite -DestinationPath $SqliteRoot -Force
$SqliteSource = Join-Path $SqliteRoot 'sqlite-amalgamation-3500400'
New-Item -ItemType Directory -Force (Join-Path $SqliteRoot 'include'),(Join-Path $SqliteRoot 'lib') | Out-Null
Copy-Item (Join-Path $SqliteSource '*.h') (Join-Path $SqliteRoot 'include')
Checked-Run 'cl.exe' @('/nologo','/c','/O2','/MT','/DSQLITE_THREADSAFE=1',('/Fo'+(Join-Path $SqliteRoot 'sqlite3.obj')),(Join-Path $SqliteSource 'sqlite3.c'))
Checked-Run 'lib.exe' @('/nologo',('/OUT:'+(Join-Path $SqliteRoot 'lib\sqlite3.lib')),(Join-Path $SqliteRoot 'sqlite3.obj'))
$Build = Join-Path $Output 'build'
$Targets = @('blastn','blastp','blastx','tblastn','makeblastdb','blast_formatter')
$Configuration = @('-S',(Join-Path $Extracted 'c++\src'),'-B',$Build,'-G','Visual Studio 17 2022','-A','x64',
    '-DBUILD_SHARED_LIBS=OFF','-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded','-DNCBI_PTBCFG_CONFIGURATION_TYPES=Release',
    '-DCMAKE_CONFIGURATION_TYPES=Release','-DNCBI_PTBCFG_PROJECT_FEATURES=CfgMT',
    ('-DNCBI_PTBCFG_PROJECT_TARGETS='+($Targets -join ';')),
    '-DNCBI_COMPONENT_SQLITE3_FOUND=ON',('-DNCBI_COMPONENT_SQLITE3_INCLUDE='+(Join-Path $SqliteRoot 'include')),
    ('-DNCBI_COMPONENT_SQLITE3_LIBS='+(Join-Path $SqliteRoot 'lib\sqlite3.lib')),
    '-DNCBI_PTBCFG_PROJECT_COMPONENTS=-NGHTTP2;-VDB;-ZSTD;-GNUTLS')
Checked-Run 'cmake' $Configuration
Checked-Run 'cmake' (@('--build',$Build,'--config','Release','--parallel','2','--target')+$Targets)
$Bin = Join-Path $Output 'bin'
New-Item -ItemType Directory -Force $Bin | Out-Null
$Inventory = @()
foreach ($Target in $Targets) {
    $Found = @(Get-ChildItem $Output -Recurse -File -Filter ($Target+'.exe') | Where-Object { $_.FullName -ne (Join-Path $Bin ($Target+'.exe')) })
    if ($Found.Count -ne 1) { throw "Expected exactly one built executable for $Target; found $($Found.Count)" }
    $Dest = Join-Path $Bin ($Target+'.exe')
    Copy-Item $Found[0].FullName $Dest
    $Imports = (& dumpbin /nologo /dependents $Dest | Out-String)
    $Imports | Set-Content (Join-Path $Output ($Target+'-imports.txt'))
    if ($Imports -match '(?i)(MSVCP[0-9_]*|VCRUNTIME[0-9_]*|ucrtbase|nghttp2|sqlite3)\.dll') { throw "Unexpected external runtime dependency in $Target" }
    $Version = (& $Dest -version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch '2\.17\.0') { throw "Version/startup failed: $Target" }
    $Inventory += @{name=$Target+'.exe';sha256=(Get-FileHash $Dest -Algorithm SHA256).Hash.ToLower();version=$Version;imports=$Imports}
}
Checked-Run 'cl.exe' @('/nologo','/std:c++17','/EHsc','/O2','/MT',('/Fe:'+(Join-Path $Bin 'blast-guard.exe')),('/Fo'+(Join-Path $Output 'guard.obj')),(Join-Path $Root 'tools\blast\guard.cpp'))
$GuardImports = (& dumpbin /nologo /dependents (Join-Path $Bin 'blast-guard.exe') | Out-String)
$GuardImports | Set-Content (Join-Path $Output 'blast-guard-imports.txt')
if ($GuardImports -match '(?i)(MSVCP[0-9_]*|VCRUNTIME[0-9_]*|ucrtbase)\.dll') { throw 'Guard has an external runtime dependency' }
@{schema=1;tool='NCBI BLAST+';version='2.17.0';sourceSha256=$SourceHash;sqliteSha256=$SqliteHash;sqliteVersion='3.50.4';
  sourcePatched=$true;patch='Quote makeblastdb metadata database path for the existing BLAST database-list parser';
  patchSha256=(Get-FileHash (Join-Path $Root 'tools\blast\makeblastdb-space-path.patch') -Algorithm SHA256).Hash.ToLower();
  patchedSourceBeforeSha256=$BeforePatch;patchedSourceAfterSha256=$AfterPatch;
  offlinePatches=$OfflinePatches;
  configuration=$Configuration;compiler=@{path=(Get-Command cl.exe).Source;fileVersion=(Get-Item (Get-Command cl.exe).Source).VersionInfo.FileVersion};binaries=$Inventory;
  adapterSha256=(Get-FileHash (Join-Path $Bin 'blast-guard.exe') -Algorithm SHA256).Hash.ToLower();
  adapterImports=$GuardImports;
  adapterSourceSha256=(Get-FileHash (Join-Path $Root 'tools\blast\guard.cpp') -Algorithm SHA256).Hash.ToLower();
  windowsStartupTested=$true;scientificTestsPerformed=$false;runtime='Static MSVC runtime, built with /MT in Visual Studio environment'} |
    ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $Output 'build-provenance.json')
