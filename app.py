import json
import math
import os
import re
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from flask import (Flask, abort, flash, redirect, render_template,
                   request, send_file, session, url_for)
from flask_wtf.csrf import CSRFProtect, CSRFError

import servico
from auth import autenticar, tem_permissao, exigir_permissao, AutenticacaoErro

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Defina SECRET_KEY no arquivo .env")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

CSRFProtect(app)

POR_PAGINA = 10
CAMPOS = ["nome", "endereco", "email", "telefone",
          "cargo", "data_nascimento", "cpf"]


# ---------- Utilidades ----------

def login_obrigatorio(funcao):
    @wraps(funcao)
    def envoltorio(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return envoltorio


@app.context_processor
def injetar_no_template():
    usuario = session.get("usuario")
    pendentes = 0
    if usuario and tem_permissao(usuario, "gerenciar_usuarios"):
        pendentes = servico.contar_usuarios_pendentes(usuario)
    return {
        "usuario": usuario,
        "pendentes": pendentes,
        "pode": (lambda p: tem_permissao(usuario, p)) if usuario else (lambda p: False),
    }


@app.template_filter("data_br")
def data_br(valor):
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y") if hasattr(valor, "strftime") else valor


@app.template_filter("data_iso")
def data_iso(valor):
    if not valor:
        return ""
    return valor.isoformat() if hasattr(valor, "isoformat") else valor


@app.template_filter("json_legivel")
def json_legivel(valor):
    return json.dumps(valor, indent=2, ensure_ascii=False)


def _normalizar_cpf(texto):
    """Valida o CPF e devolve no formato 000.000.000-00 (ou None se inválido)."""
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return None
    for i in (9, 10):
        soma = sum(int(d) * (i + 1 - n) for n, d in enumerate(digitos[:i]))
        if (soma * 10 % 11) % 10 != int(digitos[i]):
            return None
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def _ler_formulario():
    """Lê e valida os campos do formulário. Devolve (dados, lista_de_erros)."""
    dados = {c: request.form.get(c, "").strip() or None for c in CAMPOS}
    erros = []

    if not dados["nome"]:
        erros.append("O nome é obrigatório.")
    if dados["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", dados["email"]):
        erros.append("E-mail inválido.")
    if dados["data_nascimento"]:
        try:
            date.fromisoformat(dados["data_nascimento"])
        except ValueError:
            erros.append("Data de nascimento inválida.")
    if dados["cpf"]:
        cpf = _normalizar_cpf(dados["cpf"])
        if cpf:
            dados["cpf"] = cpf
        else:
            erros.append("CPF inválido.")
    return dados, erros


def _tentar_salvar(funcao, *args):
    """Executa a gravação. Devolve (resultado, mensagem_de_erro)."""
    try:
        return funcao(*args), None
    except psycopg2.errors.UniqueViolation:
        return None, "Já existe um contato com esse CPF ou e-mail."
    except ValueError as erro:
        return None, str(erro)
    except psycopg2.Error:
        app.logger.exception("Erro ao gravar contato")
        return None, "Não foi possível salvar. Tente novamente."


# ---------- Erros ----------

@app.errorhandler(PermissionError)
def sem_permissao(erro):
    return render_template("erro.html", titulo="Acesso negado",
                           mensagem=str(erro)), 403


@app.errorhandler(404)
def nao_encontrado(erro):
    return render_template("erro.html", titulo="Página não encontrada",
                           mensagem="O endereço ou o registro não existe."), 404


@app.errorhandler(CSRFError)
def csrf_invalido(erro):
    return render_template("erro.html", titulo="Sessão expirada",
                           mensagem="Recarregue a página e tente novamente."), 400


# ---------- Login ----------

@app.route("/")
def inicio():
    return redirect(url_for("listar"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            usuario = autenticar(request.form.get("login", ""),
                                 request.form.get("senha", ""))
        except AutenticacaoErro as erro:
            flash(str(erro), "erro")
        else:
            session.clear()
            session["usuario"] = usuario
            session.permanent = True
            return redirect(url_for("listar"))
    return render_template("login.html")

# ---------- Logout ----------  

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------Cadastro -------------

@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if "usuario" in session:
        return redirect(url_for("listar"))

    dados = {"nome": "", "login": ""}
    if request.method == "POST":
        dados["nome"] = request.form.get("nome", "").strip()
        dados["login"] = request.form.get("login", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar", "")

        erros = []
        if not dados["nome"]:
            erros.append("Informe seu nome.")
        elif len(dados["nome"]) > 100:
            erros.append("O nome deve ter no máximo 100 caracteres.")
        if not re.fullmatch(r"[a-z0-9._-]{3,50}", dados["login"]):
            erros.append("O login deve ter de 3 a 50 caracteres: letras minúsculas, "
                         "números, ponto, hífen ou sublinhado.")
        if senha != confirmar:
            erros.append("As senhas não conferem.")

        if not erros:
            try:
                servico.cadastrar_leitor(dados["login"], dados["nome"], senha)
            except ValueError as erro:
                erros.append(str(erro))
            except psycopg2.Error:
                app.logger.exception("Erro ao cadastrar usuário")
                erros.append("Não foi possível concluir o cadastro. Tente novamente.")
            else:
                flash("Cadastro enviado! Você poderá entrar assim que um " 
                      "administrador aprovar seu acesso.", "ok")
                return redirect(url_for("login"))

        for erro in erros:
            flash(erro, "erro")

    return render_template("cadastro.html", **dados)

# ---------- Contatos ----------

@app.route("/contatos")
@login_obrigatorio
def listar():
    usuario = session["usuario"]
    nome = request.args.get("nome", "").strip()
    cargo = request.args.get("cargo", "").strip()
    pagina = max(request.args.get("pagina", 1, type=int), 1)

    filtros = {"nome": nome or None, "cargo": cargo or None}
    total = servico.contar_contatos(usuario, **filtros)
    total_paginas = max(math.ceil(total / POR_PAGINA), 1)
    pagina = min(pagina, total_paginas)

    contatos = servico.filtrar_contatos(
        usuario, **filtros, limite=POR_PAGINA, offset=(pagina - 1) * POR_PAGINA
    )
    return render_template("contatos.html", contatos=contatos, nome=nome,
                           cargo=cargo, pagina=pagina,
                           total_paginas=total_paginas, total=total)


@app.route("/contatos/novo", methods=["GET", "POST"])
@login_obrigatorio
def novo():
    usuario = session["usuario"]
    exigir_permissao(usuario, "inserir")

    contato = {}
    if request.method == "POST":
        contato, erros = _ler_formulario()
        if not erros:
            _, erro = _tentar_salvar(servico.inserir_contato, usuario, contato)
            if erro:
                erros.append(erro)
            else:
                flash("Contato cadastrado.", "ok")
                return redirect(url_for("listar"))
        for erro in erros:
            flash(erro, "erro")
    return render_template("contato_form.html", contato=contato,
                           titulo="Novo contato")


@app.route("/contatos/<int:contato_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar(contato_id):
    usuario = session["usuario"]
    exigir_permissao(usuario, "editar")

    contato = servico.buscar_por_id(usuario, contato_id)
    if contato is None:
        abort(404)

    if request.method == "POST":
        dados, erros = _ler_formulario()
        if not erros:
            resultado, erro = _tentar_salvar(
                servico.editar_contato, usuario, contato_id, dados)
            if erro:
                erros.append(erro)
            elif resultado is None:
                abort(404)
            else:
                flash("Contato atualizado.", "ok")
                return redirect(url_for("listar"))
        for erro in erros:
            flash(erro, "erro")
        contato = {**dados, "id": contato_id}
    return render_template("contato_form.html", contato=contato,
                           titulo="Editar contato")


@app.route("/contatos/<int:contato_id>/excluir", methods=["POST"])
@login_obrigatorio
def excluir(contato_id):
    if servico.excluir_contato(session["usuario"], contato_id):
        flash("Contato excluído.", "ok")
    else:
        flash("Contato não encontrado.", "erro")
    return redirect(url_for("listar"))


@app.route("/contatos/exportar", methods=["POST"])
@login_obrigatorio
def exportar():
    filtros = {
        "nome": request.form.get("nome", "").strip() or None,
        "cargo": request.form.get("cargo", "").strip() or None,
    }
    caminho, _ = servico.exportar_contatos_csv(session["usuario"], **filtros)
    arquivo = Path(caminho).resolve()
    return send_file(arquivo, as_attachment=True,
                     download_name=arquivo.name, mimetype="text/csv")


# ---------- Auditoria ----------

@app.route("/auditoria")
@login_obrigatorio
def auditoria():
    registros = servico.listar_auditoria(session["usuario"], limite=100)
    return render_template("auditoria.html", registros=registros)

# ---------- Aprovação de usuários ----------

# ---------- Chamados (leitor e editor) ----------

@app.route("/chamados", methods=["GET", "POST"])
@login_obrigatorio
def meus_chamados():
    usuario = session["usuario"]
    if tem_permissao(usuario, "gerenciar_chamados"):
        return redirect(url_for("solicitacoes", aba="abertos"))
    exigir_permissao(usuario, "abrir_chamado")

    dados = {"categoria": "", "assunto": "", "mensagem": ""}
    if request.method == "POST":
        dados = {campo: request.form.get(campo, "").strip() for campo in dados}
        try:
            servico.abrir_chamado(usuario, dados["categoria"],
                                  dados["assunto"], dados["mensagem"])
        except ValueError as erro:
            flash(str(erro), "erro")
        except psycopg2.Error:
            app.logger.exception("Erro ao abrir chamado")
            flash("Não foi possível abrir o chamado. Tente novamente.", "erro")
        else:
            flash("Chamado aberto! A resposta do administrador aparecerá aqui.", "ok")
            return redirect(url_for("meus_chamados"))

    return render_template("chamados.html",
                           chamados_lista=servico.meus_chamados(usuario),
                           categorias=servico.CATEGORIAS_CHAMADO, **dados)


# ---------- Solicitações (admin) ----------

ABAS = ("cadastros", "abertos", "resolvidos")


@app.route("/solicitacoes")
@login_obrigatorio
def solicitacoes():
    usuario = session["usuario"]
    n_cad = servico.contar_usuarios_pendentes(usuario)
    n_ab = servico.contar_chamados_abertos(usuario)

    aba = request.args.get("aba")
    if aba not in ABAS:
        aba = "abertos" if (n_ab and not n_cad) else "cadastros"

    cadastros = []
    lista_chamados = []
    if aba == "cadastros":
        cadastros = servico.listar_usuarios_pendentes(usuario)
    else:
        status = "aberto" if aba == "abertos" else "resolvido"
        lista_chamados = servico.listar_chamados(usuario, status)

    return render_template("solicitacoes.html", aba=aba, n_cad=n_cad, n_ab=n_ab,
                           cadastros=cadastros, lista_chamados=lista_chamados)


@app.route("/usuarios/<int:usuario_id>/aprovar", methods=["POST"])
@login_obrigatorio
def aprovar_usuario(usuario_id):
    aprovado = servico.aprovar_usuario(session["usuario"], usuario_id)
    if aprovado:
        flash(f"Acesso de '{aprovado['login']}' aprovado.", "ok")
    else:
        flash("Solicitação não encontrada ou já tratada.", "erro")
    return redirect(url_for("solicitacoes", aba="cadastros"))


@app.route("/usuarios/<int:usuario_id>/recusar", methods=["POST"])
@login_obrigatorio
def recusar_usuario(usuario_id):
    recusado = servico.recusar_usuario(session["usuario"], usuario_id)
    if recusado:
        flash(f"Solicitação de '{recusado['login']}' recusada.", "ok")
    else:
        flash("Solicitação não encontrada ou já tratada.", "erro")
    return redirect(url_for("solicitacoes", aba="cadastros"))


@app.route("/chamados/<int:chamado_id>/responder", methods=["POST"])
@login_obrigatorio
def responder_chamado(chamado_id):
    resposta = request.form.get("resposta", "")
    try:
        resolvido = servico.responder_chamado(session["usuario"], chamado_id, resposta)
    except ValueError as erro:
        flash(str(erro), "erro")
    else:
        if resolvido:
            flash(f"Chamado #{chamado_id} respondido e marcado como resolvido.", "ok")
        else:
            flash("Chamado não encontrado ou já resolvido.", "erro")
    return redirect(url_for("solicitacoes", aba="abertos"))

if __name__ == "__main__":
    app.run(debug=True)  # debug só para uso local