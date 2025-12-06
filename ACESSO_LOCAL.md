# Guia de Configuração para Acesso Local ao Sistema de Inventário OAIBV

Este guia explica como configurar o acesso ao sistema de inventário através de um nome local amigável como `http://inventario.local` em vez de usar endereços IP.

## Opção 1: Configuração via arquivo hosts (mais simples)

### Para Windows:

1. Abra o Bloco de Notas como administrador
   - Clique com o botão direito no ícone do Bloco de Notas
   - Selecione "Executar como administrador"

2. Abra o arquivo hosts
   - Navegue para: `C:\Windows\System32\drivers\etc\hosts`
   - Selecione "Todos os arquivos" no seletor de tipo de arquivo para visualizar o arquivo hosts

3. Adicione a seguinte linha ao final do arquivo:
   ```
   127.0.0.1 inventario.local
   ```
   
4. Salve o arquivo

### Para Linux/Mac:

1. Abra o terminal

2. Edite o arquivo hosts com privilégios de administrador:
   ```bash
   sudo nano /etc/hosts
   ```

3. Adicione a seguinte linha ao final do arquivo:
   ```
   127.0.0.1 inventario.local
   ```

4. Salve o arquivo (Ctrl+O, Enter) e saia (Ctrl+X)

### Acesso na rede local:

Se você deseja que outros computadores na rede acessem o sistema pelo nome, você precisará adicionar uma entrada no arquivo hosts de cada computador, mas usando o IP do servidor em vez de 127.0.0.1:

```
192.168.31.88 inventario.local
```

## Opção 2: Configuração via DNS local (mais avançado)

Para uma solução mais robusta em uma rede com vários computadores, você pode configurar um servidor DNS local:

1. Instale e configure um servidor DNS como o BIND ou dnsmasq no servidor

2. Configure uma zona para o domínio "local"

3. Adicione um registro A para "inventario.local" apontando para o IP do servidor (192.168.31.88)

4. Configure os computadores da rede para usar o servidor DNS local

## Configuração do Flask para responder ao nome de host

Para garantir que o Flask responda corretamente ao nome de host, certifique-se de que o servidor esteja configurado para escutar em todas as interfaces:

```python
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
```

## Testando a configuração

Após fazer as alterações no arquivo hosts ou configurar o DNS:

1. Reinicie o navegador

2. Acesse o sistema usando a URL: `http://inventario.local:5000`

3. Se tudo estiver configurado corretamente, o sistema deve carregar normalmente

## Solução de problemas

- Se o sistema não carregar, verifique se o servidor Flask está em execução
- Tente limpar o cache do navegador ou usar uma janela anônima/privativa
- Verifique se o arquivo hosts foi salvo corretamente
- Use o comando `ping inventario.local` para verificar se a resolução de nome está funcionando
