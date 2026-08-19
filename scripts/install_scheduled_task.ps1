# Registra a tarefa semanal do Radar de Credito Incentivado no Task Scheduler do Windows.
# Rode este script UMA VEZ (como usuario normal, nao precisa ser admin) para agendar o refresh automatico.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RefreshScript = Join-Path $ProjectRoot "src\refresh.py"
$LogFile = Join-Path $ProjectRoot "data\refresh_task.log"
$TaskName = "RadarCreditoIncentivado"

if (-not (Test-Path $PythonExe)) {
    throw "Python do venv nao encontrado em $PythonExe. Rode 'python -m venv .venv' e instale requirements.txt primeiro."
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$RefreshScript`"" -WorkingDirectory (Join-Path $ProjectRoot "src")
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Baixa e atualiza as bases do BNDES e da FINEP a cada 7 dias." -Force

Write-Host "Tarefa '$TaskName' registrada. Roda toda segunda-feira as 7h."
Write-Host "Para rodar manualmente agora: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Para conferir: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
