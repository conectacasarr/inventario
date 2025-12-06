#!/usr/bin/env python3
"""
Script de migração do banco de dados OAIBV
Adiciona as novas tabelas e campos conforme as alterações solicitadas
"""

import sqlite3
import os
from datetime import datetime

# Caminho do banco de dados
DATABASE = os.path.abspath("instance/oaibv.db")

def migrar_banco():
    """Executa as migrações necessárias no banco de dados"""
    
    print("Iniciando migração do banco de dados...")
    
    # Conectar ao banco
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # 1. Criar tabela de grupos
        print("Criando tabela 'grupos'...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grupos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome VARCHAR(100) UNIQUE NOT NULL
            )
        """)
        
        # 2. Criar tabela de marcas
        print("Criando tabela 'marcas'...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS marcas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome VARCHAR(100) UNIQUE NOT NULL
            )
        """)
        
        # 3. Verificar se as colunas já existem na tabela itens
        cursor.execute("PRAGMA table_info(itens)")
        colunas_existentes = [coluna[1] for coluna in cursor.fetchall()]
        
        # 4. Adicionar novos campos à tabela itens se não existirem
        novos_campos = [
            ("data_aquisicao", "DATE"),
            ("situacao_bem", "VARCHAR(20) DEFAULT 'Em uso'"),
            ("valor_unitario", "FLOAT"),
            ("grupo_id", "INTEGER"),
            ("marca_id", "INTEGER")
        ]
        
        for campo, tipo in novos_campos:
            if campo not in colunas_existentes:
                print(f"Adicionando campo '{campo}' à tabela 'itens'...")
                cursor.execute(f"ALTER TABLE itens ADD COLUMN {campo} {tipo}")
        
        # 5. Migrar dados existentes de grupo e marca para as novas tabelas
        print("Migrando grupos existentes...")
        cursor.execute("SELECT DISTINCT grupo FROM itens WHERE grupo IS NOT NULL AND grupo != ''")
        grupos_existentes = cursor.fetchall()
        
        for (grupo,) in grupos_existentes:
            cursor.execute("INSERT OR IGNORE INTO grupos (nome) VALUES (?)", (grupo,))
        
        print("Migrando marcas existentes...")
        cursor.execute("SELECT DISTINCT marca FROM itens WHERE marca IS NOT NULL AND marca != ''")
        marcas_existentes = cursor.fetchall()
        
        for (marca,) in marcas_existentes:
            cursor.execute("INSERT OR IGNORE INTO marcas (nome) VALUES (?)", (marca,))
        
        # 6. Atualizar referências na tabela itens
        print("Atualizando referências de grupos na tabela 'itens'...")
        cursor.execute("""
            UPDATE itens 
            SET grupo_id = (SELECT id FROM grupos WHERE nome = itens.grupo)
            WHERE grupo IS NOT NULL AND grupo != '' AND grupo_id IS NULL
        """)
        
        print("Atualizando referências de marcas na tabela 'itens'...")
        cursor.execute("""
            UPDATE itens 
            SET marca_id = (SELECT id FROM marcas WHERE nome = itens.marca)
            WHERE marca IS NOT NULL AND marca != '' AND marca_id IS NULL
        """)
        
        # 7. Verificar se precisa migrar empréstimos
        cursor.execute("PRAGMA table_info(emprestimos)")
        colunas_emprestimos = [coluna[1] for coluna in cursor.fetchall()]
        
        if "grupo_id" not in colunas_emprestimos:
            print("Adicionando campo 'grupo_id' à tabela 'emprestimos'...")
            cursor.execute("ALTER TABLE emprestimos ADD COLUMN grupo_id INTEGER")
            
            # Migrar grupos dos empréstimos
            print("Migrando grupos dos empréstimos...")
            cursor.execute("""
                UPDATE emprestimos 
                SET grupo_id = (SELECT id FROM grupos WHERE nome = emprestimos.grupo)
                WHERE grupo IS NOT NULL AND grupo != '' AND grupo_id IS NULL
            """)
        
        # 8. Gerar tombamentos automáticos para itens que não possuem
        print("Verificando tombamentos...")
        cursor.execute("SELECT COUNT(*) FROM itens WHERE tombamento IS NULL OR tombamento = ''")
        itens_sem_tombamento = cursor.fetchone()[0]
        
        if itens_sem_tombamento > 0:
            print(f"Gerando tombamentos para {itens_sem_tombamento} itens...")
            cursor.execute("SELECT MAX(CAST(tombamento AS INTEGER)) FROM itens WHERE tombamento REGEXP '^[0-9]+$'")
            max_tombamento = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT id FROM itens WHERE tombamento IS NULL OR tombamento = '' ORDER BY id")
            itens_ids = cursor.fetchall()
            
            for i, (item_id,) in enumerate(itens_ids, start=max_tombamento + 1):
                novo_tombamento = str(i).zfill(4)
                cursor.execute("UPDATE itens SET tombamento = ? WHERE id = ?", (novo_tombamento, item_id))
        
        # Commit das alterações
        conn.commit()
        print("Migração concluída com sucesso!")
        
        # Mostrar estatísticas
        cursor.execute("SELECT COUNT(*) FROM grupos")
        total_grupos = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM marcas")
        total_marcas = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM itens")
        total_itens = cursor.fetchone()[0]
        
        print(f"\nEstatísticas após migração:")
        print(f"- Total de grupos: {total_grupos}")
        print(f"- Total de marcas: {total_marcas}")
        print(f"- Total de itens: {total_itens}")
        
    except Exception as e:
        print(f"Erro durante a migração: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrar_banco()

