import os
import sqlite3
from werkzeug.security import generate_password_hash

# Caminho para o banco de dados
db_path = 'oaibv.db'

# Verificar se o banco de dados existe
if os.path.exists(db_path):
    # Conectar ao banco de dados
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Verificar se a tabela de usuários existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'")
    if cursor.fetchone():
        # Listar todos os usuários
        cursor.execute("SELECT id, nome, usuario, tipo FROM usuarios")
        usuarios = cursor.fetchall()
        
        if usuarios:
            print("\nUsuários cadastrados no sistema:")
            print("-" * 50)
            for user in usuarios:
                print(f"ID: {user['id']}, Nome: {user['nome']}, Login: {user['usuario']}, Tipo: {user['tipo']}")
            print("-" * 50)
            
            # Perguntar se deseja redefinir a senha de algum usuário
            user_id = input("\nDigite o ID do usuário para redefinir a senha (ou Enter para sair): ")
            if user_id.strip():
                nova_senha = input("Digite a nova senha: ")
                senha_hash = generate_password_hash(nova_senha)
                
                cursor.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (senha_hash, user_id))
                conn.commit()
                
                print(f"\nSenha atualizada com sucesso! Tente fazer login com a nova senha.")
        else:
            print("Não há usuários cadastrados no sistema.")
            
            # Criar um novo usuário admin
            criar_admin = input("\nDeseja criar um novo usuário admin? (s/n): ")
            if criar_admin.lower() == 's':
                senha = input("Digite a senha para o novo usuário admin: ")
                senha_hash = generate_password_hash(senha)
                
                cursor.execute("""
                    INSERT INTO usuarios (nome, usuario, senha_hash, tipo) 
                    VALUES (?, ?, ?, ?)
                """, ('Administrador', 'admin', senha_hash, 'admin'))
                conn.commit()
                
                print(f"\nUsuário admin criado com sucesso! Tente fazer login com:")
                print(f"Usuário: admin")
                print(f"Senha: {senha}")
    else:
        print("A tabela de usuários não existe. Execute primeiro o script create_db.py")
    
    # Fechar conexão
    conn.close()
else:
    print("Banco de dados não encontrado. Execute primeiro o script create_db.py")
