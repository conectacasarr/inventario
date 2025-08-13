import sqlite3

# Altere aqui se for necessário testar outro caminho
caminho_banco = 'instance/oaibv.db'

con = sqlite3.connect(caminho_banco)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tabelas = cur.fetchall()

print("Tabelas encontradas:")
for t in tabelas:
    print("-", t[0])
