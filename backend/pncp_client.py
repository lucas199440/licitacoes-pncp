"""
backend/pncp_client.py
Cliente da API pública do PNCP.
Lições aprendidas:
- codigoModalidadeContratacao é OBRIGATÓRIO
- Apenas modalidades de licitação (sem leilão, concurso, etc)
- Palavra-chave filtra localmente pois API não tem full-text search
"""

import requests
from datetime import datetime, timedelta
import time

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Apenas modalidades relevantes para assessoria de licitação
# Excluídos: Leilão (1,12), Concurso (3), Manifestação de Interesse (6), Pré-qualificação (7)
MODALIDADES_LICITACAO = {
    8:  "Pregão - Eletrônico",
    9:  "Pregão - Presencial",
    4:  "Concorrência - Eletrônica",
    5:  "Concorrência - Presencial",
    10: "Dispensa de Licitação",
    11: "Inexigibilidade",
    2:  "Diálogo Competitivo",
    13: "Compra Direta",
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


def _buscar_pagina(mod_id, data_ini, data_fim, uf="", pagina=1):
    params = {
        "dataInicial": data_ini,
        "dataFinal":   data_fim,
        "codigoModalidadeContratacao": mod_id,  # OBRIGATÓRIO
        "pagina":      pagina,
        "tamanhoPagina": 50,
    }
    if uf:
        params["uf"] = uf.upper()

    r = requests.get(f"{BASE_URL}/contratacoes/publicacao", params=params, headers=HEADERS, timeout=30)
    if r.status_code == 204:
        return {"dados": [], "total_paginas": 0, "total_registros": 0}
    r.raise_for_status()
    d = r.json()
    return {
        "dados":           [_parse(i) for i in d.get("data", [])],
        "total_paginas":   d.get("totalPaginas", 1),
        "total_registros": d.get("totalRegistros", 0),
    }


def buscar_multiplas_paginas(
    data_inicial="", data_final="", uf="",
    modalidade_id=None, palavras_chave="",
    max_paginas=5,
):
    """
    Busca no PNCP respeitando filtro de modalidade.
    modalidade_id=None → percorre todas as 8 modalidades de licitação.
    modalidade_id=8    → só Pregão Eletrônico.
    """
    ini = _fmt_data(data_inicial) or (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    fim = _fmt_data(data_final)   or datetime.now().strftime("%Y%m%d")

    # Respeita filtro de modalidade
    mods = [int(modalidade_id)] if modalidade_id else list(MODALIDADES_LICITACAO.keys())

    # Com palavra-chave busca mais páginas para garantir cobertura
    pags = max_paginas if not palavras_chave else max(max_paginas, 15)

    todas = []
    total_api = 0

    for mod in mods:
        nome = MODALIDADES_LICITACAO.get(mod, str(mod))
        print(f"[PNCP] {nome} | UF={uf or 'Todas'} | {ini}→{fim}")
        try:
            for p in range(1, pags + 1):
                res = _buscar_pagina(mod, ini, fim, uf, p)
                dados = res.get("dados", [])
                if not dados:
                    break
                todas.extend(dados)
                if p == 1:
                    total_api += res.get("total_registros", 0)
                time.sleep(0.2)
                if p >= res.get("total_paginas", 1):
                    break
        except Exception as e:
            print(f"[PNCP] Erro {nome}: {e}")
            continue

    # Filtro por palavra-chave (local, pois API não suporta)
    if palavras_chave and todas:
        termos = palavras_chave.lower().split()
        antes  = len(todas)
        todas  = [
            l for l in todas
            if all(
                t in (l.get("objeto") or "").lower() or
                t in (l.get("orgao") or "").lower()
                for t in termos
            )
        ]
        print(f"[PNCP] Filtro '{palavras_chave}': {antes}→{len(todas)}")

    return {"sucesso": True, "dados": todas, "total_api": total_api}


def varredura_completa(dias=1):
    """
    Usado pelo agendador automático.
    Busca todas as modalidades do último dia e salva no banco.
    """
    fim = datetime.now().strftime("%Y%m%d")
    ini = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
    return buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)


def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MODALIDADES_LICITACAO.items()]


def testar_conexao():
    try:
        hoje  = datetime.now().strftime("%Y%m%d")
        sete  = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        r = requests.get(
            f"{BASE_URL}/contratacoes/publicacao",
            params={"dataInicial": sete, "dataFinal": hoje,
                    "codigoModalidadeContratacao": 8, "pagina": 1, "tamanhoPagina": 1},
            headers=HEADERS, timeout=10,
        )
        if r.status_code in (200, 204):
            return {"online": True, "mensagem": "API PNCP disponível"}
        return {"online": False, "mensagem": f"Status {r.status_code}"}
    except Exception as e:
        return {"online": False, "mensagem": str(e)}
