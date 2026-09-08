"""Exercise installer functions with mocked network, shortcuts and launches."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

HARNESS = r'''
$ErrorActionPreference = "Stop"
# Load the native utility functions before network mocks shadow module exports.
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
foreach ($name in @("install.ps1", "install-source.ps1")) {
    $parseErrors = $null; $tokens = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $env:PS5LED_TEST_REPO $name), [ref]$tokens, [ref]$parseErrors)
    Assert ($parseErrors.Count -eq 0) "PowerShell parse errors in $name"
    $commands = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true)
    foreach ($command in $commands) {
        Assert ($command.GetCommandName() -notin @("python", "pythonw", "py", "pip", "winget")) "Runtime installer invoked development tooling"
    }
    foreach ($fn in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
        . ([scriptblock]::Create($fn.Extent.Text))
    }
}
$env:TEMP = Join-Path $env:PS5LED_TEST_ROOT "temporary"
New-Item -ItemType Directory -Path $env:TEMP | Out-Null
$script:mode = "ok"; $script:launches = 0; $script:shortcuts = 0; $script:calls = 0
$script:archiveFixture = "source.zip"
function Start-Sleep { param($Seconds) }
function Start-Process {
    param($FilePath, $WorkingDirectory)
    Assert ($FilePath.EndsWith("PS5-LED.exe")) "Unexpected program launch"
    $script:launches++
}
function New-PS5LEDShortcut { param($Executable, $WorkingDirectory) $script:shortcuts++ }
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    $script:calls++
    if ($script:mode -eq "network-error") { throw "fixture network unavailable" }
    if ($Uri -like "https://api.github.com/repos/u2n4/ps5-led/releases/*") {
        $assets = @(@{name="PS5-LED.exe";browser_download_url="https://github.com/u2n4/ps5-led/releases/download/v-test/PS5-LED.exe"})
        if ($script:mode -ne "no-manifest") {
            $assets += @{name="PS5-LED.exe.sha256";browser_download_url="https://github.com/u2n4/ps5-led/releases/download/v-test/PS5-LED.exe.sha256"}
        }
        $json = @{tag_name="v-test";assets=$assets} | ConvertTo-Json -Depth 4
        if ($script:mode -eq "json-bytes") { return [pscustomobject]@{Content=[Text.Encoding]::UTF8.GetBytes($json)} }
        return [pscustomobject]@{Content=$json}
    }
    if ($Uri -like "https://github.com/u2n4/ps5-led/releases/download/*/PS5-LED.exe") {
        [IO.File]::Copy((Join-Path $env:PS5LED_TEST_ROOT "fixture.exe"), $OutFile, $true)
        return
    }
    if ($Uri -like "https://github.com/u2n4/ps5-led/releases/download/*/PS5-LED.exe.sha256") {
        $hash = (Get-FileHash (Join-Path $env:PS5LED_TEST_ROOT "fixture.exe") -Algorithm SHA256).Hash
        if ($script:mode -eq "bad-hash") { $hash = "0" * 64 }
        if ($script:mode -eq "malformed") { $hash = "not-a-checksum" }
        return [pscustomobject]@{Content=[Text.Encoding]::UTF8.GetBytes($hash + "  PS5-LED.exe")}
    }
    if ($Uri -eq ("https://codeload.github.com/u2n4/ps5-led/zip/" + ("a" * 40))) {
        [IO.File]::Copy((Join-Path $env:PS5LED_TEST_ROOT $script:archiveFixture), $OutFile, $true)
        return
    }
    throw "Unexpected network request: $Uri"
}
function Invoke-RestMethod {
    param($Uri, $Headers)
    Assert ($Uri -eq "https://api.github.com/repos/u2n4/ps5-led/commits/feature%2Ffixture") "Source ref was not encoded"
    return [pscustomobject]@{sha=("a" * 40)}
}
function Must-Fail($Action, $Pattern) {
    $failed = $false
    try { & $Action | Out-Null }
    catch { $failed = $true; Assert ($_.Exception.Message -match $Pattern) $_.Exception.Message }
    Assert $failed "Expected operation to fail: $Pattern"
}

$installed = Join-Path $env:PS5LED_TEST_ROOT "portable"
Install-PS5LED -InstallDir $installed | Out-Null
Assert ((Get-ChildItem $installed -File).Count -eq 1) "Fresh EXE install fetched extra files"
Assert ($script:launches -eq 1 -and $script:shortcuts -eq 1) "Shortcut/launch default changed"
$oldHash = (Get-FileHash (Join-Path $installed "PS5-LED.exe")).Hash
foreach ($mode in @("bad-hash", "malformed")) {
    $script:mode = $mode
    Must-Fail { Install-PS5LED -InstallDir $installed } "checksum|SHA256"
    Assert ((Get-FileHash (Join-Path $installed "PS5-LED.exe")).Hash -eq $oldHash) "Rejected download replaced existing EXE"
}
$script:mode = "no-manifest"
$missing = Join-Path $env:PS5LED_TEST_ROOT "missing-release"
Must-Fail { Install-PS5LED -InstallDir $missing } "No complete portable release"
Assert (-not (Test-Path $missing)) "Incomplete release created an installation"
$script:mode = "network-error"; $before = $script:calls
Must-Fail { Install-PS5LED -InstallDir $missing } "No complete portable release"
Assert (($script:calls - $before) -eq 3) "Network retries were not bounded to three attempts"
$script:mode = "json-bytes"
Install-PS5LED -InstallDir $installed -NoLaunch -NoShortcut | Out-Null
Assert ((Get-ChildItem $installed -File).Count -eq 1) "Repeated install accumulated files"
Assert ((Get-FileHash (Join-Path $installed "PS5-LED.exe")).Hash -eq $oldHash) "Unchanged release was corrupted"
[IO.File]::AppendAllText((Join-Path $env:PS5LED_TEST_ROOT "fixture.exe"), "updated release")
Install-PS5LED -InstallDir $installed -NoLaunch -NoShortcut | Out-Null
Assert ((Get-FileHash (Join-Path $installed "PS5-LED.exe")).Hash -ne $oldHash) "Changed release was not installed"
Assert ((Get-ChildItem $installed -File).Count -eq 1) "Updated release accumulated backup files"
Assert ($script:launches -eq 1 -and $script:shortcuts -eq 1) "NoLaunch/NoShortcut ignored"
Assert ((Get-ChildItem $installed -Filter ".download-*").Count -eq 0) "Staged download leaked"

$source = Join-Path $env:PS5LED_TEST_ROOT "source"
Get-PS5LEDSource -Ref "feature/fixture" -Destination $source | Out-Null
foreach ($file in @("README.md", "dualled_pro.py", "assets/model.bin", ".github/workflows/ci.yml", "tests/test_example.py", "tools/check.py")) {
    Assert (Test-Path -LiteralPath (Join-Path $source $file)) "Complete source missed $file"
}
Must-Fail { Get-PS5LEDSource -Ref "feature/fixture" -Destination $source } "Destination already exists"
foreach ($fixture in @("traversal.zip", "symlink.zip")) {
    $script:archiveFixture = $fixture
    $rejected = Join-Path $env:PS5LED_TEST_ROOT $fixture.Replace(".zip", "")
    Must-Fail { Get-PS5LEDSource -Ref "feature/fixture" -Destination $rejected } "Unsafe archive|Archive links"
    Assert (-not (Test-Path $rejected)) "Unsafe archive extracted before validation"
}
Assert (-not (Test-Path (Join-Path $env:PS5LED_TEST_ROOT "escape.txt"))) "Archive escaped destination"
Assert ((Get-ChildItem $env:TEMP).Count -eq 0) "Temporary installer downloads leaked"
Assert ($script:launches -eq 1) "Source downloader launched an application"
Write-Output "PASS: EXE only, checksum gates, bounded retries, preserved update, full source, traversal/link refusal"
'''


@unittest.skipUnless(POWERSHELL, "PowerShell is required for installer behavior tests")
class InstallerTests(unittest.TestCase):
    def test_mocked_exe_and_source_installers(self):
        runtimes = dict.fromkeys(filter(None, (shutil.which("pwsh"), shutil.which("powershell"))))
        for runtime in runtimes:
            with self.subTest(runtime=runtime):
                self.run_installers(runtime)

    def run_installers(self, runtime):
        with tempfile.TemporaryDirectory(prefix="ps5led-installer-test-") as directory:
            root = Path(directory)
            root.joinpath("fixture.exe").write_bytes(b"MZ" + bytes(range(128)))
            files = {
                "README.md": "fixture", "dualled_pro.py": "# fixture",
                "assets/model.bin": "mesh", ".github/workflows/ci.yml": "name: fixture",
                "tests/test_example.py": "# test", "tools/check.py": "# check",
            }
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                for name, content in files.items():
                    archive.writestr("ps5-led-fixture/" + name, content)
            with zipfile.ZipFile(root / "traversal.zip", "w") as archive:
                archive.writestr("ps5-led-fixture/../escape.txt", "bad")
            with zipfile.ZipFile(root / "symlink.zip", "w") as archive:
                entry = zipfile.ZipInfo("ps5-led-fixture/link")
                entry.create_system = 3
                entry.external_attr = 0o120777 << 16
                archive.writestr(entry, "../escape.txt")
            script = root / "test.ps1"
            script.write_text(HARNESS, encoding="utf-8")
            test_env = dict(os.environ, PS5LED_TEST_ROOT=str(root), PS5LED_TEST_REPO=str(REPO))
            # Each PowerShell edition must discover its own bundled modules.
            test_env.pop("PSModulePath", None)
            result = subprocess.run(
                [runtime, "-NoProfile", "-NonInteractive", "-File", str(script)],
                capture_output=True, text=True, timeout=45,
                env=test_env,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS: EXE only", result.stdout)


if __name__ == "__main__":
    unittest.main()
