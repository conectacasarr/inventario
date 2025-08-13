from app import app, db, UsuarioLogin
from werkzeug.security import generate_password_hash

with app.app_context():
    # Verificar se o banco de dados existe
    db.create_all()
    
    # Verificar se já existe um usuário admin
    admin = UsuarioLogin.query.filter_by(usuario='admin').first()
    
    if not admin:
        # Criar usuário admin
        novo_admin = UsuarioLogin(
            nome='Administrador',
            usuario='admin',
            tipo='admin',
            senha_hash=generate_password_hash('admin123')
        )
        
        # Adicionar ao banco de dados
        db.session.add(novo_admin)
        db.session.commit()
        print("Usuário admin criado com sucesso!")
    else:
        # Atualizar senha do admin existente
        admin.senha_hash = generate_password_hash('admin123')
        db.session.commit()
        print("Senha do usuário admin atualizada!")
