from getpass import getpass

import servico
from auth import autenticar, AutenticacaoErro

login = input("Login: ")
senha = getpass("Senha: ")

try:
    usuario = autenticar(login, senha)
except AutenticacaoErro as erro:
    print(erro)
    raise SystemExit(1)

print(f"Perfil: {usuario['perfil']}")

try:
    caminho, total = servico.exportar_contatos_csv(usuario, cargo="Analista")
    print(f"Exportados {total} contatos para: {caminho}")
except PermissionError as erro:
    print("Bloqueado:", erro)