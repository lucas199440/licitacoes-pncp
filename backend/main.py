"""
backend/main.py
Servidor FastAPI para produção (Railway + Supabase).
Sincronização Direta Integrada com Scanner de Diagnóstico Profundo.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import threading
import time
import requests

from database.db import (
    init_db, salvar_licitacoes, buscar_licitacoes,
    toggle_favorito, salvar_filtro, listar_filtros_salvos,
    deletar_filtro, estatisticas_db, get_conn
)
from backend.exportador import exportar_excel

app = FastAPI(title="Licitações PNCP", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def varredura_startup_silenciosa():
    """Ignora o agendador. Faz a extração e salvamento de forma DIRETA no arranque."""
    print("[AUTO-SYNC] Aguardando 5s para o servidor estabilizar...")
    time.sleep(5)
    try:
        from backend.pncp_client import varredura_completa
        print("[AUTO-SYNC] A extrair dados do PNCP de forma direta...")
        resultado = varredura_completa(15)
        dados = resultado.get("dados", [])
        
        if dados:
            print(f"[AUTO-SYNC] {len(dados)} licitações capturadas. A gravar no banco de dados...")
            stats = salvar_licitacoes(dados)
            print(f"[AUTO-SYNC] Sucesso! Banco atualizado: {stats}")
        else:
            print("[AUTO-SYNC] ⚠️ Falha: O PNCP não devolveu nenhuma licitação.")
    except Exception as e:
        print(f"[AUTO-SYNC] ❌ Erro fatal no processo de sincronização: {e}")

# Inicializa banco e varredura ao subir
@app.on_event("startup")
async def startup():
    try:
        init_db()
        # Inicia a captura imediatamente em segundo plano sem travar o site
        threading.Thread(target=varredura_startup_silenciosa, daemon=True).start()
        print("[APP] Sistema iniciado com sucesso!")
    except Exception as e:
        print(f"[APP] Erro no startup: {e}")

# Serve o frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
static_path = os.path.join(frontend_path, "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# ── Models ────────────────────────────────────────────────────────────────────
class FavoritoRequest(BaseModel):
    licitacao_id: int
    nota: Optional[str] = ""

class FiltroSalvoRequest(BaseModel):
    nome: str
    palavras_chave: Optional[str] = ""
    uf: Optional[str] = ""
    modalidade: Optional[str] = ""
    valor_min: Optional[float] = None
    valor_max: Optional[float] = None
    dias_atras: Optional[int] = 30

class BuscaRequest(BaseModel):
    palavras_chave: Optional[str] = ""
    uf: Optional[str] = ""
    modalidade_id: Optional[int] = None
    valor_min: Optional[float] = None
    valor_max: Optional[float] = None
    dias_atras: Optional[int] = 30
    pagina: Optional[int] = 1
    por_pagina: Optional[int] = 50

# ── ROTA DE DIAGNÓSTICO PROFUNDO (A NOSSA NOVA LINHA DE INVESTIGAÇÃO) ────────
@app.get("/api/diagnostico")
async def executar_diagnostico():
    """
    Testa cada um dos elos da corrente (Governo -> Railway -> Supabase)
    para descobrir exatamente onde a informação se perde.
    """
    relatorio = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0"}

    # 1. Teste de Internet do Servidor
    try:
        requests.get("https://www.google.com", timeout=5)
        relatorio["1_INTERNET_RAILWAY"] = "OK"
    except Exception as e:
        relatorio["1_INTERNET_RAILWAY"] = f"FALHA ({e})"

    # 2. Teste de Acesso à API do Governo (Bloqueio de IP / Firewall)
    try:
        r = requests.get("https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao", headers=headers, timeout=10)
        relatorio["2_PNCP_CONEXAO"] = f"OK (HTTP {r.status_code})"
    except Exception as e:
        relatorio["2_PNCP_CONEXAO"] = f"FALHA (O Governo pode estar a bloquear o seu servidor Railway): {e}"

    # 3. Teste de Dados do PNCP (Ignorando datas do sistema e forçando Março de 2024)
    try:
        r = requests.get(
            "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao?dataInicial=20240301&dataFinal=20240305&codigoModalidadeContratacao=8&pagina=1",
            headers=headers, timeout=15
        )
        if r.status_code == 200:
            qtd = len(r.json().get("data", []))
            relatorio["3_PNCP_DADOS"] = f"SUCESSO: Trouxe {qtd} licitações de 2024 da API."
        else:
            relatorio["3_PNCP_DADOS"] = f"AVISO: O Governo respondeu com código {r.status_code}. (Vazio)"
    except Exception as e:
        relatorio["3_PNCP_DADOS"] = f"FALHA AO LER DADOS: {e}"

    # 4. Teste de Escrita e Leitura do Supabase
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as t FROM licitacoes")
        count = cur.fetchone()["t"]
        relatorio["4_SUPABASE_ESTADO"] = f"SUCESSO: Acesso total à base de dados. Tabela tem {count} registros."
        cur.close()
        conn.close()
    except Exception as e:
        relatorio["4_SUPABASE_ESTADO"] = f"FALHA NA BASE DE DADOS: {e}"

    return relatorio

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
async def serve_frontend():
    p = os.path.join(frontend_path, "index.html")
    return FileResponse(p) if os.path.exists(p) else JSONResponse({"ok": True})

# ── Busca no banco local (rápida — PostgreSQL) ────────────────────────────────
@app.get("/api/licitacoes")
async def listar_licitacoes(
    palavras_chave: str = Query(""),
    uf: str = Query(""),
    modalidade: str = Query(""),
    valor_min: Optional[float] = Query(None),
    valor_max: Optional[float] = Query(None),
    data_inicio: str = Query(""),
    data_fim: str = Query(""),
    apenas_favoritos: bool = Query(False),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=200),
):
    # ESCUDO CONTRA O BUG DE 2026: Ignora datas futuras vindas do frontend
    if data_inicio and data_inicio.startswith("2026"):
        data_inicio = ""
    if data_fim and data_fim.startswith("2026"):
        data_fim = ""

    return buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max,
        data_inicio=data_inicio, data_fim=data_fim,
        apenas_favoritos=apenas_favoritos,
        pagina=pagina, por_pagina=por_pagina,
    )

# ── Busca ao vivo ─────────────────────────────────────────────────────────────
@app.post("/api/buscar-pncp")
async def buscar_pncp_live(req: BuscaRequest):
    from backend.pncp_client import buscar_multiplas_paginas
    from datetime import timedelta
    fim = datetime.now()
    ini = fim - timedelta(days=req.dias_atras or 30)

    resultado = buscar_multiplas_paginas(
        data_inicial=ini.strftime("%Y-%m-%d"),
        data_final=fim.strftime("%Y-%m-%d"),
        uf=req.uf or "",
        modalidade_id=req.modalidade_id,
        palavras_chave=req.palavras_chave or "",
        max_paginas=5 if not req.palavras_chave else 15,
    )

    licitacoes = resultado.get("dados", [])
    salvas = salvar_licitacoes(licitacoes) if licitacoes else {}

    return {
        "sucesso": True,
        "coletadas": len(licitacoes),
        "salvas_db": salvas,
        "licitacoes": licitacoes,
    }

# ── Varredura Manual ──────────────────────────────────────────────────────────
@app.post("/api/varredura-manual")
async def varredura_manual():
    """Dispara uma varredura manual DIRETA."""
    try:
        from backend.pncp_client import varredura_completa
        res = varredura_completa(15)
        dados = res.get("dados", [])
        if dados:
            salvar_licitacoes(dados)
        return {"sucesso": True, "baixadas": len(dados)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Outras Rotas ──────────────────────────────────────────────────────────────
@app.get("/api/exportar")
async def exportar(
    palavras_chave: str = Query(""), uf: str = Query(""), modalidade: str = Query(""),
    valor_min: Optional[float] = Query(None), valor_max: Optional[float] = Query(None),
    apenas_favoritos: bool = Query(False),
):
    resultado = buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max, apenas_favoritos=apenas_favoritos,
        pagina=1, por_pagina=10000,
    )
    licitacoes = resultado.get("resultados", [])
    if not licitacoes:
        raise HTTPException(status_code=404, detail="Nenhuma licitação para exportar.")
    caminho = exportar_excel(licitacoes)
    return FileResponse(path=caminho, filename=os.path.basename(caminho), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.post("/api/favoritos")
async def gerenciar_favorito(req: FavoritoRequest):
    return toggle_favorito(req.licitacao_id, req.nota)

@app.get("/api/filtros")
async def listar_filtros():
    return listar_filtros_salvos()

@app.post("/api/filtros")
async def criar_filtro(req: FiltroSalvoRequest):
    return salvar_filtro(req.nome, req.dict())

@app.delete("/api/filtros/{filtro_id}")
async def remover_filtro(filtro_id: int):
    deletar_filtro(filtro_id)
    return {"sucesso": True}

@app.get("/api/modalidades")
async def modalidades():
    from backend.pncp_client import listar_modalidades
    return listar_modalidades()

@app.get("/api/estatisticas")
async def estatisticas():
    return estatisticas_db()

@app.get("/api/status")
async def status():
    from backend.pncp_client import testar_conexao
    return {
        "sistema": "online",
        "pncp_api": testar_conexao(),
        "banco_dados": estatisticas_db(),
    }
