import os
import sqlite3

# Caminho para o banco de dados
db_path = 'oaibv.db'

# Verificar se o banco de dados existe
if os.path.exists(db_path):
    # Conectar ao banco de dados
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Verificar se a tabela de empréstimos existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='emprestimos'")
    if cursor.fetchone():
        # Listar todos os empréstimos
        cursor.execute("SELECT * FROM emprestimos")
        emprestimos = cursor.fetchall()
        
        if emprestimos:
            print("\nEmpréstimos registrados no sistema:")
            print("-" * 50)
            for emp in emprestimos:
                print(f"ID: {emp['id']}, Item ID: {emp['item_id']}, Nome: {emp['nome']} {emp['sobrenome']}")
                print(f"Data Empréstimo: {emp['data_emprestimo']}, Data Devolução: {emp['data_devolucao'] or 'Não devolvido'}")
                print("-" * 50)
        else:
            print("Não há empréstimos registrados no sistema.")
    else:
        print("A tabela de empréstimos não existe. Execute primeiro o script create_db.py")
    
    # Fechar conexão
    conn.close()
else:
    print("Banco de dados não encontrado.")
