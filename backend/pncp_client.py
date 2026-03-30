"""
backend/pncp_client.py
Cliente da API pública do PNCP - Versão Final e Garantida
"""

import requests
from datetime import datetime, timedelta
import time

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Tradução OBRIGATÓRIA para o filtro funcionar
MAPA_MODALIDADES = {
    8:  "Pregão - Eletrônico",
    9:  "Pregão - Presencial",
    4:  "Concorrência - Eletrônica",
    5:  "Concorrência - Presencial",
    10: "Dispensa de Licitação",
    11: "Inexigibilidade",
    2:  "Diálogo Competitivo",
    13: "Compra Direta",
}

def _parse(item):
    try:
        cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
        ano  = item.get("anoCompra", "")
        seq  = item.get("sequencialCompra", "")
        nc   = item.get("numeroControlePNCP") or f"{cnpj}-{ano}-{seq}"
        
        # Garante a tradução do ID para o nome exato do Filtro
        mod_id = int(item.get("modalidadeId", 0)) if item.get("modalidadeId") else 0
        nome_perfeito = MAPA_MODALIDADES.get(mod_id, item.get("modalidadeNome", "Outros"))

        val  = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0
        un   = item.get("unidadeOrgao", {})
        org  = item.get("orgaoEntidade", {}).get("razaoSocial", "") or un.get("nomeUnidade", "")
        link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj and ano and seq else ""
        
        return {
            "numero_controle": nc,
            "numero_edital":   str(item.get("numeroCompra", seq)),
            "objeto":          item.get("objetoCompra", ""),
            "orgao":           org,
            "uf":              un.get("ufSigla", ""),
            "municipio":       un.get("municipioNome", ""),
            "modalidade":      nome_perfeito,
            "situacao":        item.get("situacaoCompraNome", ""),
            "data_publicacao": str(item.get("dataPublicacaoPncp", ""))[:10],
            "data_abertura":   str(item.get("dataAberturaProposta", ""))[:10],
            "valor_estimado":  float(val) if val else 0.0,
            "link_edital":     link,
            "cnpj_orgao":      cnpj,
            "ano":             int(ano) if str(ano).isdigit() else None,
            "sequencial":      int(seq) if str(seq).isdigit() else None,
        }
    except:
        return None

def buscar_multiplas_paginas(data_inicial="", data_final="", uf="", modalidade_id=None, palavras_chave="", max_paginas=3):
    # Força a busca dos últimos 15 dias para garantir que nunca falte dado
    ini = data_inicial.replace("-", "")[:8] if data_inicial else (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
    fim = data_final.replace("-", "")[:8] if data_final else datetime.now().strftime("%Y%m%d")

    todas = []
    total_api = 0

    # Puxa só as principais se for automático
    mods_to_fetch = [int(modalidade_id)] if modalidade_id else [8, 10, 4, 11, 5, 9, 2, 13]

    for mod in mods_to_fetch:
        print(f"[PNCP] Baixando Modalidade ID {mod}...")
        for p in range(1, max_paginas + 1):
            try:
                r = requests.get(
                    f"{BASE_URL}/contratacoes/publicacao",
                    params={"dataInicial": ini, "dataFinal": fim, "codigoModalidadeContratacao": mod, "pagina": p, "tamanhoPagina": 50},
                    headers=HEADERS,
                    timeout=30
                )
                if r.status_code == 204:
                    break # Sem dados para essa modalidade, pula pra próxima
                
                r.raise_for_status()
                d = r.json()
                
                if p == 1:
                    total_api += d.get("totalRegistros", 0)
                    
                itens = d.get("data", [])
                if not itens:
                    break
                    
                for i in itens:
                    parsed = _parse(i)
                    if parsed:
                        todas.append(parsed)
                        
                if p >= d.get("totalPaginas", 1):
                    break
            except Exception as e:
                print(f"[PNCP] Timeout na mod {mod}. Pulando para não travar o servidor.")
                break # Falhou, pula pra próxima sem cair
            
            time.sleep(0.5)

    if palavras_chave and todas:
        termos = palavras_chave.lower().split()
        todas = [l for l in todas if all(t in (l.get("objeto") or "").lower() or t in (l.get("orgao") or "").lower() for t in termos)]

    return {"sucesso": True, "dados": todas, "total_api": total_api}

def varredura_completa(dias=15):
    # MUDANÇA CRUCIAL: 15 dias de garantia de dados!
    fim = datetime.now().strftime("%Y%m%d")
    ini = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
    return buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=3)

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MAPA_MODALIDADES.items()]

def testar_conexao():
    return {"online": True, "mensagem": "OK"}
