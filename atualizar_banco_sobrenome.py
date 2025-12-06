#!/usr/bin/env python3
"""
Script para atualizar o banco de dados removendo a coluna 'sobrenome' da tabela emprestimos
"""

import sqlite3
import os

# Caminho para o banco de dados
DATABASE = os.path.abspath("instance/oaibv.db")

def atualizar_banco():
    """Remove a coluna sobrenome da tabela emprestimos"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        # Verificar se a coluna sobrenome existe
        cursor.execute("PRAGMA table_info(emprestimos)")
        colunas = [coluna[1] for coluna in cursor.fetchall()]
        
        if 'sobrenome' in colunas:
            print("Removendo coluna 'sobrenome' da tabela emprestimos...")
            
            # Criar nova tabela sem a coluna sobrenome
            cursor.execute("""
                CREATE TABLE emprestimos_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    grupo TEXT,
                    contato TEXT,
                    data_emprestimo TIMESTAMP NOT NULL,
                    data_devolucao TIMESTAMP,
                    usuario_id INTEGER,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
                )
            """)
            
            # Copiar dados da tabela antiga para a nova (sem sobrenome)
            cursor.execute("""
                INSERT INTO emprestimos_new (id, nome, grupo, contato, data_emprestimo, data_devolucao, usuario_id)
                SELECT id, nome, grupo, contato, data_emprestimo, data_devolucao, usuario_id
                FROM emprestimos
            """)
            
            # Remover tabela antiga
            cursor.execute("DROP TABLE emprestimos")
            
            # Renomear nova tabela
            cursor.execute("ALTER TABLE emprestimos_new RENAME TO emprestimos")
            
            conn.commit()
            print("Coluna 'sobrenome' removida com sucesso!")
        else:
            print("Coluna 'sobrenome' não encontrada na tabela emprestimos.")
            
    except Exception as e:
        print(f"Erro ao atualizar banco de dados: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("Atualizando banco de dados...")
    atualizar_banco()
    print("Atualização concluída!")

