# Requisitos do Sistema de Inventário OAIBV

Para instalar e executar o Sistema de Inventário OAIBV, você precisará das seguintes bibliotecas Python:

```
flask
flask-login
flask-sqlalchemy
werkzeug
```

## Instruções de Instalação

1. Abra o prompt de comando (CMD)
2. Execute os seguintes comandos para instalar todas as dependências necessárias:

```bash
pip install flask
pip install flask-login
pip install flask-sqlalchemy
pip install werkzeug
```

3. Após instalar as dependências, navegue até a pasta do sistema e execute:

```bash
python create_db.py
python app.py
```

4. Acesse o sistema no navegador através do endereço: http://localhost:5000

## Credenciais Iniciais
- Usuário: admin
- Senha: admin123

**Importante:** Altere a senha do administrador após o primeiro acesso.

## Solução de Problemas

Se encontrar erros relacionados a módulos não encontrados, verifique se todas as dependências foram instaladas corretamente.

Para qualquer outro problema, entre em contato com o suporte técnico.
