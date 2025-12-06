# Sistema de Inventário OAIBV - Documentação

## Visão Geral
O Sistema de Inventário OAIBV é uma aplicação web desenvolvida em Flask com SQLite para gerenciar o inventário, controle de empréstimos, transações e usuários da OAIBV – Organização e Apoio à Igreja em Boa Vista.

## Funcionalidades Principais
- Controle de acesso com login e senha
- Gestão de inventário (cadastro, edição, busca)
- Registro de transações (entrada e saída)
- Controle de empréstimos
- Geração de relatórios
- Gestão de usuários
- Registro automático de logs

## Requisitos do Sistema
- Python 3.6 ou superior
- Flask e suas dependências
- Navegador web moderno

## Instalação e Execução

### 1. Instalar dependências
```bash
pip install flask flask-sqlalchemy werkzeug
```

### 2. Inicializar o banco de dados
```bash
python create_db.py
```

### 3. Executar a aplicação
```bash
python app.py
```

### 4. Acessar o sistema
Abra o navegador e acesse: http://localhost:5000

## Credenciais Iniciais
- Usuário: admin
- Senha: admin123

**Importante:** Altere a senha do administrador após o primeiro acesso.

## Estrutura do Sistema

### Módulos Principais
1. **Autenticação**: Controle de acesso com limite de 5 tentativas
2. **Dashboard**: Visão geral dos dados do sistema
3. **Inventário**: Gestão de itens com filtros e busca
4. **Transações**: Registro de entradas e saídas
5. **Empréstimos**: Controle de itens emprestados
6. **Relatórios**: Visualização e exportação de dados
7. **Usuários**: Gestão de usuários (admin e comum)
8. **Logs**: Registro de atividades do sistema

### Estrutura de Arquivos
- `app.py`: Aplicação principal
- `models.py`: Modelos de dados
- `create_db.py`: Script de inicialização do banco
- `templates/`: Arquivos HTML
- `static/`: Arquivos CSS, JavaScript e imagens

## Guia de Uso

### Inventário
- Cadastre itens com tombamento único
- Utilize filtros para buscar itens específicos
- Edite informações dos itens (apenas administradores)

### Transações
- Registre entradas e saídas de itens
- O sistema atualiza automaticamente o estoque
- Visualize o histórico de transações

### Empréstimos
- Registre empréstimos com dados do solicitante
- Devolva itens quando retornados
- O sistema atualiza automaticamente o estoque

### Relatórios
- Filtre por grupo ou data
- Exporte dados em formato CSV

### Usuários
- Crie novos usuários (admin ou comum)
- Edite informações de usuários existentes
- Redefina senhas quando necessário

## Segurança
- Senhas armazenadas com hash
- Proteção contra tentativas excessivas de login
- Controle de acesso baseado em perfil
- Registro de todas as ações no sistema

## Suporte
Para suporte ou dúvidas, entre em contato com o administrador do sistema.
