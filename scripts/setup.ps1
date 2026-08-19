# Setup inicial do projeto: cria o venv, instala dependencias e inicializa o banco.
# Rode uma unica vez. Depois use scripts\install_scheduled_task.ps1 para agendar o refresh semanal.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual..."
    python -m venv .venv
}

Write-Host "Instalando dependencias (isso pode demorar alguns minutos na primeira vez)..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "Inicializando banco de dados..."
& ".venv\Scripts\python.exe" "src\db.py"

Write-Host ""
Write-Host "Setup concluido. Proximos passos:"
Write-Host "  1) Rodar o primeiro refresh completo:  .venv\Scripts\python.exe src\refresh.py"
Write-Host "  2) Rodar o enriquecimento de setor da FINEP (uma vez / mensal):  .venv\Scripts\python.exe src\enrich_cnae.py"
Write-Host "  3) Gerar os embeddings de busca:  .venv\Scripts\python.exe src\embeddings.py"
Write-Host "  4) Agendar o refresh semanal:  powershell scripts\install_scheduled_task.ps1"
Write-Host "  5) Subir o site local:  .venv\Scripts\python.exe -m uvicorn webapp.main:app --reload"
