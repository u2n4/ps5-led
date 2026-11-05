# EXE-only Windows installer. No Python, package installation or source fallback.
# irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | iex
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "DualLED-Pro"),
    [string]$Version = "latest",
    [switch]$NoLaunch,
    [switch]$NoShortcut
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-PS5LEDDownload {
    param([string]$Uri, [string]$OutFile)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            if ($OutFile) { Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $OutFile }
            else {
                $content = (Invoke-WebRequest -UseBasicParsing -Uri $Uri).Content
                # Decode before returning: PowerShell enumerates a returned byte array.
                if ($content -is [byte[]]) { $content = [Text.Encoding]::UTF8.GetString($content) }
                return $content
            }
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Write-Warning "Download attempt $attempt failed; retrying..."
            Start-Sleep -Seconds 3
        }
    }
}

function New-PS5LEDShortcut {
    param([string]$Executable, [string]$WorkingDirectory)
    # CreateShortcut().Save() fails in a non-ASCII folder, so the .lnk is saved in this user's own TEMP.
    # If TEMP is not ASCII, its 8.3 short path is used. No shared folder is ever used: without an ASCII
    # private folder the shortcut is skipped with a warning, and the install still succeeds.
    $folder = $env:TEMP
    if ($folder -match '[^\x00-\x7F]') {
        if (-not ('PS5LED.ShortPath' -as [type])) {
            Add-Type -Namespace PS5LED -Name ShortPath -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode, SetLastError = true)]
public static extern uint GetShortPathName(string longPath, System.Text.StringBuilder shortPath, uint bufferLength);
'@
        }
        $buffer = New-Object System.Text.StringBuilder 32767
        $length = [PS5LED.ShortPath]::GetShortPathName($folder, $buffer, $buffer.Capacity)
        $folder = if ($length -gt 0 -and $length -lt $buffer.Capacity) { $buffer.ToString(0, [int]$length) } else { "" }
    }
    if (-not $folder -or $folder -match '[^\x00-\x7F]' -or -not (Test-Path -LiteralPath $folder -PathType Container)) {
        Write-Warning "No private ASCII folder for the shortcut (TEMP is missing, not ASCII, or has no usable 8.3 short path). The desktop shortcut was skipped; PS5 LED is still installed."
        return
    }
    $desktop = [Environment]::GetFolderPath("Desktop")
    $temporary = Join-Path $folder ("ps5led-" + [guid]::NewGuid().ToString("N") + ".lnk")
    $sibling = Join-Path $desktop ("PS5 LED-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($temporary)
        $shortcut.TargetPath = $Executable
        $shortcut.WorkingDirectory = $WorkingDirectory
        $shortcut.IconLocation = "$Executable,0"
        $shortcut.Description = "PS5 LED - PS5/PS4 RGB lightbar control"
        $shortcut.Save()
        # Copy to a sibling name, then move over the old shortcut. A failed copy leaves the old one as it was.
        Copy-Item -LiteralPath $temporary -Destination $sibling
        Move-Item -LiteralPath $sibling -Destination (Join-Path $desktop "PS5 LED.lnk") -Force
    } finally {
        Remove-Item -LiteralPath $temporary, $sibling -Force -ErrorAction SilentlyContinue
    }
}

function Install-PS5LED {
    param([string]$InstallDir, [string]$Version = "latest", [switch]$NoLaunch, [switch]$NoShortcut)
    $releasePath = if ($Version -eq "latest") { "latest" } else { "tags/" + [uri]::EscapeDataString($Version) }
    try {
        $releaseJson = Get-PS5LEDDownload -Uri ("https://api.github.com/repos/u2n4/ps5-led/releases/" + $releasePath)
        if ($releaseJson -is [byte[]]) { $releaseJson = [Text.Encoding]::UTF8.GetString($releaseJson) }
        $release = $releaseJson | ConvertFrom-Json
        $exeAsset = @($release.assets | Where-Object { $_.name -eq "PS5-LED.exe" })
        $hashAsset = @($release.assets | Where-Object { $_.name -eq "PS5-LED.exe.sha256" })
        if ($exeAsset.Count -ne 1 -or $hashAsset.Count -ne 1) {
            throw "The release must include PS5-LED.exe and PS5-LED.exe.sha256."
        }
    } catch {
        throw "No complete portable release is available: $($_.Exception.Message) Check https://github.com/u2n4/ps5-led/releases. Nothing was installed."
    }
    # Use one release response so a new release cannot mix EXE and checksum versions.
    foreach ($asset in @($exeAsset[0], $hashAsset[0])) {
        if ($asset.browser_download_url -notlike "https://github.com/u2n4/ps5-led/releases/download/*") {
            throw "Unexpected release asset URL. Nothing was installed."
        }
    }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $executable = Join-Path $InstallDir "PS5-LED.exe"
    $download = Join-Path $InstallDir (".download-" + [guid]::NewGuid().ToString("N") + ".exe")
    try {
        Write-Host "Downloading PS5 LED $($release.tag_name)..."
        Get-PS5LEDDownload -Uri $exeAsset[0].browser_download_url -OutFile $download
        $manifest = Get-PS5LEDDownload -Uri $hashAsset[0].browser_download_url
        if ($manifest -is [byte[]]) { $manifest = [Text.Encoding]::UTF8.GetString($manifest) }
        # A UTF-8 byte-order mark (Windows PowerShell 5.1 writes one) is not whitespace, so Trim() keeps it.
        $manifest = $manifest.TrimStart([char]0xFEFF).Trim()
        if ($manifest -notmatch '^(?<hash>[a-fA-F0-9]{64})(?:\s+\*?PS5-LED\.exe)?$') {
            throw "The release checksum is missing or malformed."
        }
        $expected = $Matches['hash']
        $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash
        if ($actual -ne $expected) { throw "SHA256 verification failed: the download is $actual but the release manifest says $expected. The existing installation was not changed." }
        $stream = [IO.File]::OpenRead($download)
        try {
            if ($stream.Length -lt 2 -or $stream.ReadByte() -ne 0x4d -or $stream.ReadByte() -ne 0x5a) {
                throw "The verified download is not a Windows executable."
            }
        } finally { $stream.Dispose() }
        if (Test-Path -LiteralPath $executable) {
            if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -eq $expected) {
                Write-Host "This verified release is already installed."
            } else {
                [IO.File]::Replace($download, $executable, [NullString]::Value)
            }
        } else {
            Move-Item -LiteralPath $download -Destination $executable
        }
    } catch {
        throw "Portable installation failed: $($_.Exception.Message) Close PS5 LED before retrying if it is running."
    } finally {
        if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force }
    }
    if (-not $NoShortcut) {
        try { New-PS5LEDShortcut -Executable $executable -WorkingDirectory $InstallDir }
        catch { Write-Warning "Installed, but the desktop shortcut could not be created: $($_.Exception.Message)" }
    }
    Write-Host "Installed verified EXE: $executable"
    if (-not $NoLaunch) { Start-Process -FilePath $executable -WorkingDirectory $InstallDir }
    return $executable
}

Install-PS5LED -InstallDir $InstallDir -Version $Version -NoLaunch:$NoLaunch -NoShortcut:$NoShortcut
