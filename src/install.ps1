$destination = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns"

Copy-Item -Path "$PSScriptRoot\Flatten-Layout" -Destination $destination -Recurse -Force

Write-Host "Installed to $destination\Flatten-Layout"
