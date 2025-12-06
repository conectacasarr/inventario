# Instruções para Atualização do Sistema OAIBV

Este arquivo contém instruções importantes para a instalação e atualização do Sistema OAIBV.

## Correção de Erros de Sintaxe

Esta versão corrige erros de sintaxe relacionados a f-strings no arquivo `app.py` que impediam a execução do sistema.

## Instruções de Instalação

Para garantir o funcionamento correto do sistema, siga estas etapas:

1. **Descompacte o arquivo** `OAIBVFinal_Corrigido_Final.zip` em uma pasta de sua escolha.

2. **Recrie o banco de dados** para garantir que todas as tabelas necessárias sejam criadas corretamente:
   - Feche o aplicativo se estiver rodando
   - Delete a pasta `instance` dentro da pasta do projeto (se existir)
   - Execute o comando: `python create_db.py`
   - Isso criará um novo banco de dados com a estrutura correta, incluindo a tabela `emprestimo_itens`
   - Um usuário administrador padrão será criado (usuário: `admin`, senha: `admin123`)

3. **Inicie o aplicativo** com o comando: `python app.py`

## Funcionalidades Principais

Esta versão inclui todas as melhorias solicitadas:

1. **Dashboard aprimorado** com visual mais moderno e informativo
2. **Formatação de campos**:
   - Tombamento com 4 dígitos (ex: 0001)
   - Valor no formato R$ 00,00
   - Contato no formato (00)90000-0000
3. **Empréstimo de múltiplos itens** em um único registro
4. **Exportação CSV** com separação correta de colunas
5. **Navegação aprimorada** com destaque visual para a aba ativa

## Solução de Problemas

Se encontrar algum erro ao iniciar o sistema, verifique:

1. Se você deletou a pasta `instance` e executou `create_db.py` antes de iniciar o aplicativo
2. Se está usando uma versão compatível do Python (3.7 ou superior)
3. Se todas as dependências estão instaladas (Flask, ReportLab, etc.)

Para qualquer dúvida adicional, entre em contato com o suporte.
