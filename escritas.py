import json
from psycopg2.extras import RealDictCursor, Json
from consultas import conectar

COLUNAS_PERMITIDAS = {
    "nome", "endereco", "email", "telefone",
    "cargo", "data_nascimento", "cpf",
}


def _json(dados):
    """Converte dict em JSON (datas viram texto) ou None."""
    if dados is None:
        return None
    return Json(dict(dados), dumps=lambda o: json.dumps(o, default=str))


def _registrar_auditoria(cur, usuario, acao, registro_id, antes=None, depois=None):
    cur.execute(
        """
        INSERT INTO auditoria
            (usuario, acao, tabela, registro_id, dados_antes, dados_depois)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (usuario, acao, "contatos", registro_id, _json(antes), _json(depois)),
    )


def _validar_colunas(dados):
    invalidas = set(dados) - COLUNAS_PERMITIDAS
    if invalidas:
        raise ValueError(f"Campos não permitidos: {', '.join(sorted(invalidas))}")


def inserir_contato(dados, usuario):
    """Insere um contato e devolve o registro criado."""
    _validar_colunas(dados)
    if not dados.get("nome"):
        raise ValueError("O campo 'nome' é obrigatório.")

    colunas = list(dados.keys())
    marcadores = ", ".join(["%s"] * len(colunas))
    sql = (
        f"INSERT INTO contatos ({', '.join(colunas)}) "
        f"VALUES ({marcadores}) RETURNING *"
    )

    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [dados[c] for c in colunas])
            novo = cur.fetchone()
            _registrar_auditoria(cur, usuario, "INSERT", novo["id"], depois=novo)
            return novo


def editar_contato(contato_id, dados, usuario):
    """Atualiza só os campos informados. Devolve o registro atualizado
    ou None se o contato não existir."""
    _validar_colunas(dados)
    if not dados:
        raise ValueError("Nenhum campo informado para atualizar.")

    colunas = list(dados.keys())
    set_sql = ", ".join(f"{c} = %s" for c in colunas)

    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM contatos WHERE id = %s FOR UPDATE", (contato_id,))
            antes = cur.fetchone()
            if antes is None:
                return None

            cur.execute(
                f"UPDATE contatos SET {set_sql} WHERE id = %s RETURNING *",
                [dados[c] for c in colunas] + [contato_id],
            )
            depois = cur.fetchone()
            _registrar_auditoria(cur, usuario, "UPDATE", contato_id, antes, depois)
            return depois


def excluir_contato(contato_id, usuario):
    """Exclui o contato. Devolve True se excluiu, False se não existia."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM contatos WHERE id = %s FOR UPDATE", (contato_id,))
            antes = cur.fetchone()
            if antes is None:
                return False

            cur.execute("DELETE FROM contatos WHERE id = %s", (contato_id,))
            _registrar_auditoria(cur, usuario, "DELETE", contato_id, antes=antes)
            return True

def registrar_exportacao(usuario, filtros, total, arquivo):
    """Registra na auditoria que uma exportação foi feita (sem os dados)."""
    with conectar() as conn:
        with conn.cursor() as cur:
            _registrar_auditoria(
                cur, usuario, "EXPORT", None,
                depois={"filtros": filtros, "total": total, "arquivo": arquivo},
            )
            
def listar_auditoria(limite=50):
    """Últimos registros de auditoria (mais recentes primeiro)."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM auditoria ORDER BY data_hora DESC LIMIT %s", (limite,)
            )
            return cur.fetchall()


if __name__ == "__main__":
    # Teste: cria, edita e exclui um contato fictício
    novo = inserir_contato(
        {
            "nome": "Teste Auditoria",
            "email": "teste@exemplo.com.br",
            "cargo": "Tester",
        },
        usuario="joyce",
    )
    print("Criado:", novo["id"], novo["nome"])

    editado = editar_contato(novo["id"], {"cargo": "QA"}, usuario="joyce")
    print("Editado:", editado["cargo"])

    print("Excluído:", excluir_contato(novo["id"], usuario="joyce"))

    print("\nÚltimos registros da auditoria:")
    for a in listar_auditoria(3):
        print(a["data_hora"], a["usuario"], a["acao"], a["registro_id"])