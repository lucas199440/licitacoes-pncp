"""
database/db.py
Banco de dados PostgreSQL via Supabase.
Compatível com Railway + Supabase gratuito.
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """Cria as tabelas se não existirem."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licitacoes (
            id SERIAL PRIMARY KEY,
            numero_controle TEXT UNIQUE,
            numero_edital TEXT,
            objeto TEXT,
            orgao TEXT,
            uf TEXT,
            municipio TEXT,
            modalidade TEXT,
            situacao TEXT,
            data_publicacao TEXT,
            data_abertura TEXT,
            valor_estimado FLOAT DEFAULT 0,
            link_edital TEXT,
            cnpj_orgao TEXT,
            ano INTEGER,
            sequencial INTEGER,
            criado_em TEXT DEFAULT NOW()::TEXT,
            atualizado_em TEXT DEFAULT NOW()::TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favoritos (
            id SERIAL PRIMARY KEY,
            licitacao_id INTEGER REFERENCES licitacoes(id) ON DELETE CASCADE,
            nota TEXT DEFAULT '',
            adicionado_em TEXT DEFAULT NOW()::TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS filtros_salvos (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            palavras_chave TEXT DEFAULT '',
            uf TEXT DEFAULT '',
            modalidade TEXT DEFAULT '',
            valor_min FLOAT,
            valor_max FLOAT,
            dias_atras INTEGER DEFAULT 30,
            criado_em TEXT DEFAULT NOW()::TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS log_atualizacoes (
            id SERIAL PRIMARY KEY,
            total_inseridas INTEGER DEFAULT 0,
            total_atualizadas INTEGER DEFAULT 0,
            executado_em TEXT DEFAULT NOW()::TEXT
        )
    """)

    # Índices para performance
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lic_uf ON licitacoes(uf)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lic_modalidade ON licitacoes(modalidade)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lic_data ON licitacoes(data_publicacao)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lic_objeto ON licitacoes USING gin(to_tsvector('portuguese', COALESCE(objeto,'')))")

    conn.commit()
    cur.close()
    conn.close()
    print("[DB] Banco PostgreSQL inicializado.")


def salvar_licitacoes(licitacoes: list) -> dict:
    """Upsert de licitações no banco."""
    conn = get_conn()
    cur = conn.cursor()
    inseridas = 0
    atualizadas = 0
    agora = datetime.now().isoformat()

    for l in licitacoes:
        nc = l.get("numero_controle")
        if not nc:
            continue
        cur.execute("SELECT id FROM licitacoes WHERE numero_controle = %s", (nc,))
        existe = cur.fetchone()

        if existe:
            cur.execute("""
                UPDATE licitacoes SET
                    objeto=%s, orgao=%s, uf=%s, municipio=%s, modalidade=%s,
                    situacao=%s, data_publicacao=%s, data_abertura=%s,
                    valor_estimado=%s, link_edital=%s, atualizado_em=%s
                WHERE numero_controle=%s
            """, (
                l.get("objeto"), l.get("orgao"), l.get("uf"), l.get("municipio"),
                l.get("modalidade"), l.get("situacao"), l.get("data_publicacao"),
                l.get("data_abertura"), l.get("valor_estimado"), l.get("link_edital"),
                agora, nc
            ))
            atualizadas += 1
        else:
            cur.execute("""
                INSERT INTO licitacoes (numero_controle, numero_edital, objeto, orgao, uf,
                    municipio, modalidade, situacao, data_publicacao, data_abertura,
                    valor_estimado, link_edital, cnpj_orgao, ano, sequencial, criado_em, atualizado_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                nc, l.get("numero_edital"), l.get("objeto"), l.get("orgao"),
                l.get("uf"), l.get("municipio"), l.get("modalidade"), l.get("situacao"),
                l.get("data_publicacao"), l.get("data_abertura"), l.get("valor_estimado"),
                l.get("link_edital"), l.get("cnpj_orgao"), l.get("ano"), l.get("sequencial"),
                agora, agora
            ))
            inseridas += 1

    conn.commit()
    cur.close()
    conn.close()
    return {"inseridas": inseridas, "atualizadas": atualizadas}


def buscar_licitacoes(
    palavras_chave="", uf="", modalidade="",
    valor_min=None, valor_max=None,
    data_inicio="", data_fim="",
    apenas_favoritos=False,
    pagina=1, por_pagina=50,
) -> dict:
    """Busca no banco PostgreSQL com full-text search nativo."""
    conn = get_conn()
    cur = conn.cursor()

    conditions = []
    params = []

    if apenas_favoritos:
        conditions.append("l.id IN (SELECT licitacao_id FROM favoritos)")

    # Full-text search em português (PostgreSQL nativo — muito mais rápido)
    if palavras_chave:
        conditions.append(
            "to_tsvector('portuguese', COALESCE(l.objeto,'') || ' ' || COALESCE(l.orgao,'')) "
            "@@ plainto_tsquery('portuguese', %s)"
        )
        params.append(palavras_chave)

    if uf:
        conditions.append("UPPER(l.uf) = %s")
        params.append(uf.upper())

    if modalidade:
        conditions.append("LOWER(l.modalidade) LIKE %s")
        params.append(f"%{modalidade.lower()}%")

    if valor_min is not None:
        conditions.append("l.valor_estimado >= %s")
        params.append(valor_min)

    if valor_max is not None:
        conditions.append("l.valor_estimado <= %s")
        params.append(valor_max)

    if data_inicio:
        conditions.append("l.data_publicacao >= %s")
        params.append(data_inicio)

    if data_fim:
        conditions.append("l.data_publicacao <= %s")
        params.append(data_fim)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    cur.execute(f"SELECT COUNT(*) as total FROM licitacoes l {where}", params)
    total = cur.fetchone()["total"]

    offset = (pagina - 1) * por_pagina
    cur.execute(f"""
        SELECT l.*,
               CASE WHEN f.id IS NOT NULL THEN 1 ELSE 0 END AS favoritado,
               f.nota AS nota_favorito
        FROM licitacoes l
        LEFT JOIN favoritos f ON l.id = f.licitacao_id
        {where}
        ORDER BY l.data_publicacao DESC, l.valor_estimado DESC
        LIMIT %s OFFSET %s
    """, params + [por_pagina, offset])

    resultados = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total_paginas": max(1, (total + por_pagina - 1) // por_pagina),
        "resultados": resultados,
    }


def toggle_favorito(licitacao_id: int, nota: str = "") -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM favoritos WHERE licitacao_id = %s", (licitacao_id,))
    existe = cur.fetchone()
    if existe:
        cur.execute("DELETE FROM favoritos WHERE licitacao_id = %s", (licitacao_id,))
        acao = "removido"
    else:
        cur.execute("INSERT INTO favoritos (licitacao_id, nota) VALUES (%s, %s)", (licitacao_id, nota))
        acao = "adicionado"
    conn.commit()
    cur.close()
    conn.close()
    return {"acao": acao, "licitacao_id": licitacao_id}


def salvar_filtro(nome: str, filtros: dict) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO filtros_salvos (nome, palavras_chave, uf, modalidade, valor_min, valor_max, dias_atras)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (
        nome, filtros.get("palavras_chave",""), filtros.get("uf",""),
        filtros.get("modalidade",""), filtros.get("valor_min"),
        filtros.get("valor_max"), filtros.get("dias_atras", 30),
    ))
    fid = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": fid, "nome": nome}


def listar_filtros_salvos() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM filtros_salvos ORDER BY criado_em DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def deletar_filtro(filtro_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM filtros_salvos WHERE id = %s", (filtro_id,))
    conn.commit()
    cur.close()
    conn.close()


def estatisticas_db() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as t FROM licitacoes")
    total = cur.fetchone()["t"]
    cur.execute("SELECT COUNT(*) as t FROM favoritos")
    favs = cur.fetchone()["t"]
    cur.execute("SELECT MAX(atualizado_em) as u FROM licitacoes")
    ultima = cur.fetchone()["u"]
    cur.execute("SELECT modalidade, COUNT(*) as qtd FROM licitacoes GROUP BY modalidade ORDER BY qtd DESC LIMIT 8")
    por_mod = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT uf, COUNT(*) as qtd FROM licitacoes GROUP BY uf ORDER BY qtd DESC LIMIT 10")
    por_uf = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT executado_em, total_inseridas, total_atualizadas FROM log_atualizacoes ORDER BY id DESC LIMIT 1")
    ultimo_log = cur.fetchone()
    cur.close()
    conn.close()
    return {
        "total_licitacoes": total,
        "total_favoritos": favs,
        "ultima_atualizacao": ultima,
        "por_modalidade": por_mod,
        "por_uf": por_uf,
        "ultimo_log": dict(ultimo_log) if ultimo_log else None,
    }


def registrar_log(inseridas: int, atualizadas: int):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO log_atualizacoes (total_inseridas, total_atualizadas) VALUES (%s,%s)",
            (inseridas, atualizadas)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LOG] Erro: {e}")
