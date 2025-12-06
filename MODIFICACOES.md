# Modificações Realizadas no Sistema OAIBV

## Resumo das Alterações

Este documento descreve todas as modificações implementadas no sistema de inventário OAIBV conforme as solicitações do usuário.

## 1. Termo de Compromisso
- **Alteração**: Modificado "Quantidade" para "Qtd" no termo de compromisso
- **Motivo**: Melhorar o espaçamento no quadro do PDF
- **Arquivos modificados**: 
  - `templates/termo_compromisso.html`
  - `templates/relatorio_pdf.html`
  - `app.py` (funções de exportação)

## 2. Opção de Edição para Usuário Administrador
- **Alteração**: Adicionado texto "Editar" ao botão de edição
- **Motivo**: Tornar mais clara a função do botão para usuários administradores
- **Arquivos modificados**: 
  - `templates/inventario.html`
  - `templates/inventario_simples.html`

## 3. Relatórios - Adição do Inventário
- **Alteração**: Incluído inventário na aba de relatórios com filtro específico
- **Motivo**: Permitir visualização do inventário junto com transações e empréstimos
- **Arquivos modificados**: 
  - `templates/relatorios.html`
  - `templates/relatorios_simples.html`

## 4. Login Centralizado e Redesign do Título
- **Alteração**: Centralizado o formulário de login e redesenhado o título "Inventário - OAIBV"
- **Motivo**: Melhorar a apresentação visual da página de login
- **Arquivos modificados**: 
  - `templates/login.html`
  - `templates/login_simples.html`

## 5. Logs com Horário e Usuário
- **Alteração**: Adicionado horário junto com a data e nome do usuário nos logs
- **Motivo**: Melhorar a rastreabilidade das ações no sistema
- **Arquivos modificados**: 
  - `app.py` (função `format_date` e `registrar_log`)
  - `templates/logs.html`

## 6. Visualização Completa do Inventário
- **Alteração**: Ajustado para mostrar todas as colunas do cadastro de item
- **Motivo**: Garantir que todas as informações sejam visíveis
- **Arquivos modificados**: 
  - `templates/inventario.html`
  - `templates/inventario_simples.html`

## 7. Simplificação da Execução
- **Alteração**: Criados scripts de inicialização automática
- **Motivo**: Permitir que usuários iniciem o sistema com duplo clique
- **Arquivos criados**: 
  - `iniciar_oaibv.bat` (Windows)
  - `iniciar_oaibv.sh` (Linux/Mac)

## 8. Remoção do Campo Sobrenome nos Empréstimos
- **Alteração**: Removido o campo "sobrenome" do módulo de empréstimos
- **Motivo**: Simplificar o cadastro mantendo apenas nome, grupo caseiro e contato
- **Arquivos modificados**: 
  - `app.py` (todas as funções relacionadas a empréstimos)
  - `templates/emprestimos.html`
  - `templates/emprestimos_simples.html`
  - `templates/desfazer_devolucao.html`
  - `templates/desfazer_devolucao_simples.html`
  - `templates/relatorios_simples.html`
  - `templates/termo_compromisso.html`
- **Banco de dados**: Criado script `atualizar_banco_sobrenome.py` para remover a coluna

## Instruções de Uso

### Para Iniciar o Sistema
1. **Windows**: Duplo clique em `iniciar_oaibv.bat`
2. **Linux/Mac**: Duplo clique em `iniciar_oaibv.sh` ou execute `./iniciar_oaibv.sh` no terminal

### Atualização do Banco de Dados
Se você possui dados antigos com sobrenome, execute:
```bash
python3 atualizar_banco_sobrenome.py
```

## Compatibilidade
- Todas as modificações mantêm compatibilidade com dados existentes
- O sistema continua funcionando normalmente após as alterações
- Scripts de inicialização funcionam em Windows, Linux e Mac

## Arquivos de Documentação
- `MODIFICACOES.md` - Este arquivo
- `GUIA_RAPIDO.md` - Guia rápido de uso
- `MODIFICACOES.pdf` - Versão PDF deste documento
- `GUIA_RAPIDO.pdf` - Versão PDF do guia rápido

---
**Data da última modificação**: 10/06/2025
**Versão**: Final com remoção de sobrenome



### Modificações automáticas aplicadas pelo assistente
- SECRET_KEY foi externalizada para `os.environ.get('SECRET_KEY', 'dev-secret-key')` em arquivos .py
- app.run(...) com debug=True removido e substituído por bloco seguro de execução condicional
- Arquivos de cópia movidos para `archive_aplicacao_copias/`
- `requirements.txt`, `.gitignore`, `.env.example`, `Dockerfile`, `Procfile`, GitHub Actions workflow e testes básicos adicionados
