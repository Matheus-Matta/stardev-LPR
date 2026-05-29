# ─────────────────────────────────────────────────────────────────────────────
# start_ngrok.ps1 — abre túneis ngrok para o media server LPR
#
# Uso:
#   .\scripts\start_ngrok.ps1
#
# Pré-requisito:
#   ngrok config add-authtoken SEU_TOKEN
# ─────────────────────────────────────────────────────────────────────────────

$configFile = Join-Path $PSScriptRoot "..\ngrok.yml"
$configFile = (Resolve-Path $configFile).Path

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "ERRO: ngrok não encontrado no PATH." -ForegroundColor Red
    Write-Host "  Baixe em: https://ngrok.com/download" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Iniciando túneis ngrok..." -ForegroundColor Cyan
Write-Host "  Config: $configFile" -ForegroundColor Gray
Write-Host ""
Write-Host "Túneis:" -ForegroundColor Cyan
Write-Host "  HLS  (HTTP ) porta 8888 → URL HTTPS pública (player ao vivo)"
Write-Host "  RTMP (TCP  ) porta 1935 → endereço TCP público (push de câmeras)"
Write-Host "  RTSP (TCP  ) porta 8554 → endereço TCP público (pull RTSP)"
Write-Host ""
Write-Host "Após iniciar, copie as URLs para o .env:" -ForegroundColor Yellow
Write-Host "  MEDIAMTX_HLS_PUBLIC_URL=https://xxxx.ngrok-free.app"
Write-Host "  MEDIAMTX_RTMP_PUBLIC_URL=rtmp://0.tcp.sa.ngrok.io:PORTA"
Write-Host ""

ngrok start --all --config $configFile
