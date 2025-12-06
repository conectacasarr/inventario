import os
import sqlite3
from datetime import datetime

# Script para verificar e atualizar a estrutura do banco de dados
print("Iniciando verificação e atualização do banco de dados...")

# Caminho para o banco de dados
db_path = 'oaibv.db'

# Verificar se o banco de dados existe
if os.path.exists(db_path):
    # Conectar ao banco de dados
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verificar se a tabela de itens existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='itens'")
    if cursor.fetchone():
        # Verificar se a coluna 'marca' existe na tabela 'itens'
        cursor.execute("PRAGMA table_info(itens)")
        colunas = cursor.fetchall()
        
        # Imprimir todas as colunas da tabela
        print("\nColunas da tabela 'itens':")
        print("-" * 50)
        for coluna in colunas:
            print(f"ID: {coluna[0]}, Nome: {coluna[1]}, Tipo: {coluna[2]}")
        
        # Verificar se a coluna 'marca' existe
        marca_existe = any(coluna[1] == 'marca' for coluna in colunas)
        
        if not marca_existe:
            print("\nA coluna 'marca' NÃO existe na tabela 'itens'.")
            
            # Adicionar a coluna 'marca' à tabela
            try:
                cursor.execute("ALTER TABLE itens ADD COLUMN marca TEXT")
                conn.commit()
                print("Coluna 'marca' adicionada com sucesso à tabela 'itens'.")
            except Exception as e:
                print(f"Erro ao adicionar coluna 'marca': {str(e)}")
        else:
            print("\nA coluna 'marca' JÁ existe na tabela 'itens'.")
    else:
        print("A tabela 'itens' não existe no banco de dados.")
    
    # Verificar se a tabela de empréstimos existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='emprestimos'")
    if cursor.fetchone():
        # Verificar se a coluna 'quantidade' existe na tabela 'emprestimos'
        cursor.execute("PRAGMA table_info(emprestimos)")
        colunas = cursor.fetchall()
        
        print("\nColunas da tabela 'emprestimos':")
        print("-" * 50)
        for coluna in colunas:
            print(f"ID: {coluna[0]}, Nome: {coluna[1]}, Tipo: {coluna[2]}")
        
        # Verificar se a coluna 'quantidade' existe
        quantidade_existe = any(coluna[1] == 'quantidade' for coluna in colunas)
        
        if not quantidade_existe:
            print("\nA coluna 'quantidade' NÃO existe na tabela 'emprestimos'.")
            
            # Adicionar a coluna 'quantidade' à tabela
            try:
                cursor.execute("ALTER TABLE emprestimos ADD COLUMN quantidade INTEGER DEFAULT 1")
                conn.commit()
                print("Coluna 'quantidade' adicionada com sucesso à tabela 'emprestimos'.")
            except Exception as e:
                print(f"Erro ao adicionar coluna 'quantidade': {str(e)}")
        else:
            print("\nA coluna 'quantidade' JÁ existe na tabela 'emprestimos'.")
        
        # Verificar se a coluna 'justificativa_desfazer' existe na tabela 'emprestimos'
        justificativa_existe = any(coluna[1] == 'justificativa_desfazer' for coluna in colunas)
        
        if not justificativa_existe:
            print("\nA coluna 'justificativa_desfazer' NÃO existe na tabela 'emprestimos'.")
            
            # Adicionar a coluna 'justificativa_desfazer' à tabela
            try:
                cursor.execute("ALTER TABLE emprestimos ADD COLUMN justificativa_desfazer TEXT")
                conn.commit()
                print("Coluna 'justificativa_desfazer' adicionada com sucesso à tabela 'emprestimos'.")
            except Exception as e:
                print(f"Erro ao adicionar coluna 'justificativa_desfazer': {str(e)}")
        else:
            print("\nA coluna 'justificativa_desfazer' JÁ existe na tabela 'emprestimos'.")
    else:
        print("A tabela 'emprestimos' não existe no banco de dados.")
    
    # Verificar se há empréstimos registrados
    cursor.execute("SELECT COUNT(*) FROM emprestimos")
    count = cursor.fetchone()[0]
    print(f"\nTotal de empréstimos registrados: {count}")
    
    if count > 0:
        # Listar alguns empréstimos para verificação
        cursor.execute("SELECT id, item_id, nome, sobrenome, data_emprestimo, data_devolucao, quantidade FROM emprestimos LIMIT 5")
        emprestimos = cursor.fetchall()
        
        print("\nÚltimos empréstimos registrados:")
        print("-" * 50)
        for emp in emprestimos:
            data_emp = datetime.fromisoformat(emp[4]) if emp[4] else None
            data_dev = datetime.fromisoformat(emp[5]) if emp[5] else None
            
            print(f"ID: {emp[0]}, Item ID: {emp[1]}, Nome: {emp[2]} {emp[3]}")
            print(f"Data Empréstimo: {data_emp.strftime('%d/%m/%Y %H:%M') if data_emp else 'N/A'}")
            print(f"Data Devolução: {data_dev.strftime('%d/%m/%Y %H:%M') if data_dev else 'Não devolvido'}")
            print(f"Quantidade: {emp[6] if len(emp) > 6 else 1}")
            print("-" * 50)
    
    # Fechar conexão
    conn.close()
    print("\nVerificação e atualização do banco de dados concluída com sucesso!")
else:
    print("Banco de dados não encontrado. Execute primeiro o script create_db.py")
