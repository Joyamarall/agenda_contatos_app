from getpass import getpass

import servico
from auth import autenticar, tem_permissao, AutenticacaoErro

login = input("Login: ")
senha = getpass("Senha: ")

try:
    usuario = autenticar(login, senha)
except AutenticacaoErro as erro:
    print(erro)
    raise SystemExit(1)

print(f"\nBem-vinda, {usuario['nome']} (perfil: {usuario['perfil']})")

print("\nContatos com 'ana' (veja o CPF):")
for c in servico.filtrar_contatos(usuario, nome="ana", limite=3):
    print(" ", c["nome"], "|", c["cpf"])

print("\nPermissões:")
for acao in ("inserir", "editar", "excluir", "ver_auditoria"):
    print(f"  {acao}: {'sim' if tem_permissao(usuario, acao) else 'não'}")

print("\nTentando ver a auditoria...")
try:
    registros = servico.listar_auditoria(usuario, limite=3)
    for r in registros:
        print(" ", r["data_hora"], r["usuario"], r["acao"])
except PermissionError as erro:
    print(" Bloqueado:", erro)