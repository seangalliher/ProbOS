# Launch a two-node ProbOS federation cluster on Windows.
#
# Usage:
#   .\scripts\launch-cluster.ps1

$ErrorActionPreference = "Stop"

Push-Location (Split-Path $PSScriptRoot -Parent)

try {
    Write-Host "Starting ProbOS node-1..."
    $node1 = Start-Process -FilePath "$env:USERPROFILE\.local\bin\uv.exe" `
        -ArgumentList "run", "python", "-m", "probos", "--config", "config/node-1.yaml", "--data-dir", "./data/node-1" `
        -NoNewWindow -PassThru

    Write-Host "Starting ProbOS node-2..."
    $node2 = Start-Process -FilePath "$env:USERPROFILE\.local\bin\uv.exe" `
        -ArgumentList "run", "python", "-m", "probos", "--config", "config/node-2.yaml", "--data-dir", "./data/node-2" `
        -NoNewWindow -PassThru

    Write-Host "ProbOS cluster running: node-1 (PID $($node1.Id)), node-2 (PID $($node2.Id))"
    Write-Host "Press Ctrl-C to stop both nodes."

    try {
        Wait-Process -Id $node1.Id, $node2.Id
    } finally {
        foreach ($proc in @($node1, $node2)) {
            if (!$proc.HasExited) {
                Write-Host "Stopping PID $($proc.Id)..."
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
} finally {
    Pop-Location
}
