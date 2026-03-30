"""
backend/pncp_client.py
Cliente da API pública do PNCP com busca de fluxo geral (trazendo TODAS as modalidades juntas).
"""

import requests
from datetime import datetime, timedelta
import time

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Usado apenas para o filtro do frontend e fallback de nomes
MODALIDADES_LICITACAO = {
    8:  "Pregão - Eletrônico",
    9:  "Pregão - Presencial",
    4:  "Concorrência - Eletrônica",
    5:  "Concorrência - Presencial",
    10: "Dispensa de Licitação",
    11: "Inexigibilidade",
    2:  "Diálogo Competitivo",
    13: "Compra Direta",
    1:  "Leilão",
    3:  "Concurso",
    6:  "Manifestação de Interesse",
    7:  "Pré-qualificação"
}

def _fmt_data(d):
    return d.replace("-", "")[:8] if d else ""

def _parse(item):
    cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
    ano  = item.get("anoCompra", "")
    seq  = item.get("sequencialCompra", "")
    link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj and ano and seq else ""
    nc   = item.get("numeroControlePNCP") or f"{cnpj}-{ano}-{seq}"
    mod_id = item.get("modalidadeId")
    mod  = item.get("modalidadeNome") or MODALIDADES_LICITACAO.get(mod_id, "")
    val  = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0
    un   = item.get("unidadeOrgao", {})
    org  = item.get("orgaoEntidade", {}).get("razaoSocial", "") or un.get("nomeUnidade", "")
    def fd(d): return str(d)[:10] if d else ""
    return {
        "numero_controle": nc,
        "numero_edital":   str(item.get("numeroCompra", seq)),
        "objeto":          item.get("objetoCompra", ""),
        "orgao":           org,
        "uf":              un.get("ufSigla", ""),
        "municipio":       un.get("municipioNome", ""),
        "modalidade":      mod,
        "situacao":        item.get("situacaoCompraNome", ""),
        "data_publicacao": fd(item.get("dataPublicacaoPncp", "")),
        "data_abertura":   fd(item.get("dataAberturaProposta", "")),
        "valor_estimado":  float(val) if val else 0.0,
        "link_edital":     link,
        "cnpj_orgao":      cnpj,
        "ano":             int(ano) if str(ano).isdigit() else None,
        "sequencial":      int(seq) if str(seq).isdigit() else None,
    }

def _buscar_pagina(data_ini, data_fim, uf="", mod_id=None, pagina=1):
    # Parâmetros base: puxa tudo o que foi publicado nas datas informadas
    params = {
        "dataInicial": data_ini,
        "dataFinal":   data_fim,
        "pagina":      pagina,
        "tamanhoPagina": 50,
    }
    
    # Se o usuário escolheu uma modalidade específica no filtro, nós aplicamos
    if mod_id:
        params["codigoModalidadeContratacao"] = mod_id
    if uf:
        params["uf"] = uf.upper()

    tentativas = 4
    for tentativa in range(tentativas):
        try:
            r = requests.get(f"{BASE_URL}/contratacoes/publicacao", params=params, headers=HEADERS, timeout=60)
            if r.status_code == 204:
                return {"dados": [], "total_paginas": 0, "total_registros": 0}
            r.raise_for_status()
            d = r.json()
            return {
                "dados":           [_parse(i) for i in d.get("data", [])],
                "total_paginas":   d.get("totalPaginas", 1),
                "total_registros": d.get("totalRegistros", 0),
            }
        except Exception as e:
            if tentativa < tentativas - 1:
                espera = (tentativa + 1) * 3
                print(f"[PNCP] Lentidão no governo (Pág {pagina}). Tentando em {espera}s... ({e})")
                time.sleep(espera)
            else:
                print(f"[PNCP] ❌ Falha definitiva na página {pagina}: {e}")
    
    return {"dados": [], "total_paginas": 1, "total_registros": 0, "erro": True}

def buscar_multiplas_paginas(
    data_inicial="", data_final="", uf="",
    modalidade_id=None, palavras_chave="",
    max_paginas=50, # Aumentamos para 50 páginas (2.500 licitações) num único fluxo
):
    ini = _fmt_data(data_inicial) or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    fim = _fmt_data(data_final)   or datetime.now().strftime("%Y%m%d")

    todas = []
    total_api = 0
    pags = max_paginas if not palavras_chave else max(max_paginas, 60)

    # Verifica se estamos buscando o fluxo geral ou apenas uma modalidade específica pedida pelo filtro
    tipo_busca = MODALIDADES_LICITACAO.get(int(modalidade_id), "Todas as Modalidades") if modalidade_id else "TODAS AS MODALIDADES MISTURADAS"
    print(f"[PNCP] 🔍 Iniciando extração: {tipo_busca} | {ini}→{fim}")
    
    # Loop único: avança as páginas pegando tudo o que o governo tiver na ordem de publicação
    for p in range(1, pags + 1):
        res = _buscar_pagina(data_ini=ini, data_fim=fim, uf=uf, mod_id=modalidade_id, pagina=p)
        
        if res.get("erro"):
            print(f"[PNCP] ⚠️ Instabilidade no portal na página {p}. Interrompendo busca para salvar o que já foi baixado.")
            break 
            
        dados = res.get("dados", [])
        if not dados:
            break 
            
        todas.extend(dados)
        if p == 1:
            total_api += res.get("total_registros", 0)
            
        time.sleep(0.5) # Pausa rápida para não ser bloqueado pelo governo
        
        if p >= res.get("total_paginas", 1):
            break

    # Filtro local de palavras-chave
    if palavras_chave and todas:
        termos = palavras_chave.lower().split()
        todas  = [
            l for l in todas
            if all(
                t in (l.get("objeto") or "").lower() or
                t in (l.get("orgao") or "").lower()
                for t in termos
            )
        ]

    return {"sucesso": True, "dados": todas, "total_api": total_api}

def varredura_completa(dias=1):
    fim = datetime.now().strftime("%Y%m%d")
    ini = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
    # Traz as últimas 50 páginas (cerca de 2.500 licitações) do fluxo geral do dia
    return buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=50)

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MODALIDADES_LICITACAO.items()]

def testar_conexao():
    try:
        # Ping simples no portal sem forçar modalidades
        r = requests.get(f"{BASE_URL}/contratacoes/publicacao", params={"dataInicial": datetime.now().strftime("%Y%m%d"), "dataFinal": datetime.now().strftime("%Y%m%d"), "pagina": 1, "tamanhoPagina": 1}, headers=HEADERS, timeout=10)
        return {"online": r.status_code in (200, 204), "mensagem": f"Status {r.status_code}"}
    except Exception as e:
        return {"online": False, "mensagem": str(e)}
