# An installer that compiles is not one that installs. Install it the way the
# in-app updater runs it (per user, silently), run the installed app's own
# self-tests, check the .ctpr association, uninstall, and check nothing is left.
param(
  [Parameter(Mandatory)][string]$Setup,
  [string[]]$SelfTests = @('--skia-self-test')
)
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:RUNNER_TEMP 'ToonStudioInstall'
$log = Join-Path $env:RUNNER_TEMP 'setup.log'

$p = Start-Process -FilePath $Setup -Wait -PassThru -ArgumentList `
  '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=$dir", "/LOG=$log", '/TASKS=ctpr'
if ($p.ExitCode -ne 0) { Get-Content $log -Tail 40; Write-Error "setup exited $($p.ExitCode)"; exit 1 }
$exe = Join-Path $dir 'ToonStudio.exe'
if (-not (Test-Path $exe)) { Write-Error 'setup did not install ToonStudio.exe'; exit 1 }

foreach ($flag in $SelfTests) {
  # Start-Process -Wait: a --windowed exe returns at once under the call operator.
  $errFile = Join-Path $env:RUNNER_TEMP 'installed-self-test.err'
  $proc = Start-Process -FilePath $exe -ArgumentList $flag -Wait -PassThru -NoNewWindow -RedirectStandardError $errFile
  if ($proc.ExitCode -ne 0) {
    Write-Error "the installed app failed $flag (exit $($proc.ExitCode)): $(Get-Content $errFile -Raw)"; exit 1
  }
  Write-Output "installed app passed $flag"
}

$assoc = (Get-ItemProperty 'HKCU:\Software\Classes\ToonStudio.Project\shell\open\command').'(default)'
if ($assoc -notlike '*ToonStudio.exe*') { Write-Error ".ctpr is not associated: $assoc"; exit 1 }

$un = Start-Process -FilePath (Join-Path $dir 'unins000.exe') -Wait -PassThru -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
if ($un.ExitCode -ne 0) { Write-Error "uninstall exited $($un.ExitCode)"; exit 1 }
# The uninstaller finishes from a temp copy of itself.
for ($i = 0; $i -lt 30 -and (Test-Path $exe); $i++) { Start-Sleep -Seconds 2 }
if (Test-Path $exe) { Write-Error 'uninstall left ToonStudio.exe behind'; exit 1 }
if (Test-Path 'HKCU:\Software\Classes\ToonStudio.Project') { Write-Error 'uninstall left the .ctpr association'; exit 1 }
Write-Output "$(Split-Path $Setup -Leaf) installs, runs and uninstalls cleanly"
