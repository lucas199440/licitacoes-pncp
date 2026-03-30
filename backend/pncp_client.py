"""
backend/pncp_client.py
Cliente da API pública do PNCP - Versão Padrão Ouro (Ultraestável + Importação Corrigida)
"""

import requests
from datetime import datetime, timedelta
import time

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# MAPEAMENTO OBRIGATÓRIO: Força o nome no banco a ser 100% igual ao filtro do seu site
MAPA_MODALIDADES = {
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

def _parse(item):
    """Lê um item e evita que dados corrompidos do governo derrubem o servidor"""
    try:
        cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
        ano  = item.get("anoCompra", "")
        seq  = item.get("sequencialCompra", "")
        nc   = item.get("numeroControlePNCP") or f"{cnpj}-{ano}-{seq}"
        
        # TRADUÇÃO FORÇADA: Ignora o que o governo escreveu e usa a nossa tabela perfeita
        mod_id = item.get("modalidadeId")
        nome_perfeito = MAPA_MODALIDADES.get(mod_id, item.get("modalidadeNome", "Outros"))

        val  = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0
        un   = item.get("unidadeOrgao", {})
        org  = item.get("orgaoEntidade", {}).get("razaoSocial", "") or un.get("nomeUnidade", "")
        link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj and ano and seq else ""
        
        def fd(d): return str(d)[:10] if d else ""
        
        return {
            "numero_controle": nc,
            "numero_edital":   str(item.get("numeroCompra", seq)),
            "objeto":          item.get("objetoCompra", ""),
            "orgao":           org,
            "uf":              un.get("ufSigla", ""),
            "municipio":       un.get("municipioNome", ""),
            "modalidade":      nome_perfeito, # <-- Isso garante que o filtro funcione!
            "situacao":        item.get("situacaoCompraNome", ""),
            "data_publicacao": fd(item.get("dataPublicacaoPncp", "")),
            "data_abertura":   fd(item.get("dataAberturaProposta", "")),
            "valor_estimado":  float(val) if val else 0.0,
            "link_edital":     link,
            "cnpj_orgao":      cnpj,
            "ano":             int(ano) if str(ano).isdigit() else None,
            "sequencial":      int(seq) if str(seq).isdigit() else None,
        }
    except Exception as e:
        print(f"[PNCP] Aviso: Item ignorado devido a formatação incorreta do governo: {e}")
        return None

def buscar_multiplas_paginas(
    data_inicial="", data_final="", uf="",
    modalidade_id=None, palavras_chave="",
    max_paginas=20
):
    """Função restaurada para o main.py não dar erro de importação"""
    ini = data_inicial.replace("-", "")[:8] if data_inicial else (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    fim = data_final.replace("-", "")[:8] if data_final else datetime.now().strftime("%Y%m%d")

    todas = []
    total_api = 0
    pags = max_paginas if not palavras_chave else max(max_paginas, 30)

    base_params = {
        "dataInicial": ini,
        "dataFinal": fim,
        "tamanhoPagina": 50
    }
    if uf:
        base_params["uf"] = uf.upper()
    if modalidade_id:
        base_params["codigoModalidadeContratacao"] = modalidade_id

    for p in range(1, pags + 1):
        tentativas = 3
        sucesso_na_pagina = False

        for tentativa in range(tentativas):
            try:
                params = base_params.copy()
                params["pagina"] = p
                
                r = requests.get(
                    f"{BASE_URL}/contratacoes/publicacao",
                    params=params,
                    headers=HEADERS,
                    timeout=25
                )
                if r.status_code == 204:
                    sucesso_na_pagina = True
                    break
                
                r.raise_for_status()
                d = r.json()
                
                if p == 1:
                    total_api = d.get("totalRegistros", 0)
                    
                itens = d.get("data", [])
                if not itens:
                    sucesso_na_pagina = True
                    break
                    
                for i in itens:
                    parsed_item = _parse(i)
                    if parsed_item:
                        todas.append(parsed_item)
                        
                sucesso_na_pagina = True
                time.sleep(0.3)
                
                if p >= d.get("totalPaginas", 1):
                    break # Fim das páginas disponíveis
                    
                break # Sai do loop de tentativas e vai para a próxima página
                
            except Exception as e:
                if tentativa < tentativas - 1:
                    time.sleep(3) # Espera 3 segundos e tenta de novo
                else:
                    print(f"[PNCP] ⚠️ Falha na pág {p} após {tentativas} tentativas. ({e})")

        if not sucesso_na_pagina:
            print(f"[PNCP] Interrompendo busca na página {p}.")
            break

    # Aplica o filtro de palavras-chave se existir
    if palavras_chave and todas:
        termos = palavras_chave.lower().split()
        todas = [
            l for l in todas
            if all(t in (l.get("objeto") or "").lower() or t in (l.get("orgao") or "").lower() for t in termos)
        ]

    return {"sucesso": True, "dados": todas, "total_api": total_api}

def varredura_completa(dias=1):
    fim = datetime.now().strftime("%Y%m%d")
    ini = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
    print(f"[PNCP] 🔍 Buscando fluxo geral (Estável): {ini} a {fim}")
    return buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=20)

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MAPA_MODALIDADES.items()]

def testar_conexao():
    try:
        r = requests.get(
            f"{BASE_URL}/contratacoes/publicacao",
            params={"dataInicial": datetime.now().strftime("%Y%m%d"), "dataFinal": datetime.now().strftime("%Y%m%d"), "pagina": 1, "tamanhoPagina": 1},
            headers=HEADERS,
            timeout=5
        )
        return {"online": r.status_code in (200, 204), "mensagem": "OK"}
    except Exception as e:
        return {"online": False, "mensagem": str(e)}
