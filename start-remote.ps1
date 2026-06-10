<#
.SYNOPSIS
  Start the MT5 MCP HTTP server and a Cloudflare quick tunnel,
  then print the public connector URL (https://<random>.trycloudflare.com<path>).

.DESCRIPTION
  - Launches `py -m mt5_mcp.server --http` (streamable-http) on the configured port.
  - Waits for the /healthz endpoint to come up.
  - Launches `cloudflared tunnel --url http://localhost:<port>`.
  - Parses cloudflared's output for the trycloudflare.com hostname.
  - Prints the full MCP endpoint + healthz URLs to register in Cowork / claude.ai.
  - Keeps both processes running until you press Ctrl+C, then cleans them up.

.PARAMETER Cowork
  Start in Cowork / claude.ai mode: NO bearer auth + a secret random path.
  claude.ai custom connectors only support OAuth (not a pasted bearer token), so requiring
  a token makes the client prompt for OAuth. Use -Cowork to avoid that prompt.

.EXAMPLE
  .\start-remote.ps1                 # bearer-token mode (curl / Claude Code clients)
  .\start-remote.ps1 -Cowork         # Cowork / claude.ai mode (no auth, secret path)

.NOTES
  WARNING: when MT5_TRADE_ENABLED=true this MCP can place REAL orders on a live account.
           In -Cowork mode there is no token: anyone who learns the full URL (host + secret
           path) can use it, including placing real orders. Keep the URL private.

  Honors these env vars:
    $env:MT5_MCP_HTTP_PORT   (default 8790)
    $env:MT5_MCP_HTTP_PATH   (default /mcp; -Cowork generates /mcp-<random> if left default)
    $env:MT5_MCP_TOKEN       (bearer token for default mode; ignored/cleared in -Cowork mode)
#>

[CmdletBinding()]
param(
    [int]$Port = $(if ($env:MT5_MCP_HTTP_PORT) { [int]$env:MT5_MCP_HTTP_PORT } else { 8790 }),
    [string]$Path = $(if ($env:MT5_MCP_HTTP_PATH) { $env:MT5_MCP_HTTP_PATH } else { '/mcp' }),
    # Cowork / claude.ai mode. claude.ai custom connectors do NOT support a pasted bearer token
    # (only OAuth), so a 401 makes the client prompt for OAuth. This switch starts the server with
    # NO bearer auth and instead protects the endpoint with a hard-to-guess secret PATH on a random
    # trycloudflare host. Anyone who learns the full URL can use it (and trade, if trading is on).
    [switch]$Cowork
)

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

function New-UrlSafeSecret([int]$nbytes) {
    $bytes = New-Object byte[] $nbytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}

# Normalize the path so it always starts with a single leading slash.
if ($Path -notmatch '^/') { $Path = "/$Path" }

if ($Cowork) {
    # No bearer auth, so claude.ai does not see a 401 and does not start an OAuth flow.
    $env:MT5_MCP_ALLOW_NO_AUTH = 'true'
    Remove-Item Env:\MT5_MCP_TOKEN -ErrorAction SilentlyContinue
    $Token = $null
    if ($Path -eq '/mcp') {
        $Path = "/mcp-" + (New-UrlSafeSecret 18)
        Write-Host "Cowork mode: no bearer auth; generated a secret path for obscurity-based protection." -ForegroundColor DarkYellow
    }
} else {
    # Bearer token mode (for clients that CAN send an Authorization header, e.g. curl / Claude Code).
    if (-not $env:MT5_MCP_TOKEN) {
        $env:MT5_MCP_TOKEN = New-UrlSafeSecret 32
        Write-Host "MT5_MCP_TOKEN was not set - generated a new one for this session." -ForegroundColor DarkYellow
    }
    $Token = $env:MT5_MCP_TOKEN
}

# Bind the child server and expose the same port/path through the tunnel.
$env:MT5_MCP_HTTP_PORT = "$Port"
$env:MT5_MCP_HTTP_PATH = $Path
$env:MT5_MCP_HTTP_HOST = '127.0.0.1'

$serverProc = $null
$tunnelProc = $null
$tunnelLog  = Join-Path $env:TEMP "mt5-mcp-cloudflared-$Port.log"

function Stop-Procs {
    foreach ($p in @($script:tunnelProc, $script:serverProc)) {
        if ($p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

try {
    # --- 1. Start the HTTP MCP server ---------------------------------------
    Write-Host "Starting MT5 MCP HTTP server on port $Port ..." -ForegroundColor Cyan
    $serverProc = Start-Process -FilePath 'py' -ArgumentList '-m', 'mt5_mcp.server', '--http' `
        -WorkingDirectory $ScriptDir -NoNewWindow -PassThru

    # --- 2. Wait for /healthz ------------------------------------------------
    $healthUrl = "http://127.0.0.1:$Port/healthz"
    $ready = $false
    $tradeEnabled = $false
    foreach ($i in 1..40) {   # up to ~20s
        if ($serverProc.HasExited) {
            throw "HTTP server exited early (exit code $($serverProc.ExitCode)). Run 'py -m mt5_mcp.server --http' manually to see the error (likely MT5_MCP_TOKEN missing or MT5 not running)."
        }
        try {
            $r = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
            if ($r.ok) { $ready = $true; $tradeEnabled = [bool]$r.trade_enabled; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Server did not become healthy at $healthUrl" }
    Write-Host "Server healthy at $healthUrl" -ForegroundColor Green

    # --- 3. Start the Cloudflare quick tunnel --------------------------------
    Write-Host "Starting Cloudflare tunnel ..." -ForegroundColor Cyan
    if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }
    $tunnelProc = Start-Process -FilePath 'cloudflared' `
        -ArgumentList 'tunnel', '--url', "http://localhost:$Port" `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput $tunnelLog -RedirectStandardError "$tunnelLog.err"

    # --- 4. Parse the public hostname from cloudflared output ----------------
    $publicHost = $null
    foreach ($i in 1..60) {   # up to ~30s
        if ($tunnelProc.HasExited) {
            throw "cloudflared exited early (exit code $($tunnelProc.ExitCode)). Is it installed and on PATH?"
        }
        foreach ($f in @($tunnelLog, "$tunnelLog.err")) {
            if (Test-Path $f) {
                $m = Select-String -Path $f -Pattern 'https://([a-z0-9-]+\.trycloudflare\.com)' -List | Select-Object -First 1
                if ($m) { $publicHost = $m.Matches[0].Groups[1].Value; break }
            }
        }
        if ($publicHost) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $publicHost) { throw "Could not find the trycloudflare.com URL in cloudflared output ($tunnelLog)" }

    # --- 5. Print the connector URLs -----------------------------------------
    $mcpUrl    = "https://$publicHost$Path"
    $healthPub = "https://$publicHost/healthz"

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  MT5 MCP is now public" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  Connector URL (register this):  " -NoNewline; Write-Host $mcpUrl -ForegroundColor Green
    Write-Host "  Health check:                   " -NoNewline; Write-Host $healthPub -ForegroundColor Green
    if ($Token) {
        Write-Host "  Auth header:                    " -NoNewline; Write-Host "Authorization: Bearer $Token" -ForegroundColor Magenta
    } else {
        Write-Host "  Auth:                           " -NoNewline; Write-Host "NONE - URL+path is the only secret (Cowork mode)" -ForegroundColor DarkYellow
    }
    if ($tradeEnabled) {
        Write-Host "  Trading:                        " -NoNewline; Write-Host "ENABLED (real orders possible!)" -ForegroundColor Red
    } else {
        Write-Host "  Trading:                        " -NoNewline; Write-Host "disabled (read/analyze only)" -ForegroundColor DarkYellow
    }
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Ctrl+C to stop the server and tunnel." -ForegroundColor DarkGray

    # --- 6. Keep alive until a child dies or Ctrl+C --------------------------
    while ($true) {
        if ($serverProc.HasExited) { Write-Host "HTTP server stopped." -ForegroundColor Red; break }
        if ($tunnelProc.HasExited) { Write-Host "Cloudflare tunnel stopped." -ForegroundColor Red; break }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host "Shutting down ..." -ForegroundColor DarkGray
    Stop-Procs
}
