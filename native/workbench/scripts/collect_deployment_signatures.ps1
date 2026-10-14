# Observe the exact inventoried executable files. This script neither signs
# files nor changes execution policy, trust stores, network or security policy.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundleRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256,
    [Parameter(Mandatory = $true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$diagnosticStage = 'startup'

function Assert-NoReparse([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Reparse points are not accepted.'
        }
        if ($item -is [IO.FileInfo]) { $item = $item.Directory }
        else { $item = $item.Parent }
    }
}

function Certificate-PublicFields($Certificate) {
    if ($null -eq $Certificate) { return $null }
    return [ordered]@{
        subject = $Certificate.Subject
        issuer = $Certificate.Issuer
        thumbprint = $Certificate.Thumbprint
        notBefore = $Certificate.NotBefore.ToUniversalTime().ToString('o')
        notAfter = $Certificate.NotAfter.ToUniversalTime().ToString('o')
    }
}

function Test-PortableExecutable([string]$Path, [long]$Length) {
    if ($Length -lt 64) { return $false }
    $stream = [IO.File]::OpenRead($Path)
    $reader = New-Object IO.BinaryReader($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D) { return $false }
        [void]$stream.Seek(60, [IO.SeekOrigin]::Begin)
        $offset = $reader.ReadUInt32()
        if ($offset -lt 64 -or $offset -gt 1048576 -or $offset -gt ($Length - 4)) { return $false }
        [void]$stream.Seek($offset, [IO.SeekOrigin]::Begin)
        return $reader.ReadUInt32() -eq 0x00004550
    }
    finally { $reader.Dispose() }
}

try {
    # A Windows PowerShell grandchild of pwsh -> Python can inherit the pwsh
    # module search path and resolve shared names to incompatible PS7 modules.
    # Select only the modules shipped with this system PowerShell by exact
    # manifest path. This does not modify policy, trust or PSModulePath.
    # https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_psmodulepath
    $diagnosticStage = 'system-modules'
    foreach ($moduleName in @('Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Utility', 'Microsoft.PowerShell.Security')) {
        $modulePath = [IO.Path]::Combine($PSHOME, 'Modules', $moduleName, $moduleName + '.psd1')
        Import-Module -Name $modulePath -ErrorAction Stop
    }
    $diagnosticStage = 'root-check'
    Assert-NoReparse $BundleRoot
    $root = [IO.Path]::GetFullPath($BundleRoot).TrimEnd('\', '/')
    $diagnosticStage = 'manifest-check'
    $manifestPath = Join-Path $root 'deployment-manifest.json'
    Assert-NoReparse $manifestPath
    $manifestItem = Get-Item -LiteralPath $manifestPath
    if ($manifestItem.Length -gt 8388608) { throw 'Manifest exceeds the supported bound.' }
    if ((Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ManifestSha256) {
        throw 'Manifest identity differs.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.sourceCommit -cne 'e855dc4396e0c16ae35f4e840eb9cc734adb4441' -or
        $manifest.toolkitCommit -cnotmatch '^[0-9a-f]{40}$' -or $manifest.toolkitDirty -eq $true) {
        throw 'Invalid immutable bundle source identity.'
    }
    $files = @($manifest.files)
    if ($files.Count -lt 1 -or $files.Count -gt 20000) { throw 'Invalid inventory size.' }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $inventory = @()
    $diagnosticStage = 'inventory-check'
    # Validate and hash the COMPLETE manifest inventory before signature helpers.
    foreach ($entry in $files) {
        $relative = [string]$entry.path
        if ($relative.Length -lt 1 -or $relative.Length -gt 1024 -or $relative -match '[:\\\x00-\x1f]' -or
            $relative.StartsWith('/') -or $relative -eq 'deployment-manifest.json' -or -not $seen.Add($relative)) {
            throw 'Unsafe or duplicate inventory path.'
        }
        foreach ($part in $relative.Split('/')) {
            if ($part -eq '' -or $part -eq '.' -or $part -eq '..' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
                $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { throw 'Unsafe path component.' }
        }
        $path = Join-Path $root $relative
        Assert-NoReparse $path
        $item = Get-Item -LiteralPath $path
        if ($item -isnot [IO.FileInfo] -or $entry.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $item.Length -ne $entry.bytes -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) {
            throw 'Inventoried file identity differs.'
        }
        # Updater content-addressed blobs preserve PE files without .exe/.dll
        # names. Observe those same bytes as well; unsupported trust resolution
        # remains explicit rather than silently excluding the file.
        if ([IO.Path]::GetExtension($relative).ToLowerInvariant() -in @('.exe', '.dll', '.pyd') -or
            (Test-PortableExecutable $path $item.Length)) {
            $inventory += $entry
        }
    }
    $diagnosticStage = 'output-check'
    $output = [IO.Path]::GetFullPath($OutputPath)
    if ($output.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
        $output.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        (Test-Path -LiteralPath $output) -or [IO.Path]::GetExtension($output) -ne '.json') {
        throw 'Output must be a new JSON file outside the immutable bundle.'
    }
    $parent = [IO.Path]::GetDirectoryName($output)
    Assert-NoReparse $parent
    $observations = @()
    $diagnosticStage = 'signature-observation'
    foreach ($entry in $inventory) {
        $observedAt = [DateTime]::UtcNow.ToString('o')
        $status = 'Unavailable'
        $state = 'unavailable'
        $signer = $null
        $timestampSigner = $null
        try {
            $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $root $entry.path)
            $status = [string]$signature.Status
            switch ($status) {
                'Valid' { $state = 'valid-in-current-trust-context' }
                'NotSigned' { $state = 'unsigned' }
                'HashMismatch' { $state = 'invalid' }
                'NotTrusted' { $state = 'untrusted-in-current-trust-context' }
                default { $state = 'unavailable' }
            }
            $signer = Certificate-PublicFields $signature.SignerCertificate
            $timestampSigner = Certificate-PublicFields $signature.TimeStamperCertificate
        }
        catch {
            # Exceptions may contain a private local path. Retain a bounded
            # unavailable observation instead of exporting exception messages.
            $status = 'Unavailable'
            $state = 'unavailable'
        }
        $observations += [ordered]@{
            path = $entry.path
            bytes = $entry.bytes
            sha256 = $entry.sha256
            observedAt = $observedAt
            signatureStatus = $status
            observationState = $state
            signerCertificate = $signer
            timestampCertificate = $timestampSigner
        }
    }
    $report = [ordered]@{
        schemaVersion = 1
        kind = 'native-workbench-authenticode-observations'
        bundleManifestSha256 = $ManifestSha256
        sourceCommit = $manifest.sourceCommit
        toolkitCommit = $manifest.toolkitCommit
        observedAt = [DateTime]::UtcNow.ToString('o')
        method = 'Get-AuthenticodeSignature -LiteralPath, under unchanged current Windows policy and trust configuration'
        moduleResolution = 'Management, Utility and Security modules are selected by their exact built-in manifests under the running system Windows PowerShell installation; inherited module search paths are not used to select them.'
        selectionScope = 'Inventoried PE content, including extensionless updater blobs, plus .exe/.dll/.pyd paths. Script formats (.py/.cmd/.ps1) and other inventory kinds are not checked by this collector.'
        trustLimit = 'Status is an observation, not institutional approval. Offline or restricted trust resolution can be unavailable; checksums do not establish publisher identity. No execution policy, trust store or security control was changed.'
        files = @($observations)
    }
    $diagnosticStage = 'write-observations'
    $text = $report | ConvertTo-Json -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $stream = New-Object IO.FileStream($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = $encoding.GetBytes($text + [Environment]::NewLine)
        $stream.Write($bytes, 0, $bytes.Length)
    }
    finally { $stream.Dispose() }
    exit 0
}
catch {
    # No error message, invocation text, stack or file path is exported. The
    # invoking Python helper accepts only this small, explicitly typed record.
    # Do not depend on Utility/ConvertTo-Json here: module initialization itself
    # may be the failure. Values are fixed stage labels, a checked public .NET
    # type identifier and an integer, never an exception message or path.
    $errorType = $_.Exception.GetType().FullName
    if ($errorType.Length -gt 160 -or $errorType -cnotmatch '^(System\.|Microsoft\.)[A-Za-z0-9_.+`]+$') {
        $errorType = 'System.Exception'
    }
    $scriptLine = [int]$_.InvocationInfo.ScriptLineNumber
    if ($scriptLine -lt 0 -or $scriptLine -gt 100000) { $scriptLine = 0 }
    [Console]::Out.WriteLine('NW_SIGNATURE_DIAGNOSTIC {"schemaVersion":1,"stage":"' +
        $diagnosticStage + '","errorType":"' + $errorType + '","scriptLine":' +
        $scriptLine.ToString([Globalization.CultureInfo]::InvariantCulture) + '}')
    exit 2
}
