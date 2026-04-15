import os
import re
import sqlite3
from datetime import datetime


DATABASE = os.path.abspath("instance/oaibv.db")


def gerar_email_placeholder(usuario):
    base = re.sub(r"[^a-z0-9]+", "-", (usuario or "usuario").strip().lower()).strip("-") or "usuario"
    return f"{base}@sem-email.local"


def main():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    colunas = {
        coluna["name"]: coluna
        for coluna in conn.execute("PRAGMA table_info(usuarios)").fetchall()
    }

    if "email" not in colunas:
        conn.execute("ALTER TABLE usuarios ADD COLUMN email TEXT")
        print("Coluna email adicionada.")

    if "ativo" not in colunas:
        conn.execute("ALTER TABLE usuarios ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
        print("Coluna ativo adicionada.")

    if "criado_em" not in colunas:
        conn.execute("ALTER TABLE usuarios ADD COLUMN criado_em TIMESTAMP")
        print("Coluna criado_em adicionada.")

    usuarios_sem_email = conn.execute(
        "SELECT id, usuario FROM usuarios WHERE email IS NULL OR TRIM(email) = ''"
    ).fetchall()

    for usuario in usuarios_sem_email:
        conn.execute(
            "UPDATE usuarios SET email = ? WHERE id = ?",
            (gerar_email_placeholder(usuario["usuario"]), usuario["id"]),
        )

    conn.execute("UPDATE usuarios SET ativo = 1 WHERE ativo IS NULL")
    conn.execute(
        "UPDATE usuarios SET criado_em = ? WHERE criado_em IS NULL",
        (datetime.now(),),
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)")
    conn.commit()
    conn.close()
    print("Migracao de autenticacao concluida com sucesso.")


if __name__ == "__main__":
    main()
