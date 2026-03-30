"""
backend/pncp_client.py
Motor de Captação Viterbo - Arquitetura Refinada
Focado em extração robusta sem manipulação de datas no servidor.
"""

import requests
from datetime import datetime, timedelta
import time

class MotorPNCP:
    def __init__(self):
        self.base_url = "https://pncp.gov.br/api/consulta/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "ViterboLicitacoes/3.0 (Motor de Captacao)"
        })
        
        # O Dicionário Sagrado: Os nomes aqui TEM que ser exatos para o frontend funcionar
        self.mapa_modalidades = {
            8:  "Pregão - Eletrônico",
            10: "Dispensa de Licitação",
            4:  "Concorrência - Eletrônica",
            11: "Inexigibilidade",
            5:  "Concorrência - Presencial",
            9:  "Pregão - Presencial",
            2:  "Diálogo Competitivo",
            13: "Compra Direta"
        }

    def _get_seguro(self, url, params):
        """Faz a requisição com 3 tentativas silenciosas. Timeout de 60s para o PNCP não falhar."""
        for tentativa in range(1, 4):
            try:
                resposta = self.session.get(url, params=params, timeout=60)
                return resposta
            except requests.exceptions.RequestException as erro:
                if tentativa == 3:
                    print(f"[MOTOR VITERBO] Falha na comunicação após 3 tentativas: {erro}")
                    return None
                time.sleep(3) # Espera 3 segundos antes de tentar de novo

    def _limpar_item(self, item):
        """Transforma o JSON confuso do Governo num formato perfeito para o nosso banco"""
        try:
            cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
            ano  = item.get("anoCompra", "")
            seq  = item.get("sequencialCompra", "")
            
            # Padroniza a Modalidade usando apenas o ID
            mod_id = int(item.get("modalidadeId", 0)) if item.get("modalidadeId") else 0
            nome_modalidade = self.mapa_modalidades.get(mod_id, item.get("modalidadeNome", "Outros"))

            orgao = item.get("orgaoEntidade", {}).get("razaoSocial", "")
            if not orgao:
                orgao = item.get("unidadeOrgao", {}).get("nomeUnidade", "")
                
            valor = item.get("valorTotalEstimado") or item.get("valorTotalHomologado") or 0.0

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
                "valor_estimado": float(valor) if valor else 0.0,
                "link_edital": f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if (cnpj and ano and seq) else "",
                "cnpj_orgao": cnpj,
                "ano": int(ano) if str(ano).isdigit() else None,
                "sequencial": int(seq) if str(seq).isdigit() else None,
            }
        except Exception:
            return None

# Instância global do motor
motor = MotorPNCP()

def buscar_multiplas_paginas(data_inicial="", data_final="", uf="", modalidade_id=None, palavras_chave="", max_paginas=10):
    """Função unificada que atende tanto o Agendador quanto as buscas manuais"""
    hoje = datetime.now()
    
    # Usa EXATAMENTE as datas fornecidas ou recua 30 dias a partir de hoje
    ini = data_inicial.replace("-", "")[:8] if data_inicial else (hoje - timedelta(days=30)).strftime("%Y%m%d")
    fim = data_final.replace("-", "")[:8] if data_final else hoje.strftime("%Y%m%d")
    
    print(f"\n[MOTOR VITERBO] 🚀 Extraindo período: {ini} até {fim}")

    editais_capturados = []
    
    # Se pedir uma modalidade específica (ex: filtro), busca só essa. Senão, busca todas da lista de prioridade.
    mods = [int(modalidade_id)] if modalidade_id else list(motor.mapa_modalidades.keys())

    for mod_id in mods:
        nome_mod = motor.mapa_modalidades.get(mod_id, str(mod_id))
        print(f" -> Processando {nome_mod}...")
        
        for pagina in range(1, max_paginas + 1):
            params = {
                "dataInicial": ini,
                "dataFinal": fim,
                "codigoModalidadeContratacao": mod_id,
                "pagina": pagina,
                "tamanhoPagina": 50
            }
            if uf:
                params["uf"] = uf.upper()
                
            resposta = motor._get_seguro(f"{motor.base_url}/contratacoes/publicacao", params)
            
            if not resposta or resposta.status_code == 204:
                break # Sem dados para esta modalidade nestes dias, pula para a próxima de forma limpa
                
            if resposta.status_code == 200:
                dados_json = resposta.json()
                lista_itens = dados_json.get("data", [])
                
                if not lista_itens:
                    break
                    
                for item_bruto in lista_itens:
                    item_limpo = motor._limpar_item(item_bruto)
                    if item_limpo:
                        editais_capturados.append(item_limpo)
                        
                if pagina >= dados_json.get("totalPaginas", 1):
                    break # Acabaram as páginas disponíveis
            
            time.sleep(0.5) # Pausa amigável para não ser bloqueado pelo Governo

    # Aplica o filtro de palavras-chave, se existir
    if palavras_chave and editais_capturados:
        termos = palavras_chave.lower().split()
        editais_capturados = [
            d for d in editais_capturados 
            if all(t in (d.get("objeto") or "").lower() or t in (d.get("orgao") or "").lower() for t in termos)
        ]
        
    print(f"[MOTOR VITERBO] ✅ Captura finalizada! {len(editais_capturados)} editais processados.\n")
    return {"sucesso": True, "dados": editais_capturados, "total_api": len(editais_capturados)}

def varredura_completa(dias=30):
    """Chamado pelo Agendador (background) para alimentar a base de dados."""
    hoje = datetime.now()
    ini = (hoje - timedelta(days=dias)).strftime("%Y%m%d")
    fim = hoje.strftime("%Y%m%d")
    return buscar_multiplas_paginas(data_inicial=ini, data_final=fim, max_paginas=10)

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in motor.mapa_modalidades.items()]

def testar_conexao():
    return {"online": True, "mensagem": "Motor Viterbo Operacional"}
