from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(128), nullable=False)
    tipo = db.Column(db.String(20), default='comum')  # admin ou comum
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    pode_acessar_inventario = db.Column(db.Boolean, default=True, nullable=False)
    pode_editar_igreja = db.Column(db.Boolean, default=False, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.now, nullable=False)
    
    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)
    
    def verificar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

class Grupo(db.Model):
    __tablename__ = 'grupos'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relação com itens
    itens = db.relationship('Item', backref='grupo_obj', lazy=True)

class Marca(db.Model):
    __tablename__ = 'marcas'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relação com itens
    itens = db.relationship('Item', backref='marca_obj', lazy=True)

class Item(db.Model):
    __tablename__ = 'itens'
    
    id = db.Column(db.Integer, primary_key=True)
    tombamento = db.Column(db.String(20), unique=True, nullable=False)
    descricao = db.Column(db.String(200), nullable=False)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos.id'), nullable=False)
    marca_id = db.Column(db.Integer, db.ForeignKey('marcas.id'))
    nota_fiscal = db.Column(db.String(50))
    data_aquisicao = db.Column(db.Date)
    situacao_bem = db.Column(db.String(20), default='Em uso')  # Em uso, Descartado, Vendido, Doado
    valor_unitario = db.Column(db.Float)
    quantidade = db.Column(db.Integer, default=0)
    
    transacoes = db.relationship('Transacao', backref='item', lazy=True)
    # Relação com a tabela associativa EmprestimoItem
    emprestimos_associados = db.relationship('EmprestimoItem', back_populates='item', lazy=True)
    
    @property
    def valor_total(self):
        if self.valor_unitario and self.quantidade:
            return self.valor_unitario * self.quantidade
        return 0.0
    
    @staticmethod
    def normalizar_tombamento(tombamento):
        return tombamento.strip().lstrip('0')

class Transacao(db.Model):
    __tablename__ = 'transacoes'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('itens.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # entrada ou saida
    data = db.Column(db.DateTime, default=datetime.now)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    usuario = db.relationship('Usuario', backref='transacoes')

class Log(db.Model):
    __tablename__ = 'logs'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    acao = db.Column(db.String(200), nullable=False)
    data = db.Column(db.DateTime, default=datetime.now)
    
    usuario = db.relationship('Usuario', backref='logs')

# Tabela principal de Empréstimo (dados do solicitante)
class Emprestimo(db.Model):
    __tablename__ = 'emprestimos'
    
    id = db.Column(db.Integer, primary_key=True)
    # item_id e quantidade removidos daqui
    nome = db.Column(db.String(100), nullable=False)
    sobrenome = db.Column(db.String(100), nullable=False)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos.id'), nullable=False) # Grupo/Setor do solicitante
    contato = db.Column(db.String(20), nullable=False)
    data_emprestimo = db.Column(db.DateTime, default=datetime.now)
    data_devolucao = db.Column(db.DateTime)
    justificativa_desfazer = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id')) # Quem registrou

    # Relação com a tabela associativa EmprestimoItem
    itens_emprestados = db.relationship('EmprestimoItem', back_populates='emprestimo', lazy=True, cascade="all, delete-orphan")
    usuario = db.relationship('Usuario', backref='emprestimos_registrados')
    grupo_emprestimo = db.relationship('Grupo', backref='emprestimos')

# Tabela associativa para Empréstimo de Múltiplos Itens
class EmprestimoItem(db.Model):
    __tablename__ = 'emprestimo_itens'
    
    id = db.Column(db.Integer, primary_key=True)
    emprestimo_id = db.Column(db.Integer, db.ForeignKey('emprestimos.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('itens.id'), nullable=False)
    quantidade = db.Column(db.Integer, default=1, nullable=False)
    
    emprestimo = db.relationship('Emprestimo', back_populates='itens_emprestados')
    item = db.relationship('Item', back_populates='emprestimos_associados')

class TentativaLogin(db.Model):
    __tablename__ = 'tentativas_login'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50), nullable=False)
    ip = db.Column(db.String(50), nullable=False)
    data = db.Column(db.DateTime, default=datetime.now)
