"""
backend/main.py
Servidor FastAPI para produção (Railway + Supabase).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import threading
import time

from database.db import (
    init_db, salvar_licitacoes, buscar_licitacoes,
    toggle_favorito, salvar_filtro, listar_filtros_salvos,
    deletar_filtro, estatisticas_db
)
from backend.exportador import exportar_excel

app = FastAPI(title="Licitações PNCP", version="2.0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def varredura_startup():
    """Busca licitações dos últimos 30 dias ao iniciar o servidor."""
    print("[AUTO-SYNC] Aguardando 15s para estabilização...")
    time.sleep(15)
    try:
        from backend.pncp_client import buscar_multiplas_paginas
        # USA A DATA ATUAL CORRETA (2026)
        hoje = datetime.now()
        ini = (hoje - timedelta(days=30)).strftime("%Y-%m-%d")
        fim = hoje.strftime("%Y-%m-%d")
        print(f"[AUTO-SYNC] Buscando de {ini} até {fim}...")
        resultado = buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)
        dados = resultado.get("dados", [])
        if dados:
            stats = salvar_licitacoes(dados)
            print(f"[AUTO-SYNC] {len(dados)} licitações processadas: {stats}")
        else:
            print("[AUTO-SYNC] Nenhum dado retornado pelo PNCP.")
    except Exception as e:
        print(f"[AUTO-SYNC] Erro: {e}")

@app.on_event("startup")
async def startup():
    try:
        init_db()
        threading.Thread(target=varredura_startup, daemon=True).start()
        print("[APP] Servidor iniciado!")
    except Exception as e:
        print(f"[APP] Erro na inicialização: {e}")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
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

# ── Status ────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    from backend.pncp_client import testar_conexao
    return {
        "sistema": "online",
        "data_servidor": datetime.now().isoformat(),
        "pncp_api": testar_conexao(),
        "banco_dados": estatisticas_db(),
    }

# ── Diagnóstico ───────────────────────────────────────────────────────────────
@app.get("/api/diagnostico")
async def diagnostico():
    import requests as req
    relatorio = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    hoje = datetime.now()
    ini = (hoje - timedelta(days=7)).strftime("%Y%m%d")
    fim = hoje.strftime("%Y%m%d")

    try:
        req.get("https://www.google.com", timeout=5)
        relatorio["internet"] = "OK"
    except Exception as e:
        relatorio["internet"] = f"FALHA: {e}"

    try:
        r = req.get(
            "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao",
            params={"dataInicial": ini, "dataFinal": fim,
                    "codigoModalidadeContratacao": 8, "pagina": 1, "tamanhoPagina": 5},
            headers=headers, timeout=15
        )
        qtd = len(r.json().get("data", []))
        relatorio["pncp"] = f"OK — {qtd} licitações encontradas (período: {ini} a {fim})"
    except Exception as e:
        relatorio["pncp"] = f"FALHA: {e}"

    try:
        stats = estatisticas_db()
        relatorio["banco"] = f"OK — {stats['total_licitacoes']} licitações no banco"
    except Exception as e:
        relatorio["banco"] = f"FALHA: {e}"

    relatorio["data_servidor"] = hoje.isoformat()
    return relatorio

# ── Busca no banco (instantânea) ──────────────────────────────────────────────
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
    return buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max,
        data_inicio=data_inicio, data_fim=data_fim,
        apenas_favoritos=apenas_favoritos,
        pagina=pagina, por_pagina=por_pagina,
    )

# ── Busca ao vivo no PNCP ─────────────────────────────────────────────────────
@app.post("/api/buscar-pncp")
async def buscar_pncp_live(req: BuscaRequest):
    from backend.pncp_client import buscar_multiplas_paginas
    hoje = datetime.now()
    ini = (hoje - timedelta(days=req.dias_atras or 30)).strftime("%Y-%m-%d")
    fim = hoje.strftime("%Y-%m-%d")

    resultado = buscar_multiplas_paginas(
        data_inicial=ini,
        data_final=fim,
        uf=req.uf or "",
        modalidade_id=req.modalidade_id,
        palavras_chave=req.palavras_chave or "",
        max_paginas=10,
    )

    licitacoes = resultado.get("dados", [])
    salvas = salvar_licitacoes(licitacoes) if licitacoes else {"inseridas": 0, "atualizadas": 0}
    return {"sucesso": True, "coletadas": len(licitacoes), "salvas_db": salvas, "licitacoes": licitacoes}

# ── Varredura manual ──────────────────────────────────────────────────────────
@app.post("/api/varredura-manual")
async def varredura_manual():
    try:
        from backend.pncp_client import buscar_multiplas_paginas
        hoje = datetime.now()
        ini = (hoje - timedelta(days=15)).strftime("%Y-%m-%d")
        fim = hoje.strftime("%Y-%m-%d")
        res = buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)
        dados = res.get("dados", [])
        if dados:
            salvar_licitacoes(dados)
        return {"sucesso": True, "baixadas": len(dados)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Exportar Excel ────────────────────────────────────────────────────────────
@app.get("/api/exportar")
async def exportar(
    palavras_chave: str = Query(""),
    uf: str = Query(""),
    modalidade: str = Query(""),
    valor_min: Optional[float] = Query(None),
    valor_max: Optional[float] = Query(None),
    apenas_favoritos: bool = Query(False),
):
    resultado = buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max,
        apenas_favoritos=apenas_favoritos,
        pagina=1, por_pagina=10000,
    )
    licitacoes = resultado.get("resultados", [])
    if not licitacoes:
        raise HTTPException(status_code=404, detail="Nenhuma licitação para exportar.")
    caminho = exportar_excel(licitacoes)
    return FileResponse(
        path=caminho,
        filename=os.path.basename(caminho),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ── Favoritos ─────────────────────────────────────────────────────────────────
@app.post("/api/favoritos")
async def gerenciar_favorito(req: FavoritoRequest):
    return toggle_favorito(req.licitacao_id, req.nota)

# ── Filtros Salvos ────────────────────────────────────────────────────────────
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

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
async def serve_frontend():
    p = os.path.join(frontend_path, "index.html")
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse(content={"erro": "Frontend não encontrado"}, status_code=404)
