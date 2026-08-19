# Registra a tarefa MENSAL de enriquecimento de setor da FINEP (CNPJ -> CNAE via Receita Federal).
# Job pesado (varios GB de download) -- por isso roda mensal, separado do refresh semanal.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Script = Join-Path $ProjectRoot "src\enrich_cnae.py"
$TaskName = "RadarCreditoIncentivado_EnriquecimentoCNAE"

if (-not (Test-Path $PythonExe)) {
    throw "Python do venv nao encontrado em $PythonExe. Rode scripts\setup.ps1 primeiro."
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$Script`"" -WorkingDirectory (Join-Path $ProjectRoot "src")
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am -WeeksInterval 4
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Reenriquece o setor das operacoes da FINEP via Receita Federal (mensal, job pesado)." -Force

Write-Host "Tarefa '$TaskName' registrada (a cada 4 semanas, domingo as 3h)."
