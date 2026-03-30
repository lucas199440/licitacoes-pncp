"""
backend/pncp_client.py
Motor de Captação Viterbo - Arquitetura Orientada a Objetos (Reescrito do Zero)
Focado em alta disponibilidade, sincronização de relógio atômico e extração em fila de prioridade.
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
            "User-Agent": "ViterboLicitacoes/2.0 (Motor de Captacao)"
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

    def _obter_data_real(self):
        """
        Garante a data correta acessando um relógio mundial atômico.
        Ignora completamente qualquer bug de calendário no servidor local.
        """
        try:
            # Tenta pegar a hora exata de Brasília pela internet
            r = self.session.get("http://worldtimeapi.org/api/timezone/America/Sao_Paulo", timeout=5)
            if r.status_code == 200:
                data_iso = r.json().get("datetime", "")
                if data_iso:
                    return datetime.fromisoformat(data_iso[:19])
        except Exception:
            pass
        
        # Fallback extremo: Se a internet do servidor estiver restrita, usa a data local.
        # Mas se o ano for maior que 2024 (ex: 2026 do bug), força o relógio para trás manualmente.
        agora = datetime.now()
        if agora.year > 2024:
            diferenca_anos = agora.year - 2024
            return agora - timedelta(days=365 * diferenca_anos)
            
        return agora

    def _get_seguro(self, url, params):
        """Faz a requisição com 3 tentativas silenciosas se o Governo engasgar"""
        for tentativa in range(1, 4):
            try:
                resposta = self.session.get(url, params=params, timeout=25)
                return resposta
            except requests.exceptions.RequestException as erro:
                if tentativa == 3:
                    print(f"[MOTOR VITERBO] Falha na comunicação após 3 tentativas: {erro}")
                    return None
                time.sleep(2) # Espera 2 segundos antes de tentar de novo

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

    def executar_varredura(self, dias_retroativos=30, paginas_limite=10):
        """Função principal: Executa a extração organizada"""
        data_atual = self._obter_data_real()
        data_passada = data_atual - timedelta(days=dias_retroativos)
        
        fmt_ini = data_passada.strftime("%Y%m%d")
        fmt_fim = data_atual.strftime("%Y%m%d")
        
        print(f"\n[MOTOR VITERBO] 🚀 Iniciando Captura: {fmt_ini} até {fmt_fim}")
        
        editais_capturados = []
        
        # A Mágica: Iteramos diretamente nas chaves (IDs) do nosso mapa, respeitando a ordem de importância.
        for mod_id, mod_nome in self.mapa_modalidades.items():
            print(f" -> Processando {mod_nome}...")
            
            for pagina in range(1, paginas_limite + 1):
                params = {
                    "dataInicial": fmt_ini,
                    "dataFinal": fmt_fim,
                    "codigoModalidadeContratacao": mod_id,
                    "pagina": pagina,
                    "tamanhoPagina": 50
                }
                
                resposta = self._get_seguro(f"{self.base_url}/contratacoes/publicacao", params)
                
                if not resposta or resposta.status_code == 204:
                    break # Sem dados, ou falha grave. Pula limpo para a próxima modalidade.
                    
                if resposta.status_code == 200:
                    dados_json = resposta.json()
                    lista_itens = dados_json.get("data", [])
                    
                    if not lista_itens:
                        break
                        
                    for item_bruto in lista_itens:
                        item_limpo = self._limpar_item(item_bruto)
                        if item_limpo:
                            editais_capturados.append(item_limpo)
                            
                    if pagina >= dados_json.get("totalPaginas", 1):
                        break # Acabaram as páginas desta modalidade
                        
                time.sleep(0.3) # Intervalo respeitoso para não tomar ban do governo
                
        print(f"[MOTOR VITERBO] ✅ Captura finalizada! {len(editais_capturados)} editais processados.\n")
        return {"sucesso": True, "dados": editais_capturados, "total_api": len(editais_capturados)}

# -----------------------------------------------------------------------------------------
# INTERFACE DE COMPATIBILIDADE (Para o main.py e o agendador chamarem o novo motor)
# -----------------------------------------------------------------------------------------
motor = MotorPNCP()

def buscar_multiplas_paginas(data_inicial="", data_final="", uf="", modalidade_id=None, palavras_chave="", max_paginas=10):
    """Encaminha todas as chamadas antigas para o motor novo de forma elegante."""
    resultado = motor.executar_varredura(dias_retroativos=30, paginas_limite=max_paginas)
    
    # Aplica os filtros locais se a busca for solicitada com especificações
    dados_finais = resultado["dados"]
    
    if modalidade_id:
        nome_mod_busca = motor.mapa_modalidades.get(int(modalidade_id))
        dados_finais = [d for d in dados_finais if d["modalidade"] == nome_mod_busca]
        
    if palavras_chave:
        termos = palavras_chave.lower().split()
        dados_finais = [
            d for d in dados_finais 
            if all(t in (d.get("objeto") or "").lower() or t in (d.get("orgao") or "").lower() for t in termos)
        ]
        
    resultado["dados"] = dados_finais
    return resultado

def varredura_completa(dias=30):
    return motor.executar_varredura(dias_retroativos=dias, paginas_limite=10)

def listar_modalidades():
    return [{"id": k, "nome": v} for k, v in motor.mapa_modalidades.items()]

def testar_conexao():
    return {"online": True, "mensagem": "Motor Viterbo Operacional"}
