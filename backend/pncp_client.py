"""
backend/pncp_client.py
Cliente da API pública do PNCP - Versão Padrão Ouro (Anti-Timeout e Nomes Exatos)
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import time

BASE_URL = "https://pncp.gov.br/api/consulta/v1"

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

def get_session():
    """Cria uma sessão blindada contra quedas do governo (tenta 3 vezes antes de falhar)"""
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    return session

def _parse(item):
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

def varredura_completa(dias=1):
    session = get_session()
    fim = datetime.now().strftime("%Y%m%d")
    ini = (datetime.now() - timedelta(days=dias)).strftime("%Y%m%d")
    
    todas = []
    total_api = 0
    
    print(f"[PNCP] 🔍 Buscando fluxo geral: {ini} a {fim}")
    
    # Busca fluxo geral (tudo misturado cronologicamente) para o governo não dar timeout
    # 25 páginas = 1.250 licitações puxadas e traduzidas de uma vez.
    for p in range(1, 26):
        try:
            r = session.get(
                f"{BASE_URL}/contratacoes/publicacao",
                params={"dataInicial": ini, "dataFinal": fim, "pagina": p, "tamanhoPagina": 50},
                timeout=25
            )
            if r.status_code == 204:
                break
            r.raise_for_status()
            d = r.json()
            
            if p == 1:
                total_api = d.get("totalRegistros", 0)
                
            itens = d.get("data", [])
            if not itens:
                break
                
            todas.extend([_parse(i) for i in itens])
            time.sleep(0.3)
            
            if p >= d.get("totalPaginas", 1):
                break
                
        except Exception as e:
            print(f"[PNCP] ⚠️ Governo engasgou na pág {p}. Salvando {len(todas)} registros já puxados. ({e})")
            break
            
    return {"sucesso": True, "dados": todas, "total_api": total_api}

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in MAPA_MODALIDADES.items()]

def testar_conexao():
    try:
        # Teste super leve para não dar erro "PNCP Offline" falso na tela
        r = requests.get(f"{BASE_URL}/contratacoes/publicacao", params={"dataInicial": datetime.now().strftime("%Y%m%d"), "dataFinal": datetime.now().strftime("%Y%m%d"), "pagina": 1, "tamanhoPagina": 1}, timeout=5)
        return {"online": r.status_code in (200, 204), "mensagem": "OK"}
    except Exception as e:
        return {"online": False, "mensagem": str(e)}
