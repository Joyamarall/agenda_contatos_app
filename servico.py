import csv
from datetime import date, datetime
from pathlib import Path
import consultas
import escritas
import chamados
import auth
from auth import exigir_permissao, tem_permissao


def _mascarar_cpf(cpf):
    if not cpf:
        return cpf
    if len(cpf) == 14:                  # formato 000.000.000-00
        return f"***.{cpf[4:11]}-**"
    return "***"


def _tratar(contato, usuario):
    """Mascara o CPF para quem não pode vê-lo inteiro."""
    if contato is None:
        return None
    contato = dict(contato)
    if "cpf" in contato and not tem_permissao(usuario, "ver_cpf"):
        contato["cpf"] = _mascarar_cpf(contato["cpf"])
    return contato


# ---------- Consultas ----------

def listar_contatos(usuario, **opcoes):
    exigir_permissao(usuario, "consultar")
    return [_tratar(c, usuario) for c in consultas.listar_contatos(**opcoes)]


def buscar_por_id(usuario, contato_id):
    exigir_permissao(usuario, "consultar")
    return _tratar(consultas.buscar_por_id(contato_id), usuario)


def filtrar_contatos(usuario, **filtros):
    exigir_permissao(usuario, "consultar")
    return [_tratar(c, usuario) for c in consultas.filtrar_contatos(**filtros)]


def contar_contatos(usuario, **filtros):
    exigir_permissao(usuario, "consultar")
    return consultas.contar_contatos(**filtros)


def aniversariantes_do_mes(usuario, mes):
    exigir_permissao(usuario, "consultar")
    return [_tratar(c, usuario) for c in consultas.aniversariantes_do_mes(mes)]


# ---------- Alterações ----------

def inserir_contato(usuario, dados):
    exigir_permissao(usuario, "inserir")
    novo = escritas.inserir_contato(dados, usuario=usuario["login"])
    return _tratar(novo, usuario)


def editar_contato(usuario, contato_id, dados):
    exigir_permissao(usuario, "editar")
    editado = escritas.editar_contato(contato_id, dados, usuario=usuario["login"])
    return _tratar(editado, usuario)


def excluir_contato(usuario, contato_id):
    exigir_permissao(usuario, "excluir")
    return escritas.excluir_contato(contato_id, usuario=usuario["login"])


# ---------- Administração ----------

def listar_auditoria(usuario, limite=50):
    exigir_permissao(usuario, "ver_auditoria")
    return escritas.listar_auditoria(limite)


def criar_usuario(usuario, login, nome, senha, perfil):
    exigir_permissao(usuario, "gerenciar_usuarios")
    return auth.criar_usuario(login, nome, senha, perfil, criado_por=usuario["login"])

# ---------- Exportação ----------

CABECALHOS_CSV = {
    "id": "ID",
    "nome": "Nome",
    "endereco": "Endereço",
    "email": "E-mail",
    "telefone": "Telefone",
    "cargo": "Cargo",
    "data_nascimento": "Data de nascimento",
    "cpf": "CPF",
}


def _formatar_celula(valor):
    if valor is None:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor)
    # Evita "injeção de fórmula" quando o CSV é aberto no Excel
    if texto and texto[0] in "=+-@\t\r":
        texto = "'" + texto
    return texto


def exportar_contatos_csv(usuario, pasta="exportacoes", **filtros):
    """Exporta os contatos (com os mesmos filtros de filtrar_contatos)
    para um arquivo CSV. Devolve (caminho_do_arquivo, total_de_linhas)."""
    exigir_permissao(usuario, "exportar")

    # A exportação traz todos os resultados, sem paginação
    filtros.pop("limite", None)
    filtros.pop("offset", None)

    contatos = [
        _tratar(c, usuario)
        for c in consultas.filtrar_contatos(limite=None, **filtros)
    ]

    Path(pasta).mkdir(exist_ok=True)
    nome_arquivo = f"contatos_{datetime.now():%Y%m%d_%H%M%S}.csv"
    caminho = Path(pasta) / nome_arquivo

    # utf-8-sig e ";" para o Excel em português abrir com os acentos certos
    with open(caminho, "w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(CABECALHOS_CSV.values())
        for contato in contatos:
            escritor.writerow(
                [_formatar_celula(contato.get(coluna)) for coluna in CABECALHOS_CSV]
            )

    escritas.registrar_exportacao(
        usuario["login"], filtros, len(contatos), str(caminho)
    )
    return str(caminho), len(contatos)

# ---------- Autocadastro ----------

def cadastrar_leitor(login, nome, senha):
    """Autocadastro: cria o usuário como leitor, PENDENTE de aprovação."""
    return auth.criar_usuario(login, nome, senha, "leitor",
                              criado_por="autocadastro", aprovado=False)

# ---------- Aprovação de cadastros ----------

def contar_usuarios_pendentes(usuario):
    exigir_permissao(usuario, "gerenciar_usuarios")
    return auth.contar_pendentes()


def listar_usuarios_pendentes(usuario):
    exigir_permissao(usuario, "gerenciar_usuarios")
    return auth.listar_pendentes()


def aprovar_usuario(usuario, usuario_id):
    exigir_permissao(usuario, "gerenciar_usuarios")
    return auth.aprovar_usuario(usuario_id, aprovado_por=usuario["login"])


def recusar_usuario(usuario, usuario_id):
    exigir_permissao(usuario, "gerenciar_usuarios")
    return auth.recusar_usuario(usuario_id, recusado_por=usuario["login"])


# ---------- Chamados ----------

CATEGORIAS_CHAMADO = chamados.CATEGORIAS


def abrir_chamado(usuario, categoria, assunto, mensagem):
    exigir_permissao(usuario, "abrir_chamado")
    return chamados.abrir_chamado(usuario["id"], usuario["login"],
                                  categoria, assunto, mensagem)


def meus_chamados(usuario):
    exigir_permissao(usuario, "abrir_chamado")
    return chamados.listar_do_usuario(usuario["id"])


def contar_chamados_abertos(usuario):
    exigir_permissao(usuario, "gerenciar_chamados")
    return chamados.contar_abertos()


def listar_chamados(usuario, status):
    exigir_permissao(usuario, "gerenciar_chamados")
    return chamados.listar_por_status(status)


def responder_chamado(usuario, chamado_id, resposta):
    exigir_permissao(usuario, "gerenciar_chamados")
    return chamados.responder_chamado(chamado_id, resposta, usuario["login"])


def contar_solicitacoes(usuario):
    """Cadastros pendentes + chamados abertos (selo do menu do admin)."""
    exigir_permissao(usuario, "gerenciar_usuarios")
    exigir_permissao(usuario, "gerenciar_chamados")
    return auth.contar_pendentes() + chamados.contar_abertos()