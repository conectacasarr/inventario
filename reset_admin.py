import os
import sqlite3

# Caminho para o banco de dados
db_path = 'oaibv.db'

# Verificar se o banco de dados existe
if os.path.exists(db_path):
    # Conectar ao banco de dados
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verificar se a tabela de usuários existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'")
    if cursor.fetchone():
        # Gerar hash da senha 'admin123'
        # Este é um hash gerado pelo werkzeug.security.generate_password_hash('admin123')
        senha_hash = 'pbkdf2:sha256:600000$7DEMaXvGlT1KBZC2$a4fb4d95cf81fe9dd2eb209a3c91407c3ab5fd33c91145e9c2a33eb9d0fb8692'
        
        # Verificar se o usuário admin existe
        cursor.execute("SELECT id FROM usuarios WHERE usuario='admin'")
        admin = cursor.fetchone()
        
        if admin:
            # Atualizar senha do admin existente
            cursor.execute("UPDATE usuarios SET senha_hash=?, tipo='admin' WHERE usuario='admin'", (senha_hash,))
            print("Senha do usuário admin atualizada!")
        else:
            # Criar usuário admin
            cursor.execute("""
                INSERT INTO usuarios (nome, usuario, senha_hash, tipo) 
                VALUES (?, ?, ?, ?)
            """, ('Administrador', 'admin', senha_hash, 'admin'))
            print("Usuário admin criado com sucesso!")
        
        # Salvar alterações
        conn.commit()
    else:
        print("A tabela de usuários não existe. Execute primeiro o script create_db.py")
    
    # Fechar conexão
    conn.close()
else:
    print("Banco de dados não encontrado. Execute primeiro o script create_db.py")

print("\nAgora tente fazer login com:")
print("Usuário: admin")
print("Senha: admin123")
