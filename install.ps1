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
    # COM saves in an ASCII temporary path before moving to an Arabic desktop.
    # CreateShortcut().Save() fails in any non-ASCII folder, and %TEMP% sits in the
    # profile folder, so an Arabic profile name needs another ASCII folder.
    $temporaryRoot = if ($env:TEMP -notmatch '[^\x00-\x7F]') { $env:TEMP } elseif ($env:PUBLIC -notmatch '[^\x00-\x7F]') { $env:PUBLIC } else { Join-Path $env:SystemRoot "Temp" }
    # The root can be a shared folder (C:\Users\Public, Windows\Temp), so the .lnk never goes straight
    # into it. A new random subfolder, locked to the current user, SYSTEM and Administrators before
    # anything is written, holds the file, so another local account cannot swap it.
    $staging = Join-Path $temporaryRoot ("ps5led-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null   # fails if the name is taken
    try {
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)   # no inheritance from the shared root
        $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        foreach ($sid in @([System.Security.Principal.WindowsIdentity]::GetCurrent().User,
                           (New-Object System.Security.Principal.SecurityIdentifier 'S-1-5-18'),
                           (New-Object System.Security.Principal.SecurityIdentifier 'S-1-5-32-544'))) {
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', $inherit, 'None', 'Allow')))
        }
        Set-Acl -LiteralPath $staging -AclObject $acl
        $temporary = Join-Path $staging "PS5 LED.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($temporary)
        $shortcut.TargetPath = $Executable
        $shortcut.WorkingDirectory = $WorkingDirectory
        $shortcut.IconLocation = "$Executable,0"
        $shortcut.Description = "PS5 LED - PS5/PS4 RGB lightbar control"
        $shortcut.Save()
        $desktop = [Environment]::GetFolderPath("Desktop")
        $destination = Join-Path $desktop "PS5 LED.lnk"
        Move-Item -LiteralPath $temporary -Destination $destination -Force
        # The moved file keeps the staging rules. Give it back the desktop's inherited rules.
        $shortcutAcl = Get-Acl -LiteralPath $destination
        $shortcutAcl.SetAccessRuleProtection($false, $false)
        Set-Acl -LiteralPath $destination -AclObject $shortcutAcl
    } finally {
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
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
