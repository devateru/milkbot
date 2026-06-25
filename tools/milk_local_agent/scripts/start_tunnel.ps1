param(
    [string]$Target = $env:MILK_TUNNEL_TARGET
)

if ([string]::IsNullOrWhiteSpace($Target)) {
    Write-Error "usage: .\start_tunnel.ps1 USER@SERVER_HOST"
    exit 2
}

ssh -N `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -o ExitOnForwardFailure=yes `
  -R 127.0.0.1:18080:127.0.0.1:18080 `
  $Target
