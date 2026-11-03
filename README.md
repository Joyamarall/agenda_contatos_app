# Agenda de Contatos

Aplicação web em Flask com PostgreSQL para gerenciar uma agenda de contatos,
com controle de acesso por perfil e auditoria.

## Funcionalidades
- Login com senha protegida (bcrypt) e bloqueio após tentativas erradas
- Autocadastro de leitores com aprovação do administrador
- Perfis: **admin**, **editor** e **leitor**, com permissões diferentes
- Consulta, filtros e paginação de contatos; CPF mascarado para quem não tem permissão
- Cadastro, edição e exclusão de contatos
- Exportação para CSV
- Auditoria de todas as ações (quem fez, o quê e quando)
- Chamados dos usuários para o administrador

## Tecnologias
Python, Flask, PostgreSQL (psycopg2), bcrypt, Jinja2, HTML e CSS.

## Como rodar
1. Crie um banco PostgreSQL e execute o `schema.sql`.
2. Crie o ambiente virtual e instale as dependências:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copie `.env.example` para `.env` e preencha os dados do banco e a `SECRET_KEY`
   (gere uma com `python -c "import secrets; print(secrets.token_hex(32))"`).
4. Crie o primeiro usuário administrador:
   ```bash
   python auth.py
   ```
5. Inicie a aplicação e acesse http://127.0.0.1:5000:
   ```bash
   python app.py
   ```

## Estrutura
- `app.py`: rotas e telas (Flask)
- `servico.py`: regras de permissão (única porta de entrada para os dados)
- `consultas.py`, `escritas.py`, `auth.py`, `chamados.py`: acesso ao banco
- `templates/` e `static/`: interface