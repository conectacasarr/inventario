from flask import Flask
from models import db, Usuario
from werkzeug.security import generate_password_hash
import os

# Garante que a pasta 'instance' exista antes de criar o banco lá
os.makedirs("instance", exist_ok=True)

app = Flask(__name__)
caminho_absoluto = os.path.abspath("instance/oaibv.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{caminho_absoluto}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def create_admin_user():
    """Cria um usuário administrador padrão"""
    admin = Usuario.query.filter_by(usuario='admin').first()
    if not admin:
        admin = Usuario(
            nome='Administrador',
            usuario='admin',
            tipo='admin'
        )
        admin.set_senha('admin123')  # Senha inicial que deve ser alterada após o primeiro login
        db.session.add(admin)
        db.session.commit()
        print('Usuário administrador criado com sucesso!')
    else:
        print('Usuário administrador já existe!')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin_user()
        print('Banco de dados inicializado com sucesso!')
