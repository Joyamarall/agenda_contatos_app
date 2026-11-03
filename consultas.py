import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()


def conectar():
    """Abre uma conexão com o PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def _executar(sql, params=None):
    """Executa um SELECT e devolve uma lista de dicionários."""
    with conectar() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()


def listar_contatos(limite=50, offset=0):
    sql = "SELECT * FROM contatos ORDER BY nome LIMIT %s OFFSET %s"
    return _executar(sql, (limite, offset))


def buscar_por_id(contato_id):
    sql = "SELECT * FROM contatos WHERE id = %s"
    resultado = _executar(sql, (contato_id,))
    return resultado[0] if resultado else None


def filtrar_contatos(nome=None, email=None, cargo=None,
                     nascimento_de=None, nascimento_ate=None,
                     ordenar_por="nome", limite=50, offset=0):
    """Filtros opcionais: só entram na consulta os que você informar."""
    colunas_permitidas = {"nome", "email", "cargo", "data_nascimento"}
    if ordenar_por not in colunas_permitidas:
        ordenar_por = "nome"

    sql = "SELECT * FROM contatos WHERE 1=1"
    params = []

    if nome:
        sql += " AND nome ILIKE %s"
        params.append(f"%{nome}%")
    if email:
        sql += " AND email ILIKE %s"
        params.append(f"%{email}%")
    if cargo:
        sql += " AND cargo ILIKE %s"
        params.append(f"%{cargo}%")
    if nascimento_de:
        sql += " AND data_nascimento >= %s"
        params.append(nascimento_de)
    if nascimento_ate:
        sql += " AND data_nascimento <= %s"
        params.append(nascimento_ate)

    sql += f" ORDER BY {ordenar_por} LIMIT %s OFFSET %s"
    params.extend([limite, offset])

    return _executar(sql, params)


def contar_contatos(nome=None, cargo=None):
    sql = "SELECT COUNT(*) AS total FROM contatos WHERE 1=1"
    params = []
    if nome:
        sql += " AND nome ILIKE %s"
        params.append(f"%{nome}%")
    if cargo:
        sql += " AND cargo ILIKE %s"
        params.append(f"%{cargo}%")
    return _executar(sql, params)[0]["total"]


def aniversariantes_do_mes(mes):
    sql = """
        SELECT * FROM contatos
        WHERE EXTRACT(MONTH FROM data_nascimento) = %s
        ORDER BY EXTRACT(DAY FROM data_nascimento)
    """
    return _executar(sql, (mes,))


if __name__ == "__main__":
    print("Por ID:", buscar_por_id(1))
    print("Analistas:", contar_contatos(cargo="Analista"))
    for c in filtrar_contatos(cargo="Analista", ordenar_por="nome", limite=3):
        print(c["nome"], "-", c["cargo"])
    print("Aniversariantes de outubro:", len(aniversariantes_do_mes(10)))