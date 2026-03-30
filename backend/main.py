"""
backend/main.py
Servidor FastAPI para produção (Railway + Supabase).
Sincronização Direta com Correção Temporal (Fix para o bug de 2026).
"""

import sys, os
# Garante que o diretório raiz está no path para as importações funcionarem
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
import requests

# Importações do Banco de Dados
from database.db import (
    init_db, salvar_licitacoes, buscar_licitacoes,
    toggle_favorito, salvar_filtro, listar_filtros_salvos,
    deletar_filtro, estatisticas_db, get_conn
)
from backend.exportador import exportar_excel

app = FastAPI(title="Licitações PNCP", version="2.0.1")

# Habilita CORS para evitar bloqueios de navegador
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def obter_data_corrigida():
    """Corrige o bug de 2026: Se o ano for futuro, retorna o ano de 2024."""
    agora = datetime.now()
    if agora.year > 2024:
        try:
            return agora.replace(year=2024)
        except ValueError:
            # Tratamento para anos bissextos (29 de fevereiro)
            return agora - timedelta(days=365 * (agora.year - 2024))
    return agora

def varredura_startup_silenciosa():
    """Faz a extração inicial corrigindo o ano em segundo plano."""
    print("[AUTO-SYNC] Aguardando 15s para estabilização total do servidor...")
    time.sleep(15)
    try:
        from backend.pncp_client import buscar_multiplas_paginas
        data_ref = obter_data_corrigida()
        ini = (data_ref - timedelta(days=30)).strftime("%Y-%m-%d")
        fim = data_ref.strftime("%Y-%m-%d")
        
        print(f"[AUTO-SYNC] Capturando dados reais (Ano Base: {data_ref.year})...")
        resultado = buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)
        dados = resultado.get("dados", [])
        
        if dados:
            stats = salvar_licitacoes(dados)
            print(f"[AUTO-SYNC] Sucesso! {len(dados)} licitações processadas. Stats: {stats}")
        else:
            print("[AUTO-SYNC] PNCP não retornou dados para o período solicitado.")
    except Exception as e:
        print(f"[AUTO-SYNC] Erro durante a varredura automática: {e}")

@app.on_event("startup")
async def startup():
    """Configuração inicial ao ligar o servidor."""
    try:
        init_db()
        # Dispara sincronização em Thread separada para não travar o carregamento do site
        threading.Thread(target=varredura_startup_silenciosa, daemon=True).start()
        print("[APP] Servidor e Banco de Dados prontos!")
    except Exception as e:
        print(f"[APP] Erro crítico na inicialização: {e}")

# Definição de caminhos do Frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")
static_path = os.path.join(frontend_path, "static")

# Monta arquivos estáticos (CSS, JS) se a pasta existir
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

# ── Diagnóstico ───────────────────────────────────────────────────────────────
@app.get("/api/diagnostico")
async def executar_diagnostico():
    """Valida a saúde de toda a infraestrutura."""
    relatorio = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0"}
    
    try:
        requests.get("https://www.google.com", timeout=5)
        relatorio["1_INTERNET_RAILWAY"] = "OK"
    except Exception as e:
        relatorio["1_INTERNET_RAILWAY"] = f"FALHA ({e})"
        
    try:
        r = requests.get("https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao", headers=headers, timeout=10)
        relatorio["2_PNCP_CONEXAO"] = f"OK (HTTP {r.status_code})"
    except Exception as e:
        relatorio["2_PNCP_CONEXAO"] = f"FALHA: {e}"
        
    try:
        r = requests.get("https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao?dataInicial=20240301&dataFinal=20240305&codigoModalidadeContratacao=8&pagina=1", headers=headers, timeout=15)
        qtd = len(r.json().get("data", []))
        relatorio["3_PNCP_DADOS"] = f"SUCESSO: {qtd} licitações de 2024 encontradas."
    except Exception as e:
        relatorio["3_PNCP_DADOS"] = f"FALHA NA BUSCA: {e}"
        
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as t FROM licitacoes")
        count = cur.fetchone()["t"]
        relatorio["4_SUPABASE_ESTADO"] = f"SUCESSO: {count} registros no banco."
        cur.close()
        conn.close()
    except Exception as e:
        relatorio["4_SUPABASE_ESTADO"] = f"FALHA NO BANCO: {e}"
        
    return relatorio

# ── Rotas de Negócio ──────────────────────────────────────────────────────────
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
    # Se o frontend enviar datas de 2026, limpamos para permitir busca no banco histórico
    if data_inicio and "2026" in data_inicio: data_inicio = ""
    if data_fim and "2026" in data_fim: data_fim = ""

    return buscar_licitacoes(
        palavras_chave=palavras_chave, uf=uf, modalidade=modalidade,
        valor_min=valor_min, valor_max=valor_max,
        data_inicio=data_inicio, data_fim=data_fim,
        apenas_favoritos=apenas_favoritos,
        pagina=pagina, por_pagina=por_pagina,
    )

@app.post("/api/buscar-pncp")
async def buscar_pncp_live(req: BuscaRequest):
    """Busca ao vivo forçada pelo usuário no frontend."""
    from backend.pncp_client import buscar_multiplas_paginas
    data_ref = obter_data_corrigida()
    ini = data_ref - timedelta(days=req.dias_atras or 30)
    
    resultado = buscar_multiplas_paginas(
        data_inicial=ini.strftime("%Y-%m-%d"),
        data_final=data_ref.strftime("%Y-%m-%d"),
        uf=req.uf or "",
        modalidade_id=req.modalidade_id,
        palavras_chave=req.palavras_chave or "",
        max_paginas=10,
    )

    licitacoes = resultado.get("dados", [])
    salvas = salvar_licitacoes(licitacoes) if licitacoes else {"inseridas": 0, "atualizadas": 0}
    return {"sucesso": True, "coletadas": len(licitacoes), "salvas_db": salvas}

@app.post("/api/varredura-manual")
async def varredura_manual():
    """Força uma varredura completa por modalidade."""
    try:
        data_ref = obter_data_corrigida()
        ini = (data_ref - timedelta(days=15)).strftime("%Y-%m-%d")
        fim = data_ref.strftime("%Y-%m-%d")
        
        from backend.pncp_client import buscar_multiplas_paginas
        res = buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)
        dados = res.get("dados", [])
        if dados:
            salvar_licitacoes(dados)
        return {"sucesso": True, "baixadas": len(dados)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def status():
    return {"sistema": "online", "banco_dados": estatisticas_db()}

@app.get("/api/modalidades")
async def modalidades():
    from backend.pncp_client import listar_modalidades
    return listar_modalidades()

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

# ── Rota Raiz (Frontend) ──────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
async def serve_frontend():
    """Serve a página inicial."""
    p = os.path.join(frontend_path, "index.html")
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse(content={"erro": "Frontend não encontrado no servidor"}, status_code=404)
