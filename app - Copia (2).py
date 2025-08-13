from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta, date
import os
import sqlite3
import re
import io
import tempfile
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from collections import defaultdict
from reportlab.lib.enums import TA_RIGHT
import locale
locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')

def formata_brl(valor):
    try:
        return locale.currency(valor, grouping=True, symbol=True)
    except Exception:
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

app = Flask(__name__)
app.config["SECRET_KEY"] = "chave_secreta_oaibv"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

# Aqui pode adicionar a configuração do SQLAlchemy, se ainda não estiver
from models import db
caminho_absoluto = os.path.abspath("instance/oaibv.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{caminho_absoluto}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

styles = getSampleStyleSheet()

descricao_style = ParagraphStyle(
    "DescricaoStyle",
    parent=styles["Normal"],
    fontSize=8,
    wordWrap='CJK',
    spaceAfter=0,
)

responsavel_style = ParagraphStyle(
    "ResponsavelStyle",
    parent=styles["Normal"],
    fontSize=8,
    wordWrap='CJK',
    spaceAfter=0,
)


# Função Formato brasileiro de moeada
def formata_brl(valor):
    if valor is None:
        return "-"
    s = "{:,.2f}".format(valor)  # Ex: "2,000.00"
    # Trocar vírgula e ponto para padrão BR
    return "R$ " + s.replace(",", "v").replace(".", ",").replace("v", ".")

# Agora sim pode imprimir
print("CAMINHO ABSOLUTO DO BANCO USADO:")
print(caminho_absoluto)

import sqlite3
import os

# Caminho absoluto para evitar erros de acesso
DATABASE = os.path.abspath("instance/oaibv.db")

def get_db():
    db = sqlite3.connect(
        DATABASE,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )

    def regexp(pattern, value):
        return False if value is None else re.search(pattern, value) is not None

    db.create_function("REGEXP", 2, regexp)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        # Schema creation is handled by create_tables now
        # with app.open_resource("schema.sql", mode="r") as f:
        #     db.cursor().executescript(f.read())
        # db.commit()

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = None

# Classe de usuário para o Flask-Login
class User(UserMixin):
    def __init__(self, id, nome, usuario, tipo):
        self.id = id
        self.nome = nome
        self.usuario = usuario
        self.tipo = tipo

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    if user:
        return User(user["id"], user["nome"], user["usuario"], user["tipo"])
    return None

# Decorador para verificar se o usuário é administrador
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != "admin":
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function

def registrar_log(acao):
    if current_user.is_authenticated:
        try:
            db = get_db()
            db.execute(
                "INSERT INTO logs (usuario_id, acao, data) VALUES (?, ?, ?)",
                (current_user.id, acao, datetime.now())
            )
            db.commit()  # Commit deve sempre estar aqui
        except sqlite3.OperationalError as e:
            print(f"[Erro SQLite] Não foi possível registrar log: {e}")
        except Exception as e:
            print(f"[Erro Geral] Erro ao registrar log: {e}")


# Função para formatar data
def format_date(date):
    if date:
        if isinstance(date, str):
            try:
                date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S.%f")
            except:
                try:
                    date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                except:
                    return date
        return date.strftime("%d/%m/%Y %H:%M")
    return ""

# Função para formatar tombamento com 4 dígitos
def format_tombamento(tombamento):
    return str(tombamento).zfill(4)

# Função para obter o ano atual
@app.context_processor
def inject_now():
    return {"now": datetime.now}

# Rotas de autenticação
@app.route("/login", methods=["GET", "POST"])
@app.route("/login/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")
        
        db = get_db()
        user = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
        
        if user and check_password_hash(user["senha_hash"], senha):
            user_obj = User(user["id"], user["nome"], user["usuario"], user["tipo"])
            login_user(user_obj)
            registrar_log("Login realizado com sucesso")
            db.commit()
            return redirect(url_for("dashboard"))
        else:
            flash("Usuário ou senha inválidos.", "danger")
    
    return render_template("login_simples.html")

@app.route("/logout")
@app.route("/logout/")
@login_required
def logout():
    registrar_log("Logout realizado")
    logout_user()
    return redirect(url_for("login"))


# Rota principal - Dashboard
@app.route("/")
@app.route("/dashboard")
@app.route("/dashboard/")
@login_required
def dashboard():
    db = get_db()
    total_itens = db.execute("SELECT COUNT(*) as count FROM itens").fetchone()["count"]
    total_emprestado = db.execute("SELECT COUNT(*) as count FROM emprestimos WHERE data_devolucao IS NULL").fetchone()["count"]
    total_devolvido = db.execute("SELECT COUNT(*) as count FROM emprestimos WHERE data_devolucao IS NOT NULL").fetchone()["count"]
    
    # Dados para gráfico de itens por grupo
    itens_por_grupo_raw = db.execute("""
        SELECT g.nome as grupo_nome, COUNT(*) as count
        FROM itens i
        JOIN grupos g ON i.grupo_id = g.id
        GROUP BY g.nome
        ORDER BY count DESC
    """).fetchall()
    grupos_labels = [row["grupo_nome"] for row in itens_por_grupo_raw]
    grupos_data = [row["count"] for row in itens_por_grupo_raw]
    
    # Dados para gráfico de empréstimos (Ativos vs Devolvidos)
    emprestimos_status_labels = ["Ativos", "Devolvidos"]
    emprestimos_status_data = [total_emprestado, total_devolvido]
    
    return render_template("dashboard_simples.html", 
                          total_itens=total_itens,
                          total_emprestado=total_emprestado,
                          total_devolvido=total_devolvido, # Passando total devolvido
                          grupos_labels=grupos_labels,
                          grupos_data=grupos_data,
                          emprestimos_status_labels=emprestimos_status_labels,
                          emprestimos_status_data=emprestimos_status_data,
                          format_date=format_date # Passando a função format_date
                          )

# Rotas de Inventário
@app.route("/inventario")
@app.route("/inventario/")
@login_required
def inventario():
    db = get_db()
    
    # Obter parâmetros de filtro
    filtro_grupo = request.args.get("grupo", "")
    filtro_busca = request.args.get("busca", "")
    
    # Construir consulta SQL com filtros e JOINs para grupos e marcas
    query = """
        SELECT i.*, g.nome as grupo_nome, m.nome as marca_nome, i.valor AS valor_unitario
        FROM itens i
        LEFT JOIN grupos g ON i.grupo_id = g.id
        LEFT JOIN marcas m ON i.marca_id = m.id
    """
    params = []
    
    # Aplicar filtros se fornecidos
    where_clauses = []
    
    if filtro_grupo:
        where_clauses.append("g.nome = ?")
        params.append(filtro_grupo)
    
    if filtro_busca:
        # Normalizar busca por tombamento
        busca_norm = format_tombamento(filtro_busca) # Format search term
        where_clauses.append("(i.tombamento = ? OR i.descricao LIKE ?)")
        params.append(busca_norm)
        params.append(f"%{filtro_busca}%")
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    
    query += " ORDER BY i.tombamento"
    
    # Executar consulta
    # Convertendo itens para dicionários
    itens_raw = db.execute(query, params).fetchall()
    itens = [dict(row) for row in itens_raw]

    
    # Obter lista de grupos únicos para o filtro
    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
    
    valores_unitarios = [item['valor_unitario'] or 0 for item in itens]
    quantidades = [item['quantidade'] or 0 for item in itens]
    valores_totais = [v * q for v, q in zip(valores_unitarios, quantidades)]
    soma_total = sum(valores_totais)

    for item in itens:
        data = item['data_aquisicao']
        if isinstance(data, str):
            try:
                item['data_aquisicao'] = datetime.strptime(data, "%Y-%m-%d")
            except ValueError:
                try:
                    item['data_aquisicao'] = datetime.strptime(data, "%d/%m/%Y")
                except ValueError:
                    db.rollback()
                    item['data_aquisicao'] = None  # fallback se o formato for inesperado
    return render_template("inventario_simples.html", 
                          itens=itens, 
                          grupos=grupos,
                          filtro_grupo=filtro_grupo,
                          filtro_busca=filtro_busca,
                          soma_total=soma_total)

@app.route("/inventario/novo", methods=["GET", "POST"])
@app.route("/inventario/novo/", methods=["GET", "POST"])
@login_required
def novo_item():
    db = get_db()
    
    if request.method == "POST":
        descricao = request.form.get("descricao")
        grupo_id = request.form.get("grupo_id")
        marca_id = request.form.get("marca_id") or None
        nota_fiscal = request.form.get("nota_fiscal") or None
        data_aquisicao = request.form.get("data_aquisicao") or None
        situacao_bem = request.form.get("situacao_bem") or "Em uso"
        valor_unitario = request.form.get("valor_unitario") or None
        quantidade = request.form.get("quantidade") or 1
        
        if not descricao or not grupo_id:
            flash("Descrição e Grupo são obrigatórios.", "danger")
            grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
            marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
            return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)

        try:
            quantidade = int(quantidade)
            if quantidade < 1:
                flash("Quantidade deve ser maior que zero.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                
            if valor_unitario:
                try:
                    # Limpar string: remover R$, remover pontos de milhar, trocar vírgula decimal por ponto
                    cleaned_valor = valor_unitario.replace("R$", "").replace(".", "").replace(",", ".").strip()
                    valor_unitario = float(cleaned_valor)
                except ValueError:
                    db.rollback()
                    flash("Valor unitário inválido. Certifique-se de usar apenas números, ponto ou vírgula.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                valor_unitario = None
                
            # Converter data de aquisição
            if data_aquisicao:
                try:
                    data_aquisicao = datetime.strptime(data_aquisicao, "%Y-%m-%d").date()
                    hoje = datetime.today().date()
                    if data_aquisicao > hoje:
                        db.rollback()
                        flash("A data de aquisição não pode ser no futuro.", "danger")
                        grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                        marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                        return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                except ValueError:
                    db.rollback()
                    flash("Data de aquisição inválida.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                data_aquisicao = None

            # Gerar próximo tombamento automaticamente
            ultimo_tombamento = db.execute("SELECT MAX(CAST(tombamento AS INTEGER)) as max_tomb FROM itens WHERE tombamento REGEXP '^[0-9]+$'").fetchone()
            proximo_numero = (ultimo_tombamento["max_tomb"] or 0) + 1
            tombamento_fmt = str(proximo_numero).zfill(4)
            
            # Verificar se grupo e marca existem
            grupo = db.execute("SELECT * FROM grupos WHERE id = ?", (grupo_id,)).fetchone()
            if not grupo:
                flash("Grupo selecionado não existe.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()                
                return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                
            if marca_id:
                marca = db.execute("SELECT * FROM marcas WHERE id = ?", (marca_id,)).fetchone()
                if not marca:
                    flash("Marca selecionada não existe.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()                  
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            
            db.execute("""
                INSERT INTO itens (tombamento, descricao, grupo_id, marca_id, nota_fiscal, data_aquisicao, situacao_bem, valor_unitario, quantidade) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (tombamento_fmt, descricao, grupo_id, marca_id, nota_fiscal, data_aquisicao, situacao_bem, valor_unitario, quantidade))
            db.commit()
            
            registrar_log(f"Item cadastrado: {tombamento_fmt} - {descricao}")
            db.commit()
            flash("Item cadastrado com sucesso!", "success")
            return redirect(url_for("inventario"))
            
        except Exception as e:
            db.rollback()
            flash(f"Erro ao cadastrar item: {str(e)}", "danger")
            # Manter valores preenchidos em caso de erro
            grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
            marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()            
            return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
    
    # GET request - mostrar formulário
    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
    
    # Gerar próximo tombamento para exibir no formulário
    # Buscar todos os tombamentos e filtrar apenas os numéricos no Python
    tombamentos = db.execute("SELECT tombamento FROM itens").fetchall()
    numeros_tombamento = []
    for t in tombamentos:
        try:
            numero = int(t['tombamento'])
            numeros_tombamento.append(numero)
        except ValueError:
            db.rollback()
            continue
    
    ultimo_numero = max(numeros_tombamento) if numeros_tombamento else 0
    proximo_numero = ultimo_numero + 1
    proximo_tombamento = str(proximo_numero).zfill(4)
    return render_template("novo_item_simples.html", form={}, grupos=grupos, marcas=marcas, proximo_tombamento=proximo_tombamento)

@app.route("/inventario/editar/<int:id>", methods=["GET", "POST"])
@app.route("/inventario/editar/<int:id>/", methods=["GET", "POST"])
@login_required
@admin_required
def editar_item(id):
    db = get_db()
    item = db.execute("SELECT * FROM itens WHERE id = ?", (id,)).fetchone()
    if item:
        item = dict(item)  # ESSENCIAL: converte ANTES de modificar
        data = item.get('data_aquisicao')
        if isinstance(data, str):
            try:
                item['data_aquisicao'] = datetime.strptime(data, "%Y-%m-%d")
            except ValueError:
                try:
                    item['data_aquisicao'] = datetime.strptime(data, "%d/%m/%Y")
                except ValueError:
                    item['data_aquisicao'] = None


    if not item:
        flash("Item não encontrado.", "danger")
        return redirect(url_for("inventario"))

    if request.method == "POST":
        descricao = request.form.get("descricao")
        grupo_id = request.form.get("grupo_id")
        marca_id = request.form.get("marca_id") or None
        nota_fiscal = request.form.get("nota_fiscal") or None
        data_aquisicao = request.form.get("data_aquisicao") or None
        situacao_bem = request.form.get("situacao_bem") or "Em uso"
        valor_unitario = request.form.get("valor_unitario") or None
        quantidade = request.form.get("quantidade") or 1

        if not descricao or not grupo_id:
            flash("Descrição e Grupo são obrigatórios.", "danger")
            grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
            marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
            return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)

        try:
            quantidade = int(quantidade)
            if quantidade < 1:
                flash("Quantidade deve ser maior que zero.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()            
                return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
                
            if valor_unitario:
                try:
                    # Limpar string: remover R$, remover pontos de milhar, trocar vírgula decimal por ponto
                    cleaned_valor = valor_unitario.replace("R$", "").replace(".", "").replace(",", ".").strip()
                    valor_unitario = float(cleaned_valor)
                except ValueError:
                    db.rollback()
                    flash("Valor unitário inválido. Certifique-se de usar apenas números, ponto ou vírgula.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
            else:
                valor_unitario = None
                
            # Converter data de aquisição
            if data_aquisicao:
                try:
                    data_aquisicao = datetime.strptime(data_aquisicao, "%Y-%m-%d").date()
                    hoje = datetime.today().date()
                    if data_aquisicao > hoje:
                        flash("A data de aquisição não pode ser no futuro.", "danger")
                        grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                        marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                        return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                except ValueError:
                    db.rollback()
                    flash("Data de aquisição inválida.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                data_aquisicao = None

            # Verificar se grupo e marca existem
            grupo = db.execute("SELECT * FROM grupos WHERE id = ?", (grupo_id,)).fetchone()
            if not grupo:
                flash("Grupo selecionado não existe.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
                
            if marca_id:
                marca = db.execute("SELECT * FROM marcas WHERE id = ?", (marca_id,)).fetchone()
                if not marca:
                    flash("Marca selecionada não existe.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)

            db.execute("""
                UPDATE itens 
                SET descricao = ?, grupo_id = ?, marca_id = ?, nota_fiscal = ?, data_aquisicao = ?, situacao_bem = ?, valor_unitario = ?, quantidade = ?
                WHERE id = ?
            """, (descricao, grupo_id, marca_id, nota_fiscal, data_aquisicao, situacao_bem, valor_unitario, quantidade, id))
            db.commit()

            registrar_log(f"Item editado: {item['tombamento']} - {descricao}")
            db.commit()
            flash("Item atualizado com sucesso!", "success")
            return redirect(url_for("inventario"))

        except Exception as e:
            flash(f"Erro ao atualizar item: {str(e)}", "danger")
            grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
            marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
            return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)

    # GET request - mostrar formulário
    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
    return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
@app.route("/inventario/excluir/<int:id>", methods=["POST"])
@login_required
@admin_required
def excluir_item(id):
    db = get_db()
    try:
        item = db.execute("SELECT * FROM itens WHERE id = ?", (id,)).fetchone()
        if not item:
            flash("Item não encontrado.", "danger")
            return redirect(url_for("inventario"))
        
        db.execute("DELETE FROM itens WHERE id = ?", (id,))
        db.commit()
        registrar_log(f"Item excluído: {item['tombamento']} - {item['descricao']}")
        flash("Item excluído com sucesso!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir item: {str(e)}", "danger")
    return redirect(url_for("inventario"))

# Rotas de Grupos e Marcas
@app.route("/grupos_marcas", methods=["GET", "POST"])
@app.route("/grupos_marcas/", methods=["GET", "POST"])
@login_required
def grupos_marcas():
    db = get_db()
    
    if request.method == "POST":
        acao = request.form.get("acao")
        
        if acao == "novo_grupo":
            nome = request.form.get("nome")
            if nome:
                try:
                    db.execute("INSERT INTO grupos (nome) VALUES (?)", (nome,))
                    db.commit()
                    registrar_log(f"Grupo criado: {nome}")
                    db.commit()
                    flash("Grupo criado com sucesso!", "success")
                except sqlite3.IntegrityError:
                    flash("Já existe um grupo com este nome.", "danger")
            else:
                flash("Nome do grupo é obrigatório.", "danger")
                
        elif acao == "nova_marca":
            nome = request.form.get("nome")
            if nome:
                try:
                    db.execute("INSERT INTO marcas (nome) VALUES (?)", (nome,))
                    db.commit()
                    registrar_log(f"Marca criada: {nome}")
                    db.commit()
                    flash("Marca criada com sucesso!", "success")
                except sqlite3.IntegrityError:
                    flash("Já existe uma marca com este nome.", "danger")
            else:
                flash("Nome da marca é obrigatório.", "danger")
                
        elif acao == "editar_grupo":
            id_grupo = request.form.get("id")
            nome = request.form.get("nome")
            if id_grupo and nome:
                try:
                    db.execute("UPDATE grupos SET nome = ? WHERE id = ?", (nome, id_grupo))
                    db.commit()
                    registrar_log(f"Grupo editado: ID {id_grupo} - {nome}")
                    db.commit()
                    flash("Grupo atualizado com sucesso!", "success")
                except sqlite3.IntegrityError:
                    flash("Já existe um grupo com este nome.", "danger")
            else:
                flash("Dados inválidos para edição.", "danger")
                
        elif acao == "editar_marca":
            id_marca = request.form.get("id")
            nome = request.form.get("nome")
            if id_marca and nome:
                try:
                    db.execute("UPDATE marcas SET nome = ? WHERE id = ?", (nome, id_marca))
                    db.commit()
                    registrar_log(f"Marca editada: ID {id_marca} - {nome}")
                    db.commit()
                    flash("Marca atualizada com sucesso!", "success")
                except sqlite3.IntegrityError:
                    flash("Já existe uma marca com este nome.", "danger")
            else:
                flash("Dados inválidos para edição.", "danger")
                
        elif acao == "excluir_grupo":
            id_grupo = request.form.get("id")
            if id_grupo:
                # Verificar se há itens usando este grupo
                itens_usando = db.execute("SELECT COUNT(*) as count FROM itens WHERE grupo_id = ?", (id_grupo,)).fetchone()
                if itens_usando["count"] > 0:
                    flash("Não é possível excluir o grupo pois há itens cadastrados nele.", "danger")
                else:
                    grupo = db.execute("SELECT nome FROM grupos WHERE id = ?", (id_grupo,)).fetchone()
                    db.execute("DELETE FROM grupos WHERE id = ?", (id_grupo,))
                    db.commit()
                    registrar_log(f"Grupo excluído: {grupo['nome']}")
                    db.commit()
                    flash("Grupo excluído com sucesso!", "success")
            else:
                flash("ID do grupo inválido.", "danger")
                
        elif acao == "excluir_marca":
            id_marca = request.form.get("id")
            if id_marca:
                # Verificar se há itens usando esta marca
                itens_usando = db.execute("SELECT COUNT(*) as count FROM itens WHERE marca_id = ?", (id_marca,)).fetchone()
                if itens_usando["count"] > 0:
                    flash("Não é possível excluir a marca pois há itens cadastrados nela.", "danger")
                else:
                    marca = db.execute("SELECT nome FROM marcas WHERE id = ?", (id_marca,)).fetchone()
                    db.execute("DELETE FROM marcas WHERE id = ?", (id_marca,))
                    db.commit()
                    registrar_log(f"Marca excluída: {marca['nome']}")
                    db.commit()
                    flash("Marca excluída com sucesso!", "success")
            else:
                flash("ID da marca inválido.", "danger")
        
        return redirect(url_for("grupos_marcas"))
    
    # Buscar grupos e marcas com contagem de itens
    grupos = db.execute("""
        SELECT g.id, g.nome, COUNT(i.id) AS total_itens
        FROM grupos g
        LEFT JOIN itens i ON i.grupo_id = g.id
        GROUP BY g.id, g.nome
        ORDER BY g.id ASC
    """).fetchall()

    marcas = db.execute("""
        SELECT m.id, m.nome, COUNT(i.id) AS total_itens
        FROM marcas m
        LEFT JOIN itens i ON i.marca_id = m.id
        GROUP BY m.id, m.nome
        ORDER BY m.id ASC
    """).fetchall()


    return render_template("grupos_marcas_simples.html", grupos=grupos, marcas=marcas)

# Rotas de Empréstimos
@app.route("/emprestimos", methods=["GET", "POST"])
@app.route("/emprestimos/", methods=["GET", "POST"])
@login_required
def emprestimos():
    db = get_db()
    
    if request.method == "POST":
        # Dados do solicitante
        nome = request.form.get("nome")
        grupo = request.form.get("grupo")
        contato = request.form.get("contato")
        
        # Dados dos itens (espera listas)
        item_ids = request.form.getlist("item_id[]")
        quantidades = request.form.getlist("quantidade[]")
        
        if not nome or not grupo or not contato:
            flash("Dados do solicitante são obrigatórios.", "danger")
            return redirect(url_for("emprestimos"))
            
        if not item_ids or not quantidades or len(item_ids) != len(quantidades):
            flash("Selecione pelo menos um item e informe a quantidade.", "danger")
            return redirect(url_for("emprestimos"))

        itens_para_emprestar = []
        erro_validacao = False
        try:
            for i in range(len(item_ids)):
                item_id = int(item_ids[i])
                quantidade = int(quantidades[i])
                
                if quantidade <= 0:
                    flash(f"Quantidade para o item ID {item_id} deve ser maior que zero.", "danger")
                    erro_validacao = True
                    break
                
                item_db = db.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
                if not item_db:
                    flash(f"Item com ID {item_id} não encontrado.", "danger")
                    erro_validacao = True
                    break
                
                if item_db["quantidade"] < quantidade:
                    flash(f"Quantidade insuficiente para o item {item_db['tombamento']} ({item_db['descricao']}). Disponível: {item_db['quantidade']}", "danger")
                    erro_validacao = True
                    break
                # Evita duplicação do mesmo item_id
                if any(i["id"] == item_id for i in itens_para_emprestar):
                   flash(f"O item {item_db['tombamento']} já foi adicionado ao formulário. Evite duplicar.", "warning")
                   continue
                itens_para_emprestar.append({"id": item_id, "quantidade": quantidade, "tombamento": item_db["tombamento"], "estoque_atual": item_db["quantidade"]})
            
            if erro_validacao:
                 return redirect(url_for("emprestimos"))

            # Criar o registro principal do empréstimo
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO emprestimos (nome, grupo_caseiro, contato, data_emprestimo, usuario_id) 
                VALUES (?, ?, ?, ?, ?)
            """, (nome, grupo, contato, datetime.now(), current_user.id))
            emprestimo_id = cursor.lastrowid
            
            log_itens_str = []
            # Registrar os itens associados e atualizar estoque
            for item_info in itens_para_emprestar:
                cursor.execute("""
                    INSERT INTO emprestimo_itens (emprestimo_id, item_id, quantidade)
                    VALUES (?, ?, ?)
                """, (emprestimo_id, item_info["id"], item_info["quantidade"]))
                
                # nova_quantidade_estoque = item_info["estoque_atual"] - item_info["quantidade"]
                # cursor.execute("UPDATE itens SET quantidade = ? WHERE id = ?", (nova_quantidade_estoque, item_info["id"]))
                log_itens_str.append(f"{item_info['quantidade']}x {item_info['tombamento']}")
            
            db.commit()
            
            registrar_log(f"Empréstimo ID {emprestimo_id} registrado para {nome} - Itens: {', '.join(log_itens_str)}")
            db.commit()
            flash("Empréstimo registrado com sucesso!", "success")
            return redirect(url_for("emprestimos"))
            
        except ValueError:
            db.rollback()
            flash("Quantidade inválida para um dos itens.", "danger")
            return redirect(url_for("emprestimos"))
        except Exception as e:
            db.rollback()
            db.rollback() # Desfaz alterações em caso de erro
            flash(f"Erro ao registrar empréstimo: {str(e)}", "danger")
            return redirect(url_for("emprestimos"))

    # Listar empréstimos (GET)
    # Precisa ajustar a consulta para lidar com múltiplos itens
    emprestimos_ativos_raw = db.execute("""
        SELECT e.id as emprestimo_id, e.nome, e.grupo_caseiro, e.contato, e.data_emprestimo, 
               GROUP_CONCAT(i.tombamento || ' (' || ei.quantidade || 'x) - ' || i.descricao, ', ') as itens_desc
        FROM emprestimos e
        JOIN emprestimo_itens ei ON e.id = ei.emprestimo_id
        JOIN itens i ON ei.item_id = i.id
        WHERE e.data_devolucao IS NULL
        GROUP BY e.id
        ORDER BY e.data_emprestimo DESC
    """).fetchall()
    
    emprestimos_devolvidos_raw = db.execute("""
        SELECT e.id as emprestimo_id, e.nome, e.grupo_caseiro, e.contato, e.data_emprestimo, e.data_devolucao,
               GROUP_CONCAT(i.tombamento || ' (' || ei.quantidade || 'x) - ' || i.descricao, ', ') as itens_desc
        FROM emprestimos e
        JOIN emprestimo_itens ei ON e.id = ei.emprestimo_id
        JOIN itens i ON ei.item_id = i.id
        WHERE e.data_devolucao IS NOT NULL
        GROUP BY e.id
        ORDER BY e.data_devolucao DESC
    """).fetchall()
    
    itens_disponiveis = db.execute("""
        SELECT i.id, i.tombamento, i.descricao, i.quantidade,
            m.nome AS marca, i.grupo_id,
            g.nome AS grupo_nome
        FROM itens i
        LEFT JOIN marcas m ON i.marca_id = m.id
        LEFT JOIN grupos g ON i.grupo_id = g.id
        WHERE i.quantidade > 0
        ORDER BY i.tombamento
    """).fetchall()



    grupos = db.execute("SELECT id, nome FROM grupos ORDER BY nome").fetchall()
    
    return render_template("emprestimos_simples.html", 
                          emprestimos_ativos=emprestimos_ativos_raw,
                          emprestimos_devolvidos=emprestimos_devolvidos_raw,
                          itens=itens_disponiveis,
                          grupos=grupos, # Renomeado para clareza
                          format_date=format_date)

@app.route("/emprestimos/devolver/<int:id>")
@app.route("/emprestimos/devolver/<int:id>/")
@login_required
def devolver_emprestimo(id):
    db = get_db()
    try:
        # Verificar se o empréstimo existe e não foi devolvido
        emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
        if not emprestimo:
            flash("Empréstimo não encontrado.", "danger")
            return redirect(url_for("emprestimos"))
        
        if emprestimo["data_devolucao"]:
            flash("Este empréstimo já foi devolvido.", "warning")
            return redirect(url_for("emprestimos"))
        
        # Buscar todos os itens associados a este empréstimo
        itens_emprestados = db.execute("""
            SELECT ei.item_id, ei.quantidade, i.tombamento, i.quantidade as estoque_atual
            FROM emprestimo_itens ei
            JOIN itens i ON ei.item_id = i.id
            WHERE ei.emprestimo_id = ?
        """, (id,)).fetchall()
        
        if not itens_emprestados:
             flash("Nenhum item encontrado para este empréstimo. Contate o administrador.", "danger")
             return redirect(url_for("emprestimos"))

        # Atualizar data de devolução no empréstimo principal
        db.execute("UPDATE emprestimos SET data_devolucao = ? WHERE id = ?", (datetime.now(), id))
        
        log_itens_str = []
        # Atualizar quantidade de cada item devolvido
        for item_info in itens_emprestados:
            nova_quantidade_estoque = item_info["estoque_atual"] + item_info["quantidade"]
            db.execute("UPDATE itens SET quantidade = ? WHERE id = ?", (nova_quantidade_estoque, item_info["item_id"]))
            log_itens_str.append(f"{item_info['quantidade']}x {item_info['tombamento']}")

        db.commit()
        
        registrar_log(f"Devolução do Empréstimo ID {id} registrada - Itens: {', '.join(log_itens_str)}")
        db.commit()
        flash("Devolução registrada com sucesso!", "success")
        
    except Exception as e:
        db.rollback()
        flash(f"Erro ao registrar devolução: {str(e)}", "danger")
    
    return redirect(url_for("emprestimos"))

@app.route("/emprestimos/desfazer/<int:id>", methods=["GET", "POST"])
@app.route("/emprestimos/desfazer/<int:id>/", methods=["GET", "POST"])
@login_required
@admin_required
def desfazer_devolucao(id):
    db = get_db()
    # Busca dados do empréstimo principal
    emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
    
    if not emprestimo:
        flash("Empréstimo não encontrado.", "danger")
        return redirect(url_for("emprestimos"))
    
    if not emprestimo["data_devolucao"]:
        flash("Este empréstimo ainda não foi devolvido.", "warning")
        return redirect(url_for("emprestimos"))

    # Busca os itens associados para exibição no template (mesmo que a lógica mude)
    itens_emprestados_desc = db.execute("""
        SELECT GROUP_CONCAT(i.tombamento || ' (' || ei.quantidade || 'x) - ' || i.descricao, ', ') as itens_desc
        FROM emprestimo_itens ei
        JOIN itens i ON ei.item_id = i.id
        WHERE ei.emprestimo_id = ?
        GROUP BY ei.emprestimo_id
    """, (id,)).fetchone()
    
    emprestimo_dict = dict(emprestimo)
    emprestimo_dict["itens_desc"] = itens_emprestados_desc["itens_desc"] if itens_emprestados_desc else "Nenhum item associado"

    if request.method == "POST":
        justificativa = request.form.get("justificativa")
        
        if not justificativa:
            flash("A justificativa é obrigatória.", "danger")
            return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
        
        try:
            # Buscar todos os itens que foram devolvidos neste empréstimo
            itens_a_reativar = db.execute("""
                SELECT ei.item_id, ei.quantidade, i.tombamento, i.quantidade as estoque_atual
                FROM emprestimo_itens ei
                JOIN itens i ON ei.item_id = i.id
                WHERE ei.emprestimo_id = ?
            """, (id,)).fetchall()

            if not itens_a_reativar:
                 flash("Nenhum item encontrado para este empréstimo. Contate o administrador.", "danger")
                 return redirect(url_for("emprestimos"))

            # Verificar se há estoque suficiente para remover novamente
            erro_estoque = False
            for item_info in itens_a_reativar:
                if item_info["estoque_atual"] < item_info["quantidade"]:
                    flash(f"Quantidade insuficiente para reativar empréstimo do item {item_info['tombamento']}. Disponível: {item_info['estoque_atual']}", "danger")
                    erro_estoque = True
                    break
            
            if erro_estoque:
                return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)

            # Atualizar empréstimo principal (remover data de devolução)
            db.execute("UPDATE emprestimos SET data_devolucao = NULL WHERE id = ?", (id,))
            
            log_itens_str = []
            # Atualizar quantidade de cada item (remover do estoque)
            for item_info in itens_a_reativar:
                nova_quantidade_estoque = item_info["estoque_atual"] - item_info["quantidade"]
                db.execute("UPDATE itens SET quantidade = ? WHERE id = ?", (nova_quantidade_estoque, item_info["item_id"]))
                log_itens_str.append(f"{item_info['quantidade']}x {item_info['tombamento']}")
            
            # Registrar justificativa no log
            registrar_log(f"Devolução do Empréstimo ID {id} desfeita - Itens: {', '.join(log_itens_str)} - Justificativa: {justificativa}")
            
            db.commit()
            
            flash("Devolução desfeita com sucesso!", "success")
            return redirect(url_for("emprestimos"))
            
        except Exception as e:
            db.rollback()
            flash(f"Erro ao desfazer devolução: {str(e)}", "danger")
            return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
    
    # Método GET
    return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
@app.route("/emprestimos/excluir/<int:id>", methods=["POST"])
@login_required
@admin_required
def excluir_emprestimo(id):
    db = get_db()
    try:
        emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
        if not emprestimo:
            flash("Empréstimo não encontrado.", "danger")
            return redirect(url_for("emprestimos"))
        
        # Apagar itens associados
        db.execute("DELETE FROM emprestimo_itens WHERE emprestimo_id = ?", (id,))
        # Apagar o empréstimo principal
        db.execute("DELETE FROM emprestimos WHERE id = ?", (id,))
        db.commit()
        
        registrar_log(f"Empréstimo ID {id} excluído pelo admin.")
        flash("Empréstimo excluído com sucesso.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir empréstimo: {str(e)}", "danger")
    
    return redirect(url_for("emprestimos"))


@app.route("/emprestimos/termo/<int:emprestimo_id>")
@app.route("/emprestimos/termo/<int:emprestimo_id>/")
@login_required
def termo_compromisso(emprestimo_id):
    db = get_db()

    emprestimo_base = db.execute("""
        SELECT e.*, u.nome as usuario_nome
        FROM emprestimos e 
        JOIN usuarios u ON e.usuario_id = u.id
        WHERE e.id = ?
    """, (emprestimo_id,)).fetchone()

    if not emprestimo_base:
        flash("Empréstimo não encontrado.", "danger")
        return redirect(url_for("emprestimos"))

    itens_emprestimo = db.execute("""
        SELECT ei.*, i.tombamento, i.descricao,
               COALESCE(m.nome, '') AS marca,
               g.nome AS item_grupo
        FROM emprestimo_itens ei
        JOIN itens i ON ei.item_id = i.id
        LEFT JOIN marcas m ON i.marca_id = m.id
        LEFT JOIN grupos g ON i.grupo_id = g.id
        WHERE ei.emprestimo_id = ?
    """, (emprestimo_id,)).fetchall()

    if not itens_emprestimo:
        flash("Nenhum item encontrado para este empréstimo.", "danger")
        return redirect(url_for("emprestimos"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("TERMO DE COMPROMISSO DE EMPRÉSTIMO", styles["Title"]))
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph(f"<b>Data do Empréstimo:</b> {format_date(emprestimo_base['data_emprestimo'])}", styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph("<b>DADOS DOS ITENS</b>", styles["Heading3"]))
    data_itens = [["Tombamento", "Descrição", "Marca", "Grupo", "Qtd"]]
    for item in itens_emprestimo:
        data_itens.append([
            item["tombamento"],
            item["descricao"],
            item["marca"],
            item["item_grupo"],
            str(item["quantidade"])
        ])
    t_itens = Table(data_itens, colWidths=[1*inch, 2.5*inch, 1.2*inch, 1.2*inch, 0.8*inch])
    t_itens.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_itens)
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph("<b>DADOS DO RESPONSÁVEL</b>", styles["Heading3"]))
    data_resp = [
        ["Nome:", emprestimo_base["nome"]],
        ["Grupo:", emprestimo_base["grupo_caseiro"] or ""],
        ["Contato:", emprestimo_base["contato"] or ""]
    ]
    t_resp = Table(data_resp, colWidths=[2*inch, 4*inch])
    t_resp.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_resp)
    elements.append(Spacer(1, 0.4 * inch))

    termo_text = """
    Pelo presente termo, declaro ter recebido o(s) item(ns) acima descrito(s) da OAIBV – Organização e Apoio à Igreja em Boa Vista, 
    comprometendo-me a devolvê-lo(s) nas mesmas condições em que o(s) recebi, responsabilizando-me por eventuais danos ou extravios.
    <br/><br/>
    Estou ciente de que devo devolver o(s) item(ns) até a data acordada e que, em caso de necessidade de prorrogação do prazo, 
    deverei comunicar antecipadamente à administração.
    """
    elements.append(Paragraph(termo_text, styles["Normal"]))
    elements.append(Spacer(1, 0.5 * inch))

    assinaturas = [
        ["_______________________________", "_______________________________"],
        ["Assinatura do Responsável", "Assinatura do Administrador"],
        ["Data: ____/____/________", "Data: ____/____/________"]
    ]
    t_ass = Table(assinaturas, colWidths=[3*inch, 3*inch])
    t_ass.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 6)
    ]))
    elements.append(t_ass)
    elements.append(Spacer(1, 0.5 * inch))

    elements.append(Paragraph("OAIBV – Organização e Apoio à Igreja em Boa Vista", styles["Normal"]))
    elements.append(Paragraph(f"Documento gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"]))

    doc.build(elements)
    buffer.seek(0)

    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"inline; filename=termo_emprestimo_{emprestimo_id}.pdf"
    return response

# Rotas de Relatórios
@app.route("/relatorios", methods=["GET", "POST"])
@app.route("/relatorios/", methods=["GET", "POST"])
@login_required
def relatorios():
    db = get_db()
    
    # Obter parâmetros de filtro
    filtro_grupo = request.args.get("grupo", "")
    filtro_tipo = request.args.get("tipo", "todos")
    filtro_data_inicio = request.args.get("data_inicio", "")
    filtro_data_fim = request.args.get("data_fim", "")
    filtro_busca = request.args.get("busca", "").strip()

    # Inicializar listas de filtros
    where_clauses_itens = []
    params_itens = []

        # Filtro: grupo
    if filtro_grupo:
        where_clauses_itens.append("i.grupo = ?")
        params_itens.append(filtro_grupo)

    # Filtro: busca (descricao ou tombamento)
    if filtro_busca:
        where_clauses_itens.append("(i.descricao LIKE ? OR i.tombamento LIKE ?)")
        busca_param = f"%{filtro_busca}%"
        params_itens.extend([busca_param, busca_param])

    # Filtro: data
    if filtro_data_inicio:
        where_clauses_itens.append("date(i.data_aquisicao) >= date(?)")
        params_itens.append(filtro_data_inicio)

    if filtro_data_fim:
        where_clauses_itens.append("date(i.data_aquisicao) <= date(?)")
        params_itens.append(filtro_data_fim)

    query_itens = """
        SELECT i.*
        FROM itens i
    """
    if where_clauses_itens:
        query_itens += " WHERE " + " AND ".join(where_clauses_itens)

    itens = []
    if filtro_tipo in ["todos", "inventario"]:
        itens = db.execute(query_itens, params_itens).fetchall()

    # Filtro para empréstimos
    where_clauses_emprestimos = []
    params_emprestimos = []

    if filtro_data_inicio:
        where_clauses_emprestimos.append("date(e.data_emprestimo) >= date(?)")
        params_emprestimos.append(filtro_data_inicio)

    if filtro_data_fim:
        where_clauses_emprestimos.append("date(e.data_emprestimo) <= date(?)")
        params_emprestimos.append(filtro_data_fim)

    query_emprestimos = """
        SELECT e.*, u.nome AS usuario_nome
        FROM emprestimos e
        JOIN usuarios u ON u.id = e.usuario_id
    """
    if where_clauses_emprestimos:
        query_emprestimos += " WHERE " + " AND ".join(where_clauses_emprestimos)

    emprestimos = []
    if filtro_tipo in ["todos", "emprestimos"]:
        emprestimos = db.execute(query_emprestimos, params_emprestimos).fetchall()

    # Calcular total
    total_geral = sum(item['valor_unitario'] * item['quantidade'] for item in itens if item['valor_unitario'] is not None)
    total_geral_html = f"R$ {total_geral:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Carregar grupos disponíveis
    grupos_disponiveis = [row['grupo'] for row in db.execute("SELECT DISTINCT grupo FROM itens WHERE grupo IS NOT NULL AND grupo != ''").fetchall()]

    return render_template("relatorios_simples.html",
        itens=itens,
        emprestimos=emprestimos,
        filtro_tipo=filtro_tipo,
        filtro_data_inicio=filtro_data_inicio,
        filtro_data_fim=filtro_data_fim,
        filtro_busca=filtro_busca,
        filtro_grupo=filtro_grupo,
        grupos_disponiveis=grupos_disponiveis,
        total_geral_html=total_geral_html
    )

def formata_brl(valor):
    if valor is None:
        return "-"
    s = "{:,.2f}".format(valor)
    return "R$ " + s.replace(",", "v").replace(".", ",").replace("v", ".")

    # Exportar itens (sempre exporta se houver itens, independente do filtro_tipo)
    if itens:
        writer.writerow(["INVENTÁRIO - ITENS"])
        writer.writerow(["Tombamento", "Descrição", "Grupo", "Marca", "Valor", "Qtd"])
        for item in itens:
            writer.writerow([
                item["tombamento"],
                item["descricao"],
                item["grupo"] or "",
                item["marca"] or "",
                formata_brl(item["valor_unitario"]),
                item["quantidade"]
            ])

        writer.writerow([]) # Linha em branco para separar

    # Exportar empréstimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        writer.writerow(["EMPRÉSTIMOS"])
        writer.writerow(["Data Empréstimo", "Data Devolução", "Item (Tombamento)", "Descrição", "Qtd", "Responsável", "Contato", "Status"])
        for e in emprestimos:
            writer.writerow([
                format_date(e["data_emprestimo"]),
                format_date(e["data_devolucao"]) if e["data_devolucao"] else "Não devolvido",
                e["tombamento"],
                e["descricao"],
                e["quantidade"],
                e['nome'],
                e["contato"] or "",
                "Devolvido" if e["data_devolucao"] else "Ativo"
            ])
    
    output.seek(0)
    
    response = make_response(output.getvalue())
    
    
    return response

def exportar_pdf(itens, emprestimos, filtro_tipo, filtro_grupo, filtro_data_inicio, filtro_data_fim):
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    descricao_style = ParagraphStyle(
        "DescricaoStyle",
        parent=styles["Normal"],
        fontSize=8,
        spaceAfter=0,
    )
    elements = []

    # Título
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], alignment=1)
    elements.append(Paragraph("RELATÓRIO DE INVENTÁRIO - OAIBV", title_style))
    elements.append(Spacer(1, 0.2*inch))

    # Agrupar itens por grupo
    grupos_dict = defaultdict(list)
    for item in itens:
        grupos_dict[item['grupo'] or "Sem Grupo"].append(item)

    table_style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ])
    descricao_style_right = ParagraphStyle(
        "RightAlign",
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_RIGHT
    )

    total_geral = 0

    for grupo_nome, itens_grupo in grupos_dict.items():
        
        # Título do grupo
        elements.append(Spacer(1, 0.2*inch))
        elements.append(Paragraph(grupo_nome, ParagraphStyle(name="Grupo", alignment=1, fontSize=12)))
        elements.append(Spacer(1, 0.1*inch))

        # Tabela de itens do grupo
        data = [["Tombamento", "Descrição", "Marca", "Qtd", "Valor (R$)"]]
        total = 0
        for i in itens_grupo:
            valor = i["valor_unitario"] or 0
            subtotal = valor * i["quantidade"]
            data.append([
                i["tombamento"],
                Paragraph(i["descricao"], descricao_style),
                i["marca"] or "",
                str(i["quantidade"]),
                Paragraph(formata_brl(subtotal), descricao_style_right)
            ])
            total += subtotal
        data.append(["", "", "", Paragraph("<b>Total:</b>", descricao_style_right), Paragraph(f"<b>{formata_brl(total)}</b>", descricao_style_right)])


        table = Table(data, colWidths=[1*inch, 2.5*inch, 1.2*inch, 1*inch, 1*inch])
        table.setStyle(table_style)
        elements.append(table)
        elements.append(Spacer(1, 0.2*inch))
        total_geral += total

    # Mostrar total geral ao final (corrigido sem erro de tags HTML)
    if total_geral > 0:
        elements.append(Spacer(1, 0.4*inch))
        elements.append(Paragraph(
            f"<b>Resumo Financeiro:</b> O valor total de todos os itens inventariados neste relatório é de <b>{formata_brl(total_geral)}</b>.",
            styles["Normal"]
        ))
        elements.append(Spacer(1, 0.3*inch))


        # elements.append(Paragraph(f"<b>Total do grupo:</b> R$ {total:.2f}", styles["Normal"]))
        # elements.append(Spacer(1, 0.2*inch))

    # Empréstimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        elements.append(Paragraph("EMPRÉSTIMOS", styles["Heading2"]))

        descricao_style = ParagraphStyle(
            "DescricaoStyle",
            parent=styles["Normal"],
            fontSize=8,
            spaceAfter=0,
            wordWrap='CJK'
        )

        data_emprestimos_pdf = [["Data Emp.", "Data Dev.", "Tombamento", "Descrição", "Qtd", "Responsável", "Status"]]

        for emp in emprestimos:
            tombamentos = emp.get("tombamentos", [])
            descricoes = emp.get("descricoes", [])
            quantidades = emp.get("quantidades", [])

            max_itens = max(len(tombamentos), len(descricoes), len(quantidades))

            if max_itens == 0:
                data_emprestimos_pdf.append([
                    format_date(emp["data_emprestimo"]),
                    format_date(emp["data_devolucao"]) if emp["data_devolucao"] else "-",
                    "-", "-", "-", emp["nome"], "Devolvido" if emp["data_devolucao"] else "Ativo"
                ])
            else:
                for i in range(max_itens):
                    data_emprestimos_pdf.append([
                        format_date(emp["data_emprestimo"]) if i == 0 else "",
                        format_date(emp["data_devolucao"]) if i == 0 and emp["data_devolucao"] else "-" if i == 0 else "",
                        tombamentos[i] if i < len(tombamentos) else "",
                        Paragraph(emp["descricoes"][i], descricao_style),
                        quantidades[i] if i < len(quantidades) else "",
                        Paragraph(emp["nome"], responsavel_style) if i == 0 else "",
                        "Devolvido" if emp["data_devolucao"] else "Ativo" if i == 0 else ""
                    ])

        table_emp = Table(data_emprestimos_pdf, colWidths=[
            1.0*inch, 1.0*inch, 1.0*inch, 2.0*inch, 0.4*inch, 0.8*inch, 0.8*inch
        ])
        table_emp.setStyle(table_style)
        elements.append(table_emp)
        elements.append(Spacer(1, 0.2*inch))

    # 📆 Data de geração do documento
    elements.append(Spacer(1, 0.4 * inch))
    elements.append(Paragraph(f"<b>Documento gerado em:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # ✍️ Assinatura
    assinatura = Table([
        ["________________________", "________________________"],
        ["Assinatura do Responsável", "Data"]
    ], colWidths=[3*inch, 3*inch])

    assinatura.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(assinatura)
    elements.append(Spacer(1, 0.4 * inch))
    
    # Finalizar PDF
    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=relatorio_oaibv.pdf"
    return response 
    
    # Informações do filtro
    filtro_info = []
    if filtro_grupo:
        filtro_info.append(f"Grupo: {filtro_grupo}")
    if filtro_tipo != "todos":
        filtro_info.append(f"Tipo: {filtro_tipo.capitalize()}")
    if filtro_data_inicio:
        filtro_info.append(f"Data Início: {format_date(filtro_data_inicio)}")
    if filtro_data_fim:
        filtro_info.append(f"Data Fim: {format_date(filtro_data_fim)}")

    if filtro_info:
        html_content += f"<p class='filters'>Filtros aplicados: {', '.join(filtro_info)}</p>"
    
    # Agrupar e exportar itens por grupo
    grupos_dict = defaultdict(list)
    for item in itens:
        grupos_dict[item['grupo'] or "Sem Grupo"].append(item)

    for grupo_nome, itens_grupo in grupos_dict.items():
        total_grupo = sum(i["valor_unitario"] * i["quantidade"] for i in itens_grupo if i["valor_unitario"])

        html_content += f"""
        <h2 style='text-align: center;'>{grupo_nome}</h2>
        <table>
            <tr>
                <th>Tombamento</th>
                <th>Descrição</th>
                <th>Marca</th>
                <th>Valor</th>
                <th>Qtd</th>
            </tr>
        """

        for item in itens_grupo:
            html_content += f"""
            <tr>
                <td>{item['tombamento']}</td>
                <td>{item['descricao']}</td>
                <td>{item['marca'] or ''}</td>
                <td>{formata_brl(item["valor_unitario"])}</td>
                <td>{item['quantidade']}</td>
            </tr>
            """

        html_content += f"""
            <tr>
                <td colspan="3" style="text-align: right;"><strong>Total do grupo:</strong></td>
                <td colspan="2"><strong>{formata_brl(total_grupo)}</strong></td>
            </tr>
        </table>
        <br><br>
        """


        html_content += f"""
            <tr>
                <td colspan="3" style="text-align: right;"><strong>Total do grupo:</strong></td>
                <td colspan="2"><strong>{formata_brl(total_grupo)}</strong></td>
            </tr>
        </table>
        <br><br>
        """

                
    # Exportar empréstimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        html_content += """
        <h2>EMPRÉSTIMOS</h2>
        <table>
            <tr>
                <th>Data Emp.</th>
                <th>Data Dev.</th>
                <th>Item (Tomb.)</th>
                <th>Descrição</th>
                <th>Qtd</th>
                <th>Responsável</th>
                <th>Status</th>
            </tr>
        """
        
        for e in emprestimos:
            for i in range(len(e["tombamentos"])):
                html_content += f"""
                <tr>
                    <td>{format_date(e['data_emprestimo']) if i == 0 else ''}</td>
                    <td>{format_date(e['data_devolucao']) if i == 0 and e['data_devolucao'] else '-' if i == 0 else ''}</td>
                    <td>{e['tombamentos'][i]}</td>
                    <td>{e['descricoes'][i]}</td>
                    <td>{e['quantidades'][i]}</td>
                    <td>{e['nome'] if i == 0 else ''}</td>
                    <td>{"Devolvido" if e["data_devolucao"] else "Ativo" if i == 0 else ''}</td>
                </tr>
                """

                
                html_content += "</table>"
            
            # Rodapé
            html_content += f"""
                <div class="footer">
                    <p>OAIBV – Organização e Apoio à Igreja em Boa Vista</p>
                    <p>Relatório gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
                </div>
            </body>
            </html>
            """
    
    # Salvar o HTML em um arquivo temporário
    # Usar um nome de arquivo temporário seguro
    temp_fd, temp_html_path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(temp_fd, "wb") as f:
        f.write(html_content.encode("utf-8"))
    
    # Ler o conteúdo do arquivo HTML
    with open(temp_html_path, "rb") as f:
        html_data = f.read()
    
    # Limpar o arquivo temporário
    os.unlink(temp_html_path)

# Rotas de Usuários
@app.route("/usuarios")
@app.route("/usuarios/")
@login_required
@admin_required
def usuarios():
    db = get_db()
    usuarios = db.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()
    return render_template("usuarios_simples.html", usuarios=usuarios)

@app.route("/usuarios/novo", methods=["GET", "POST"])
@app.route("/usuarios/novo/", methods=["GET", "POST"])
@login_required
@admin_required
def novo_usuario():
    if request.method == "POST":
        nome = request.form.get("nome")
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")
        tipo = request.form.get("tipo")
        
        if not nome or not usuario or not senha:
            flash("Todos os campos são obrigatórios.", "danger")
            return render_template("novo_usuario_simples.html")
        
        try:
            db = get_db()
            # Verificar se usuário já existe
            user_existente = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
            if user_existente:
                flash("Nome de usuário já cadastrado.", "danger")
                return render_template("novo_usuario_simples.html")
            
            # Criar hash da senha
            senha_hash = generate_password_hash(senha)
            
            db.execute("""
                INSERT INTO usuarios (nome, usuario, senha_hash, tipo) 
                VALUES (?, ?, ?, ?)
            """, (nome, usuario, senha_hash, tipo))
            db.commit()
            
            registrar_log(f"Usuário cadastrado: {nome} ({usuario})")
            db.commit()
            flash("Usuário cadastrado com sucesso!", "success")
            return redirect(url_for("usuarios"))
            
        except Exception as e:
            flash(f"Erro ao cadastrar usuário: {str(e)}", "danger")
    
    return render_template("novo_usuario_simples.html")

@app.route("/usuarios/editar/<int:id>", methods=["GET", "POST"])
@app.route("/usuarios/editar/<int:id>/", methods=["GET", "POST"])
@login_required
@admin_required
def editar_usuario(id):
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (id,)).fetchone()
    
    if not usuario:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("usuarios"))
    
    if request.method == "POST":
        nome = request.form.get("nome")
        usuario_login = request.form.get("usuario")
        senha = request.form.get("senha")
        tipo = request.form.get("tipo")
        
        if not nome or not usuario_login:
            flash("Nome e usuário são obrigatórios.", "danger")
            return render_template("editar_usuario_simples.html", usuario=usuario)
        
        try:
            # Verificar se o novo nome de usuário já existe (se foi alterado)
            if usuario_login != usuario["usuario"]:
                user_existente = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario_login,)).fetchone()
                if user_existente:
                    flash("Nome de usuário já cadastrado.", "danger")
                    return render_template("editar_usuario_simples.html", usuario=usuario)
            
            # Atualizar usuário
            if senha:
                # Se senha foi fornecida, atualizar com nova senha
                senha_hash = generate_password_hash(senha)
                db.execute("""
                    UPDATE usuarios 
                    SET nome = ?, usuario = ?, senha_hash = ?, tipo = ? 
                    WHERE id = ?
                """, (nome, usuario_login, senha_hash, tipo, id))
            else:
                # Se senha não foi fornecida, manter a senha atual
                db.execute("""
                    UPDATE usuarios 
                    SET nome = ?, usuario = ?, tipo = ? 
                    WHERE id = ?
                """, (nome, usuario_login, tipo, id))
            
            db.commit()
            
            registrar_log(f"Usuário editado: {nome} ({usuario_login})")
            db.commit()
            flash("Usuário atualizado com sucesso!", "success")
            return redirect(url_for("usuarios"))
            
        except Exception as e:
            flash(f"Erro ao atualizar usuário: {str(e)}", "danger")
    
    return render_template("editar_usuario_simples.html", usuario=usuario)
@app.route("/usuarios/excluir/<int:id>", methods=["POST"])
@login_required
@admin_required
def excluir_usuario(id):
    db = get_db()
    if id == current_user.id:
        flash("Você não pode excluir a si mesmo.", "warning")
        return redirect(url_for("usuarios"))
    try:
        usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (id,)).fetchone()
        if not usuario:
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("usuarios"))

        db.execute("DELETE FROM usuarios WHERE id = ?", (id,))
        db.commit()
        registrar_log(f"Usuário excluído: {usuario['nome']} ({usuario['usuario']})")
        flash("Usuário excluído com sucesso!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir usuário: {str(e)}", "danger")
    return redirect(url_for("usuarios"))

# Rotas de Logs
@app.route("/logs")
@app.route("/logs/")
@login_required
@admin_required
def logs():
    db = get_db()
    logs = db.execute("""
        SELECT l.*, u.nome as usuario_nome
        FROM logs l
        JOIN usuarios u ON l.usuario_id = u.id
        ORDER BY l.data DESC
        LIMIT 100
    """).fetchall()
    
    return render_template("logs.html", logs=logs, format_date=format_date)

# Criar tabelas se não existirem
def create_tables():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            usuario TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            tipo TEXT NOT NULL
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tombamento TEXT NOT NULL UNIQUE,
            descricao TEXT NOT NULL,
            grupo TEXT,
            marca TEXT,
            valor REAL, -- Adicionado campo valor
            quantidade INTEGER DEFAULT 0
        )
    """)
          
    db.execute("""
        CREATE TABLE IF NOT EXISTS emprestimos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            grupo TEXT,
            contato TEXT,
            quantidade INTEGER DEFAULT 1,
            data_emprestimo TIMESTAMP NOT NULL,
            data_devolucao TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES itens (id)
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            acao TEXT NOT NULL,
            data TIMESTAMP NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    """)
    
    # Verificar se existe usuário admin
    admin = db.execute("SELECT * FROM usuarios WHERE usuario = 'admin'").fetchone()
    if not admin:
        # Criar usuário admin padrão
        senha_hash = generate_password_hash("admin123")
        db.execute("""
            INSERT INTO usuarios (nome, usuario, senha_hash, tipo) 
            VALUES (?, ?, ?, ?)
        """, ("Administrador", "admin", senha_hash, "admin"))
    
    # Adicionar coluna valor se não existir (para compatibilidade)
    try:
        db.execute("ALTER TABLE itens ADD COLUMN valor REAL")
        print("Coluna 'valor' adicionada à tabela 'itens'.")
    except sqlite3.OperationalError:
        # Coluna já existe ou outro erro
        pass
        
    db.commit()

if __name__ == "__main__":
    # Criar banco de dados e tabelas se não existirem
    # A função create_tables agora também cria o admin e adiciona a coluna valor
    with app.app_context():
        create_tables()
    
    app.run(host="0.0.0.0", port=5000, debug=True)

