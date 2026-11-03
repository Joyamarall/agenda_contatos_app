from psycopg2.extras import RealDictCursor, Json

from consultas import conectar

CATEGORIAS = [
    "Exportação de dados",
    "Acesso ou permissão",
    "Erro no sistema",
    "Dúvida de uso",
    "Outro",
]
MAX_ABERTOS_POR_USUARIO = 5


def _auditar(cur, login, acao, registro_id, dados=None):
    cur.execute(
        """
        INSERT INTO auditoria (usuario, acao, tabela, registro_id, dados_depois)
        VALUES (%s, %s, 'chamados', %s, %s)
        """,
        (login[:100], acao, registro_id, Json(dados) if dados else None),
    )


def abrir_chamado(usuario_id, login, categoria, assunto, mensagem):
    categoria = (categoria or "").strip()
    assunto = (assunto or "").strip()
    mensagem = (mensagem or "").strip()

    if categoria not in CATEGORIAS:
        raise ValueError("Selecione uma categoria válida.")
    if not assunto:
        raise ValueError("Informe o assunto.")
    if len(assunto) > 100:
        raise ValueError("O assunto deve ter no máximo 100 caracteres.")
    if not mensagem:
        raise ValueError("Descreva o problema.")
    if len(mensagem) > 2000:
        raise ValueError("A descrição deve ter no máximo 2000 caracteres.")

    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM chamados "
                "WHERE usuario_id = %s AND status = 'aberto'",
                (usuario_id,),
            )
            if cur.fetchone()["total"] >= MAX_ABERTOS_POR_USUARIO:
                raise ValueError(
                    f"Você já tem {MAX_ABERTOS_POR_USUARIO} chamados abertos. "
                    "Aguarde a resposta do administrador."
                )

            cur.execute(
                """
                INSERT INTO chamados (usuario_id, categoria, assunto, mensagem)
                VALUES (%s, %s, %s, %s)
                RETURNING id, categoria, assunto, status, criado_em
                """,
                (usuario_id, categoria, assunto, mensagem),
            )
            novo = cur.fetchone()
            _auditar(cur, login, "CHAMADO_ABRIR", novo["id"],
                     {"categoria": categoria, "assunto": assunto})
            return novo


def listar_do_usuario(usuario_id):
    """Chamados do próprio usuário, do mais recente para o mais antigo."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM chamados WHERE usuario_id = %s "
                "ORDER BY criado_em DESC LIMIT 50",
                (usuario_id,),
            )
            return cur.fetchall()


def listar_por_status(status):
    """Chamados de todos os usuários (uso do admin)."""
    if status == "aberto":
        ordem = "c.criado_em ASC"          # mais antigos primeiro
    elif status == "resolvido":
        ordem = "c.respondido_em DESC"     # mais recentes primeiro
    else:
        raise ValueError("Status inválido.")

    sql = f"""
        SELECT c.*, u.nome, u.login, u.perfil
        FROM chamados c
        JOIN usuarios u ON u.id = c.usuario_id
        WHERE c.status = %s
        ORDER BY {ordem}
        LIMIT 100
    """
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (status,))
            return cur.fetchall()


def contar_abertos():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chamados WHERE status = 'aberto'")
            return cur.fetchone()[0]


def responder_chamado(chamado_id, resposta, respondido_por):
    """Responde e marca como resolvido. Devolve o id ou None se o chamado
    não existir ou já estiver resolvido."""
    resposta = (resposta or "").strip()
    if not resposta:
        raise ValueError("Escreva uma resposta antes de enviar.")
    if len(resposta) > 2000:
        raise ValueError("A resposta deve ter no máximo 2000 caracteres.")

    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chamados
                SET status = 'resolvido', resposta = %s,
                    respondido_por = %s, respondido_em = NOW()
                WHERE id = %s AND status = 'aberto'
                RETURNING id
                """,
                (resposta, respondido_por, chamado_id),
            )
            linha = cur.fetchone()
            if linha:
                _auditar(cur, respondido_por, "CHAMADO_RESPONDER", linha["id"])
            return linha["id"] if linha else None