"""
backend/main.py
Servidor FastAPI para produção (Railway + Supabase).
Com Sincronização Automática em Background.
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

from database.db import (
    init_db, salvar_licitacoes, buscar_licitacoes,
    toggle_favorito, salvar_filtro, listar_filtros_salvos,
    deletar_filtro, estatisticas_db
)
from backend.pncp_client import buscar_multiplas_paginas, listar_modalidades, testar_conexao
from backend.exportador import exportar_excel

app = FastAPI(title="Licitações PNCP", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def varredura_startup_silenciosa():
    """Roda em segundo plano para encher o banco sem travar a tela do usuário"""
    print("[AUTO-SYNC] Aguardando 10s para o servidor estabilizar...")
    time.sleep(10)
    print("[AUTO-SYNC] Iniciando primeira captura de dados em background...")
    try:
        from backend.agendador import varredura_horaria
        varredura_horaria()
        print("[AUTO-SYNC] Banco preenchido com sucesso! O sistema está pronto.")
    except Exception as e:
        print(f"[AUTO-SYNC] Erro: {e}")

# Inicializa banco e agendador ao subir
@app.on_event("startup")
async def startup():
    try:
        init_db()
        from backend.agendador import iniciar_agendador
        iniciar_agendador()
        print("[APP] Sistema iniciado com sucesso!")
        
        # Dispara a busca num thread isolado (Zero travamento no frontend)
        threading.Thread(target=varredura_startup_silenciosa, daemon=True).start()
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

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
async def serve_frontend():
    p = os.path.join(frontend_path, "index.html")
    return FileResponse(p) if os.path.exists(p) else JSONResponse({"ok": True})

# ── Status ────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    return {
        "sistema": "online",
        "versao": "2.0.0",
        "pncp_api": testar_conexao(),
        "banco_dados": estatisticas_db(),
        "timestamp": datetime.now().isoformat(),
    }

# ── Busca no banco local (rápida — PostgreSQL com full-text) ──────────────────
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
    """Busca no banco PostgreSQL — resultado instantâneo."""
    return buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max,
        data_inicio=data_inicio, data_fim=data_fim,
        apenas_favoritos=apenas_favoritos,
        pagina=pagina, por_pagina=por_pagina,
    )

# ── Busca ao vivo no PNCP (quando usuário quer dados frescos) ─────────────────
@app.post("/api/buscar-pncp")
async def buscar_pncp_live(req: BuscaRequest):
    """Busca diretamente na API do PNCP e salva resultados no banco."""
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

    if not resultado.get("sucesso"):
        raise HTTPException(status_code=502, detail="Erro ao consultar API do PNCP")

    licitacoes = resultado.get("dados", [])
    salvas = {}
    if licitacoes:
        salvas = salvar_licitacoes(licitacoes)

    return {
        "sucesso": True,
        "coletadas": len(licitacoes),
        "salvas_db": salvas,
        "licitacoes": licitacoes,
    }

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

# ── Utilitários ───────────────────────────────────────────────────────────────
@app.get("/api/modalidades")
async def modalidades():
    return listar_modalidades()

@app.get("/api/estatisticas")
async def estatisticas():
    return estatisticas_db()

@app.post("/api/varredura-manual")
async def varredura_manual():
    """Dispara uma varredura manual do PNCP."""
    try:
        from backend.agendador import varredura_horaria
        varredura_horaria()
        return {"sucesso": True, "mensagem": "Varredura iniciada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
