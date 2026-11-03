from datetime import datetime, timedelta
from getpass import getpass

import bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor, Json

from consultas import conectar

MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15

PERMISSOES = {
    "admin": {"consultar", "ver_cpf", "inserir", "editar", "excluir",
              "exportar", "ver_auditoria", "gerenciar_usuarios",
              "gerenciar_chamados"},
    "editor": {"consultar", "ver_cpf", "inserir", "editar", "exportar",
               "abrir_chamado"},
    "leitor": {"consultar", "exportar", "abrir_chamado"},
}

# Hash falso, usado para o tempo de resposta ser igual quando o login não existe
_HASH_FALSO = bcrypt.hashpw(b"senha-falsa", bcrypt.gensalt())


class AutenticacaoErro(Exception):
    pass


def _hash_senha(senha):
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _confere_senha(senha, senha_hash):
    dados = senha.encode("utf-8")
    if len(dados) > 72:  # limite do bcrypt
        return False
    return bcrypt.checkpw(dados, senha_hash.encode("utf-8"))


def _auditar(cur, usuario, acao, registro_id, dados=None):
    cur.execute(
        """
        INSERT INTO auditoria
            (usuario, acao, tabela, registro_id, dados_depois)
        VALUES (%s, %s, 'usuarios', %s, %s)
        """,
        (usuario[:100], acao, registro_id, Json(dados) if dados else None),
    )


# ---------- Permissões ----------

def tem_permissao(usuario, permissao):
    return permissao in PERMISSOES.get(usuario["perfil"], set())


def exigir_permissao(usuario, permissao):
    if not tem_permissao(usuario, permissao):
        raise PermissionError("Você não tem permissão para esta ação.")


# ---------- Criar Usuários ----------

def criar_usuario(login, nome, senha, perfil, criado_por="sistema", aprovado=True):
    login = (login or "").strip().lower()
    nome = (nome or "").strip()
    perfil = (perfil or "").strip().lower()

    if not login or not nome:
        raise ValueError("Login e nome são obrigatórios.")
    if perfil not in PERMISSOES:
        raise ValueError(f"Perfil inválido. Use: {', '.join(PERMISSOES)}.")
    if len(senha) < 8 or len(senha.encode("utf-8")) > 72:
        raise ValueError("A senha deve ter de 8 a 72 caracteres.")

    try:
        with conectar() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (login, nome, senha_hash, perfil, aprovado)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, login, nome, perfil, aprovado
                    """,
                    (login, nome, _hash_senha(senha), perfil, aprovado),
                )
                novo = cur.fetchone()
                _auditar(cur, criado_por, "INSERT", novo["id"],
                         {"login": novo["login"], "perfil": novo["perfil"],
                          "aprovado": novo["aprovado"]})
                return novo
    except psycopg2.errors.UniqueViolation:
        raise ValueError("Já existe um usuário com esse login.")


# --------- Autenticar ----------

def autenticar(login, senha):
    """Devolve o dict do usuário se o login estiver correto.
    Caso contrário, levanta AutenticacaoErro."""
    login = (login or "").strip().lower()
    if not login or not senha:
        raise AutenticacaoErro("Login ou senha inválidos.")

    agora = datetime.now()
    usuario_ok = None
    motivo = None
    registro_id = None

    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM usuarios WHERE login = %s FOR UPDATE", (login,))
            u = cur.fetchone()

            if u is None:
                bcrypt.checkpw(b"senha-falsa", _HASH_FALSO)
                motivo = "usuario_inexistente"
            else:
                registro_id = u["id"]
                if not u["ativo"]:
                    motivo = "inativo"
                elif u["bloqueado_ate"] and u["bloqueado_ate"] > agora:
                    motivo = "bloqueado"
                elif not _confere_senha(senha, u["senha_hash"]):
                    motivo = "senha_incorreta"
                    falhas = u["tentativas_falhas"] + 1
                    if falhas >= MAX_TENTATIVAS:
                        cur.execute(
                            "UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = %s "
                            "WHERE id = %s",
                            (agora + timedelta(minutes=BLOQUEIO_MINUTOS), u["id"]),
                        )
                    else:
                        cur.execute(
                            "UPDATE usuarios SET tentativas_falhas = %s WHERE id = %s",
                            (falhas, u["id"]),
                        )
                elif not u["aprovado"]:
                    # só chega aqui com a senha correta, então não revela
                    # a existência do login para quem não sabe a senha
                    motivo = "aguardando_aprovacao"
                else:
                    cur.execute(
                        "UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL "
                        "WHERE id = %s",
                        (u["id"],),
                    )
                    usuario_ok = {
                        "id": u["id"], "login": u["login"],
                        "nome": u["nome"], "perfil": u["perfil"],
                    }

            _auditar(
                cur, login,
                "LOGIN" if usuario_ok else "LOGIN_FALHA",
                registro_id,
                None if usuario_ok else {"motivo": motivo},
            )

    if usuario_ok is None:
        if motivo == "bloqueado":
            raise AutenticacaoErro(
                "Conta temporariamente bloqueada. Tente novamente em alguns minutos."
            )
        if motivo == "aguardando_aprovacao":
            raise AutenticacaoErro(
                "Seu cadastro ainda aguarda a aprovação de um administrador."
            )
        raise AutenticacaoErro("Login ou senha inválidos.")
    return usuario_ok


# ------------------------------

def contar_pendentes():
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM usuarios WHERE aprovado = FALSE")
            return cur.fetchone()[0]


def listar_pendentes():
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, login, nome, perfil, criado_em FROM usuarios "
                "WHERE aprovado = FALSE ORDER BY criado_em"
            )
            return cur.fetchall()


def aprovar_usuario(usuario_id, aprovado_por):
    """Aprova um cadastro pendente. Devolve o usuário ou None."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE usuarios SET aprovado = TRUE "
                "WHERE id = %s AND aprovado = FALSE "
                "RETURNING id, login, nome, perfil",
                (usuario_id,),
            )
            u = cur.fetchone()
            if u:
                _auditar(cur, aprovado_por, "APROVAR", u["id"],
                         {"login": u["login"], "perfil": u["perfil"]})
            return u


def recusar_usuario(usuario_id, recusado_por):
    """Remove um cadastro pendente. Só atua sobre pendentes, nunca sobre
    usuários já aprovados. Devolve o usuário removido ou None."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "DELETE FROM usuarios WHERE id = %s AND aprovado = FALSE "
                "RETURNING id, login, nome, perfil",
                (usuario_id,),
            )
            u = cur.fetchone()
            if u:
                _auditar(cur, recusado_por, "RECUSAR", u["id"],
                         {"login": u["login"], "perfil": u["perfil"]})
            return u

#------------------------------

if __name__ == "__main__":
    # Rode `python auth.py` para criar usuários pelo terminal
    print("=== Criar usuário ===")
    login = input("Login: ")
    nome = input("Nome: ")
    perfil = input("Perfil (admin/editor/leitor): ")
    senha = getpass("Senha (mínimo 8 caracteres): ")
    confirmar = getpass("Confirme a senha: ")

    if senha != confirmar:
        print("As senhas não conferem.")
        raise SystemExit(1)

    try:
        novo = criar_usuario(login, nome, senha, perfil, criado_por="terminal")
        print(f"Usuário '{novo['login']}' criado com perfil '{novo['perfil']}'.")
    except ValueError as erro:
        print("Erro:", erro)