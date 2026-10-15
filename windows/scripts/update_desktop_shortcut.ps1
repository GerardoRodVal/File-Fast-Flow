$ErrorActionPreference = 'Stop'
$windowsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $windowsRoot
$venvConfig = Join-Path $windowsRoot '.venv\pyvenv.cfg'
if (-not (Test-Path -LiteralPath $venvConfig -PathType Leaf)) { throw 'No se encontró el entorno virtual.' }
$pythonHomeEntry = Get-Content -LiteralPath $venvConfig | Where-Object { $_ -match '^home\s*=' } | Select-Object -First 1
if (-not $pythonHomeEntry) { throw 'No se encontró el intérprete del entorno virtual.' }
$pythonWindowed = Join-Path (($pythonHomeEntry -split '=', 2)[1].Trim()) 'pythonw.exe'
$launcher = Join-Path $PSScriptRoot 'launch_desktop.pyw'
$icon = Join-Path $projectRoot 'assets\FileFastFlow.ico'
foreach ($requiredPath in @($pythonWindowed, $launcher, $icon)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "No se encontró el archivo requerido: $requiredPath"
    }
}
$desktopFolder = [Environment]::GetFolderPath('Desktop')
if (-not $desktopFolder) { throw 'No se encontró la carpeta del escritorio.' }
$shortcutPath = Join-Path $desktopFolder 'FileFastFlow.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonWindowed
$shortcut.Arguments = '-S "' + $launcher + '"'
$shortcut.WorkingDirectory = $windowsRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'FileFastFlow: versión actual del proyecto'
$shortcut.WindowStyle = 1
$shortcut.Save()
$savedShortcut = $shortcutShell.CreateShortcut($shortcutPath)
if ($savedShortcut.TargetPath -ne $pythonWindowed -or $savedShortcut.Arguments -ne ('-S "' + $launcher + '"')) {
    throw 'No se pudo verificar el acceso directo actualizado.'
}
$savedShortcut | Select-Object FullName, TargetPath, Arguments, WorkingDirectory, IconLocation
