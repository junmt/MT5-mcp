# Local check of the HTTP server (no tunnel): verify healthz and bearer auth.
$ErrorActionPreference = 'Stop'
$port = 8791
$env:MT5_MCP_HTTP_PORT = "$port"
$env:MT5_MCP_TOKEN = "test-token-123"
$env:MT5_MCP_HTTP_HOST = "127.0.0.1"

$proc = Start-Process -FilePath 'py' -ArgumentList '-m','mt5_mcp.server','--http' `
    -WorkingDirectory 'C:\Users\jun\mt5-mcp' -NoNewWindow -PassThru
try {
    $health = "http://127.0.0.1:$port/healthz"
    $ready = $false
    foreach ($i in 1..40) {
        if ($proc.HasExited) { throw "server exited early ($($proc.ExitCode))" }
        try { $r = Invoke-RestMethod -Uri $health -TimeoutSec 2; if ($r.ok) { $ready = $true; break } } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "not healthy" }
    Write-Host "[OK] /healthz ->" ($r | ConvertTo-Json -Compress) -ForegroundColor Green

    # No-auth request to /mcp should be rejected with 401
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$port/mcp" -Method POST -TimeoutSec 3 `
            -Headers @{ 'Content-Type'='application/json'; 'Accept'='application/json, text/event-stream' } `
            -Body '{"jsonrpc":"2.0","id":1,"method":"ping"}' | Out-Null
        Write-Host "[FAIL] no-auth request was NOT rejected" -ForegroundColor Red
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 401) {
            Write-Host "[OK] no-token -> 401 Unauthorized" -ForegroundColor Green
        } else {
            Write-Host "[??] no-token -> HTTP $code" -ForegroundColor Yellow
        }
    }
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "stopped." -ForegroundColor DarkGray
}
