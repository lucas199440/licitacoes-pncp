"""
backend/agendador.py
Agendador automático: busca novas licitações no PNCP a cada hora.
Roda em background no Railway sem precisar de intervenção.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def varredura_horaria():
    """Busca licitações das últimas 2 horas e salva no banco."""
    print(f"[AGENDADOR] Iniciando varredura — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        from backend.pncp_client import varredura_completa
        from database.db import salvar_licitacoes, registrar_log

        resultado = varredura_completa(dias=1)
        licitacoes = resultado.get("dados", [])

        if licitacoes:
            salvo = salvar_licitacoes(licitacoes)
            registrar_log(salvo["inseridas"], salvo["atualizadas"])
            print(f"[AGENDADOR] ✅ {salvo['inseridas']} novas, {salvo['atualizadas']} atualizadas")
        else:
            print("[AGENDADOR] Nenhuma nova licitação encontrada.")
    except Exception as e:
        print(f"[AGENDADOR] ❌ Erro: {e}")


def varredura_semanal():
    """Toda segunda-feira: baixa os últimos 7 dias completos para garantir cobertura."""
    print(f"[AGENDADOR] Varredura semanal completa — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        from backend.pncp_client import buscar_multiplas_paginas
        from database.db import salvar_licitacoes, registrar_log

        resultado = buscar_multiplas_paginas(max_paginas=20)
        licitacoes = resultado.get("dados", [])

        if licitacoes:
            salvo = salvar_licitacoes(licitacoes)
            registrar_log(salvo["inseridas"], salvo["atualizadas"])
            print(f"[AGENDADOR] Semanal ✅ {salvo['inseridas']} novas, {salvo['atualizadas']} atualizadas")
    except Exception as e:
        print(f"[AGENDADOR] ❌ Erro semanal: {e}")


def iniciar_agendador():
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")

    # Varredura a cada hora
    scheduler.add_job(varredura_horaria, "interval", hours=1, id="varredura_horaria")

    # Varredura completa toda segunda às 3h da manhã
    scheduler.add_job(varredura_semanal, "cron", day_of_week="mon", hour=3, id="varredura_semanal")

    scheduler.start()
    print("[AGENDADOR] ✅ Agendador iniciado — varredura a cada hora")

    # Roda uma vez imediatamente ao subir o servidor
    varredura_horaria()

    return scheduler
