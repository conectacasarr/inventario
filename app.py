from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, timedelta, date
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from email_validator import validate_email, EmailNotValidError
import os
import sqlite3
import re
import io
import tempfile
import json
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from collections import defaultdict
from reportlab.lib.enums import TA_RIGHT
import locale

load_dotenv()

for locale_name in ("pt_BR.UTF-8", "pt_BR.utf8", ""):
    try:
        locale.setlocale(locale.LC_ALL, locale_name)
        break
    except locale.Error:
        continue

def formata_brl(valor):
    try:
        return locale.currency(valor, grouping=True, symbol=True)
    except Exception:
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def format_date(data):
    if not data:
        return "-"
    try:
        return datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return data


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "oaibv.diaconato@gmail.com")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "oaibv.diaconato@gmail.com")
app.config["RESET_PASSWORD_MAX_AGE"] = int(os.environ.get("RESET_PASSWORD_MAX_AGE", 3600))
app.config["APP_BASE_URL"] = os.environ.get("APP_BASE_URL", "http://localhost:5000")

# Aqui pode adicionar a configuração do SQLAlchemy, se ainda não estiver
from models import db, Usuario
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
if os.name == "nt":
    DEFAULT_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", PROJECT_DIR), "OAIBV")
else:
    DEFAULT_DATA_DIR = os.path.join(PROJECT_DIR, "instance")

DATABASE = os.environ.get("OAIBV_DB_PATH", os.path.join(DEFAULT_DATA_DIR, "oaibv.db"))
os.makedirs(os.path.dirname(DATABASE), exist_ok=True)

UPLOADS_DIR = os.path.join(PROJECT_DIR, "static", "uploads", "conectacasa")
LOGO_UPLOAD_DIR = os.path.join(UPLOADS_DIR, "logos")
PIX_UPLOAD_DIR = os.path.join(UPLOADS_DIR, "pix")
os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
os.makedirs(PIX_UPLOAD_DIR, exist_ok=True)

caminho_absoluto = DATABASE
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{caminho_absoluto}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
mail = Mail(app)

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


def get_table_columns(db_conn, table_name):
    return {row["name"] for row in db_conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def emprestimos_tem_grupo_id(db_conn):
    return "grupo_id" in get_table_columns(db_conn, "emprestimos")


def emprestimos_grupo_select_sql(db_conn, alias="e"):
    if emprestimos_tem_grupo_id(db_conn):
        return f"COALESCE(gsol.nome, '')"
    return f"COALESCE({alias}.grupo_caseiro, '')"


def emprestimos_grupo_join_sql(db_conn, alias="e"):
    if emprestimos_tem_grupo_id(db_conn):
        return f"LEFT JOIN grupos gsol ON {alias}.grupo_id = gsol.id"
    return f"LEFT JOIN grupos gsol ON gsol.nome = {alias}.grupo_caseiro"


def conectacasa_criar_tabelas():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conectacasa_orcamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            titulo TEXT NOT NULL,
            cliente_nome TEXT NOT NULL,
            cliente_empresa TEXT,
            cliente_email TEXT,
            cliente_telefone TEXT,
            descricao TEXT,
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'rascunho',
            validade_dias INTEGER NOT NULL DEFAULT 7,
            desconto REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0,
            valor_total REAL NOT NULL DEFAULT 0,
            itens_json TEXT NOT NULL,
            criado_por INTEGER,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (criado_por) REFERENCES usuarios(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conectacasa_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            empresa_nome TEXT NOT NULL DEFAULT 'ConectaCasa',
            logo_path TEXT,
            pix_imagem_path TEXT,
            pix_nome TEXT,
            pix_chave TEXT,
            pix_cidade TEXT,
            pix_identificador TEXT,
            pix_descricao TEXT,
            pix_beneficiario TEXT,
            acesso_usuario TEXT NOT NULL DEFAULT 'admin',
            acesso_senha_hash TEXT,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    colunas_config = get_table_columns(conn, "conectacasa_config")
    if "acesso_usuario" not in colunas_config:
        conn.execute("ALTER TABLE conectacasa_config ADD COLUMN acesso_usuario TEXT NOT NULL DEFAULT 'admin'")
    if "acesso_senha_hash" not in colunas_config:
        conn.execute("ALTER TABLE conectacasa_config ADD COLUMN acesso_senha_hash TEXT")
    if "pix_imagem_path" not in colunas_config:
        conn.execute("ALTER TABLE conectacasa_config ADD COLUMN pix_imagem_path TEXT")
    colunas = get_table_columns(conn, "conectacasa_orcamentos")
    if "audio_path" not in colunas:
        conn.execute("ALTER TABLE conectacasa_orcamentos ADD COLUMN audio_path TEXT")
    if "audio_transcricao" not in colunas:
        conn.execute("ALTER TABLE conectacasa_orcamentos ADD COLUMN audio_transcricao TEXT")
    if "audio_observacoes" not in colunas:
        conn.execute("ALTER TABLE conectacasa_orcamentos ADD COLUMN audio_observacoes TEXT")
    conn.execute(
        """
        INSERT INTO conectacasa_config (id, empresa_nome)
        SELECT 1, 'ConectaCasa'
        WHERE NOT EXISTS (SELECT 1 FROM conectacasa_config WHERE id = 1)
        """
    )
    config = conn.execute("SELECT acesso_senha_hash FROM conectacasa_config WHERE id = 1").fetchone()
    if config and not config["acesso_senha_hash"]:
        conn.execute(
            "UPDATE conectacasa_config SET acesso_senha_hash = ? WHERE id = 1",
            (generate_password_hash("conectacasa123"),),
        )
    conn.commit()


def conectacasa_obter_config(conn):
    config = conn.execute("SELECT * FROM conectacasa_config WHERE id = 1").fetchone()
    return dict(config) if config else {"empresa_nome": "ConectaCasa"}

def conectacasa_preparar_urls_config(config):
    if not config:
        return {"empresa_nome": "ConectaCasa"}
    config = dict(config)
    config["logo_url"] = url_for("static", filename=config["logo_path"]) if config.get("logo_path") else None
    config["pix_imagem_url"] = url_for("static", filename=config["pix_imagem_path"]) if config.get("pix_imagem_path") else None
    return config


def igreja_criar_tabelas():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS igreja_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            nome_site TEXT NOT NULL DEFAULT 'Igreja em Boa Vista',
            hero_titulo TEXT NOT NULL DEFAULT 'Igreja em Boa Vista',
            hero_subtitulo TEXT NOT NULL DEFAULT 'Avisos, programacao e canais oficiais da igreja em um so lugar.',
            mensagem_boas_vindas TEXT,
            agenda_titulo TEXT NOT NULL DEFAULT 'Agenda e horarios',
            agenda_texto TEXT,
            youtube_url TEXT,
            instagram_url TEXT,
            pix_cnpj TEXT,
            pix_texto TEXT,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS igreja_avisos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            link_url TEXT,
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO igreja_config (
            id, nome_site, hero_titulo, hero_subtitulo, mensagem_boas_vindas,
            agenda_titulo, agenda_texto, youtube_url, instagram_url, pix_cnpj, pix_texto
        )
        SELECT
            1,
            'Igreja em Boa Vista',
            'Igreja em Boa Vista',
            'Avisos, programacao e canais oficiais da igreja em um so lugar.',
            'Acompanhe os avisos da igreja, nossos canais oficiais e a area de contribuicao.',
            'Agenda e horarios',
            'Atualize aqui os horarios de cultos, reunioes e eventos da semana.',
            'https://www.youtube.com/@igrejaemboavista',
            'https://www.instagram.com/igrejaemboavista?igsh=MWR1aXR6NzNuNm1kNw%3D%3D',
            '09.148.629/0001-58',
            'Sua contribuicao ajuda a manter os trabalhos e projetos da igreja.'
        WHERE NOT EXISTS (SELECT 1 FROM igreja_config WHERE id = 1)
        """
    )
    conn.commit()
    conn.close()


def igreja_obter_config(conn):
    config = conn.execute("SELECT * FROM igreja_config WHERE id = 1").fetchone()
    return dict(config) if config else {}


def igreja_listar_avisos(conn, somente_ativos=False):
    query = "SELECT * FROM igreja_avisos"
    params = []
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY ordem ASC, atualizado_em DESC, id DESC"
    return [dict(item) for item in conn.execute(query, params).fetchall()]


def igreja_salvar_config(conn, form):
    conn.execute(
        """
        UPDATE igreja_config
        SET nome_site = ?,
            hero_titulo = ?,
            hero_subtitulo = ?,
            mensagem_boas_vindas = ?,
            agenda_titulo = ?,
            agenda_texto = ?,
            youtube_url = ?,
            instagram_url = ?,
            pix_cnpj = ?,
            pix_texto = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            (form.get("nome_site") or "").strip() or "Igreja em Boa Vista",
            (form.get("hero_titulo") or "").strip() or "Igreja em Boa Vista",
            (form.get("hero_subtitulo") or "").strip() or "Avisos, programacao e canais oficiais da igreja em um so lugar.",
            (form.get("mensagem_boas_vindas") or "").strip(),
            (form.get("agenda_titulo") or "").strip() or "Agenda e horarios",
            (form.get("agenda_texto") or "").strip(),
            (form.get("youtube_url") or "").strip(),
            (form.get("instagram_url") or "").strip(),
            (form.get("pix_cnpj") or "").strip(),
            (form.get("pix_texto") or "").strip(),
        ),
    )
    conn.commit()


def igreja_salvar_aviso(conn, form, aviso_id=None):
    titulo = (form.get("titulo") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    link_url = (form.get("link_url") or "").strip()
    try:
        ordem = int(form.get("ordem") or 0)
    except ValueError:
        ordem = 0
    ativo = 1 if form.get("ativo") == "1" else 0

    if not titulo or not descricao:
        return False, "Titulo e descricao do aviso sao obrigatorios."

    if aviso_id:
        conn.execute(
            """
            UPDATE igreja_avisos
            SET titulo = ?, descricao = ?, link_url = ?, ordem = ?, ativo = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (titulo, descricao, link_url, ordem, ativo, aviso_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO igreja_avisos (titulo, descricao, link_url, ordem, ativo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titulo, descricao, link_url, ordem, ativo),
        )
    conn.commit()
    return True, None


def conectacasa_autenticado():
    return bool(session.get("conectacasa_auth"))


def conectacasa_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if conectacasa_autenticado():
            return func(*args, **kwargs)
        return redirect(url_for("conectacasa_login", next=request.path))

    return wrapper


def conectacasa_salvar_upload_imagem(arquivo, diretorio, prefixo, caminho_relativo):
    if not arquivo or not arquivo.filename:
        return None
    nome_base = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_base)[1].lower()
    if extensao not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    nome_arquivo = f"{prefixo}-{datetime.now().strftime('%Y%m%d%H%M%S')}{extensao}"
    caminho = os.path.join(diretorio, nome_arquivo)
    arquivo.save(caminho)
    return f"{caminho_relativo}/{nome_arquivo}"


def conectacasa_salvar_logo(arquivo):
    return conectacasa_salvar_upload_imagem(arquivo, LOGO_UPLOAD_DIR, "logo", "uploads/conectacasa/logos")


def conectacasa_salvar_pix_imagem(arquivo):
    return conectacasa_salvar_upload_imagem(arquivo, PIX_UPLOAD_DIR, "pix", "uploads/conectacasa/pix")


def conectacasa_gerar_codigo(conn):
    prefixo = datetime.now().strftime("CC-%Y%m%d")
    ultimo = conn.execute(
        "SELECT codigo FROM conectacasa_orcamentos WHERE codigo LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefixo}-%",),
    ).fetchone()
    sequencia = 1
    if ultimo and ultimo["codigo"]:
        try:
            sequencia = int(ultimo["codigo"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            sequencia = 1
    return f"{prefixo}-{sequencia:03d}"


def conectacasa_status_opcoes():
    return [
        ("orcamento", "Orcamento"),
        ("enviado", "Enviado"),
        ("aceito", "Aceito"),
        ("finalizado", "Finalizado"),
        ("rejeitado", "Rejeitado"),
    ]


def conectacasa_status_normalizado(status):
    status = (status or "").strip().lower()
    mapa_legado = {
        "rascunho": "orcamento",
        "aprovado": "aceito",
    }
    return mapa_legado.get(status, status or "orcamento")


def conectacasa_status_label(status):
    mapa = dict(conectacasa_status_opcoes())
    status = conectacasa_status_normalizado(status)
    return mapa.get(status, status.title() if status else "Orcamento")


def conectacasa_data_referencia(valor_data):
    if not valor_data:
        return None
    try:
        return datetime.fromisoformat(str(valor_data))
    except ValueError:
        return None


def conectacasa_mes_valido(valor):
    try:
        return datetime.strptime((valor or "").strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        return None


def conectacasa_mes_label(valor):
    nomes_meses = [
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    mes_normalizado = conectacasa_mes_valido(valor)
    if not mes_normalizado:
        return valor or ""
    data_ref = datetime.strptime(mes_normalizado, "%Y-%m")
    return f"{nomes_meses[data_ref.month - 1]} de {data_ref.year}"


def conectacasa_normalizar_item(descricao, quantidade, valor_unitario, unidade):
    descricao = (descricao or "").strip()
    unidade = (unidade or "").strip() or "un"
    if not descricao:
        return None

    try:
        quantidade = float((quantidade or "0").replace(",", "."))
    except ValueError:
        quantidade = 0

    try:
        valor_unitario = float((valor_unitario or "0").replace(",", "."))
    except ValueError:
        valor_unitario = 0

    quantidade = max(quantidade, 0)
    valor_unitario = max(valor_unitario, 0)
    total = round(quantidade * valor_unitario, 2)

    return {
        "descricao": descricao,
        "quantidade": quantidade,
        "unidade": unidade,
        "valor_unitario": valor_unitario,
        "total": total,
    }


def conectacasa_itens_do_formulario(form):
    descricoes = form.getlist("item_descricao[]")
    quantidades = form.getlist("item_quantidade[]")
    valores = form.getlist("item_valor[]")
    unidades = form.getlist("item_unidade[]")

    itens = []
    for descricao, quantidade, valor_unitario, unidade in zip(descricoes, quantidades, valores, unidades):
        item = conectacasa_normalizar_item(descricao, quantidade, valor_unitario, unidade)
        if item:
            itens.append(item)
    return itens


def conectacasa_calcular_totais(itens, desconto):
    subtotal = round(sum(item["total"] for item in itens), 2)
    try:
        desconto = float((desconto or "0").replace(",", "."))
    except (ValueError, AttributeError):
        desconto = 0
    desconto = max(desconto, 0)
    valor_total = round(max(subtotal - desconto, 0), 2)
    return subtotal, desconto, valor_total


def conectacasa_carregar_orcamento(conn, orcamento_id):
    orcamento = conn.execute(
        """
        SELECT o.*, u.nome AS criado_por_nome
        FROM conectacasa_orcamentos o
        LEFT JOIN usuarios u ON u.id = o.criado_por
        WHERE o.id = ?
        """,
        (orcamento_id,),
    ).fetchone()
    if not orcamento:
        return None
    dados = dict(orcamento)
    dados["status"] = conectacasa_status_normalizado(dados.get("status"))
    dados["itens"] = json.loads(dados.get("itens_json") or "[]")
    dados["status_label"] = conectacasa_status_label(dados.get("status"))
    return dados


def conectacasa_salvar_orcamento(conn, dados_formulario, itens, usuario_id, arquivos=None, orcamento_id=None):
    subtotal, desconto, valor_total = conectacasa_calcular_totais(itens, dados_formulario.get("desconto"))
    titulo = (dados_formulario.get("titulo") or "").strip()
    cliente_nome = (dados_formulario.get("cliente_nome") or "").strip()
    cliente_empresa = (dados_formulario.get("cliente_empresa") or "").strip()
    cliente_email = normalizar_email(dados_formulario.get("cliente_email"))
    cliente_telefone = (dados_formulario.get("cliente_telefone") or "").strip()
    descricao = (dados_formulario.get("descricao") or "").strip()
    observacoes = (dados_formulario.get("observacoes") or "").strip()
    status = conectacasa_status_normalizado(dados_formulario.get("status") or "orcamento")

    status_validos = {codigo for codigo, _ in conectacasa_status_opcoes()}
    if status not in status_validos:
        status = "orcamento"

    validade_dias = 7

    if not titulo or not cliente_nome:
        return False, "Informe o titulo e o nome do cliente.", None
    if not itens:
        return False, "Adicione pelo menos um item ao orcamento.", None

    itens_json = json.dumps(itens, ensure_ascii=False)

    if orcamento_id:
        conn.execute(
            """
            UPDATE conectacasa_orcamentos
            SET titulo = ?, cliente_nome = ?, cliente_empresa = ?, cliente_email = ?, cliente_telefone = ?,
                descricao = ?, observacoes = ?, status = ?, validade_dias = ?, desconto = ?,
                subtotal = ?, valor_total = ?, itens_json = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                titulo,
                cliente_nome,
                cliente_empresa,
                cliente_email,
                cliente_telefone,
                descricao,
                observacoes,
                status,
                validade_dias,
                desconto,
                subtotal,
                valor_total,
                itens_json,
                orcamento_id,
            ),
        )
        conn.commit()
        return True, None, orcamento_id

    codigo = conectacasa_gerar_codigo(conn)
    cursor = conn.execute(
        """
        INSERT INTO conectacasa_orcamentos (
            codigo, titulo, cliente_nome, cliente_empresa, cliente_email, cliente_telefone,
            descricao, observacoes, status, validade_dias, desconto, subtotal, valor_total,
            itens_json, criado_por
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            codigo,
            titulo,
            cliente_nome,
            cliente_empresa,
            cliente_email,
            cliente_telefone,
            descricao,
            observacoes,
            status,
            validade_dias,
            desconto,
            subtotal,
            valor_total,
            itens_json,
            usuario_id,
        ),
    )
    conn.commit()
    return True, None, cursor.lastrowid


def conectacasa_render_pdf(orcamento, config):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=34, bottomMargin=34, leftMargin=34, rightMargin=34)
    elementos = []

    cor_tinta = colors.HexColor("#1f2937")
    cor_navy = colors.HexColor("#102132")
    cor_muted = colors.HexColor("#64748b")
    cor_line = colors.HexColor("#d7dee7")
    cor_soft = colors.HexColor("#f8efe3")
    cor_warm = colors.HexColor("#d97706")

    def carregar_logo_flowable(relative_path=None, max_width=110, max_height=72):
        imagem_path = relative_path if relative_path is not None else config.get("logo_path")
        if not imagem_path:
            return None
        caminho_logo = os.path.join(PROJECT_DIR, "static", imagem_path.replace("/", os.sep))
        if not os.path.exists(caminho_logo):
            return None
        try:
            largura_original, altura_original = ImageReader(caminho_logo).getSize()
            proporcao = min(max_width / float(largura_original), max_height / float(altura_original))
            proporcao = min(proporcao, 1.0)
            largura_final = largura_original * proporcao
            altura_final = altura_original * proporcao
            return Image(caminho_logo, width=largura_final, height=altura_final)
        except Exception:
            return None

    overline_style = ParagraphStyle(
        "ConectaCasaOverline",
        parent=styles["BodyText"],
        fontSize=9,
        textColor=cor_warm,
        spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    titulo_style = ParagraphStyle(
        "ConectaCasaTitulo",
        parent=styles["Heading1"],
        fontSize=23,
        textColor=cor_tinta,
        leading=28,
        spaceAfter=8,
    )
    subtitulo_style = ParagraphStyle(
        "ConectaCasaSubtitulo",
        parent=styles["BodyText"],
        fontSize=10,
        textColor=cor_muted,
        leading=14,
        spaceAfter=6,
    )
    secao_style = ParagraphStyle(
        "ConectaCasaSecao",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=cor_navy,
        spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    card_title_style = ParagraphStyle(
        "ConectaCasaCardTitle",
        parent=styles["BodyText"],
        fontSize=12,
        textColor=cor_tinta,
        spaceAfter=8,
        fontName="Helvetica-Bold",
    )
    resumo_label_style = ParagraphStyle(
        "ConectaCasaResumoLabel",
        parent=styles["BodyText"],
        fontSize=8,
        textColor=cor_muted,
        fontName="Helvetica-Bold",
    )
    resumo_valor_style = ParagraphStyle(
        "ConectaCasaResumoValor",
        parent=styles["BodyText"],
        fontSize=10,
        textColor=cor_tinta,
    )
    valor_final_style = ParagraphStyle(
        "ConectaCasaValorFinal",
        parent=styles["Heading2"],
        fontSize=19,
        textColor=cor_navy,
        fontName="Helvetica-Bold",
        leading=22,
    )

    cabecalho_esquerda = [
        Paragraph("CONECTACASA", overline_style),
        Paragraph("Projetos, orcamentos e propostas com visual profissional.", titulo_style),
        Paragraph(
            f"Orcamento {orcamento['codigo']} para {orcamento['cliente_nome']}. "
            f"Documento preparado para apresentacao comercial e aprovacao.",
            subtitulo_style,
        ),
    ]

    logo_flowable = carregar_logo_flowable()
    cabecalho_direita = []
    if logo_flowable:
        cabecalho_direita.extend([logo_flowable, Spacer(1, 10)])
    cabecalho_direita.extend(
        [
            Paragraph(config.get("empresa_nome") or "ConectaCasa", card_title_style),
            Paragraph("Proposta comercial", subtitulo_style),
        ]
    )

    cabecalho = Table(
        [[cabecalho_esquerda, cabecalho_direita]],
        colWidths=[320, 170],
        hAlign="LEFT",
    )
    cabecalho.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, cor_line),
                ("LEFTPADDING", (0, 0), (-1, -1), 20),
                ("RIGHTPADDING", (0, 0), (-1, -1), 20),
                ("TOPPADDING", (0, 0), (-1, -1), 18),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fcfcfd")),
            ]
        )
    )
    elementos.append(cabecalho)
    elementos.append(Spacer(1, 18))

    cliente_bloco = [
        Paragraph("Cliente", secao_style),
        Paragraph(f"<b>{orcamento['cliente_nome']}</b>", styles["BodyText"]),
    ]
    if orcamento.get("cliente_empresa"):
        cliente_bloco.append(Paragraph(orcamento["cliente_empresa"], styles["BodyText"]))
    if orcamento.get("cliente_email"):
        cliente_bloco.append(Paragraph(orcamento["cliente_email"], styles["BodyText"]))
    if orcamento.get("cliente_telefone"):
        cliente_bloco.append(Paragraph(orcamento["cliente_telefone"], styles["BodyText"]))

    resumo_bloco = [
        Paragraph("Resumo", secao_style),
        Table(
            [
                [Paragraph("Status", resumo_label_style), Paragraph(orcamento["status_label"], resumo_valor_style)],
                [Paragraph("Subtotal", resumo_label_style), Paragraph(formata_brl(orcamento["subtotal"]), resumo_valor_style)],
                [Paragraph("Desconto", resumo_label_style), Paragraph(formata_brl(orcamento["desconto"]), resumo_valor_style)],
                [Paragraph("Valor final", resumo_label_style), Paragraph(formata_brl(orcamento["valor_total"]), valor_final_style)],
            ],
            colWidths=[70, 120],
        ),
    ]
    resumo_bloco[-1].setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEABOVE", (0, 4), (-1, 4), 1, cor_line),
            ]
        )
    )

    resumo_tabela = Table([[cliente_bloco, resumo_bloco]], colWidths=[260, 230], hAlign="LEFT")
    resumo_tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 1, cor_line),
                ("LEFTPADDING", (0, 0), (-1, -1), 18),
                ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ("TOPPADDING", (0, 0), (-1, -1), 16),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elementos.append(resumo_tabela)
    elementos.append(Spacer(1, 18))

    tabela_dados = [["Descricao", "Qtd.", "Un.", "Valor unit.", "Total"]]
    for item in orcamento["itens"]:
        tabela_dados.append(
            [
                item["descricao"],
                str(item["quantidade"]).replace(".", ","),
                item["unidade"],
                formata_brl(item["valor_unitario"]),
                formata_brl(item["total"]),
            ]
        )

    tabela = Table(tabela_dados, colWidths=[220, 45, 45, 90, 90])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), cor_navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, cor_line),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#fbfcfd")]),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    elementos.append(tabela)
    elementos.append(Spacer(1, 16))

    resumo = [
        ["Subtotal", formata_brl(orcamento["subtotal"])],
        ["Desconto", formata_brl(orcamento["desconto"])],
        ["Valor final", formata_brl(orcamento["valor_total"])],
    ]
    resumo_tabela = Table(resumo, colWidths=[110, 120], hAlign="RIGHT")
    resumo_tabela.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, -1), cor_tinta),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("LINEABOVE", (0, 2), (-1, 2), 1, cor_navy),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elementos.append(resumo_tabela)

    if orcamento.get("descricao"):
        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph("Escopo", secao_style))
        elementos.append(Paragraph(orcamento["descricao"].replace("\n", "<br/>"), styles["BodyText"]))

    if orcamento.get("observacoes"):
        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph("Observacoes", secao_style))
        elementos.append(Paragraph(orcamento["observacoes"].replace("\n", "<br/>"), styles["BodyText"]))

    pix_imagem = carregar_logo_flowable(config.get("pix_imagem_path"), max_width=120, max_height=120)
    if pix_imagem:
        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph("Pagamento via PIX", secao_style))
        pix_info = []
        if config.get("pix_beneficiario"):
            pix_info.append(Paragraph(f"<b>Beneficiario:</b> {config['pix_beneficiario']}", styles["BodyText"]))
        pix_info.append(Paragraph(f"<b>Valor:</b> {formata_brl(orcamento['valor_total'])}", styles["BodyText"]))
        pix_tabela = Table([[pix_info, pix_imagem]], colWidths=[340, 120], hAlign="LEFT")
        pix_tabela.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), cor_soft),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#ead8c4")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 18),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                    ("TOPPADDING", (0, 0), (-1, -1), 16),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ]
            )
        )
        elementos.append(pix_tabela)

    doc.build(elementos)
    buffer.seek(0)
    return buffer

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
    def __init__(self, id, nome, usuario, tipo, pode_acessar_inventario=1, pode_editar_igreja=0):
        self.id = id
        self.nome = nome
        self.usuario = usuario
        self.tipo = tipo
        self.pode_acessar_inventario = bool(int(pode_acessar_inventario or 0))
        self.pode_editar_igreja = bool(int(pode_editar_igreja or 0))


def usuario_pode_acessar_inventario(user):
    return bool(getattr(user, "tipo", "") == "admin" or getattr(user, "pode_acessar_inventario", False))


def usuario_pode_editar_igreja(user):
    return bool(getattr(user, "tipo", "") == "admin" or getattr(user, "pode_editar_igreja", False))


def destino_pos_login(user):
    if usuario_pode_acessar_inventario(user):
        return url_for("dashboard")
    if usuario_pode_editar_igreja(user):
        return url_for("igreja_admin")
    return None

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    if user:
        return User(
            user["id"],
            user["nome"],
            user["usuario"],
            user["tipo"],
            user["pode_acessar_inventario"] if "pode_acessar_inventario" in user.keys() else 1,
            user["pode_editar_igreja"] if "pode_editar_igreja" in user.keys() else 0,
        )
    return None

def get_reset_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])

def get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

def normalizar_email(valor):
    return (valor or "").strip().lower()

def validar_email_informado(valor):
    try:
        return validate_email(normalizar_email(valor), check_deliverability=False).normalized
    except EmailNotValidError:
        return None

def senha_atende_requisitos(senha):
    return bool(senha) and len(senha) >= 8

def gerar_email_placeholder(usuario):
    base = re.sub(r"[^a-z0-9]+", "-", (usuario or "usuario").strip().lower()).strip("-") or "usuario"
    return f"{base}@sem-email.local"

def email_usa_placeholder(email):
    return normalizar_email(email).endswith("@sem-email.local")

def email_configurado_corretamente():
    campos_obrigatorios = (
        "MAIL_SERVER",
        "MAIL_USERNAME",
        "MAIL_PASSWORD",
        "MAIL_DEFAULT_SENDER",
    )
    faltando = [campo for campo in campos_obrigatorios if not app.config.get(campo)]
    if faltando:
        return False, f"Configuracao de e-mail incompleta: {', '.join(faltando)}"
    return True, None

def montar_url_publica(caminho):
    base_url = (app.config.get("APP_BASE_URL") or "").strip().rstrip("/")
    caminho = f"/{(caminho or '').lstrip('/')}"
    if base_url:
        return f"{base_url}{caminho}"
    return caminho

def enviar_email_reset(nome, email_destino, link_reset):
    configurado, erro_config = email_configurado_corretamente()
    if not configurado:
        return False, erro_config
    if email_usa_placeholder(email_destino):
        return False, "Usuario sem e-mail real cadastrado."

    mensagem = Message(
        subject="Redefinicao de senha - Inventario OAIBV",
        recipients=[email_destino],
    )
    mensagem.body = (
        f"Ola, {nome}.\n\n"
        "Recebemos um pedido para redefinir sua senha.\n"
        f"Acesse este link: {link_reset}\n\n"
        f"Este link expira em {app.config['RESET_PASSWORD_MAX_AGE'] // 60} minutos.\n"
        "Se voce nao solicitou esta alteracao, ignore este e-mail."
    )

    try:
        mail.send(mensagem)
        return True, None
    except Exception as exc:
        return False, str(exc)

def enviar_email_simples(assunto, email_destino, corpo):
    configurado, erro_config = email_configurado_corretamente()
    if not configurado:
        return False, erro_config
    if email_usa_placeholder(email_destino):
        return False, "Usuario sem e-mail real cadastrado."

    mensagem = Message(
        subject=assunto,
        recipients=[email_destino],
    )
    mensagem.body = corpo

    try:
        mail.send(mensagem)
        return True, None
    except Exception as exc:
        return False, str(exc)

def enviar_email_cadastro_pendente(nome, email_destino):
    corpo = (
        f"Ola, {nome}.\n\n"
        "Recebemos seu cadastro no sistema de inventario da OAIBV.\n"
        "Seu acesso foi criado e agora aguarda aprovacao de um administrador.\n\n"
        "Assim que a aprovacao for concluida, voce recebera um novo e-mail informando que ja pode entrar no sistema.\n\n"
        "Atenciosamente,\n"
        "Equipe OAIBV"
    )
    return enviar_email_simples(
        "Cadastro recebido - aguardando aprovacao",
        email_destino,
        corpo,
    )

def enviar_email_cadastro_aprovado(nome, email_destino):
    corpo = (
        f"Ola, {nome}.\n\n"
        "Seu cadastro no sistema de inventario da OAIBV foi aprovado por um administrador.\n"
        "Voce ja pode acessar o sistema com seu usuario ou e-mail e a senha cadastrada.\n\n"
        f"Link de acesso: {montar_url_publica('/login')}\n\n"
        "Atenciosamente,\n"
        "Equipe OAIBV"
    )
    return enviar_email_simples(
        "Cadastro aprovado - acesso liberado",
        email_destino,
        corpo,
    )

def migrar_usuarios_auth():
    conn = get_db()
    try:
        colunas = {
            coluna["name"]: coluna
            for coluna in conn.execute("PRAGMA table_info(usuarios)").fetchall()
        }

        if "email" not in colunas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN email TEXT")
        if "ativo" not in colunas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
        if "criado_em" not in colunas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN criado_em TIMESTAMP")
        if "pode_acessar_inventario" not in colunas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN pode_acessar_inventario INTEGER NOT NULL DEFAULT 1")
        if "pode_editar_igreja" not in colunas:
            conn.execute("ALTER TABLE usuarios ADD COLUMN pode_editar_igreja INTEGER NOT NULL DEFAULT 0")

        usuarios_sem_email = conn.execute(
            "SELECT id, usuario FROM usuarios WHERE email IS NULL OR TRIM(email) = ''"
        ).fetchall()
        for usuario in usuarios_sem_email:
            conn.execute(
                "UPDATE usuarios SET email = ? WHERE id = ?",
                (gerar_email_placeholder(usuario["usuario"]), usuario["id"]),
            )

        conn.execute(
            "UPDATE usuarios SET ativo = 1 WHERE ativo IS NULL"
        )
        conn.execute(
            "UPDATE usuarios SET criado_em = CURRENT_TIMESTAMP WHERE criado_em IS NULL"
        )
        conn.execute(
            "UPDATE usuarios SET pode_acessar_inventario = 1 WHERE pode_acessar_inventario IS NULL"
        )
        conn.execute(
            "UPDATE usuarios SET pode_editar_igreja = 0 WHERE pode_editar_igreja IS NULL"
        )
        conn.execute(
            "UPDATE usuarios SET pode_editar_igreja = 1 WHERE usuario = 'admin'"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)"
        )
        conn.commit()
    finally:
        conn.close()

# Decorador para verificar se o usuário é administrador
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.tipo != "admin" or not usuario_pode_acessar_inventario(current_user):
            flash("Acesso restrito a administradores.", "danger")
            destino = destino_pos_login(current_user) if current_user.is_authenticated else url_for("login")
            return redirect(destino or url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def igreja_edit_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not usuario_pode_editar_igreja(current_user):
            flash("Voce nao tem permissao para editar o portal da igreja.", "danger")
            destino = destino_pos_login(current_user)
            return redirect(destino or url_for("login"))
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
    return {"now": datetime.now, "formata_brl": formata_brl}


INVENTARIO_ENDPOINTS = {
    "dashboard",
    "inventario",
    "novo_item",
    "editar_item",
    "excluir_item",
    "grupos_marcas",
    "emprestimos",
    "devolver_emprestimo",
    "desfazer_devolucao",
    "excluir_emprestimo",
    "termo_compromisso",
    "relatorios",
    "usuarios",
    "ativar_usuario",
    "novo_usuario",
    "editar_usuario",
    "excluir_usuario",
    "logs",
}


@app.before_request
def aplicar_permissoes_de_acesso():
    if not current_user.is_authenticated:
        return None

    endpoint = request.endpoint or ""
    if endpoint in INVENTARIO_ENDPOINTS and not usuario_pode_acessar_inventario(current_user):
        flash("Seu usuario nao tem acesso ao inventario.", "warning")
        destino = destino_pos_login(current_user)
        return redirect(destino or url_for("logout"))

    if endpoint.startswith("igreja_") and endpoint != "igreja_publico" and not usuario_pode_editar_igreja(current_user):
        flash("Seu usuario nao tem permissao para editar o portal da igreja.", "warning")
        destino = destino_pos_login(current_user)
        return redirect(destino or url_for("logout"))

# Rotas de autenticação
@app.route("/login", methods=["GET", "POST"])
@app.route("/login/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(destino_pos_login(current_user) or url_for("logout"))
    
    if request.method == "POST":
        identificador = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")
        
        db = get_db()
        user = db.execute(
            """
            SELECT * FROM usuarios
            WHERE lower(usuario) = lower(?) OR lower(coalesce(email, '')) = lower(?)
            """,
            (identificador, identificador),
        ).fetchone()
        
        if user and int(user["ativo"]) == 1 and check_password_hash(user["senha_hash"], senha):
            user_obj = User(
                user["id"],
                user["nome"],
                user["usuario"],
                user["tipo"],
                user["pode_acessar_inventario"] if "pode_acessar_inventario" in user.keys() else 1,
                user["pode_editar_igreja"] if "pode_editar_igreja" in user.keys() else 0,
            )
            destino = destino_pos_login(user_obj)
            if not destino:
                flash("Seu usuario esta ativo, mas ainda nao possui acessos liberados.", "warning")
                return render_template("login_auth.html")
            login_user(user_obj)
            registrar_log("Login realizado com sucesso")
            db.commit()
            return redirect(destino)
        elif user and int(user["ativo"]) != 1:
            flash("Seu cadastro foi recebido, mas ainda aguarda aprovacao de um administrador.", "warning")
        else:
            flash("Usuario, e-mail ou senha invalidos.", "danger")
    
    return render_template("login_auth.html")

@app.route("/cadastro", methods=["GET", "POST"])
@app.route("/cadastro/", methods=["GET", "POST"])
def cadastro():
    if current_user.is_authenticated:
        return redirect(destino_pos_login(current_user) or url_for("logout"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario = request.form.get("usuario", "").strip()
        email = validar_email_informado(request.form.get("email"))
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not nome or not usuario or not email or not senha:
            flash("Preencha todos os campos obrigatorios.", "danger")
            return render_template("cadastro.html")

        if not senha_atende_requisitos(senha):
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template("cadastro.html")

        if senha != confirmar_senha:
            flash("As senhas nao coincidem.", "danger")
            return render_template("cadastro.html")

        db = get_db()
        existente = db.execute(
            """
            SELECT id FROM usuarios
            WHERE lower(usuario) = lower(?) OR lower(coalesce(email, '')) = lower(?)
            """,
            (usuario, email),
        ).fetchone()

        if existente:
            flash("Ja existe uma conta com este usuario ou e-mail.", "danger")
            return render_template("cadastro.html")

        db.execute(
            """
            INSERT INTO usuarios (nome, usuario, email, senha_hash, tipo, ativo, criado_em, pode_acessar_inventario, pode_editar_igreja)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nome, usuario, email, generate_password_hash(senha), "comum", 0, datetime.now(), 1, 0),
        )
        db.commit()
        enviado, erro = enviar_email_cadastro_pendente(nome, email)
        if not enviado:
            print(f"[Email] Falha ao enviar aviso de cadastro pendente para {email}: {erro}")
        flash("Cadastro enviado com sucesso. Aguarde a aprovacao de um administrador para acessar o sistema.", "success")
        return redirect(url_for("login"))

    return render_template("cadastro.html")

@app.route("/esqueci-senha", methods=["GET", "POST"])
@app.route("/esqueci-senha/", methods=["GET", "POST"])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(destino_pos_login(current_user) or url_for("logout"))

    if request.method == "POST":
        email = validar_email_informado(request.form.get("email"))

        if not email:
            flash("Informe um e-mail valido para recuperar a senha.", "danger")
            return render_template("esqueci_senha.html")

        db = get_db()
        usuario = db.execute(
            "SELECT id, nome, email FROM usuarios WHERE lower(email) = lower(?) AND ativo = 1",
            (email,),
        ).fetchone()

        if usuario:
            token = get_reset_serializer().dumps(
                {"user_id": usuario["id"], "email": usuario["email"]},
                salt="resetar-senha",
            )
            caminho_reset = url_for("resetar_senha_curto", token=token, _external=False)
            link_reset = montar_url_publica(caminho_reset)
            enviado, erro = enviar_email_reset(usuario["nome"], usuario["email"], link_reset)
            if not enviado:
                print(f"[Email] Falha ao enviar reset para {usuario['email']}: {erro}")
                flash(f"Nao foi possivel enviar o e-mail de recuperacao: {erro}", "danger")
                return render_template("esqueci_senha.html")
            flash("E-mail de recuperacao enviado com sucesso.", "success")
        else:
            print(f"[Email] Pedido de reset ignorado para e-mail nao encontrado/ativo: {email}")
            flash("Nao encontramos um usuario ativo com este e-mail.", "danger")
            return render_template("esqueci_senha.html")

        return redirect(url_for("login"))

    return render_template("esqueci_senha.html")

@app.route("/r/<token>", methods=["GET", "POST"], endpoint="resetar_senha_curto")
@app.route("/resetar-senha/<token>", methods=["GET", "POST"])
@app.route("/resetar-senha/<token>/", methods=["GET", "POST"])
def resetar_senha(token):
    try:
        dados = get_reset_serializer().loads(
            token,
            salt="resetar-senha",
            max_age=app.config["RESET_PASSWORD_MAX_AGE"],
        )
    except (BadSignature, SignatureExpired):
        flash("O link de redefinicao e invalido ou expirou.", "danger")
        return redirect(url_for("esqueci_senha"))

    db = get_db()
    usuario = db.execute(
        "SELECT id, nome, email FROM usuarios WHERE id = ? AND ativo = 1",
        (dados["user_id"],),
    ).fetchone()

    if not usuario or normalizar_email(usuario["email"]) != normalizar_email(dados.get("email")):
        flash("Nao foi possivel validar este pedido de redefinicao.", "danger")
        return redirect(url_for("esqueci_senha"))

    if request.method == "POST":
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not senha_atende_requisitos(senha):
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template("resetar_senha.html", token=token, usuario=usuario)

        if senha != confirmar_senha:
            flash("As senhas nao coincidem.", "danger")
            return render_template("resetar_senha.html", token=token, usuario=usuario)

        db.execute(
            "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
            (generate_password_hash(senha), usuario["id"]),
        )
        db.commit()
        if current_user.is_authenticated:
            logout_user()
        flash("Senha redefinida com sucesso. Voce ja pode entrar.", "success")
        return redirect(url_for("login"))

    return render_template("resetar_senha.html", token=token, usuario=usuario)

@app.route("/logout")
@app.route("/logout/")
@login_required
def logout():
    registrar_log("Logout realizado")
    logout_user()
    return redirect(url_for("login"))


@app.route("/conectacasa")
@app.route("/conectacasa/")
def conectacasa_publico():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    return render_template("conectacasa_publico.html", config=config)


@app.route("/conectacasa/entrar", methods=["GET", "POST"])
@app.route("/conectacasa/entrar/", methods=["GET", "POST"])
def conectacasa_login():
    if conectacasa_autenticado():
        return redirect(url_for("conectacasa_home"))

    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    proximo = request.args.get("next") or request.form.get("next") or url_for("conectacasa_home")

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        senha = request.form.get("senha") or ""
        config_bruta = conectacasa_obter_config(conn)
        usuario_salvo = (config_bruta.get("acesso_usuario") or "admin").strip()
        senha_hash = config_bruta.get("acesso_senha_hash") or ""

        if usuario == usuario_salvo and senha_hash and check_password_hash(senha_hash, senha):
            session["conectacasa_auth"] = True
            session["conectacasa_user"] = usuario_salvo
            session.permanent = True
            if proximo.startswith("/conectacasa"):
                return redirect(proximo)
            return redirect(url_for("conectacasa_home"))

        flash("Usuario ou senha invalidos.", "danger")

    return render_template("conectacasa_login.html", config=config, proximo=proximo)


@app.route("/conectacasa/sair")
@app.route("/conectacasa/sair/")
def conectacasa_logout():
    session.pop("conectacasa_auth", None)
    session.pop("conectacasa_user", None)
    return redirect(url_for("conectacasa_publico"))


@app.route("/conectacasa/painel")
@app.route("/conectacasa/painel/")
@conectacasa_required
def conectacasa_home():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    orcamentos_raw = conn.execute(
        """
        SELECT id, codigo, titulo, cliente_nome, cliente_empresa, status, valor_total, criado_em, atualizado_em
        FROM conectacasa_orcamentos
        ORDER BY atualizado_em DESC, id DESC
        """
    ).fetchall()

    orcamentos = []
    for item in orcamentos_raw:
        item_dict = dict(item)
        item_dict["status"] = conectacasa_status_normalizado(item_dict.get("status"))
        data_referencia = conectacasa_data_referencia(item_dict.get("atualizado_em")) or conectacasa_data_referencia(item_dict.get("criado_em"))
        item_dict["referencia_data"] = data_referencia
        item_dict["mes_referencia"] = data_referencia.strftime("%Y-%m") if data_referencia else datetime.now().strftime("%Y-%m")
        orcamentos.append(item_dict)

    meses_disponiveis = sorted({item["mes_referencia"] for item in orcamentos if item.get("mes_referencia")}, reverse=True)
    mes_atual = datetime.now().strftime("%Y-%m")
    if not meses_disponiveis:
        meses_disponiveis = [mes_atual]

    mes_selecionado = conectacasa_mes_valido(request.args.get("mes")) or mes_atual
    if mes_selecionado not in meses_disponiveis:
        mes_selecionado = meses_disponiveis[0]

    orcamentos_filtrados = [item for item in orcamentos if item.get("mes_referencia") == mes_selecionado]

    total_orcamentos = len(orcamentos_filtrados)
    total_em_orcamento = sum(1 for item in orcamentos_filtrados if item["status"] == "orcamento")
    valor_a_receber = round(
        sum(
            item["valor_total"] or 0
            for item in orcamentos_filtrados
            if item["status"] in {"enviado", "aceito"}
        ),
        2,
    )
    valor_recebido = round(
        sum(item["valor_total"] or 0 for item in orcamentos_filtrados if item["status"] == "finalizado"),
        2,
    )

    return render_template(
        "conectacasa_lista.html",
        orcamentos=orcamentos_filtrados,
        total_orcamentos=total_orcamentos,
        total_em_orcamento=total_em_orcamento,
        valor_a_receber=valor_a_receber,
        valor_recebido=valor_recebido,
        config=config,
        conectacasa_status_label=conectacasa_status_label,
        status_opcoes=conectacasa_status_opcoes(),
        mes_selecionado=mes_selecionado,
        mes_selecionado_label=conectacasa_mes_label(mes_selecionado),
        meses_disponiveis=[{"valor": mes, "label": conectacasa_mes_label(mes)} for mes in meses_disponiveis],
    )


@app.route("/conectacasa/configuracoes", methods=["GET", "POST"])
@app.route("/conectacasa/configuracoes/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_configuracoes():
    conn = get_db()
    config = conectacasa_obter_config(conn)

    if request.method == "POST":
        logo_path = conectacasa_salvar_logo(request.files.get("logo_arquivo")) or config.get("logo_path")
        pix_imagem_path = conectacasa_salvar_pix_imagem(request.files.get("pix_imagem_arquivo")) or config.get("pix_imagem_path")
        dados = {
            "empresa_nome": (request.form.get("empresa_nome") or "ConectaCasa").strip(),
            "pix_nome": (request.form.get("pix_nome") or "").strip(),
            "pix_chave": (request.form.get("pix_chave") or "").strip(),
            "pix_cidade": (request.form.get("pix_cidade") or "").strip(),
            "pix_identificador": (request.form.get("pix_identificador") or "").strip(),
            "pix_descricao": (request.form.get("pix_descricao") or "").strip(),
            "pix_beneficiario": (request.form.get("pix_beneficiario") or "").strip(),
            "acesso_usuario": (request.form.get("acesso_usuario") or config.get("acesso_usuario") or "admin").strip() or "admin",
            "logo_path": logo_path,
            "pix_imagem_path": pix_imagem_path,
        }
        nova_senha = (request.form.get("acesso_senha") or "").strip()
        senha_hash = generate_password_hash(nova_senha) if nova_senha else config.get("acesso_senha_hash")
        conn.execute(
            """
            UPDATE conectacasa_config
            SET empresa_nome = ?, logo_path = ?, pix_imagem_path = ?, pix_nome = ?, pix_chave = ?, pix_cidade = ?,
                pix_identificador = ?, pix_descricao = ?, pix_beneficiario = ?, acesso_usuario = ?, acesso_senha_hash = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                dados["empresa_nome"],
                dados["logo_path"],
                dados["pix_imagem_path"],
                dados["pix_nome"],
                dados["pix_chave"],
                dados["pix_cidade"],
                dados["pix_identificador"],
                dados["pix_descricao"],
                dados["pix_beneficiario"],
                dados["acesso_usuario"],
                senha_hash,
            ),
        )
        conn.commit()
        session["conectacasa_user"] = dados["acesso_usuario"]
        flash("Configuracoes da ConectaCasa atualizadas.", "success")
        return redirect(url_for("conectacasa_configuracoes"))

    config = conectacasa_preparar_urls_config(config)
    return render_template("conectacasa_configuracoes.html", config=config)


@app.route("/conectacasa/novo", methods=["GET", "POST"])
@app.route("/conectacasa/novo/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_novo_orcamento():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    if request.method == "POST":
        itens = conectacasa_itens_do_formulario(request.form)
        ok, erro, orcamento_id = conectacasa_salvar_orcamento(conn, request.form, itens, None, arquivos=request.files)
        if not ok:
            flash(erro, "danger")
            return render_template(
                "conectacasa_form.html",
                orcamento=request.form,
                itens=itens or [{"descricao": "", "quantidade": 1, "unidade": "un", "valor_unitario": 0, "total": 0}],
                status_opcoes=conectacasa_status_opcoes(),
                config=config,
                modo="novo",
            )
        flash("Orcamento criado com sucesso.", "success")
        return redirect(url_for("conectacasa_visualizar_orcamento", orcamento_id=orcamento_id))

    return render_template(
        "conectacasa_form.html",
        orcamento={"status": "orcamento", "desconto": 0, "subtotal": 0, "valor_total": 0},
        itens=[{"descricao": "", "quantidade": 1, "unidade": "un", "valor_unitario": 0, "total": 0}],
        status_opcoes=conectacasa_status_opcoes(),
        config=config,
        modo="novo",
    )


@app.route("/conectacasa/orcamentos/<int:orcamento_id>")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/")
@conectacasa_required
def conectacasa_visualizar_orcamento(orcamento_id):
    conn = get_db()
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(url_for("conectacasa_home"))
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    return render_template(
        "conectacasa_visualizar.html",
        orcamento=orcamento,
        config=config,
    )


@app.route("/conectacasa/orcamentos/<int:orcamento_id>/editar", methods=["GET", "POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/editar/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_editar_orcamento(orcamento_id):
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(url_for("conectacasa_home"))

    if request.method == "POST":
        itens = conectacasa_itens_do_formulario(request.form)
        ok, erro, _ = conectacasa_salvar_orcamento(conn, request.form, itens, None, arquivos=request.files, orcamento_id=orcamento_id)
        if not ok:
            flash(erro, "danger")
            dados = dict(request.form)
            dados["id"] = orcamento_id
            return render_template(
                "conectacasa_form.html",
                orcamento=dados,
                itens=itens or orcamento["itens"],
                status_opcoes=conectacasa_status_opcoes(),
                config=config,
                modo="editar",
            )
        flash("Orcamento atualizado com sucesso.", "success")
        return redirect(url_for("conectacasa_visualizar_orcamento", orcamento_id=orcamento_id))

    return render_template(
        "conectacasa_form.html",
        orcamento=orcamento,
        itens=orcamento["itens"],
        status_opcoes=conectacasa_status_opcoes(),
        config=config,
        modo="editar",
    )


@app.route("/conectacasa/orcamentos/<int:orcamento_id>/status", methods=["POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/status/", methods=["POST"])
@conectacasa_required
def conectacasa_atualizar_status(orcamento_id):
    conn = get_db()
    orcamento = conn.execute("SELECT id FROM conectacasa_orcamentos WHERE id = ?", (orcamento_id,)).fetchone()
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(url_for("conectacasa_home"))

    status = conectacasa_status_normalizado(request.form.get("status"))
    status_validos = {codigo for codigo, _ in conectacasa_status_opcoes()}
    if status not in status_validos:
        flash("Status invalido.", "danger")
        return redirect(url_for("conectacasa_home"))

    conn.execute(
        """
        UPDATE conectacasa_orcamentos
        SET status = ?, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, orcamento_id),
    )
    conn.commit()
    flash(f"Status atualizado para {conectacasa_status_label(status)}.", "success")

    mes = conectacasa_mes_valido(request.form.get("mes"))
    if mes:
        return redirect(url_for("conectacasa_home", mes=mes))
    return redirect(url_for("conectacasa_home"))


@app.route("/conectacasa/orcamentos/<int:orcamento_id>/pdf")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/pdf/")
@conectacasa_required
def conectacasa_orcamento_pdf(orcamento_id):
    conn = get_db()
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(url_for("conectacasa_home"))

    config = conectacasa_obter_config(conn)
    pdf = conectacasa_render_pdf(orcamento, config)
    nome_arquivo = f"{orcamento['codigo']}.pdf"
    return send_file(pdf, as_attachment=True, download_name=nome_arquivo, mimetype="application/pdf")


@app.route("/igrejaemboavista")
@app.route("/igrejaemboavista/")
def igreja_publico():
    conn = get_db()
    config = igreja_obter_config(conn)
    avisos = igreja_listar_avisos(conn, somente_ativos=True)
    return render_template("igrejaemboavista_publico.html", config=config, avisos=avisos)


@app.route("/igrejaemboavista/editar", methods=["GET", "POST"])
@app.route("/igrejaemboavista/editar/", methods=["GET", "POST"])
@login_required
@igreja_edit_required
def igreja_admin():
    conn = get_db()

    if request.method == "POST":
        igreja_salvar_config(conn, request.form)
        flash("Conteudo do portal atualizado com sucesso.", "success")
        return redirect(url_for("igreja_admin"))

    config = igreja_obter_config(conn)
    avisos = igreja_listar_avisos(conn)
    return render_template("igrejaemboavista_admin.html", config=config, avisos=avisos)


@app.route("/igrejaemboavista/avisos/novo", methods=["POST"])
@app.route("/igrejaemboavista/avisos/novo/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_novo():
    conn = get_db()
    igreja_salvar_aviso(conn, request.form)
    flash("Aviso criado com sucesso.", "success")
    return redirect(url_for("igreja_admin"))


@app.route("/igrejaemboavista/avisos/<int:aviso_id>/editar", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/editar/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_editar(aviso_id):
    conn = get_db()
    igreja_salvar_aviso(conn, request.form, aviso_id=aviso_id)
    flash("Aviso atualizado com sucesso.", "success")
    return redirect(url_for("igreja_admin"))


@app.route("/igrejaemboavista/avisos/<int:aviso_id>/excluir", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/excluir/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_excluir(aviso_id):
    conn = get_db()
    conn.execute("DELETE FROM igreja_avisos WHERE id = ?", (aviso_id,))
    conn.commit()
    flash("Aviso removido com sucesso.", "success")
    return redirect(url_for("igreja_admin"))


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
    total_grupos = len(grupos_labels)
    grupo_destaque = grupos_labels[0] if grupos_labels else "Sem grupos"
    grupo_destaque_total = grupos_data[0] if grupos_data else 0
    total_movimentacoes = total_emprestado + total_devolvido
    taxa_devolucao = round((total_devolvido / total_movimentacoes) * 100) if total_movimentacoes else 0
    
    return render_template("dashboard_simples.html", 
                          total_itens=total_itens,
                          total_emprestado=total_emprestado,
                          total_devolvido=total_devolvido, # Passando total devolvido
                          grupos_labels=grupos_labels,
                          grupos_data=grupos_data,
                          emprestimos_status_labels=emprestimos_status_labels,
                          emprestimos_status_data=emprestimos_status_data,
                          total_grupos=total_grupos,
                          grupo_destaque=grupo_destaque,
                          grupo_destaque_total=grupo_destaque_total,
                          total_movimentacoes=total_movimentacoes,
                          taxa_devolucao=taxa_devolucao,
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
    
    query += " ORDER BY date(i.data_aquisicao) ASC"
    
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
    usa_grupo_id = emprestimos_tem_grupo_id(db)
    
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
            if usa_grupo_id:
                cursor.execute("""
                    INSERT INTO emprestimos (nome, grupo_id, contato, data_emprestimo, usuario_id) 
                    VALUES (?, ?, ?, ?, ?)
                """, (nome, grupo, contato, datetime.now(), current_user.id))
            else:
                grupo_row = db.execute("SELECT nome FROM grupos WHERE id = ?", (grupo,)).fetchone()
                grupo_nome = grupo_row["nome"] if grupo_row else grupo
                cursor.execute("""
                    INSERT INTO emprestimos (nome, grupo_caseiro, contato, data_emprestimo, usuario_id) 
                    VALUES (?, ?, ?, ?, ?)
                """, (nome, grupo_nome, contato, datetime.now(), current_user.id))
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
    grupo_select = emprestimos_grupo_select_sql(db)
    grupo_join = emprestimos_grupo_join_sql(db)

    emprestimos_ativos_raw = db.execute(f"""
        SELECT e.id as emprestimo_id, e.nome, {grupo_select} as grupo_caseiro, e.contato, e.data_emprestimo, 
               GROUP_CONCAT(i.tombamento || ' (' || ei.quantidade || 'x) - ' || i.descricao, ', ') as itens_desc
        FROM emprestimos e
        JOIN emprestimo_itens ei ON e.id = ei.emprestimo_id
        JOIN itens i ON ei.item_id = i.id
        {grupo_join}
        WHERE e.data_devolucao IS NULL
        GROUP BY e.id
        ORDER BY e.data_emprestimo DESC
    """).fetchall()
    
    emprestimos_devolvidos_raw = db.execute(f"""
        SELECT e.id as emprestimo_id, e.nome, {grupo_select} as grupo_caseiro, e.contato, e.data_emprestimo, e.data_devolucao,
               GROUP_CONCAT(i.tombamento || ' (' || ei.quantidade || 'x) - ' || i.descricao, ', ') as itens_desc
        FROM emprestimos e
        JOIN emprestimo_itens ei ON e.id = ei.emprestimo_id
        JOIN itens i ON ei.item_id = i.id
        {grupo_join}
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
    grupo_select = emprestimos_grupo_select_sql(db)
    grupo_join = emprestimos_grupo_join_sql(db)

    emprestimo_base = db.execute(f"""
        SELECT e.*, u.nome as usuario_nome, {grupo_select} as grupo_caseiro
        FROM emprestimos e 
        JOIN usuarios u ON e.usuario_id = u.id
        {grupo_join}
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
    grupo_select = emprestimos_grupo_select_sql(db)
    grupo_join = emprestimos_grupo_join_sql(db)
    
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
        where_clauses_itens.append("g.nome = ?")
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
        SELECT i.*, g.nome as grupo, m.nome as marca
        FROM itens i
        LEFT JOIN grupos g ON i.grupo_id = g.id
        LEFT JOIN marcas m ON i.marca_id = m.id
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

    # Consultar empréstimos (com itens agrupados)
    emprestimos = []
    if filtro_tipo in ["todos", "emprestimos"]:
        query_emprestimos = f"""
            SELECT e.id AS emprestimo_id,
                e.nome,
                {grupo_select} AS grupo_caseiro,
                e.contato,
                e.data_emprestimo,
                e.data_devolucao,
                GROUP_CONCAT(i.tombamento) AS tombamentos,
                GROUP_CONCAT(i.descricao) AS descricoes,
                GROUP_CONCAT(ei.quantidade) AS quantidades,
                GROUP_CONCAT(m.nome) AS marcas,
                GROUP_CONCAT(g.nome) AS grupos
            FROM emprestimos e
            JOIN emprestimo_itens ei ON e.id = ei.emprestimo_id
            JOIN itens i ON ei.item_id = i.id
            LEFT JOIN marcas m ON i.marca_id = m.id
            LEFT JOIN grupos g ON i.grupo_id = g.id
            {grupo_join}
            JOIN usuarios u ON e.usuario_id = u.id
        """
         # ✅ Adicione estas linhas AQUI
        if where_clauses_emprestimos:
            query_emprestimos += " WHERE " + " AND ".join(where_clauses_emprestimos)

        query_emprestimos += " GROUP BY e.id ORDER BY e.data_emprestimo DESC"

        # ✅ Agora execute a query
        emprestimos_raw = db.execute(query_emprestimos, params_emprestimos).fetchall()

        emprestimos = [{
            "emprestimo_id": e["emprestimo_id"],
            "nome": e["nome"],
            "grupo_caseiro": e["grupo_caseiro"],
            "contato": e["contato"],
            "data_emprestimo": e["data_emprestimo"],
            "data_devolucao": e["data_devolucao"],
            "tombamentos": e["tombamentos"].split(",") if e["tombamentos"] else [],
            "descricoes": e["descricoes"].split(",") if e["descricoes"] else [],
            "quantidades": e["quantidades"].split(",") if e["quantidades"] else [],
            "marcas": e["marcas"].split(",") if e["marcas"] else [],
            "grupos": e["grupos"].split(",") if e["grupos"] else [],
        } for e in emprestimos_raw]

    # Calcular total
    total_geral = sum(item['valor_unitario'] * item['quantidade'] for item in itens if item['valor_unitario'] is not None)
    total_geral_html = f"R$ {total_geral:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Carregar grupos disponíveis
# Carregar grupos disponíveis corretamente da tabela `grupos`
    grupos_disponiveis = [row['nome'] for row in db.execute("SELECT nome FROM grupos WHERE nome IS NOT NULL AND nome != '' ORDER BY nome").fetchall()]

    formato = request.args.get("formato", "")  # ✅ fora do render_template

    if formato == "pdf":
        return exportar_pdf(
            itens,
            emprestimos,
            filtro_tipo,
            filtro_grupo,
            filtro_data_inicio,
            filtro_data_fim
        )
    
    return render_template("relatorios_simples.html",
        itens=itens,
        emprestimos=emprestimos,
        filtro_tipo=filtro_tipo,
        filtro_data_inicio=filtro_data_inicio,
        filtro_data_fim=filtro_data_fim,
        filtro_busca=filtro_busca,
        filtro_grupo=filtro_grupo,
        grupos_disponiveis=grupos_disponiveis,
        total_geral_html=total_geral_html,
        format_date=format_date
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
    return render_template("usuarios_admin.html", usuarios=usuarios)

@app.route("/usuarios/ativar/<int:id>", methods=["POST"])
@login_required
@admin_required
def ativar_usuario(id):
    db = get_db()

    try:
        usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (id,)).fetchone()
        if not usuario:
            flash("Usuario nao encontrado.", "danger")
            return redirect(url_for("usuarios"))

        if int(usuario["ativo"]) == 1:
            flash("Este usuario ja esta ativo.", "info")
            return redirect(url_for("usuarios"))

        db.execute("UPDATE usuarios SET ativo = 1 WHERE id = ?", (id,))
        db.commit()
        enviado, erro = enviar_email_cadastro_aprovado(usuario["nome"], usuario["email"])
        if not enviado:
            print(f"[Email] Falha ao enviar aprovacao para {usuario['email']}: {erro}")
        registrar_log(f"Usuario aprovado: {usuario['nome']} ({usuario['usuario']})")
        flash("Usuario aprovado com sucesso.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao aprovar usuario: {str(e)}", "danger")

    return redirect(url_for("usuarios"))

@app.route("/usuarios/novo", methods=["GET", "POST"])
@app.route("/usuarios/novo/", methods=["GET", "POST"])
@login_required
@admin_required
def novo_usuario():
    if request.method == "POST":
        nome = request.form.get("nome")
        usuario = request.form.get("usuario")
        email = validar_email_informado(request.form.get("email"))
        senha = request.form.get("senha")
        tipo = request.form.get("tipo")
        pode_acessar_inventario = 1 if request.form.get("pode_acessar_inventario") == "1" else 0
        pode_editar_igreja = 1 if request.form.get("pode_editar_igreja") == "1" else 0
        
        if not nome or not usuario or not email or not senha:
            flash("Todos os campos sao obrigatorios.", "danger")
            return render_template("novo_usuario_simples.html")

        if not senha_atende_requisitos(senha):
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template("novo_usuario_simples.html")
        
        try:
            db = get_db()
            # Verificar se usuário ou e-mail já existem
            user_existente = db.execute(
                "SELECT * FROM usuarios WHERE lower(usuario) = lower(?) OR lower(coalesce(email, '')) = lower(?)",
                (usuario, email),
            ).fetchone()
            if user_existente:
                flash("Nome de usuario ou e-mail ja cadastrado.", "danger")
                return render_template("novo_usuario_simples.html")
            
            # Criar hash da senha
            senha_hash = generate_password_hash(senha)
            
            db.execute("""
                INSERT INTO usuarios (nome, usuario, email, senha_hash, tipo, ativo, criado_em, pode_acessar_inventario, pode_editar_igreja) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nome, usuario, email, senha_hash, tipo, 1, datetime.now(), pode_acessar_inventario, pode_editar_igreja))
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
        email = validar_email_informado(request.form.get("email"))
        senha = request.form.get("senha")
        tipo = request.form.get("tipo")
        pode_acessar_inventario = 1 if request.form.get("pode_acessar_inventario") == "1" else 0
        pode_editar_igreja = 1 if request.form.get("pode_editar_igreja") == "1" else 0
        
        if not nome or not usuario_login or not email:
            flash("Nome, usuario e e-mail sao obrigatorios.", "danger")
            return render_template("editar_usuario_simples.html", usuario=usuario)
        
        try:
            # Verificar se o novo nome de usuário ou e-mail já existem
            if usuario_login != usuario["usuario"] or normalizar_email(email) != normalizar_email(usuario["email"]):
                user_existente = db.execute(
                    """
                    SELECT * FROM usuarios
                    WHERE id != ? AND (lower(usuario) = lower(?) OR lower(coalesce(email, '')) = lower(?))
                    """,
                    (id, usuario_login, email),
                ).fetchone()
                if user_existente:
                    flash("Nome de usuario ou e-mail ja cadastrado.", "danger")
                    return render_template("editar_usuario_simples.html", usuario=usuario)
            
            # Atualizar usuário
            if senha:
                # Se senha foi fornecida, atualizar com nova senha
                senha_hash = generate_password_hash(senha)
                db.execute("""
                    UPDATE usuarios 
                    SET nome = ?, usuario = ?, email = ?, senha_hash = ?, tipo = ?, pode_acessar_inventario = ?, pode_editar_igreja = ? 
                    WHERE id = ?
                """, (nome, usuario_login, email, senha_hash, tipo, pode_acessar_inventario, pode_editar_igreja, id))
            else:
                # Se senha não foi fornecida, manter a senha atual
                db.execute("""
                    UPDATE usuarios 
                    SET nome = ?, usuario = ?, email = ?, tipo = ?, pode_acessar_inventario = ?, pode_editar_igreja = ? 
                    WHERE id = ?
                """, (nome, usuario_login, email, tipo, pode_acessar_inventario, pode_editar_igreja, id))
            
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
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    with app.app_context():
        db.create_all()

    migrar_usuarios_auth()
    conectacasa_criar_tabelas()
    igreja_criar_tabelas()

    conn = get_db()
    admin = conn.execute("SELECT * FROM usuarios WHERE usuario = 'admin'").fetchone()
    if not admin:
        senha_hash = generate_password_hash("admin123")
        conn.execute(
            """
            INSERT INTO usuarios (nome, usuario, email, senha_hash, tipo, ativo, criado_em, pode_acessar_inventario, pode_editar_igreja)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Administrador", "admin", "admin@sem-email.local", senha_hash, "admin", 1, datetime.now(), 1, 1),
        )
    else:
        conn.execute(
            """
            UPDATE usuarios
            SET pode_acessar_inventario = 1, pode_editar_igreja = 1
            WHERE usuario = 'admin'
            """
        )

    try:
        conn.execute("ALTER TABLE itens ADD COLUMN valor REAL")
        print("Coluna 'valor' adicionada a tabela 'itens'.")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
    
if __name__ == "__main__":
    # Criar banco de dados e tabelas se não existirem
    # A função create_tables agora também cria o admin e adiciona a coluna valor
    with app.app_context():
        create_tables()
    
    pass  # debug run removed for safety
