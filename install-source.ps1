# Download the entire tracked project; no packages or application are installed.
# irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install-source.ps1 | iex
param([string]$Ref = "main", [string]$Destination)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-PS5LEDSource {
    param([string]$Ref = "main", [string]$Destination)
    if ([string]::IsNullOrWhiteSpace($Ref)) { throw "Specify a branch, tag or commit in -Ref." }
    # Pin the selected ref to one commit before downloading its entire tree.
    $commit = Invoke-RestMethod -Uri ("https://api.github.com/repos/u2n4/ps5-led/commits/" + [uri]::EscapeDataString($Ref)) -Headers @{ "User-Agent" = "PS5-LED-Source" }
    if ($commit.sha -notmatch '^[a-fA-F0-9]{40}$') { throw "GitHub did not return a valid commit for $Ref." }
    if (-not $Destination) {
        $downloads = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads"
        $Destination = Join-Path $downloads ("ps5-led-source-" + $commit.sha.Substring(0, 12) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    }
    $Destination = [IO.Path]::GetFullPath($Destination)
    if (Test-Path -LiteralPath $Destination) { throw "Destination already exists; choose a new folder: $Destination" }
    $archive = Join-Path $env:TEMP ("ps5led-source-" + [guid]::NewGuid().ToString("N") + ".zip")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri ("https://codeload.github.com/u2n4/ps5-led/zip/" + $commit.sha) -OutFile $archive
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            $prefix = $Destination.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
            $entries = @(); $archiveRoot = $null
            # Validate every entry before extraction, retaining .github and all assets.
            foreach ($entry in $zip.Entries) {
                $name = $entry.FullName.Replace('\', '/')
                $parts = $name.Split('/')
                if ($parts.Count -lt 2 -or -not $parts[0] -or $parts -contains '..' -or $name.Contains(':')) { throw "Unsafe archive path: $name" }
                if (-not $archiveRoot) { $archiveRoot = $parts[0] }
                if ($parts[0] -ne $archiveRoot) { throw "Archive contains multiple project roots." }
                if ((($entry.ExternalAttributes -shr 16) -band 0xf000) -eq 0xa000) { throw "Archive links are not supported: $name" }
                $relative = $name.Substring($archiveRoot.Length + 1)
                if (-not $relative) { continue }
                $target = [IO.Path]::GetFullPath((Join-Path $Destination $relative))
                if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Archive path escapes destination: $name" }
                $entries += @{ Entry = $entry; Target = $target; Directory = $name.EndsWith('/') }
            }
            if (-not $entries.Count) { throw "The project archive is empty." }
            New-Item -ItemType Directory -Path $Destination | Out-Null
            foreach ($item in $entries) {
                if ($item.Directory) { [IO.Directory]::CreateDirectory($item.Target) | Out-Null }
                else {
                    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($item.Target)) | Out-Null
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($item.Entry, $item.Target, $false)
                }
            }
        } finally { $zip.Dispose() }
    } finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    }
    Write-Host "Full project downloaded: $Destination"
    Write-Host "Ref: $Ref; commit: $($commit.sha). Includes tracked assets, tests, tools and dotfiles; Git history is not included."
    Write-Host "No dependencies were installed and no application was launched. See README.md for development setup."
    return $Destination
}

Get-PS5LEDSource -Ref $Ref -Destination $Destination
