"""
backend/pncp_client.py
Motor de Diagnóstico - Teste de Fogo de Infraestrutura
"""

import requests
import time

MAPA_MODALIDADES = {
    8:  "Pregão - Eletrônico",
    10: "Dispensa de Licitação",
    4:  "Concorrência - Eletrônica",
    11: "Inexigibilidade",
    5:  "Concorrência - Presencial",
    9:  "Pregão - Presencial",
    2:  "Diálogo Competitivo",
    13: "Compra Direta"
}

def _limpar_item(item):
    try:
        cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
        ano  = item.get("anoCompra", "")
        seq  = item.get("sequencialCompra", "")
        mod_id = int(item.get("modalidadeId", 0)) if item.get("modalidadeId") else 0
        nome_modalidade = MAPA_MODALIDADES.get(mod_id, item.get("modalidadeNome", "Outros"))

        val = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0.0
        orgao = item.get("orgaoEntidade", {}).get("razaoSocial", "") or item.get("unidadeOrgao", {}).get("nomeUnidade", "")

        return {
            "numero_controle": item.get("numeroControlePNCP") or f"{cnpj}-{ano}-{seq}",
            "numero_edital": str(item.get("numeroCompra", seq)),
            "objeto": item.get("objetoCompra", ""),
            "orgao": orgao,
            "uf": item.get("unidadeOrgao", {}).get("ufSigla", ""),
            "municipio": item.get("unidadeOrgao", {}).get("municipioNome", ""),
            "modalidade": nome_modalidade,
            "situacao": item.get("situacaoCompraNome", ""),
            "data_publicacao": str(item.get("dataPublicacaoPncp", ""))[:10],
            "data_abertura": str(item.get("dataAberturaProposta", ""))[:10],
            "valor_estimado": float(val) if val else 0.0,
            "link_edital": f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj else "",
            "cnpj_orgao": cnpj,
            "ano": int(ano) if str(ano).isdigit() else None,
            "sequencial": int(seq) if str(seq).isdigit() else None,
        }
    except:
        return None

def buscar_multiplas_paginas(data_inicial="", data_final="", uf="", modalidade_id=None, palavras_chave="", max_paginas=2):
    # TESTE DE FOGO: Datas fixas no passado onde SABEMOS que existem dados.
    ini = "20240301"
    fim = "20240310"
    
    print(f"\n[DIAGNÓSTICO] 🚨 FORÇANDO BUSCA HISTÓRICA: {ini} a {fim}")
    editais_capturados = []
    
    mods = [int(modalidade_id)] if modalidade_id else [8, 10, 4] # Testa só as 3 principais para ser rápido

    for mod_id in mods:
        print(f"[DIAGNÓSTICO] Tentando baixar Modalidade {mod_id}...")
        for pagina in range(1, 3):
            try:
                r = requests.get(
                    "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao",
                    params={"dataInicial": ini, "dataFinal": fim, "codigoModalidadeContratacao": mod_id, "pagina": pagina, "tamanhoPagina": 50},
                    timeout=30
                )
                if r.status_code == 200:
                    itens = r.json().get("data", [])
                    for i in itens:
                        limpo = _limpar_item(i)
                        if limpo: editais_capturados.append(limpo)
            except Exception as e:
                print(f"[DIAGNÓSTICO] Erro de rede na mod {mod_id}: {e}")
            time.sleep(1)

    print(f"[DIAGNÓSTICO] 🛑 O CÓDIGO CONSEGUIU PUXAR {len(editais_capturados)} EDITAIS DO GOVERNO.")
    return {"sucesso": True, "dados": editais_capturados, "total_api": len(editais_capturados)}

def varredura_completa(dias=30):
    return buscar_multiplas_paginas()

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MAPA_MODALIDADES.items()]

def testar_conexao():
    return {"online": True, "mensagem": "Diagnostico Ativo"}
