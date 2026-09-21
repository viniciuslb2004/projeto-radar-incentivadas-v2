> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Automação (GitHub Actions)

Todos em `.github/workflows/`, usando o secret `DATABASE_URL`:
- `refresh-operacoes.yml` — semanal, segunda 06:00 UTC, timeout 180min, roda `src/refresh.py`.
- `refresh-editais.yml` — diário, 08:00 UTC, timeout 15min, roda `src/refresh_editais.py`.
- `enrich-cnae.yml` — mensal, roda `src/enrich_cnae.py`.
- `refresh-primario.yml` — diário, 09:00 UTC, timeout 30min, roda `src/refresh_primario.py`
  (Radar de Crédito Primário/CVM — ver seção própria).

Se o "refresh automático parece não estar funcionando", antes de caçar bug: confira 1) se
`DATABASE_URL` está configurada há tempo suficiente pro cron já ter tido uma janela real pra
disparar (ex: cron só-segunda + secret configurado numa sexta = zero execuções até a próxima
segunda, não é bug), e 2) `SELECT * FROM refresh_log ORDER BY id DESC` pra ver o histórico real.
