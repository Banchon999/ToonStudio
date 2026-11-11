# Compile installer/toonstudio.iss into dist\ToonStudio-Windows-x86_64[-full]-Setup.exe
# from the PyInstaller folder dist\ToonStudio. Used by build-windows.yml
# (-Edition lean) and build-windows-full.yml (-Edition full).
param([ValidateSet('lean', 'full')][string]$Edition = 'lean')
$ErrorActionPreference = 'Stop'

function Find-Iscc {
  @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
}
# Inno Setup is not on every runner image.
$iscc = Find-Iscc
if (-not $iscc) { choco install innosetup -y --no-progress | Out-Null; $iscc = Find-Iscc }
if (-not $iscc) { Write-Error 'Inno Setup (ISCC.exe) not found'; exit 1 }

$version = ([regex]'__version__\s*=\s*"([^"]+)"').Match((Get-Content app/version.py -Raw)).Groups[1].Value
if (-not $version) { Write-Error 'no __version__ in app/version.py'; exit 1 }

& $iscc "/DAppVersion=$version" "/DEdition=$Edition" installer/toonstudio.iss
if ($LASTEXITCODE -ne 0) { Write-Error "ISCC failed ($LASTEXITCODE)"; exit 1 }

$name = if ($Edition -eq 'full') { 'ToonStudio-Windows-x86_64-full-Setup.exe' } else { 'ToonStudio-Windows-x86_64-Setup.exe' }
$setup = Get-Item (Join-Path 'dist' $name)
Write-Output ("{0}: {1:N0} MB" -f $setup.Name, ($setup.Length / 1MB))
# GitHub refuses a release asset of 2 GiB or more.
if ($setup.Length -ge 2147483648) {
  Write-Error ("{0} is {1:N0} MB, over GitHub's 2 GB release asset limit" -f $setup.Name, ($setup.Length / 1MB))
  exit 1
}
