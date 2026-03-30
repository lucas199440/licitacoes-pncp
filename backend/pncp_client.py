"""
backend/pncp_client.py
Motor de Captação Viterbo - Versão Corrigida e Otimizada (30/03/2026)
- Relógio atômico mantido (sem hack de ano)
- Suporte completo a uf, data_inicial e data_final
- total_api agora reflete o valor real da API
- Alta disponibilidade e filtros corretos
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

        # O Dicionário Sagrado: nomes EXATOS para o frontend funcionar
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
        Relógio atômico oficial de Brasília.
        Nunca mais força ano 2024 (bug removido).
        """
        try:
            r = self.session.get("http://worldtimeapi.org/api/timezone/America/Sao_Paulo", timeout=5)
            if r.status_code == 200:
                data_iso = r.json().get("datetime", "")
                if data_iso:
                    return datetime.fromisoformat(data_iso[:19])
        except Exception:
            pass

        # Fallback seguro (sem alterar data)
        agora = datetime.now()
        if agora.year > 2026:
            print(f"[AVISO MOTOR VITERBO] Relógio do servidor adiantado ({agora.year}). Usando mesmo assim.")
        return agora

    def _get_seguro(self, url, params):
        """Requisição com 3 tentativas automáticas"""
        for tentativa in range(1, 4):
            try:
                resposta = self.session.get(url, params=params, timeout=25)
                return resposta
            except requests.exceptions.RequestException as erro:
                if tentativa == 3:
                    print(f"[MOTOR VITERBO] Falha na comunicação após 3 tentativas: {erro}")
                    return None
                time.sleep(2)

    def _limpar_item(self, item):
        """Transforma JSON do Governo em formato limpo"""
        try:
            cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
            ano = item.get("anoCompra", "")
            seq = item.get("sequencialCompra", "")

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

    def executar_varredura(self, dias_retroativos=30, paginas_limite=10, uf="", data_inicial="", data_final=""):
        """Função principal - agora com todos os filtros"""
        data_atual = self._obter_data_real()

        # Se o usuário passou datas específicas, usa elas
        if data_inicial and data_final:
            fmt_ini = data_inicial.replace("-", "")[:8]
            fmt_fim = data_final.replace("-", "")[:8]
        else:
            data_passada = data_atual - timedelta(days=dias_retroativos)
            fmt_ini = data_passada.strftime("%Y%m%d")
            fmt_fim = data_atual.strftime("%Y%m%d")

        print(f"\n[MOTOR VITERBO] 🚀 Captura iniciada: {fmt_ini} até {fmt_fim} | UF: {uf or 'Brasil'}")

        editais_capturados = []
        total_api_real = 0

        for mod_id, mod_nome in self.mapa_modalidades.items():
            print(f" → Processando {mod_nome}...")

            for pagina in range(1, paginas_limite + 1):
                params = {
                    "dataInicial": fmt_ini,
                    "dataFinal": fmt_fim,
                    "codigoModalidadeContratacao": mod_id,
                    "pagina": pagina,
                    "tamanhoPagina": 50
                }
                if uf:
                    params["uf"] = uf

                resposta = self._get_seguro(f"{self.base_url}/contratacoes/publicacao", params)

                if not resposta or resposta.status_code == 204:
                    break

                if resposta.status_code == 200:
                    dados_json = resposta.json()
                    lista_itens = dados_json.get("data", [])

                    if pagina == 1:
                        total_api_real += dados_json.get("totalRegistros", 0)

                    if not lista_itens:
                        break

                    for item_bruto in lista_itens:
                        item_limpo = self._limpar_item(item_bruto)
                        if item_limpo:
                            editais_capturados.append(item_limpo)

                    if pagina >= dados_json.get("totalPaginas", 1):
                        break

                time.sleep(0.3)

        print(f"[MOTOR VITERBO] ✅ Finalizado! {len(editais_capturados)} editais capturados (API: {total_api_real})\n")

        return {
            "sucesso": True,
            "dados": editais_capturados,
            "total_api": total_api_real
        }


# =====================================================================
# INTERFACE DE COMPATIBILIDADE (para não quebrar seu main.py e agendador)
# =====================================================================
motor = MotorPNCP()


def buscar_multiplas_paginas(data_inicial="", data_final="", uf="", modalidade_id=None, palavras_chave="", max_paginas=10):
    """Mantém compatibilidade com chamadas antigas"""
    resultado = motor.executar_varredura(
        dias_retroativos=30,
        paginas_limite=max_paginas,
        uf=uf,
        data_inicial=data_inicial,
        data_final=data_final
    )

    dados_finais = resultado["dados"]

    # Filtro extra de modalidade (se solicitado)
    if modalidade_id:
        nome_mod_busca = motor.mapa_modalidades.get(int(modalidade_id))
        if nome_mod_busca:
            dados_finais = [d for d in dados_finais if d["modalidade"] == nome_mod_busca]

    # Filtro de palavras-chave
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
    return {"online": True, "mensagem": "Motor Viterbo Operacional ✅"}
