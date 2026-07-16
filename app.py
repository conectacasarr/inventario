from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, make_response, abort
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
import secrets
from urllib.parse import quote, urlparse, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
try:
    import fitz
except ImportError:
    fitz = None
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from collections import defaultdict
from reportlab.lib.enums import TA_RIGHT
import locale
from markupsafe import Markup, escape

load_dotenv()

GOOGLE_CONTACTS_SCOPES = [
    "https://www.googleapis.com/auth/contacts.readonly",
    "openid",
    "email",
    "profile",
]

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


def corrigir_mojibake_texto(valor):
    if valor is None:
        return ""
    texto = str(valor)
    for _ in range(2):
        if not any(marcador in texto for marcador in ("Ã", "Â", "â", "ðŸ")):
            break
        try:
            reparado = texto.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if reparado == texto:
            break
        texto = reparado
    return texto.replace("\u00a0", " ").strip()


PORTAL_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "h1",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "blockquote",
    "span",
    "div",
    "a",
    "img",
}
PORTAL_SELF_CLOSING_TAGS = {"br", "img"}
PORTAL_ALLOWED_ALIGNMENTS = {"left", "center", "right", "justify"}
PORTAL_ALLOWED_COLORS = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgb[a]?\([0-9,\s.%]+\)|hsl[a]?\([0-9,\s.%]+\)|[a-zA-Z]+)$")
PORTAL_ALLOWED_SIZE = re.compile(r"^[0-9]+(\.[0-9]+)?(px|em|rem|%)?$")
PORTAL_ALLOWED_RADIUS = re.compile(r"^[0-9]+(\.[0-9]+)?(px|%)$")
PORTAL_ALLOWED_SPACING = re.compile(r"^[0-9.\s%a-zA-Z-]+$")
PORTAL_ALLOWED_WEIGHT = re.compile(r"^(normal|bold|bolder|lighter|[1-9]00)$")
PORTAL_ALLOWED_DECORATION = re.compile(r"^(none|underline|line-through)$")
PORTAL_ALLOWED_FONT_STYLE = re.compile(r"^(normal|italic|oblique)$")
PORTAL_ALLOWED_DISPLAY = {"block", "inline", "inline-block"}


def rich_text_legado_para_html(valor):
    texto = escape((valor or "").strip())
    if not texto:
        return ""

    substituicoes = [
        (r"\[b\](.*?)\[/b\]", r"<strong>\1</strong>"),
        (r"\[i\](.*?)\[/i\]", r"<em>\1</em>"),
        (r"\[u\](.*?)\[/u\]", r"<u>\1</u>"),
        (r"\[h2\](.*?)\[/h2\]", r"<h2>\1</h2>"),
        (r"\[h3\](.*?)\[/h3\]", r"<h3>\1</h3>"),
    ]

    html = str(texto)
    for padrao, replacement in substituicoes:
        html = re.sub(padrao, replacement, html, flags=re.IGNORECASE | re.DOTALL)

    html = re.sub(
        r"\[color=(#[0-9a-fA-F]{3,8})\](.*?)\[/color\]",
        lambda m: f'<span style="color:{m.group(1)}">{m.group(2)}</span>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"\[link=(https?://[^\]]+)\](.*?)\[/link\]",
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer">{m.group(2)}</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html.replace("\r\n", "\n").replace("\n", "<br>")


def portal_url_segura(url, tipo="link"):
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("/") and not url.startswith("//"):
        return url

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return url
    if tipo == "link" and parsed.scheme in {"mailto", "tel"}:
        return url
    return None


def portal_style_sanitizado(style_value):
    if not style_value:
        return ""

    estilos_validos = []
    for item in style_value.split(";"):
        if ":" not in item:
            continue
        propriedade, valor = item.split(":", 1)
        propriedade = propriedade.strip().lower()
        valor = valor.strip()
        if not propriedade or not valor:
            continue

        if propriedade == "text-align" and valor.lower() in PORTAL_ALLOWED_ALIGNMENTS:
            estilos_validos.append(f"{propriedade}:{valor.lower()}")
        elif propriedade in {"color", "background-color"} and PORTAL_ALLOWED_COLORS.match(valor):
            estilos_validos.append(f"{propriedade}:{valor}")
        elif propriedade in {"font-size", "width", "max-width", "height", "line-height"} and PORTAL_ALLOWED_SIZE.match(valor):
            estilos_validos.append(f"{propriedade}:{valor}")
        elif propriedade == "border-radius" and PORTAL_ALLOWED_RADIUS.match(valor):
            estilos_validos.append(f"{propriedade}:{valor}")
        elif propriedade in {"margin", "margin-left", "margin-right"} and PORTAL_ALLOWED_SPACING.match(valor):
            estilos_validos.append(f"{propriedade}:{valor}")
        elif propriedade == "font-weight" and PORTAL_ALLOWED_WEIGHT.match(valor.lower()):
            estilos_validos.append(f"{propriedade}:{valor.lower()}")
        elif propriedade == "text-decoration" and PORTAL_ALLOWED_DECORATION.match(valor.lower()):
            estilos_validos.append(f"{propriedade}:{valor.lower()}")
        elif propriedade == "font-style" and PORTAL_ALLOWED_FONT_STYLE.match(valor.lower()):
            estilos_validos.append(f"{propriedade}:{valor.lower()}")
        elif propriedade == "display" and valor.lower() in PORTAL_ALLOWED_DISPLAY:
            estilos_validos.append(f"{propriedade}:{valor.lower()}")

    return "; ".join(estilos_validos)


class PortalHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in PORTAL_ALLOWED_TAGS:
            return
        attrs_html = self._build_attrs(tag, attrs)
        self.parts.append(f"<{tag}{attrs_html}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in PORTAL_ALLOWED_TAGS and tag not in PORTAL_SELF_CLOSING_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(str(escape(data)))

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def _build_attrs(self, tag, attrs):
        permitidos = []
        for nome, valor in attrs:
            nome = (nome or "").lower()
            valor = (valor or "").strip()
            if not nome or not valor:
                continue

            if nome == "style":
                style_limpo = portal_style_sanitizado(valor)
                if style_limpo:
                    permitidos.append(f'style="{escape(style_limpo)}"')
            elif tag == "a" and nome == "href":
                href = portal_url_segura(valor, tipo="link")
                if href:
                    permitidos.append(f'href="{escape(href)}"')
            elif tag == "a" and nome == "target":
                if valor.lower() == "_blank":
                    permitidos.append('target="_blank"')
            elif tag == "a" and nome == "rel":
                permitidos.append('rel="noopener noreferrer"')
            elif tag == "img" and nome == "src":
                src = portal_url_segura(valor, tipo="img")
                if src:
                    permitidos.append(f'src="{escape(src)}"')
            elif tag == "img" and nome in {"alt", "title"}:
                permitidos.append(f'{nome}="{escape(valor)}"')
        return f" {' '.join(permitidos)}" if permitidos else ""

    def get_html(self):
        return "".join(self.parts)


def sanitizar_html_portal(valor):
    html = (valor or "").strip()
    if not html:
        return ""
    parser = PortalHTMLSanitizer()
    parser.feed(html)
    parser.close()
    return parser.get_html().strip()


def rich_text_para_html(valor):
    bruto = (valor or "").strip()
    if not bruto:
        return Markup("")
    if "<" not in bruto or ">" not in bruto:
        bruto = rich_text_legado_para_html(bruto)
    return Markup(sanitizar_html_portal(bruto))


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
app.config["CONECTACASA_PUBLIC_HOST"] = os.environ.get("CONECTACASA_PUBLIC_HOST", "conectacasa.oaibv.com.br").strip().lower()
app.config["IGREJA_PUBLIC_HOST"] = os.environ.get("IGREJA_PUBLIC_HOST", "igrejaemboavista.oaibv.com.br").strip().lower()
app.config["PUBLIC_SIGNUP_ENABLED"] = os.environ.get("PUBLIC_SIGNUP_ENABLED", "false").strip().lower() == "true"

# Aqui pode adicionar a configuraÃ§Ã£o do SQLAlchemy, se ainda nÃ£o estiver
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
PROMO_UPLOAD_DIR = os.path.join(UPLOADS_DIR, "promos")
os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
os.makedirs(PIX_UPLOAD_DIR, exist_ok=True)
os.makedirs(PROMO_UPLOAD_DIR, exist_ok=True)

IGREJA_UPLOADS_DIR = os.path.join(PROJECT_DIR, "static", "uploads", "igreja")
IGREJA_DOCUMENTOS_UPLOAD_DIR = os.path.join(IGREJA_UPLOADS_DIR, "documentos")
IGREJA_CONTEUDO_UPLOAD_DIR = os.path.join(IGREJA_UPLOADS_DIR, "conteudo")
IGREJA_CAPAS_UPLOAD_DIR = os.path.join(IGREJA_UPLOADS_DIR, "capas")
os.makedirs(IGREJA_DOCUMENTOS_UPLOAD_DIR, exist_ok=True)
os.makedirs(IGREJA_CONTEUDO_UPLOAD_DIR, exist_ok=True)
os.makedirs(IGREJA_CAPAS_UPLOAD_DIR, exist_ok=True)

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


# FunÃ§Ã£o Formato brasileiro de moeada
def formata_brl(valor):
    if valor is None:
        return "-"
    s = "{:,.2f}".format(valor)  # Ex: "2,000.00"
    # Trocar vÃ­rgula e ponto para padrÃ£o BR
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


def adicionar_coluna_se_faltar(db_conn, tabela, coluna, definicao_sql):
    colunas = get_table_columns(db_conn, tabela)
    if coluna in colunas:
        return
    try:
        db_conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao_sql}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


def request_host_base():
    return (request.host or "").split(":")[0].strip().lower()


def host_eh_conectacasa(host=None):
    host = (host or request_host_base()).strip().lower()
    esperado = (app.config.get("CONECTACASA_PUBLIC_HOST") or "").strip().lower()
    return bool(esperado and host == esperado)


def host_eh_igreja(host=None):
    host = (host or request_host_base()).strip().lower()
    esperado = (app.config.get("IGREJA_PUBLIC_HOST") or "").strip().lower()
    return bool(esperado and host == esperado)


def url_no_host(host, caminho="/"):
    caminho = "/" if not caminho else f"/{str(caminho).lstrip('/')}"
    host_atual = request_host_base()
    if host and host_atual == host:
        return caminho
    esquema = request.headers.get("X-Forwarded-Proto", request.scheme or "https")
    return f"{esquema}://{host}{caminho}"


def conectacasa_path(caminho="/"):
    caminho = "/" if not caminho else f"/{str(caminho).lstrip('/')}"
    if host_eh_conectacasa():
        return caminho
    if caminho == "/":
        return "/conectacasa"
    return f"/conectacasa{caminho}"


def igreja_path(caminho="/"):
    caminho = "/" if not caminho else f"/{str(caminho).lstrip('/')}"
    if host_eh_igreja():
        return caminho
    if caminho == "/":
        return "/igrejaemboavista"
    return f"/igrejaemboavista{caminho}"


def conectacasa_request_permitida():
    return host_eh_conectacasa() or request.path.startswith("/conectacasa")


def igreja_request_permitida():
    return host_eh_igreja() or request.path.startswith("/igrejaemboavista")


def extrair_youtube_embed_url(url):
    url = (url or "").strip()
    if not url:
        return None
    padroes = [
        r"(?:youtube\.com/watch\?v=)([\w-]{11})",
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:youtube\.com/embed/)([\w-]{11})",
    ]
    for padrao in padroes:
        match = re.search(padrao, url)
        if match:
            return f"https://www.youtube.com/embed/{match.group(1)}"
    return None


def extrair_youtube_video_id(url):
    url = (url or "").strip()
    if not url:
        return None
    padroes = [
        r"(?:youtube\.com/watch\?v=)([\w-]{11})",
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:youtube\.com/embed/)([\w-]{11})",
        r"(?:youtube\.com/shorts/)([\w-]{11})",
    ]
    for padrao in padroes:
        match = re.search(padrao, url)
        if match:
            return match.group(1)
    return None


def igreja_normalizar_titulo_visivel(texto):
    if not texto:
        return ""
    ajustes = {
        "Historia": "História",
        "Historia da Igreja em Boa Vista": "História da Igreja em Boa Vista",
        "Principios Elementares": "Princípios Elementares",
        "Comuhão Com Deus": "Comunhão com Deus",
        "Apostila Familia": "Apostila Família",
        "Confissção de Pecados": "Confissão de Pecados",
    }
    texto_limpo = " ".join(str(texto).split())
    return ajustes.get(texto_limpo, texto_limpo)


def igreja_listar_pregacoes():
    caminho = os.path.join(PROJECT_DIR, "static", "data", "pregacoes.json")
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return []

    pregacoes = []
    for item in dados if isinstance(dados, list) else []:
        titulo = igreja_normalizar_titulo_visivel((item.get("titulo") or "").strip())
        youtube_url = (item.get("youtubeUrl") or item.get("youtube_url") or "").strip()
        if not titulo or not youtube_url:
            continue
        video_id = extrair_youtube_video_id(youtube_url)
        if not video_id:
            continue
        thumbnail = (item.get("thumbnail") or "").strip() or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        pregacoes.append(
            {
                "titulo": titulo,
                "youtube_url": youtube_url,
                "thumbnail": thumbnail,
                "data": (item.get("data") or "").strip(),
                "video_id": video_id,
            }
        )
    return pregacoes


def igreja_salvar_pregacoes(form):
    titulos = form.getlist("pregacao_titulo[]")
    urls = form.getlist("pregacao_url[]")
    datas = form.getlist("pregacao_data[]")

    pregacoes = []
    total_linhas = max(len(titulos), len(urls), len(datas))
    for indice in range(total_linhas):
        titulo = igreja_normalizar_titulo_visivel((titulos[indice] if indice < len(titulos) else "").strip())
        youtube_url = (urls[indice] if indice < len(urls) else "").strip()
        data = (datas[indice] if indice < len(datas) else "").strip()

        if not titulo and not youtube_url and not data:
            continue
        if not titulo or not youtube_url:
            return False, "Cada pregação precisa ter título e link do YouTube."

        video_id = extrair_youtube_video_id(youtube_url)
        if not video_id:
            return False, f"O link informado para '{titulo}' não é um vídeo válido do YouTube."

        pregacoes.append(
            {
                "titulo": titulo,
                "youtubeUrl": youtube_url,
                "data": data,
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            }
        )

    caminho = os.path.join(PROJECT_DIR, "static", "data", "pregacoes.json")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(pregacoes, arquivo, ensure_ascii=False, indent=2)
    return True, None


def igreja_salvar_textos_pregacoes(conn, form):
    conn.execute(
        """
        UPDATE igreja_config
        SET pregacoes_titulo = ?,
            pregacoes_subtitulo = ?,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            (form.get("pregacoes_titulo") or "").strip() or "Pregações",
            sanitizar_html_portal(form.get("pregacoes_subtitulo")),
        ),
    )
    conn.commit()


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
            cliente_id INTEGER,
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
            acrescimo_total REAL NOT NULL DEFAULT 0,
            acrescimo_noturno_pct REAL NOT NULL DEFAULT 0,
            acrescimo_final_semana_pct REAL NOT NULL DEFAULT 0,
            acrescimo_feriado_pct REAL NOT NULL DEFAULT 0,
            acrescimo_dificil_pct REAL NOT NULL DEFAULT 0,
            acrescimo_emergencia_pct REAL NOT NULL DEFAULT 0,
            valor_total REAL NOT NULL DEFAULT 0,
            itens_json TEXT NOT NULL,
            criado_por INTEGER,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES conectacasa_clientes(id),
            FOREIGN KEY (criado_por) REFERENCES usuarios(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conectacasa_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone_whatsapp TEXT,
            email TEXT,
            cpf_cnpj TEXT,
            endereco TEXT,
            bairro TEXT,
            cidade TEXT,
            estado TEXT,
            cep TEXT,
            observacoes TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conectacasa_orcamento_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER NOT NULL,
            servico_id INTEGER,
            descricao TEXT NOT NULL,
            unidade TEXT NOT NULL,
            quantidade REAL NOT NULL DEFAULT 0,
            valor_unitario REAL NOT NULL DEFAULT 0,
            percentual_acrescimo REAL NOT NULL DEFAULT 0,
            valor_acrescimo REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            observacao TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (orcamento_id) REFERENCES conectacasa_orcamentos(id),
            FOREIGN KEY (servico_id) REFERENCES servicos_orcamento(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS servicos_orcamento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            subcategoria TEXT,
            servico TEXT NOT NULL,
            descricao TEXT,
            unidade TEXT NOT NULL,
            regiao TEXT NOT NULL,
            valor_minimo REAL,
            valor_maximo REAL,
            valor_sugerido REAL,
            material_incluso INTEGER NOT NULL DEFAULT 0,
            observacao TEXT,
            fonte TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            preco_sob_consulta INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conectacasa_promos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descricao TEXT,
            mensagem_whatsapp TEXT,
            imagem_path TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "acesso_usuario", "TEXT NOT NULL DEFAULT 'admin'")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "acesso_senha_hash", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "pix_imagem_path", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_total", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_noturno_pct", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_final_semana_pct", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_feriado_pct", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_dificil_pct", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "acrescimo_emergencia_pct", "REAL NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "cliente_id", "INTEGER")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "data_orcamento", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "validade_orcamento", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "forma_pagamento", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "prazo_execucao", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "garantia", "TEXT")
    adicionar_coluna_se_faltar(conn, "servicos_orcamento", "preco_sob_consulta", "INTEGER NOT NULL DEFAULT 0")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "audio_path", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "audio_transcricao", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_orcamentos", "audio_observacoes", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "telefone_whatsapp", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "cpf_cnpj", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "endereco", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "bairro", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "cidade", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "estado", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "cep", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_clientes", "telefone", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "nome_responsavel", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "telefone_empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "email_empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "endereco_empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "cidade_empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "estado_empresa", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "cnpj_cpf", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "mensagem_padrao_whatsapp", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "observacao_padrao_orcamento", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "garantia_padrao", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "validade_padrao_orcamento", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "forma_pagamento_padrao", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_client_id", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_client_secret", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_contacts_token_json", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_contacts_connected_email", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_contacts_connected_name", "TEXT")
    adicionar_coluna_se_faltar(conn, "conectacasa_config", "google_contacts_sync_at", "TEXT")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_servicos_orcamento_unique
        ON servicos_orcamento (categoria, COALESCE(subcategoria, ''), servico, regiao)
        """
    )
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
    conectacasa_seed_servicos_orcamento(conn)
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
    config["google_contacts_connected"] = bool(config.get("google_contacts_token_json"))
    return config


def conectacasa_google_redirect_uri():
    host_publico = (app.config.get("CONECTACASA_PUBLIC_HOST") or "").strip()
    if host_publico:
        return f"https://{host_publico}{conectacasa_path('/clientes/google/callback')}"
    return f"{request.host_url.rstrip('/')}{conectacasa_path('/clientes/google/callback')}"


def conectacasa_google_oauth_disponivel():
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google.auth.transport.requests import Request as GoogleRequest  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
        return True
    except ImportError:
        return False


def conectacasa_google_validar_client_config(config):
    client_id = (config.get("google_client_id") or "").strip()
    client_secret = (config.get("google_client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Informe o Client ID e o Client Secret do Google nas configuracoes da ConectaCasa.")
    return client_id, client_secret


def conectacasa_google_authorization_url(config, state):
    client_id, _ = conectacasa_google_validar_client_config(config)
    params = {
        "client_id": client_id,
        "redirect_uri": conectacasa_google_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_CONTACTS_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def conectacasa_google_trocar_code_por_token(config, code):
    client_id, client_secret = conectacasa_google_validar_client_config(config)
    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": conectacasa_google_redirect_uri(),
        }
    ).encode("utf-8")
    request_token = Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request_token, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        resposta = exc.read().decode("utf-8", errors="replace")
        try:
            dados = json.loads(resposta)
        except json.JSONDecodeError:
            raise RuntimeError("Falha ao trocar o codigo do Google por token.") from exc
        descricao = dados.get("error_description") or dados.get("error") or "Falha na autenticacao com o Google."
        raise RuntimeError(descricao) from exc
    except URLError as exc:
        raise RuntimeError("Nao foi possivel conectar ao Google para concluir a autenticacao.") from exc


def conectacasa_google_obter_credentials(config):
    token_json = config.get("google_contacts_token_json") or ""
    if not token_json:
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
    except ImportError:
        return None

    try:
        cred_data = json.loads(token_json)
    except json.JSONDecodeError:
        return None

    creds = Credentials.from_authorized_user_info(cred_data, GOOGLE_CONTACTS_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
    return creds


def conectacasa_google_salvar_credentials(conn, creds, perfil=None):
    perfil = perfil or {}
    cred_json = creds.to_json()
    conn.execute(
        """
        UPDATE conectacasa_config
        SET google_contacts_token_json = ?, google_contacts_connected_email = ?, google_contacts_connected_name = ?,
            google_contacts_sync_at = CURRENT_TIMESTAMP, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            cred_json,
            (perfil.get("email") or "").strip(),
            (perfil.get("name") or "").strip(),
        ),
    )
    conn.commit()


def conectacasa_google_limpar_conexao(conn):
    conn.execute(
        """
        UPDATE conectacasa_config
        SET google_contacts_token_json = NULL, google_contacts_connected_email = NULL,
            google_contacts_connected_name = NULL, google_contacts_sync_at = NULL, atualizado_em = CURRENT_TIMESTAMP
        WHERE id = 1
        """
    )
    conn.commit()


def conectacasa_google_obter_perfil(service):
    perfil = {"name": "", "email": ""}
    try:
        dados = service.people().get(resourceName="people/me", personFields="names,emailAddresses").execute()
        nomes = dados.get("names") or []
        emails = dados.get("emailAddresses") or []
        if nomes:
            perfil["name"] = (nomes[0].get("displayName") or "").strip()
        if emails:
            perfil["email"] = (emails[0].get("value") or "").strip().lower()
    except Exception:
        pass
    return perfil


def conectacasa_google_listar_contatos(config):
    if not conectacasa_google_oauth_disponivel():
        raise RuntimeError("As dependencias do Google Contacts nao estao instaladas no servidor.")

    from googleapiclient.discovery import build

    creds = conectacasa_google_obter_credentials(config)
    if not creds or not creds.valid:
        raise RuntimeError("A conexao com o Google expirou. Reconecte a conta para importar os contatos.")

    service = build("people", "v1", credentials=creds, cache_discovery=False)
    contatos = []
    page_token = None

    while True:
        resposta = service.people().connections().list(
            resourceName="people/me",
            pageSize=500,
            pageToken=page_token,
            personFields="names,emailAddresses,phoneNumbers,organizations,addresses",
            sortOrder="LAST_MODIFIED_ASCENDING",
        ).execute()
        for person in resposta.get("connections", []):
            nomes = person.get("names") or []
            telefones = person.get("phoneNumbers") or []
            if not nomes or not telefones:
                continue

            nome = (nomes[0].get("displayName") or "").strip()
            telefone_bruto = (telefones[0].get("value") or "").strip()
            telefone = conectacasa_normalizar_telefone(telefone_bruto)
            if not nome or not telefone:
                continue

            emails = person.get("emailAddresses") or []
            orgs = person.get("organizations") or []
            enderecos = person.get("addresses") or []
            endereco = enderecos[0] if enderecos else {}

            contatos.append(
                {
                    "nome": nome,
                    "telefone_whatsapp": telefone,
                    "email": ((emails[0].get("value") or "").strip().lower() if emails else ""),
                    "empresa": ((orgs[0].get("name") or "").strip() if orgs else ""),
                    "endereco": (endereco.get("streetAddress") or "").strip(),
                    "bairro": (endereco.get("extendedAddress") or "").strip(),
                    "cidade": (endereco.get("city") or "").strip(),
                    "estado": (endereco.get("region") or "").strip(),
                    "cep": conectacasa_normalizar_telefone(endereco.get("postalCode")),
                    "observacoes": "Importado do Google Contacts",
                    "ativo": 1,
                }
            )

        page_token = resposta.get("nextPageToken")
        if not page_token:
            break

    return contatos, service, creds


def conectacasa_google_importar_clientes(conn, config):
    contatos, service, creds = conectacasa_google_listar_contatos(config)
    perfil = conectacasa_google_obter_perfil(service)
    conectacasa_google_salvar_credentials(conn, creds, perfil=perfil)

    resumo = {"importados": 0, "atualizados": 0, "ignorados": 0}
    for contato in contatos:
        telefone = contato["telefone_whatsapp"]
        email = contato["email"]
        existente = None
        if telefone:
            existente = conn.execute(
                "SELECT id FROM conectacasa_clientes WHERE COALESCE(telefone_whatsapp, telefone) = ? ORDER BY id DESC LIMIT 1",
                (telefone,),
            ).fetchone()
        if not existente and email:
            existente = conn.execute(
                "SELECT id FROM conectacasa_clientes WHERE email = ? ORDER BY id DESC LIMIT 1",
                (email,),
            ).fetchone()

        if existente:
            conn.execute(
                """
                UPDATE conectacasa_clientes
                SET nome = ?, empresa = COALESCE(NULLIF(?, ''), empresa), telefone_whatsapp = ?, telefone = ?,
                    email = COALESCE(NULLIF(?, ''), email), endereco = COALESCE(NULLIF(?, ''), endereco),
                    bairro = COALESCE(NULLIF(?, ''), bairro), cidade = COALESCE(NULLIF(?, ''), cidade),
                    estado = COALESCE(NULLIF(?, ''), estado), cep = COALESCE(NULLIF(?, ''), cep),
                    observacoes = CASE WHEN COALESCE(observacoes, '') = '' THEN ? ELSE observacoes END,
                    ativo = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    contato["nome"],
                    contato["empresa"],
                    telefone,
                    telefone,
                    email,
                    contato["endereco"],
                    contato["bairro"],
                    contato["cidade"],
                    contato["estado"],
                    contato["cep"],
                    contato["observacoes"],
                    existente["id"],
                ),
            )
            resumo["atualizados"] += 1
        else:
            conn.execute(
                """
                INSERT INTO conectacasa_clientes (
                    nome, empresa, telefone_whatsapp, telefone, email, endereco, bairro, cidade, estado, cep, observacoes, ativo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    contato["nome"],
                    contato["empresa"],
                    telefone,
                    telefone,
                    email,
                    contato["endereco"],
                    contato["bairro"],
                    contato["cidade"],
                    contato["estado"],
                    contato["cep"],
                    contato["observacoes"],
                ),
            )
            resumo["importados"] += 1

    conn.execute("UPDATE conectacasa_config SET google_contacts_sync_at = CURRENT_TIMESTAMP WHERE id = 1")
    conn.commit()
    return resumo


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
            historia_titulo TEXT,
            historia_texto TEXT,
            historia_videos TEXT,
            apostilas_titulo TEXT,
            pregacoes_titulo TEXT,
            pregacoes_subtitulo TEXT,
            ensinos_titulo TEXT,
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
        CREATE TABLE IF NOT EXISTS igreja_materiais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            titulo TEXT NOT NULL,
            descricao TEXT,
            arquivo_path TEXT,
            capa_path TEXT,
            link_url TEXT,
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    adicionar_coluna_se_faltar(conn, "igreja_materiais", "capa_path", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "historia_titulo", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "historia_texto", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "historia_videos", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "apostilas_titulo", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "pregacoes_titulo", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "pregacoes_subtitulo", "TEXT")
    adicionar_coluna_se_faltar(conn, "igreja_config", "ensinos_titulo", "TEXT")
    conn.execute(
        """
        INSERT INTO igreja_config (
            id, nome_site, hero_titulo, hero_subtitulo, mensagem_boas_vindas,
            agenda_titulo, agenda_texto, historia_titulo, historia_texto, historia_videos,
            apostilas_titulo, pregacoes_titulo, pregacoes_subtitulo, ensinos_titulo, youtube_url, instagram_url, pix_cnpj, pix_texto
        )
        SELECT
            1,
            'Igreja em Boa Vista',
            'Igreja em Boa Vista',
            'Avisos, programacao e canais oficiais da igreja em um so lugar.',
            'Acompanhe os avisos da igreja, nossos canais oficiais e a area de contribuicao.',
            'Agenda e horarios',
            'Atualize aqui os horarios de cultos, reunioes e eventos da semana.',
            'Historia da Igreja em Boa Vista',
            'Conte aqui a historia da igreja, os marcos importantes e os testemunhos que fazem parte dessa caminhada.',
            'https://www.youtube.com/watch?v=lVhH5Tjmc5Y
https://www.youtube.com/watch?v=bHlavUfkEZg',
            'Apostilas',
            'Pregações',
            '',
            'Ensinos',
            'https://www.youtube.com/@igrejaemboavista',
            'https://www.instagram.com/igrejaemboavista?igsh=MWR1aXR6NzNuNm1kNw%3D%3D',
            '09.148.629/0001-58',
            'Sua contribuicao ajuda a manter os trabalhos e projetos da igreja.'
        WHERE NOT EXISTS (SELECT 1 FROM igreja_config WHERE id = 1)
        """
    )
    conn.execute(
        """
        UPDATE igreja_config
        SET historia_titulo = COALESCE(NULLIF(historia_titulo, ''), 'Historia da Igreja em Boa Vista'),
            historia_videos = COALESCE(NULLIF(historia_videos, ''), 'https://www.youtube.com/watch?v=lVhH5Tjmc5Y
https://www.youtube.com/watch?v=bHlavUfkEZg'),
            apostilas_titulo = COALESCE(NULLIF(apostilas_titulo, ''), 'Apostilas'),
            pregacoes_titulo = COALESCE(NULLIF(pregacoes_titulo, ''), 'Pregações'),
            pregacoes_subtitulo = COALESCE(pregacoes_subtitulo, ''),
            ensinos_titulo = COALESCE(NULLIF(ensinos_titulo, ''), 'Ensinos')
        WHERE id = 1
        """
    )
    conn.commit()
    conn.close()


def igreja_obter_config(conn):
    config = conn.execute("SELECT * FROM igreja_config WHERE id = 1").fetchone()
    if not config:
        return {}
    config = dict(config)
    config["historia_titulo_visivel"] = igreja_normalizar_titulo_visivel(config.get("historia_titulo") or "Historia da Igreja em Boa Vista")
    config["apostilas_titulo_visivel"] = igreja_normalizar_titulo_visivel(config.get("apostilas_titulo") or "Apostilas")
    config["pregacoes_titulo_visivel"] = igreja_normalizar_titulo_visivel(config.get("pregacoes_titulo") or "Pregações")
    videos = []
    for linha in (config.get("historia_videos") or "").splitlines():
        url = linha.strip()
        if not url:
            continue
        embed_url = extrair_youtube_embed_url(url)
        if embed_url:
            videos.append({"url": url, "embed_url": embed_url})
    config["historia_videos_lista"] = videos
    return config


def igreja_listar_avisos(conn, somente_ativos=False):
    query = "SELECT * FROM igreja_avisos"
    params = []
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY ordem ASC, atualizado_em DESC, id DESC"
    return [dict(item) for item in conn.execute(query, params).fetchall()]


def igreja_preparar_material(material):
    material = dict(material)
    material["titulo_visivel"] = igreja_normalizar_titulo_visivel(material.get("titulo"))
    material["arquivo_url"] = url_for("static", filename=material["arquivo_path"]) if material.get("arquivo_path") else None
    material["capa_url"] = url_for("static", filename=material["capa_path"]) if material.get("capa_path") else None
    return material


def igreja_remover_arquivo_relativo(arquivo_relativo):
    if not arquivo_relativo:
        return
    caminho_arquivo = os.path.join(PROJECT_DIR, "static", arquivo_relativo.replace("/", os.sep))
    if os.path.exists(caminho_arquivo):
        try:
            os.remove(caminho_arquivo)
        except OSError:
            pass


def igreja_listar_materiais(conn, categoria=None, somente_ativos=False):
    query = "SELECT * FROM igreja_materiais"
    params = []
    filtros = []
    if categoria:
        filtros.append("categoria = ?")
        params.append(categoria)
    if somente_ativos:
        filtros.append("ativo = 1")
    if filtros:
        query += " WHERE " + " AND ".join(filtros)
    query += " ORDER BY ordem ASC, atualizado_em DESC, id DESC"
    materiais = []
    for item in conn.execute(query, params).fetchall():
        item_dict = dict(item)
        if item_dict.get("arquivo_path") and not item_dict.get("capa_path"):
            capa_path, _ = igreja_gerar_capa_pdf(item_dict["arquivo_path"])
            if capa_path:
                conn.execute("UPDATE igreja_materiais SET capa_path = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?", (capa_path, item_dict["id"]))
                conn.commit()
                item_dict["capa_path"] = capa_path
        materiais.append(igreja_preparar_material(item_dict))
    return materiais


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
            historia_titulo = ?,
            historia_texto = ?,
            historia_videos = ?,
            apostilas_titulo = ?,
            ensinos_titulo = ?,
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
            sanitizar_html_portal(form.get("hero_subtitulo")),
            sanitizar_html_portal(form.get("mensagem_boas_vindas")),
            (form.get("agenda_titulo") or "").strip() or "Agenda e horarios",
            (form.get("agenda_texto") or "").strip(),
            (form.get("historia_titulo") or "").strip() or "Historia da Igreja em Boa Vista",
            sanitizar_html_portal(form.get("historia_texto")),
            (form.get("historia_videos") or "").strip(),
            (form.get("apostilas_titulo") or "").strip() or "Apostilas",
            (form.get("ensinos_titulo") or "").strip() or "Ensinos",
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


def igreja_salvar_documento_pdf(arquivo):
    if not arquivo or not arquivo.filename:
        return None, None
    nome_base = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_base)[1].lower()
    if extensao != ".pdf":
        return None, "Envie um arquivo PDF valido."
    nome_arquivo = f"igreja-{datetime.now().strftime('%Y%m%d%H%M%S%f')}{extensao}"
    caminho_completo = os.path.join(IGREJA_DOCUMENTOS_UPLOAD_DIR, nome_arquivo)
    arquivo.save(caminho_completo)
    return f"uploads/igreja/documentos/{nome_arquivo}", None


def igreja_gerar_capa_pdf(arquivo_relativo):
    if not arquivo_relativo or fitz is None:
        return None, None

    caminho_pdf = os.path.join(PROJECT_DIR, "static", arquivo_relativo.replace("/", os.sep))
    if not os.path.exists(caminho_pdf):
        return None, None

    try:
        with fitz.open(caminho_pdf) as pdf:
            if pdf.page_count < 1:
                return None, None
            pagina = pdf.load_page(0)
            pix = pagina.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            nome_base = os.path.splitext(os.path.basename(arquivo_relativo))[0]
            nome_capa = f"{nome_base}-capa.jpg"
            caminho_capa = os.path.join(IGREJA_CAPAS_UPLOAD_DIR, nome_capa)
            pix.save(caminho_capa, "jpeg")
            return f"uploads/igreja/capas/{nome_capa}", None
    except Exception as e:
        return None, str(e)


def igreja_salvar_imagem_conteudo(arquivo):
    if not arquivo or not arquivo.filename:
        return None, "Selecione uma imagem valida."
    nome_base = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_base)[1].lower()
    if extensao not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None, "Envie uma imagem PNG, JPG, WEBP ou GIF."
    nome_arquivo = f"igreja-conteudo-{datetime.now().strftime('%Y%m%d%H%M%S%f')}{extensao}"
    caminho_completo = os.path.join(IGREJA_CONTEUDO_UPLOAD_DIR, nome_arquivo)
    arquivo.save(caminho_completo)
    return url_for("static", filename=f"uploads/igreja/conteudo/{nome_arquivo}"), None


def igreja_salvar_material(conn, form, arquivo=None, material_id=None):
    categoria = (form.get("categoria") or "").strip().lower()
    titulo = (form.get("titulo") or "").strip()
    descricao = sanitizar_html_portal(form.get("descricao"))
    link_url = (form.get("link_url") or "").strip()
    try:
        ordem = int(form.get("ordem") or 0)
    except ValueError:
        ordem = 0
    ativo = 1 if form.get("ativo") == "1" else 0

    if categoria not in {"apostila", "ensino"}:
        return False, "Escolha uma categoria valida para o material."
    if not titulo:
        return False, "Informe um titulo para o material."

    arquivo_path = None
    capa_path = None
    capa_antiga = None
    if material_id:
        existente = conn.execute("SELECT * FROM igreja_materiais WHERE id = ?", (material_id,)).fetchone()
        if not existente:
            return False, "Material nao encontrado."
        arquivo_path = existente["arquivo_path"]
        capa_path = existente["capa_path"] if "capa_path" in existente.keys() else None
        capa_antiga = capa_path

    novo_arquivo_path, erro_upload = igreja_salvar_documento_pdf(arquivo)
    if erro_upload:
        return False, erro_upload
    if novo_arquivo_path:
        arquivo_path = novo_arquivo_path
        nova_capa_path, _ = igreja_gerar_capa_pdf(novo_arquivo_path)
        if nova_capa_path:
            capa_path = nova_capa_path

    if not arquivo_path and not link_url:
        return False, "Envie um PDF ou informe um link para o material."

    if material_id:
        conn.execute(
            """
            UPDATE igreja_materiais
            SET categoria = ?, titulo = ?, descricao = ?, arquivo_path = ?, capa_path = ?, link_url = ?, ordem = ?, ativo = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (categoria, titulo, descricao, arquivo_path, capa_path, link_url, ordem, ativo, material_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO igreja_materiais (categoria, titulo, descricao, arquivo_path, capa_path, link_url, ordem, ativo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (categoria, titulo, descricao, arquivo_path, capa_path, link_url, ordem, ativo),
        )
    conn.commit()
    if material_id and capa_antiga and capa_antiga != capa_path:
        igreja_remover_arquivo_relativo(capa_antiga)
    return True, None


def igreja_excluir_material(conn, material_id):
    material = conn.execute("SELECT * FROM igreja_materiais WHERE id = ?", (material_id,)).fetchone()
    if not material:
        return False
    conn.execute("DELETE FROM igreja_materiais WHERE id = ?", (material_id,))
    conn.commit()
    igreja_remover_arquivo_relativo(material["arquivo_path"])
    if "capa_path" in material.keys():
        igreja_remover_arquivo_relativo(material["capa_path"])
    return True


def conectacasa_autenticado():
    return bool(session.get("conectacasa_auth"))


def conectacasa_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not conectacasa_request_permitida():
            abort(404)
        if conectacasa_autenticado():
            return func(*args, **kwargs)
        return redirect(f"{conectacasa_path('/entrar')}?next={quote(request.path)}")

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


def conectacasa_salvar_promo_imagem(arquivo):
    return conectacasa_salvar_upload_imagem(arquivo, PROMO_UPLOAD_DIR, "promo", "uploads/conectacasa/promos")


def conectacasa_preparar_promo(item):
    item = dict(item)
    item["imagem_url"] = url_for("static", filename=item["imagem_path"]) if item.get("imagem_path") else None
    item["mensagem_whatsapp"] = (
        item.get("mensagem_whatsapp")
        or f"Olá! Segue um material da {item.get('titulo') or 'ConectaCasa'} para você."
    )
    return item


def conectacasa_listar_promos(conn, somente_ativos=False):
    query = "SELECT * FROM conectacasa_promos"
    params = []
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY ordem ASC, atualizado_em DESC, id DESC"
    registros = conn.execute(query, params).fetchall()
    return [conectacasa_preparar_promo(item) for item in registros]


def conectacasa_fontes_catalogo():
    return {
        "guia": "Tabela de Preço - Guia do Eletricista 2026..pdf",
        "led": "Tabela de Preços ILUMINAÇÃO de Led.pdf",
    }


def conectacasa_unidades_servico():
    return [
        "diaria",
        "unidade",
        "metro",
        "ponto",
        "empreita",
        "servico",
        "projeto",
    ]


def conectacasa_categorias_servico():
    return [
        "Eletrica",
        "Iluminacao e LED",
        "Mao de obra",
        "Instalacao eletrica",
        "Manutencao eletrica",
        "Infraestrutura eletrica",
        "Quadros eletricos",
        "Empreita eletrica",
        "Automacao",
        "Outros",
    ]


def conectacasa_catalogo_servicos_inicial():
    fontes = conectacasa_fontes_catalogo()
    norte_ref = "Valores da coluna Regiao Norte; mao de obra sem materiais, salvo observacao em contrario."
    led_ref = "Valor nacional usado como referencia."
    return [
        {"categoria": "Diarias", "subcategoria": "Eletricista", "servico": "Eletricista experiente", "descricao": "Diaria do eletricista experiente.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 240.0, "valor_maximo": 395.0, "valor_sugerido": 395.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Diarias", "subcategoria": "Eletricista", "servico": "Eletricista intermediario", "descricao": "Diaria do eletricista intermediario.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 220.0, "valor_maximo": 340.0, "valor_sugerido": 340.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Diarias", "subcategoria": "Eletricista", "servico": "Eletricista meio oficial", "descricao": "Diaria do eletricista meio oficial.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 155.0, "valor_maximo": 250.0, "valor_sugerido": 250.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Diarias", "subcategoria": "Ajudante", "servico": "Ajudante experiente", "descricao": "Diaria do ajudante experiente.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 135.0, "valor_maximo": 240.0, "valor_sugerido": 240.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Diarias", "subcategoria": "Ajudante", "servico": "Ajudante intermediario", "descricao": "Diaria do ajudante intermediario.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 115.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Diarias", "subcategoria": "Ajudante", "servico": "Ajudante iniciante", "descricao": "Diaria do ajudante iniciante.", "unidade": "diaria", "regiao": "Norte", "valor_minimo": 95.0, "valor_maximo": 180.0, "valor_sugerido": 180.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Casa terrea popular ate 70 m2", "descricao": "Valor por ponto para instalacao eletrica basica.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 85.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": "Cobre tubulacao, fiacao, conexoes e testes. Materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Casa padrao medio 70 a 150 m2", "descricao": "Instalacao completa por ponto.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 105.0, "valor_maximo": 165.0, "valor_sugerido": 165.0, "material_incluso": 0, "observacao": "Inclui distribuicao de circuitos e montagem de QDC de 12 a 24 disjuntores.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Sobrado 150 a 250 m2", "descricao": "Instalacao completa de dois pavimentos por ponto.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 145.0, "valor_maximo": 210.0, "valor_sugerido": 210.0, "material_incluso": 0, "observacao": "Necessario projeto eletrico.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Residencia de alto padrao acima de 250 m2", "descricao": "Infraestrutura e distribuicao por ponto.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 200.0, "valor_maximo": 310.0, "valor_sugerido": 310.0, "material_incluso": 0, "observacao": "Pode variar conforme automacao e cabeamento estruturado.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Kitnet ou estudio ate 40 m2", "descricao": "Instalacao simples com ate 10 pontos.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 75.0, "valor_maximo": 110.0, "valor_sugerido": 110.0, "material_incluso": 0, "observacao": "Ideal para obras rapidas e padrao economico.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacoes por tipo de imovel", "subcategoria": "Residencial", "servico": "Area externa garagem varanda", "descricao": "Pontos de iluminacao e tomadas externas.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 65.0, "valor_maximo": 95.0, "valor_sugerido": 95.0, "material_incluso": 0, "observacao": "Varia conforme protecao IP65/IP67.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Edificios e condominios", "subcategoria": "Predial", "servico": "Apartamento pequeno ate 60 m2", "descricao": "Instalacao simples e QDC ate 24 disjuntores.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 95.0, "valor_maximo": 140.0, "valor_sugerido": 140.0, "material_incluso": 0, "observacao": "Avaliar pontos complexos para precificacao.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Edificios e condominios", "subcategoria": "Predial", "servico": "Apartamento medio 60 a 120 m2", "descricao": "Instalacao eletrica completa por ponto.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 130.0, "valor_maximo": 190.0, "valor_sugerido": 190.0, "material_incluso": 0, "observacao": "Materiais e mao de obra em areas comuns podem ser cobrados a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Edificios e condominios", "subcategoria": "Predial", "servico": "Apartamento grande acima de 120 m2", "descricao": "Instalacao de alta complexidade.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 185.0, "valor_maximo": 280.0, "valor_sugerido": 280.0, "material_incluso": 0, "observacao": "Requer projeto e laudo eletrico conforme NBR 5410.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Edificios e condominios", "subcategoria": "Predial", "servico": "Areas comuns de condominio", "descricao": "Iluminacao de garagem, halls, portarias, interfones e quadros.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 70.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": "Pode incluir eletrocalhas e caixas de passagem.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Estabelecimentos comerciais", "subcategoria": "Comercial", "servico": "Loja de pequeno porte ate 60 m2", "descricao": "Instalacao com ate 20 pontos e quadro de 12 disjuntores.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 120.0, "valor_maximo": 180.0, "valor_sugerido": 180.0, "material_incluso": 0, "observacao": "Inclui tomadas, iluminacao e circuito de ar-condicionado.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Estabelecimentos comerciais", "subcategoria": "Comercial", "servico": "Loja media 60 a 150 m2", "descricao": "Instalacao completa de iluminacao, tomadas e cargas especificas.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 160.0, "valor_maximo": 240.0, "valor_sugerido": 240.0, "material_incluso": 0, "observacao": "Lojas de shopping podem receber acrescimo de 35% no valor total.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Estabelecimentos comerciais", "subcategoria": "Comercial", "servico": "Restaurante bar lanchonete", "descricao": "Instalacao com circuitos de equipamentos de alta carga.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 200.0, "valor_maximo": 290.0, "valor_sugerido": 290.0, "material_incluso": 0, "observacao": "Atentar as normas aplicaveis ao tipo de estabelecimento.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Estabelecimentos comerciais", "subcategoria": "Comercial", "servico": "Escritorios e consultorios", "descricao": "Pontos de informatica e iluminacao comercial.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 130.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": "Atentar as normas ABNT NBR aplicaveis.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Instalacao geral por empreita", "subcategoria": "Casa medio padrao", "servico": "Casa 4 comodos", "descricao": "Empreita completa para casa de 4 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 2750.0, "valor_maximo": 3950.0, "valor_sugerido": 3950.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Casa medio padrao", "servico": "Casa 5 comodos", "descricao": "Empreita completa para casa de 5 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 3150.0, "valor_maximo": 4450.0, "valor_sugerido": 4450.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Casa medio padrao", "servico": "Casa 6 comodos", "descricao": "Empreita completa para casa de 6 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 3650.0, "valor_maximo": 5350.0, "valor_sugerido": 5350.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Sobrado", "servico": "Sobrado 5 comodos", "descricao": "Empreita completa para sobrado de 5 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 2650.0, "valor_maximo": 4550.0, "valor_sugerido": 4550.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Sobrado", "servico": "Sobrado 6 comodos", "descricao": "Empreita completa para sobrado de 6 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 4100.0, "valor_maximo": 6000.0, "valor_sugerido": 6000.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Sobrado", "servico": "Sobrado 7 comodos", "descricao": "Empreita completa para sobrado de 7 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 4650.0, "valor_maximo": 6650.0, "valor_sugerido": 6650.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Instalacao geral por empreita", "subcategoria": "Sobrado", "servico": "Sobrado 8 comodos", "descricao": "Empreita completa para sobrado de 8 comodos.", "unidade": "empreita", "regiao": "Norte", "valor_minimo": 5050.0, "valor_maximo": 7150.0, "valor_sugerido": 7150.0, "material_incluso": 0, "observacao": "Preco fechado por resultado entregue.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 16 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 520.0, "valor_maximo": 870.0, "valor_sugerido": 870.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 24 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 820.0, "valor_maximo": 1250.0, "valor_sugerido": 1250.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 32 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 1050.0, "valor_maximo": 1550.0, "valor_sugerido": 1550.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 48 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 1350.0, "valor_maximo": 2000.0, "valor_sugerido": 2000.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 50 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 1550.0, "valor_maximo": 2200.0, "valor_sugerido": 2200.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Quadros eletricos", "subcategoria": "QDC", "servico": "Quadro eletrico 72 disjuntores", "descricao": "Montagem e instalacao de quadro eletrico.", "unidade": "quadro", "regiao": "Norte", "valor_minimo": 2100.0, "valor_maximo": 2800.0, "valor_sugerido": 2800.0, "material_incluso": 0, "observacao": "DPS e IDR obrigatorios; materiais a parte.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Infraestrutura por metro", "subcategoria": "Infraestrutura", "servico": "Eletroduto galvanizado", "descricao": "Instalacao por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 24.0, "valor_maximo": 48.0, "valor_sugerido": 48.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Infraestrutura por metro", "subcategoria": "Infraestrutura", "servico": "Calha perfurada", "descricao": "Instalacao por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 25.0, "valor_maximo": 95.0, "valor_sugerido": 95.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Infraestrutura por metro", "subcategoria": "Infraestrutura", "servico": "Eletroduto corrugado", "descricao": "Instalacao por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 18.0, "valor_maximo": 38.0, "valor_sugerido": 38.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Infraestrutura por metro", "subcategoria": "Infraestrutura", "servico": "Passagem de cabo em calha", "descricao": "Passagem de cabo por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 14.0, "valor_maximo": 32.0, "valor_sugerido": 32.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Caixas e passagem", "subcategoria": "Caixas", "servico": "Caixa 4x2 instalacao", "descricao": "Instalacao de caixa 4x2.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 10.0, "valor_maximo": 25.0, "valor_sugerido": 25.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Caixas e passagem", "subcategoria": "Caixas", "servico": "Caixa 4x4 instalacao", "descricao": "Instalacao de caixa 4x4.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 20.0, "valor_maximo": 50.0, "valor_sugerido": 50.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Caixas e passagem", "subcategoria": "Caixas", "servico": "Caixa de passagem embutir", "descricao": "Instalacao de caixa de passagem.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 18.0, "valor_maximo": 55.0, "valor_sugerido": 55.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Manutencao", "servico": "Troca dos condutores do chuveiro", "descricao": "Substituicao dos condutores do chuveiro.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 80.0, "valor_maximo": 145.0, "valor_sugerido": 145.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Manutencao", "servico": "Troca de disjuntor simples", "descricao": "Troca de disjuntor simples.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 32.0, "valor_maximo": 55.0, "valor_sugerido": 55.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Protecao", "servico": "Instalacao de disjuntor DR", "descricao": "Instalacao de disjuntor DR.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 52.0, "valor_maximo": 95.0, "valor_sugerido": 95.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Tomadas e interruptores", "servico": "Instalacao de ponto de tomada", "descricao": "Instalacao de ponto de tomada.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 48.0, "valor_maximo": 85.0, "valor_sugerido": 85.0, "material_incluso": 0, "observacao": "Ligacao ao circuito existente proximo.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Tomadas e interruptores", "servico": "Instalacao de tomada 220V", "descricao": "Instalacao de tomada 220V.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 62.0, "valor_maximo": 115.0, "valor_sugerido": 115.0, "material_incluso": 0, "observacao": "Nao inclui novo circuito dedicado.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Tomadas e interruptores", "servico": "Instalacao de interruptor simples", "descricao": "Instalacao de interruptor simples.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 25.0, "valor_maximo": 48.0, "valor_sugerido": 48.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Tomadas e interruptores", "servico": "Instalacao de interruptor paralelo", "descricao": "Instalacao de interruptor paralelo.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 52.0, "valor_maximo": 78.0, "valor_sugerido": 78.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Instalacao de ponto de iluminacao", "descricao": "Instalacao de ponto de iluminacao.", "unidade": "ponto", "regiao": "Norte", "valor_minimo": 42.0, "valor_maximo": 75.0, "valor_sugerido": 75.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Troca de chuveiro eletrico", "descricao": "Troca de chuveiro eletrico.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 80.0, "valor_maximo": 145.0, "valor_sugerido": 145.0, "material_incluso": 0, "observacao": "Nao inclui adequacao de circuito.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Instalacao de luminaria de teto", "descricao": "Instalacao de luminaria de teto.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 65.0, "valor_maximo": 125.0, "valor_sugerido": 125.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "LED", "servico": "Instalacao de perfil de LED embutido", "descricao": "Instalacao de perfil de LED embutido por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 65.0, "valor_maximo": 125.0, "valor_sugerido": 125.0, "material_incluso": 0, "observacao": "Acabamento e embutimento nao inclusos.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Instalacao de ventilador de teto", "descricao": "Instalacao de ventilador de teto.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 100.0, "valor_maximo": 190.0, "valor_sugerido": 190.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Manutencao", "servico": "Reparo de curto-circuito", "descricao": "Diagnostico e reparo de curto-circuito.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 80.0, "valor_maximo": 135.0, "valor_sugerido": 135.0, "material_incluso": 0, "observacao": "Pode variar conforme necessidade de rastreamento.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Instalacao de arandela de parede", "descricao": "Instalacao de arandela de parede.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 40.0, "valor_maximo": 75.0, "valor_sugerido": 75.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Automacao", "servico": "Instalacao de campainha eletrica", "descricao": "Instalacao de campainha eletrica.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 52.0, "valor_maximo": 95.0, "valor_sugerido": 95.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Automacao", "servico": "Instalacao de sensor de presenca", "descricao": "Instalacao de sensor de presenca.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 80.0, "valor_maximo": 145.0, "valor_sugerido": 145.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Climatizacao", "servico": "Instalacao de fiacao para ar-condicionado", "descricao": "Instalacao de fiacao para ar-condicionado.", "unidade": "servico", "regiao": "Norte", "valor_minimo": 195.0, "valor_maximo": 370.0, "valor_sugerido": 370.0, "material_incluso": 0, "observacao": "Nao inclui material e novo circuito no quadro.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Automacao", "servico": "Instalacao de dimmer", "descricao": "Instalacao de dimmer para controle de intensidade.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 55.0, "valor_maximo": 95.0, "valor_sugerido": 95.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Tomadas e interruptores", "servico": "Instalacao de tomada USB", "descricao": "Instalacao de tomada USB.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 42.0, "valor_maximo": 75.0, "valor_sugerido": 75.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Infraestrutura", "servico": "Passagem de conduite em parede", "descricao": "Passagem de conduite em parede por metro.", "unidade": "metro", "regiao": "Norte", "valor_minimo": 15.0, "valor_maximo": 25.0, "valor_sugerido": 25.0, "material_incluso": 0, "observacao": "Nao inclui conduites e acabamento civil.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Iluminacao", "servico": "Troca de lampada de LED", "descricao": "Troca de lampada de LED por unidade.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 12.0, "valor_maximo": 20.0, "valor_sugerido": 20.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Servicos de instalacao e manutencao eletrica", "subcategoria": "Automacao", "servico": "Instalacao de interruptor remoto Wi-Fi", "descricao": "Instalacao de interruptor remoto Wi-Fi.", "unidade": "unidade", "regiao": "Norte", "valor_minimo": 80.0, "valor_maximo": 140.0, "valor_sugerido": 140.0, "material_incluso": 0, "observacao": norte_ref, "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Acrescimos e observacoes tecnicas", "subcategoria": "Percentuais", "servico": "Trabalho noturno", "descricao": "Acrescimo percentual sobre o valor base.", "unidade": "percentual", "regiao": "Norte", "valor_minimo": 25.0, "valor_maximo": 30.0, "valor_sugerido": 25.0, "material_incluso": 0, "observacao": "Aplicar sobre o valor base do servico.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Acrescimos e observacoes tecnicas", "subcategoria": "Percentuais", "servico": "Final de semana", "descricao": "Acrescimo percentual sobre o valor base.", "unidade": "percentual", "regiao": "Norte", "valor_minimo": 30.0, "valor_maximo": 50.0, "valor_sugerido": 30.0, "material_incluso": 0, "observacao": "Aplicar conforme urgencia.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Acrescimos e observacoes tecnicas", "subcategoria": "Percentuais", "servico": "Feriado", "descricao": "Acrescimo percentual sobre o valor base.", "unidade": "percentual", "regiao": "Norte", "valor_minimo": 50.0, "valor_maximo": 50.0, "valor_sugerido": 50.0, "material_incluso": 0, "observacao": "Aplicar sobre o valor base do servico.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Acrescimos e observacoes tecnicas", "subcategoria": "Percentuais", "servico": "Dificil acesso altura ou risco", "descricao": "Acrescimo percentual sobre o valor base.", "unidade": "percentual", "regiao": "Norte", "valor_minimo": 15.0, "valor_maximo": 40.0, "valor_sugerido": 15.0, "material_incluso": 0, "observacao": "Aplicar conforme complexidade.", "fonte": fontes["guia"], "preco_sob_consulta": 0},
        {"categoria": "Acrescimos e observacoes tecnicas", "subcategoria": "Percentuais", "servico": "Emergencia", "descricao": "Acrescimo percentual sobre o valor base.", "unidade": "percentual", "regiao": "Norte", "valor_minimo": 25.0, "valor_maximo": 100.0, "valor_sugerido": 25.0, "material_incluso": 0, "observacao": "Aplicar conforme urgencia e disponibilidade.", "fonte": fontes["guia"], "preco_sob_consulta": 0},

        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Lampada simples com soquete", "descricao": "Instalacao de lampada com soquete simples no teto.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 50.0, "valor_maximo": 80.0, "valor_sugerido": 80.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Plafon pequeno ate 30 cm", "descricao": "Instalacao de plafon simples ou embutido.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 100.0, "valor_sugerido": 100.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Plafon grande ou LED integrado", "descricao": "Instalacao de plafons grandes com conectores de LED integrado.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Spot de embutir por unidade", "descricao": "Instalacao de spots em teto de gesso ou drywall.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 30.0, "valor_maximo": 50.0, "valor_sugerido": 50.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Kit de spots 3 a 5 unidades", "descricao": "Instalacao de kits em sequencia.", "unidade": "kit", "regiao": "Nacional", "valor_minimo": 120.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Pendente simples", "descricao": "Instalacao de pendente decorativo de pequeno porte.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 90.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Pendente grande ou multiplo", "descricao": "Instalacao de pendentes maiores ou com varias lampadas.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 150.0, "valor_maximo": 250.0, "valor_sugerido": 250.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Lustre pequeno ou medio", "descricao": "Instalacao de lustres de ate 10kg com ligacao simples.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 150.0, "valor_maximo": 250.0, "valor_sugerido": 250.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Lustre grande ou de cristais", "descricao": "Instalacao de lustres grandes ou complexos.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 300.0, "valor_maximo": 600.0, "valor_sugerido": 600.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Arandela de parede", "descricao": "Instalacao de arandelas decorativas.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Balizadores", "descricao": "Instalacao de balizadores embutidos ou fixados em parede.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Fita de LED por metro", "descricao": "Instalacao de fita LED simples com fonte de alimentacao.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 40.0, "valor_maximo": 70.0, "valor_sugerido": 70.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Perfil de LED com difusor por metro", "descricao": "Instalacao em perfis de aluminio para acabamento decorativo.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 100.0, "valor_sugerido": 100.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Ventilador de teto com iluminacao", "descricao": "Instalacao completa com ajustes e fixacao.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 150.0, "valor_maximo": 300.0, "valor_sugerido": 300.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Iluminacao", "servico": "Ajuste de ponto eletrico", "descricao": "Alteracao ou criacao de ponto eletrico para iluminacao.", "unidade": "ponto", "regiao": "Nacional", "valor_minimo": 80.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Automacao", "servico": "Sensor de presenca para iluminacao", "descricao": "Instalacao de sensor integrado em luminaria ou circuito.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Decorativa", "servico": "Iluminacao no frame", "descricao": "Instalacao de lampadas ou fitas LED em molduras decorativas.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 150.0, "valor_maximo": 300.0, "valor_sugerido": 300.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Decorativa", "servico": "Iluminacao em nicho ou sanca de gesso", "descricao": "Instalacao de iluminacao indireta em sancas ou nichos.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Decorativa", "servico": "Iluminacao de quadro foco", "descricao": "Instalacao de focos direcionados para quadros ou obras de arte.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 80.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Decorativa", "servico": "Iluminacao de jardim", "descricao": "Instalacao de spots ou fitas LED em jardins ou areas externas.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 250.0, "valor_sugerido": 250.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Fita de LED RGB por metro", "descricao": "Instalacao de fita RGB com fonte e controlador.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 60.0, "valor_maximo": 90.0, "valor_sugerido": 90.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Perfil de aluminio por metro", "descricao": "Instalacao com difusores e fixacao em sancas, nichos ou paredes.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 100.0, "valor_sugerido": 100.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Perfil com fita LED RGB por metro", "descricao": "Instalacao com montagem de perfis e controle RGB.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Fita de LED com sensor de movimento", "descricao": "Instalacao em escadas, armarios ou corredores com sensor.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 80.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Fonte para fita de LED", "descricao": "Instalacao e configuracao de fontes compativeis.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 50.0, "valor_maximo": 80.0, "valor_sugerido": 80.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Controlador simples para fita LED", "descricao": "Configuracao de controlador basico para fita LED.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 70.0, "valor_maximo": 120.0, "valor_sugerido": 120.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Controlador inteligente Wi-Fi ou Bluetooth", "descricao": "Instalacao e configuracao de controladores compativeis com apps.", "unidade": "unidade", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 150.0, "valor_sugerido": 150.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Programacao de LED sequencial simples", "descricao": "Configuracao basica de efeitos sequenciais.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 150.0, "valor_maximo": 250.0, "valor_sugerido": 250.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Programacao de LED avancada por metro", "descricao": "Configuracao de efeitos personalizados complexos.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 300.0, "valor_maximo": 600.0, "valor_sugerido": 600.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Fita LED enderecavel WS2812 ou similar", "descricao": "Instalacao e programacao de LEDs enderecaveis com controladores dedicados.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 400.0, "valor_maximo": 800.0, "valor_sugerido": 800.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Substituicao de fita LED por metro", "descricao": "Retirada de fita antiga e substituicao por nova.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 30.0, "valor_maximo": 50.0, "valor_sugerido": 50.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "LED", "servico": "Instalacao em sancas ou nichos por metro", "descricao": "Fixacao de fitas em locais embutidos com acabamento decorativo.", "unidade": "metro", "regiao": "Nacional", "valor_minimo": 50.0, "valor_maximo": 80.0, "valor_sugerido": 80.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Automacao", "servico": "Integracao com automacao residencial", "descricao": "Configuracao de fitas e controladores com Alexa, Google e similares.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 200.0, "valor_maximo": 500.0, "valor_sugerido": 500.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Manutencao", "servico": "Manutencao de sistemas LED", "descricao": "Diagnostico e reparo de fitas, fontes ou controladores.", "unidade": "servico", "regiao": "Nacional", "valor_minimo": 100.0, "valor_maximo": 200.0, "valor_sugerido": 200.0, "material_incluso": 0, "observacao": led_ref, "fonte": fontes["led"], "preco_sob_consulta": 0},
        {"categoria": "Iluminacao e LED", "subcategoria": "Projetos", "servico": "Projeto decorativo de iluminacao LED", "descricao": "Consultoria, planejamento e execucao de iluminacao com fita LED.", "unidade": "projeto", "regiao": "Nacional", "valor_minimo": None, "valor_maximo": None, "valor_sugerido": None, "material_incluso": 0, "observacao": "Sob consulta. " + led_ref, "fonte": fontes["led"], "preco_sob_consulta": 1},
    ]


def conectacasa_seed_servicos_orcamento(conn):
    for item in conectacasa_catalogo_servicos_inicial():
        existente = conn.execute(
            """
            SELECT id FROM servicos_orcamento
            WHERE categoria = ? AND COALESCE(subcategoria, '') = COALESCE(?, '') AND servico = ? AND regiao = ?
            """,
            (item["categoria"], item.get("subcategoria"), item["servico"], item["regiao"]),
        ).fetchone()
        valores = (
            item["categoria"],
            item.get("subcategoria"),
            item["servico"],
            item.get("descricao"),
            item["unidade"],
            item["regiao"],
            item.get("valor_minimo"),
            item.get("valor_maximo"),
            item.get("valor_sugerido"),
            item.get("material_incluso", 0),
            item.get("observacao"),
            item.get("fonte"),
            item.get("ativo", 1),
            item.get("preco_sob_consulta", 0),
        )
        if existente:
            conn.execute(
                """
                UPDATE servicos_orcamento
                SET categoria = ?, subcategoria = ?, servico = ?, descricao = ?, unidade = ?, regiao = ?,
                    valor_minimo = ?, valor_maximo = ?, valor_sugerido = ?, material_incluso = ?,
                    observacao = ?, fonte = ?, ativo = ?, preco_sob_consulta = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                valores + (existente["id"],),
            )
        else:
            conn.execute(
                """
                INSERT INTO servicos_orcamento (
                    categoria, subcategoria, servico, descricao, unidade, regiao, valor_minimo, valor_maximo,
                    valor_sugerido, material_incluso, observacao, fonte, ativo, preco_sob_consulta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                valores,
            )


def conectacasa_obter_servico_orcamento(conn, servico_id):
    servico = conn.execute("SELECT * FROM servicos_orcamento WHERE id = ?", (servico_id,)).fetchone()
    return dict(servico) if servico else None


def conectacasa_listar_servicos_orcamento(
    conn,
    categoria=None,
    subcategoria=None,
    unidade=None,
    regiao=None,
    ativo=None,
    busca=None,
):
    query = "SELECT * FROM servicos_orcamento WHERE 1 = 1"
    params = []
    if ativo is not None:
        query += " AND ativo = ?"
        params.append(1 if ativo else 0)
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    if subcategoria:
        query += " AND COALESCE(subcategoria, '') = ?"
        params.append(subcategoria)
    if unidade:
        query += " AND unidade = ?"
        params.append(unidade)
    if regiao:
        query += " AND regiao = ?"
        params.append(regiao)
    if busca:
        termo = f"%{busca.strip()}%"
        query += """
            AND (
                servico LIKE ? OR
                categoria LIKE ? OR
                COALESCE(subcategoria, '') LIKE ? OR
                COALESCE(descricao, '') LIKE ? OR
                unidade LIKE ? OR
                regiao LIKE ?
            )
        """
        params.extend([termo, termo, termo, termo, termo, termo])
    query += " ORDER BY ativo DESC, categoria, subcategoria, servico"
    return [dict(item) for item in conn.execute(query, params).fetchall()]


def conectacasa_salvar_servico_orcamento(conn, form, servico_id=None):
    categoria = (form.get("categoria") or "").strip()
    subcategoria = (form.get("subcategoria") or "").strip()
    servico = (form.get("servico") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    unidade = (form.get("unidade") or "").strip() or "unidade"
    regiao = (form.get("regiao") or "").strip() or "Norte"
    observacao = (form.get("observacao") or "").strip()
    fonte = (form.get("fonte") or "").strip() or "Cadastro manual ConectaCasa"
    ativo = 1 if form.get("ativo") == "1" else 0
    material_incluso = 1 if form.get("material_incluso") == "1" else 0
    preco_sob_consulta = 1 if form.get("preco_sob_consulta") == "1" else 0

    if not categoria:
        return False, "Informe a categoria do servico."
    if not servico:
        return False, "Informe o nome do servico."
    if not unidade:
        return False, "Informe a unidade do servico."

    def parse_valor(chave):
        valor = (form.get(chave) or "").strip()
        if not valor:
            return None
        try:
            return float(valor.replace(",", "."))
        except ValueError:
            return None

    valor_minimo = parse_valor("valor_minimo")
    valor_maximo = parse_valor("valor_maximo")
    valor_sugerido = parse_valor("valor_sugerido")

    if preco_sob_consulta:
        valor_minimo = None
        valor_maximo = None
        valor_sugerido = None
    else:
        if valor_sugerido is None and valor_maximo is not None:
            valor_sugerido = valor_maximo
        if valor_sugerido is None:
            return False, "Informe o valor sugerido ou marque como preco sob consulta."
        if valor_minimo is not None and valor_maximo is not None and valor_minimo > valor_maximo:
            return False, "O valor minimo nao pode ser maior que o valor maximo."

    valores = (
        categoria,
        subcategoria or None,
        servico,
        descricao,
        unidade,
        regiao,
        valor_minimo,
        valor_maximo,
        valor_sugerido,
        material_incluso,
        observacao,
        fonte,
        ativo,
        preco_sob_consulta,
    )

    if servico_id:
        conn.execute(
            """
            UPDATE servicos_orcamento
            SET categoria = ?, subcategoria = ?, servico = ?, descricao = ?, unidade = ?, regiao = ?,
                valor_minimo = ?, valor_maximo = ?, valor_sugerido = ?, material_incluso = ?,
                observacao = ?, fonte = ?, ativo = ?, preco_sob_consulta = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            valores + (servico_id,),
        )
    else:
        conn.execute(
            """
            INSERT INTO servicos_orcamento (
                categoria, subcategoria, servico, descricao, unidade, regiao,
                valor_minimo, valor_maximo, valor_sugerido, material_incluso,
                observacao, fonte, ativo, preco_sob_consulta, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            valores,
        )
    conn.commit()
    return True, None


def conectacasa_servico_em_uso(conn, servico_id):
    registros = conn.execute("SELECT itens_json FROM conectacasa_orcamentos").fetchall()
    for registro in registros:
        try:
            itens = json.loads(registro["itens_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        for item in itens:
            if int(item.get("servico_base_id") or 0) == int(servico_id):
                return True
    return False


def conectacasa_percentual_float(valor):
    try:
        return float(str(valor or "0").replace(",", "."))
    except ValueError:
        return 0.0


def conectacasa_normalizar_telefone(telefone):
    numeros = re.sub(r"\D+", "", telefone or "")
    return numeros


def conectacasa_whatsapp_url(telefone, mensagem=""):
    numeros = conectacasa_normalizar_telefone(telefone)
    if numeros and not numeros.startswith("55") and len(numeros) >= 10:
        numeros = f"55{numeros}"
    base = f"https://wa.me/{numeros}" if numeros else "https://wa.me/"
    if mensagem:
        return f"{base}?text={quote(mensagem)}"
    return base


def conectacasa_mensagem_whatsapp_orcamento(orcamento, config=None):
    nome = (orcamento.get("cliente_nome") or "cliente").strip()
    config = config or {}
    template_personalizado = (config.get("mensagem_padrao_whatsapp") or "").strip()
    numero = orcamento.get("codigo") or "-"
    data_orcamento = orcamento.get("data_orcamento") or datetime.now().strftime("%d/%m/%Y")
    validade = orcamento.get("validade_orcamento") or config.get("validade_padrao_orcamento") or "-"
    forma_pagamento = orcamento.get("forma_pagamento") or config.get("forma_pagamento_padrao") or "-"
    prazo_execucao = orcamento.get("prazo_execucao") or "-"
    garantia = orcamento.get("garantia") or config.get("garantia_padrao") or "-"
    observacoes = orcamento.get("observacoes") or config.get("observacao_padrao_orcamento") or "-"
    empresa = config.get("empresa_nome") or "ConectaCasa"
    itens = orcamento.get("itens") or []
    itens_texto = "\n".join(
        f"- {item.get('quantidade', 0)}x {item.get('descricao', '')} — {formata_brl(item.get('total', 0))}"
        for item in itens
    ) or "- Sem itens cadastrados"
    if template_personalizado:
        return template_personalizado.format(
            nome_cliente=nome,
            numero_orcamento=numero,
            data_orcamento=data_orcamento,
            validade_orcamento=validade,
            lista_de_itens=itens_texto,
            subtotal=formata_brl(orcamento.get("subtotal", 0)),
            desconto=formata_brl(orcamento.get("desconto", 0)),
            acrescimo=formata_brl(orcamento.get("acrescimo_total", 0)),
            valor_total=formata_brl(orcamento.get("valor_total", 0)),
            forma_pagamento=forma_pagamento,
            prazo_execucao=prazo_execucao,
            garantia=garantia,
            observacoes_gerais=observacoes,
            nome_empresa=empresa,
        )
    return (
        f"Olá, {nome}! Tudo bem?\n\n"
        "Segue o orçamento solicitado:\n\n"
        f"Orçamento nº {numero}\n"
        f"Data: {data_orcamento}\n"
        f"Validade: {validade}\n\n"
        "Serviços:\n"
        f"{itens_texto}\n\n"
        f"Subtotal: {formata_brl(orcamento.get('subtotal', 0))}\n"
        f"Desconto: {formata_brl(orcamento.get('desconto', 0))}\n"
        f"Acréscimo: {formata_brl(orcamento.get('acrescimo_total', 0))}\n"
        f"Total: {formata_brl(orcamento.get('valor_total', 0))}\n\n"
        f"Forma de pagamento: {forma_pagamento}\n"
        f"Prazo de execução: {prazo_execucao}\n"
        f"Garantia: {garantia}\n\n"
        "Observações:\n"
        f"{observacoes}\n\n"
        "Fico à disposição para qualquer dúvida.\n\n"
        f"Atenciosamente,\n{empresa}"
    )


def conectacasa_listar_clientes(conn, busca=None, ativo=None):
    query = "SELECT * FROM conectacasa_clientes WHERE 1 = 1"
    params = []
    if ativo is not None:
        query += " AND ativo = ?"
        params.append(1 if ativo else 0)
    if busca:
        termo = f"%{busca.strip()}%"
        query += """
            AND (
                nome LIKE ? OR
                COALESCE(empresa, '') LIKE ? OR
                COALESCE(email, '') LIKE ? OR
                COALESCE(telefone_whatsapp, COALESCE(telefone, '')) LIKE ? OR
                COALESCE(cpf_cnpj, '') LIKE ? OR
                COALESCE(observacoes, '') LIKE ?
            )
        """
        params.extend([termo, termo, termo, termo, termo, termo])
    query += " ORDER BY ativo DESC, nome, empresa"
    return [dict(item) for item in conn.execute(query, params).fetchall()]


def conectacasa_obter_cliente(conn, cliente_id):
    cliente = conn.execute("SELECT * FROM conectacasa_clientes WHERE id = ?", (cliente_id,)).fetchone()
    return dict(cliente) if cliente else None


def conectacasa_salvar_cliente(conn, form, cliente_id=None):
    nome = (form.get("nome") or "").strip()
    empresa = (form.get("empresa") or "").strip()
    email = normalizar_email(form.get("email"))
    telefone = conectacasa_normalizar_telefone(form.get("telefone_whatsapp") or form.get("telefone"))
    cpf_cnpj = conectacasa_normalizar_telefone(form.get("cpf_cnpj"))
    endereco = (form.get("endereco") or "").strip()
    bairro = (form.get("bairro") or "").strip()
    cidade = (form.get("cidade") or "").strip()
    estado = (form.get("estado") or "").strip()
    cep = conectacasa_normalizar_telefone(form.get("cep"))
    observacoes = (form.get("observacoes") or "").strip()
    ativo = 1 if form.get("ativo") == "1" else 0

    if not nome:
        return False, "Informe o nome do cliente."
    if not telefone:
        return False, "Informe o WhatsApp do cliente."

    if cliente_id:
        conn.execute(
            """
            UPDATE conectacasa_clientes
            SET nome = ?, empresa = ?, email = ?, telefone_whatsapp = ?, telefone = ?, cpf_cnpj = ?, endereco = ?, bairro = ?,
                cidade = ?, estado = ?, cep = ?, observacoes = ?, ativo = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                nome,
                empresa or None,
                email,
                telefone,
                telefone,
                cpf_cnpj or None,
                endereco or None,
                bairro or None,
                cidade or None,
                estado or None,
                cep or None,
                observacoes or None,
                ativo,
                cliente_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO conectacasa_clientes (
                nome, empresa, email, telefone_whatsapp, telefone, cpf_cnpj, endereco, bairro, cidade, estado, cep, observacoes, ativo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome,
                empresa or None,
                email,
                telefone,
                telefone,
                cpf_cnpj or None,
                endereco or None,
                bairro or None,
                cidade or None,
                estado or None,
                cep or None,
                observacoes or None,
                ativo,
            ),
        )
        cliente_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.commit()
    return True, cliente_id


def conectacasa_sincronizar_cliente_orcamento(conn, dados_formulario):
    cliente_id_raw = (dados_formulario.get("cliente_id") or "").strip()
    nome = (dados_formulario.get("cliente_nome") or "").strip()
    empresa = (dados_formulario.get("cliente_empresa") or "").strip()
    email = normalizar_email(dados_formulario.get("cliente_email"))
    telefone = conectacasa_normalizar_telefone(dados_formulario.get("cliente_telefone"))
    endereco = (dados_formulario.get("cliente_endereco") or "").strip()
    cidade = (dados_formulario.get("cliente_cidade") or "").strip()
    estado = (dados_formulario.get("cliente_estado") or "").strip()
    observacoes = (dados_formulario.get("cliente_observacoes") or "").strip()

    if not nome:
        return None

    if cliente_id_raw.isdigit():
        cliente_id = int(cliente_id_raw)
        existente = conectacasa_obter_cliente(conn, cliente_id)
        if existente:
            conn.execute(
                """
                UPDATE conectacasa_clientes
                SET nome = ?, empresa = ?, email = ?, telefone_whatsapp = ?, telefone = ?, endereco = ?, cidade = ?, estado = ?,
                    observacoes = ?, ativo = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (nome, empresa or None, email, telefone or None, telefone or None, endereco or None, cidade or None, estado or None, observacoes or None, cliente_id),
            )
            conn.commit()
            return cliente_id

    cliente = None
    if telefone:
        cliente = conn.execute(
            "SELECT id FROM conectacasa_clientes WHERE COALESCE(telefone_whatsapp, telefone) = ? ORDER BY id DESC LIMIT 1",
            (telefone,),
        ).fetchone()
    if not cliente and email:
        cliente = conn.execute(
            "SELECT id FROM conectacasa_clientes WHERE email = ? ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
    if not cliente:
        cliente = conn.execute(
            "SELECT id FROM conectacasa_clientes WHERE nome = ? AND COALESCE(empresa, '') = COALESCE(?, '') ORDER BY id DESC LIMIT 1",
            (nome, empresa or None),
        ).fetchone()

    if cliente:
        cliente_id = cliente["id"]
        conn.execute(
            """
            UPDATE conectacasa_clientes
            SET nome = ?, empresa = ?, email = ?, telefone_whatsapp = ?, telefone = ?, endereco = ?, cidade = ?, estado = ?,
                observacoes = ?, ativo = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nome, empresa or None, email, telefone or None, telefone or None, endereco or None, cidade or None, estado or None, observacoes or None, cliente_id),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO conectacasa_clientes (nome, empresa, email, telefone_whatsapp, telefone, endereco, cidade, estado, observacoes, ativo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (nome, empresa or None, email, telefone or None, telefone or None, endereco or None, cidade or None, estado or None, observacoes or None),
        )
        cliente_id = cursor.lastrowid
    conn.commit()
    return cliente_id


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
        ("rascunho", "Rascunho"),
        ("enviado", "Enviado"),
        ("aprovado", "Aprovado"),
        ("recusado", "Recusado"),
        ("cancelado", "Cancelado"),
    ]


def conectacasa_status_normalizado(status):
    status = (status or "").strip().lower()
    mapa_legado = {
        "orcamento": "rascunho",
        "aceito": "aprovado",
        "finalizado": "aprovado",
        "rejeitado": "recusado",
    }
    return mapa_legado.get(status, status or "rascunho")


def conectacasa_status_label(status):
    mapa = dict(conectacasa_status_opcoes())
    status = conectacasa_status_normalizado(status)
    return mapa.get(status, status.title() if status else "Orcamento")


def conectacasa_sincronizar_itens_orcamento(conn, orcamento_id, itens):
    conn.execute("DELETE FROM conectacasa_orcamento_itens WHERE orcamento_id = ?", (orcamento_id,))
    for item in itens:
        subtotal = float(item.get("subtotal") or 0)
        total = float(item.get("total") or 0)
        percentual = float(item.get("acrescimo_pct") or 0)
        valor_acrescimo = round(total - subtotal, 2)
        conn.execute(
            """
            INSERT INTO conectacasa_orcamento_itens (
                orcamento_id, servico_id, descricao, unidade, quantidade, valor_unitario,
                percentual_acrescimo, valor_acrescimo, subtotal, total, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                orcamento_id,
                item.get("servico_base_id"),
                item.get("descricao"),
                item.get("unidade"),
                item.get("quantidade"),
                item.get("valor_unitario"),
                percentual,
                valor_acrescimo,
                subtotal,
                total,
                item.get("observacao") or item.get("acrescimo_motivo"),
            ),
        )


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


def conectacasa_normalizar_item(
    descricao,
    quantidade,
    valor_unitario,
    unidade,
    observacao=None,
    acrescimo_pct=None,
    acrescimo_motivo=None,
    servico_base_id=None,
):
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

    try:
        acrescimo_pct = float((acrescimo_pct or "0").replace(",", "."))
    except ValueError:
        acrescimo_pct = 0

    quantidade = max(quantidade, 0)
    valor_unitario = max(valor_unitario, 0)
    acrescimo_pct = max(acrescimo_pct, 0)
    subtotal = round(quantidade * valor_unitario, 2)
    total = round(subtotal + (subtotal * (acrescimo_pct / 100)), 2)

    return {
        "descricao": descricao,
        "quantidade": quantidade,
        "unidade": unidade,
        "valor_unitario": valor_unitario,
        "subtotal": subtotal,
        "acrescimo_pct": acrescimo_pct,
        "acrescimo_motivo": (acrescimo_motivo or "").strip(),
        "observacao": (observacao or "").strip(),
        "servico_base_id": int(servico_base_id or 0) if str(servico_base_id or "").isdigit() else None,
        "total": total,
    }


def conectacasa_itens_do_formulario(form):
    descricoes = form.getlist("item_descricao[]")
    quantidades = form.getlist("item_quantidade[]")
    valores = form.getlist("item_valor[]")
    unidades = form.getlist("item_unidade[]")
    observacoes = form.getlist("item_observacao[]")
    acrescimos_pct = form.getlist("item_acrescimo_pct[]")
    acrescimos_motivo = form.getlist("item_acrescimo_motivo[]")
    servicos_base = form.getlist("item_servico_base_id[]")

    itens = []
    for descricao, quantidade, valor_unitario, unidade, observacao, acrescimo_pct, acrescimo_motivo, servico_base_id in zip(
        descricoes,
        quantidades,
        valores,
        unidades,
        observacoes,
        acrescimos_pct,
        acrescimos_motivo,
        servicos_base,
    ):
        item = conectacasa_normalizar_item(
            descricao,
            quantidade,
            valor_unitario,
            unidade,
            observacao=observacao,
            acrescimo_pct=acrescimo_pct,
            acrescimo_motivo=acrescimo_motivo,
            servico_base_id=servico_base_id,
        )
        if item:
            itens.append(item)
    return itens


def conectacasa_obter_acrescimos_formulario(dados_formulario):
    campos = {
        "acrescimo_noturno_pct": conectacasa_percentual_float(dados_formulario.get("acrescimo_noturno_pct")),
        "acrescimo_final_semana_pct": conectacasa_percentual_float(dados_formulario.get("acrescimo_final_semana_pct")),
        "acrescimo_feriado_pct": conectacasa_percentual_float(dados_formulario.get("acrescimo_feriado_pct")),
        "acrescimo_dificil_pct": conectacasa_percentual_float(dados_formulario.get("acrescimo_dificil_pct")),
        "acrescimo_emergencia_pct": conectacasa_percentual_float(dados_formulario.get("acrescimo_emergencia_pct")),
    }
    return {chave: max(valor, 0) for chave, valor in campos.items()}


def conectacasa_calcular_totais(itens, desconto, acrescimos_percentuais=None):
    subtotal = round(sum(item["total"] for item in itens), 2)
    acrescimos_percentuais = acrescimos_percentuais or {}
    acrescimo_total = 0
    for percentual in acrescimos_percentuais.values():
        acrescimo_total += subtotal * (max(percentual, 0) / 100)
    acrescimo_total = round(acrescimo_total, 2)
    try:
        desconto = float((desconto or "0").replace(",", "."))
    except (ValueError, AttributeError):
        desconto = 0
    desconto = max(desconto, 0)
    valor_total = round(max(subtotal + acrescimo_total - desconto, 0), 2)
    return subtotal, acrescimo_total, desconto, valor_total


def conectacasa_carregar_orcamento(conn, orcamento_id):
    orcamento = conn.execute(
        """
        SELECT o.*, u.nome AS criado_por_nome,
               c.endereco AS cliente_endereco,
               c.cidade AS cliente_cidade,
               c.estado AS cliente_estado,
               c.observacoes AS cliente_observacoes,
               COALESCE(c.telefone_whatsapp, c.telefone, o.cliente_telefone) AS cliente_telefone_resolvido
        FROM conectacasa_orcamentos o
        LEFT JOIN usuarios u ON u.id = o.criado_por
        LEFT JOIN conectacasa_clientes c ON c.id = o.cliente_id
        WHERE o.id = ?
        """,
        (orcamento_id,),
    ).fetchone()
    if not orcamento:
        return None
    dados = dict(orcamento)
    dados["cliente_telefone"] = dados.get("cliente_telefone_resolvido") or dados.get("cliente_telefone")
    dados["status"] = conectacasa_status_normalizado(dados.get("status"))
    dados["itens"] = json.loads(dados.get("itens_json") or "[]")
    dados["status_label"] = conectacasa_status_label(dados.get("status"))
    config = conectacasa_obter_config(conn)
    dados["whatsapp_mensagem"] = conectacasa_mensagem_whatsapp_orcamento(dados, config=config)
    dados["cliente_whatsapp_url"] = conectacasa_whatsapp_url(dados.get("cliente_telefone"), dados["whatsapp_mensagem"])
    for campo in (
        "acrescimo_total",
        "acrescimo_noturno_pct",
        "acrescimo_final_semana_pct",
        "acrescimo_feriado_pct",
        "acrescimo_dificil_pct",
        "acrescimo_emergencia_pct",
    ):
        dados[campo] = float(dados.get(campo) or 0)
    return dados


def conectacasa_salvar_orcamento(conn, dados_formulario, itens, usuario_id, arquivos=None, orcamento_id=None):
    acrescimos_percentuais = conectacasa_obter_acrescimos_formulario(dados_formulario)
    subtotal, acrescimo_total, desconto, valor_total = conectacasa_calcular_totais(
        itens,
        dados_formulario.get("desconto"),
        acrescimos_percentuais,
    )
    titulo = (dados_formulario.get("titulo") or "").strip()
    cliente_nome = (dados_formulario.get("cliente_nome") or "").strip()
    cliente_empresa = (dados_formulario.get("cliente_empresa") or "").strip()
    cliente_email = normalizar_email(dados_formulario.get("cliente_email"))
    cliente_telefone = conectacasa_normalizar_telefone(dados_formulario.get("cliente_telefone"))
    descricao = (dados_formulario.get("descricao") or "").strip()
    observacoes = (dados_formulario.get("observacoes") or "").strip()
    status = conectacasa_status_normalizado(dados_formulario.get("status") or "rascunho")
    data_orcamento = (dados_formulario.get("data_orcamento") or datetime.now().strftime("%d/%m/%Y")).strip()
    validade_orcamento = (dados_formulario.get("validade_orcamento") or "").strip()
    forma_pagamento = (dados_formulario.get("forma_pagamento") or "").strip()
    prazo_execucao = (dados_formulario.get("prazo_execucao") or "").strip()
    garantia = (dados_formulario.get("garantia") or "").strip()

    status_validos = {codigo for codigo, _ in conectacasa_status_opcoes()}
    if status not in status_validos:
        status = "rascunho"

    validade_dias = 7

    if not titulo or not cliente_nome:
        return False, "Informe o titulo e o nome do cliente.", None
    if not itens:
        return False, "Adicione pelo menos um item ao orcamento.", None

    cliente_id = conectacasa_sincronizar_cliente_orcamento(conn, dados_formulario)
    itens_json = json.dumps(itens, ensure_ascii=False)

    if orcamento_id:
        conn.execute(
            """
            UPDATE conectacasa_orcamentos
            SET cliente_id = ?, titulo = ?, cliente_nome = ?, cliente_empresa = ?, cliente_email = ?, cliente_telefone = ?,
                descricao = ?, observacoes = ?, status = ?, data_orcamento = ?, validade_orcamento = ?, forma_pagamento = ?, prazo_execucao = ?, garantia = ?, validade_dias = ?, desconto = ?,
                subtotal = ?, acrescimo_total = ?, acrescimo_noturno_pct = ?, acrescimo_final_semana_pct = ?,
                acrescimo_feriado_pct = ?, acrescimo_dificil_pct = ?, acrescimo_emergencia_pct = ?,
                valor_total = ?, itens_json = ?, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                cliente_id,
                titulo,
                cliente_nome,
                cliente_empresa,
                cliente_email,
                cliente_telefone,
                descricao,
                observacoes,
                status,
                data_orcamento,
                validade_orcamento,
                forma_pagamento,
                prazo_execucao,
                garantia,
                validade_dias,
                desconto,
                subtotal,
                acrescimo_total,
                acrescimos_percentuais["acrescimo_noturno_pct"],
                acrescimos_percentuais["acrescimo_final_semana_pct"],
                acrescimos_percentuais["acrescimo_feriado_pct"],
                acrescimos_percentuais["acrescimo_dificil_pct"],
                acrescimos_percentuais["acrescimo_emergencia_pct"],
                valor_total,
                itens_json,
                orcamento_id,
            ),
        )
        conectacasa_sincronizar_itens_orcamento(conn, orcamento_id, itens)
        conn.commit()
        return True, None, orcamento_id

    codigo = conectacasa_gerar_codigo(conn)
    cursor = conn.execute(
        """
        INSERT INTO conectacasa_orcamentos (
            codigo, cliente_id, titulo, cliente_nome, cliente_empresa, cliente_email, cliente_telefone,
            descricao, observacoes, status, data_orcamento, validade_orcamento, forma_pagamento, prazo_execucao, garantia,
            validade_dias, desconto, subtotal, acrescimo_total,
            acrescimo_noturno_pct, acrescimo_final_semana_pct, acrescimo_feriado_pct, acrescimo_dificil_pct,
            acrescimo_emergencia_pct, valor_total,
            itens_json, criado_por
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            codigo,
            cliente_id,
            titulo,
            cliente_nome,
            cliente_empresa,
            cliente_email,
            cliente_telefone,
            descricao,
            observacoes,
            status,
            data_orcamento,
            validade_orcamento,
            forma_pagamento,
            prazo_execucao,
            garantia,
            validade_dias,
            desconto,
            subtotal,
            acrescimo_total,
            acrescimos_percentuais["acrescimo_noturno_pct"],
            acrescimos_percentuais["acrescimo_final_semana_pct"],
            acrescimos_percentuais["acrescimo_feriado_pct"],
            acrescimos_percentuais["acrescimo_dificil_pct"],
            acrescimos_percentuais["acrescimo_emergencia_pct"],
            valor_total,
            itens_json,
            usuario_id,
        ),
    )
    conectacasa_sincronizar_itens_orcamento(conn, cursor.lastrowid, itens)
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
        Paragraph("Projetos, orçamentos e propostas com visual profissional.", titulo_style),
        Paragraph(
            f"Orçamento {orcamento['codigo']} para {corrigir_mojibake_texto(orcamento['cliente_nome'])}. "
            f"Documento preparado para apresentação comercial e aprovação.",
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
        Paragraph(f"<b>{corrigir_mojibake_texto(orcamento['cliente_nome'])}</b>", styles["BodyText"]),
    ]
    if orcamento.get("cliente_empresa"):
        cliente_bloco.append(Paragraph(corrigir_mojibake_texto(orcamento["cliente_empresa"]), styles["BodyText"]))
    if orcamento.get("cliente_email"):
        cliente_bloco.append(Paragraph(corrigir_mojibake_texto(orcamento["cliente_email"]), styles["BodyText"]))
    if orcamento.get("cliente_telefone"):
        cliente_bloco.append(Paragraph(corrigir_mojibake_texto(orcamento["cliente_telefone"]), styles["BodyText"]))

    resumo_bloco = [
        Paragraph("Resumo", secao_style),
        Table(
            [
                [Paragraph("Status", resumo_label_style), Paragraph(orcamento["status_label"], resumo_valor_style)],
                [Paragraph("Subtotal", resumo_label_style), Paragraph(formata_brl(orcamento["subtotal"]), resumo_valor_style)],
                [Paragraph("Acréscimos", resumo_label_style), Paragraph(formata_brl(orcamento.get("acrescimo_total", 0)), resumo_valor_style)],
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

    tabela_dados = [["Descrição", "Qtd.", "Un.", "Valor unit.", "Total"]]
    for item in orcamento["itens"]:
        tabela_dados.append(
            [
                corrigir_mojibake_texto(item["descricao"]),
                str(item["quantidade"]).replace(".", ","),
                corrigir_mojibake_texto(item["unidade"]),
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
        ["Acréscimos", formata_brl(orcamento.get("acrescimo_total", 0))],
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
        elementos.append(Paragraph(corrigir_mojibake_texto(orcamento["descricao"]).replace("\n", "<br/>"), styles["BodyText"]))

    if orcamento.get("observacoes"):
        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph("Observações", secao_style))
        elementos.append(Paragraph(corrigir_mojibake_texto(orcamento["observacoes"]).replace("\n", "<br/>"), styles["BodyText"]))

    pix_imagem = carregar_logo_flowable(config.get("pix_imagem_path"), max_width=120, max_height=120)
    if pix_imagem:
        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph("Pagamento via PIX", secao_style))
        pix_info = []
        if config.get("pix_beneficiario"):
            pix_info.append(Paragraph(f"<b>Beneficiário:</b> {corrigir_mojibake_texto(config['pix_beneficiario'])}", styles["BodyText"]))
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

# ConfiguraÃ§Ã£o do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = None

# Classe de usuÃ¡rio para o Flask-Login
class User(UserMixin):
    def __init__(self, id, nome, usuario, tipo, pode_acessar_inventario=1, pode_editar_igreja=0, email=""):
        self.id = id
        self.nome = nome
        self.usuario = usuario
        self.tipo = tipo
        self.pode_acessar_inventario = bool(int(pode_acessar_inventario or 0))
        self.pode_editar_igreja = bool(int(pode_editar_igreja or 0))
        self.email = normalizar_email(email)

    @property
    def identificacao_portal(self):
        return self.email or self.usuario


def usuario_pode_acessar_inventario(user):
    return bool(getattr(user, "tipo", "") == "admin" or getattr(user, "pode_acessar_inventario", False))


def usuario_pode_editar_igreja(user):
    return bool(getattr(user, "tipo", "") == "admin" or getattr(user, "pode_editar_igreja", False))


def usuario_pode_gerenciar_usuarios(user):
    return bool(getattr(user, "tipo", "") == "admin" and usuario_pode_acessar_inventario(user))


def destino_pos_login(user):
    if usuario_pode_acessar_inventario(user):
        return url_for("inventario")
    if usuario_pode_editar_igreja(user):
        host_igreja = (app.config.get("IGREJA_PUBLIC_HOST") or "").strip().lower()
        if host_igreja:
            return url_no_host(host_igreja, "/editar")
        return igreja_path("/editar")
    return None


def login_next_seguro():
    proximo = (request.args.get("next") or request.form.get("next") or "").strip()
    if not proximo:
        return None
    if proximo.startswith("/") and not proximo.startswith("//"):
        return proximo
    return None


def destino_pos_login_com_next(user):
    proximo = login_next_seguro()
    if proximo:
        if proximo.startswith("/inventario") and usuario_pode_acessar_inventario(user):
            return proximo
        if proximo.startswith("/editar") and usuario_pode_editar_igreja(user):
            return proximo
        if proximo.startswith("/igrejaemboavista/editar") and usuario_pode_editar_igreja(user):
            return proximo
    if host_eh_igreja() and (usuario_pode_acessar_inventario(user) or usuario_pode_editar_igreja(user)):
        return igreja_path("/")
    return destino_pos_login(user)

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
            user["email"] if "email" in user.keys() else "",
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

        adicionar_coluna_se_faltar(conn, "usuarios", "email", "TEXT")
        adicionar_coluna_se_faltar(conn, "usuarios", "ativo", "INTEGER NOT NULL DEFAULT 1")
        adicionar_coluna_se_faltar(conn, "usuarios", "criado_em", "TIMESTAMP")
        adicionar_coluna_se_faltar(conn, "usuarios", "pode_acessar_inventario", "INTEGER NOT NULL DEFAULT 1")
        adicionar_coluna_se_faltar(conn, "usuarios", "pode_editar_igreja", "INTEGER NOT NULL DEFAULT 0")

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
            """
            UPDATE usuarios
            SET pode_acessar_inventario = 0,
                pode_editar_igreja = 0
            WHERE COALESCE(ativo, 0) = 0
              AND LOWER(COALESCE(usuario, '')) <> 'admin'
            """
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

# Decorador para verificar se o usuÃ¡rio Ã© administrador
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
            print(f"[Erro SQLite] NÃ£o foi possÃ­vel registrar log: {e}")
        except Exception as e:
            print(f"[Erro Geral] Erro ao registrar log: {e}")


# FunÃ§Ã£o para formatar data
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

# FunÃ§Ã£o para formatar tombamento com 4 dÃ­gitos
def format_tombamento(tombamento):
    return str(tombamento).zfill(4)

# FunÃ§Ã£o para obter o ano atual
@app.context_processor
def inject_now():
    pode_inventario = current_user.is_authenticated and usuario_pode_acessar_inventario(current_user)
    pode_editar_site = current_user.is_authenticated and usuario_pode_editar_igreja(current_user)
    return {
        "now": datetime.now,
        "formata_brl": formata_brl,
        "rich_text": rich_text_para_html,
        "conectacasa_path": conectacasa_path,
        "conectacasa_whatsapp_url": conectacasa_whatsapp_url,
        "igreja_path": igreja_path,
        "host_eh_conectacasa": host_eh_conectacasa,
        "host_eh_igreja": host_eh_igreja,
        "pode_inventario": pode_inventario,
        "pode_editar_site": pode_editar_site,
    }


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
    "ativar_usuario",
    "novo_usuario",
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

# Rotas de autenticaÃ§Ã£o
@app.route("/login", methods=["GET", "POST"])
@app.route("/login/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(destino_pos_login_com_next(current_user) or url_for("logout"))
    
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
                user["email"] if "email" in user.keys() else "",
            )
            destino = destino_pos_login_com_next(user_obj)
            if not destino:
                flash("Seu usuario esta ativo, mas ainda nao possui acessos liberados.", "warning")
                return render_template(
                    "login_auth.html",
                    next_url=login_next_seguro(),
                    public_signup_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                )
            login_user(user_obj)
            registrar_log("Login realizado com sucesso")
            db.commit()
            return redirect(destino)
        elif user and int(user["ativo"]) != 1:
            flash("Seu cadastro foi recebido, mas ainda aguarda aprovacao de um administrador.", "warning")
        else:
            flash("Usuario, e-mail ou senha invalidos.", "danger")
    
    return render_template(
        "login_auth.html",
        next_url=login_next_seguro(),
        public_signup_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
    )

@app.route("/cadastro", methods=["GET", "POST"])
@app.route("/cadastro/", methods=["GET", "POST"])
def cadastro():
    if current_user.is_authenticated:
        return redirect(destino_pos_login(current_user) or url_for("logout"))

    if not app.config.get("PUBLIC_SIGNUP_ENABLED"):
        flash("O cadastro publico esta desativado. Solicite a criacao do acesso a um administrador.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario = request.form.get("usuario", "").strip()
        email = validar_email_informado(request.form.get("email"))
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")
        honeypot = (request.form.get("site") or "").strip()
        form_started_at = request.form.get("form_started_at", "").strip()

        if honeypot:
            flash("Cadastro enviado com sucesso. Aguarde a aprovacao de um administrador para acessar o sistema.", "success")
            return redirect(url_for("login"))

        try:
            inicio = float(form_started_at)
        except (TypeError, ValueError):
            inicio = 0

        if not inicio or (datetime.now().timestamp() - inicio) < 3:
            flash("Nao foi possivel validar o cadastro. Tente novamente em alguns segundos.", "danger")
            return render_template(
                "cadastro.html",
                registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                form_started_at=datetime.now().timestamp(),
            )

        if not nome or not usuario or not email or not senha:
            flash("Preencha todos os campos obrigatorios.", "danger")
            return render_template(
                "cadastro.html",
                registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                form_started_at=datetime.now().timestamp(),
            )

        if not senha_atende_requisitos(senha):
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template(
                "cadastro.html",
                registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                form_started_at=datetime.now().timestamp(),
            )

        if senha != confirmar_senha:
            flash("As senhas nao coincidem.", "danger")
            return render_template(
                "cadastro.html",
                registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                form_started_at=datetime.now().timestamp(),
            )

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
            return render_template(
                "cadastro.html",
                registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
                form_started_at=datetime.now().timestamp(),
            )

        db.execute(
            """
            INSERT INTO usuarios (nome, usuario, email, senha_hash, tipo, ativo, criado_em, pode_acessar_inventario, pode_editar_igreja)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nome, usuario, email, generate_password_hash(senha), "comum", 0, datetime.now(), 0, 0),
        )
        db.commit()
        enviado, erro = enviar_email_cadastro_pendente(nome, email)
        if not enviado:
            print(f"[Email] Falha ao enviar aviso de cadastro pendente para {email}: {erro}")
        flash("Cadastro enviado com sucesso. Aguarde a aprovacao de um administrador para acessar o sistema.", "success")
        return redirect(url_for("login"))

    return render_template(
        "cadastro.html",
        registration_enabled=app.config.get("PUBLIC_SIGNUP_ENABLED"),
        form_started_at=datetime.now().timestamp(),
    )

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


@app.route("/usuarios/meu", methods=["GET", "POST"])
@app.route("/usuarios/meu/", methods=["GET", "POST"])
@login_required
def meu_usuario():
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (current_user.id,)).fetchone()

    if not usuario:
        flash("Usuario nao encontrado.", "danger")
        return redirect(destino_pos_login(current_user) or url_for("logout"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        usuario_login = (request.form.get("usuario") or "").strip()
        email = validar_email_informado(request.form.get("email"))
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        if not nome or not usuario_login or not email:
            flash("Nome, usuario e e-mail sao obrigatorios.", "danger")
            return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)

        existente = db.execute(
            """
            SELECT * FROM usuarios
            WHERE id != ? AND (lower(usuario) = lower(?) OR lower(coalesce(email, '')) = lower(?))
            """,
            (current_user.id, usuario_login, email),
        ).fetchone()
        if existente:
            flash("Nome de usuario ou e-mail ja cadastrado.", "danger")
            return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)

        senha_hash_nova = None
        if senha_atual or nova_senha or confirmar_senha:
            if not senha_atual or not nova_senha or not confirmar_senha:
                flash("Para alterar a senha, preencha a senha atual, a nova senha e a confirmacao.", "danger")
                return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)
            if not check_password_hash(usuario["senha_hash"], senha_atual):
                flash("A senha atual informada nao confere.", "danger")
                return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)
            if not senha_atende_requisitos(nova_senha):
                flash("A nova senha deve ter pelo menos 8 caracteres.", "danger")
                return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)
            if nova_senha != confirmar_senha:
                flash("A confirmacao da nova senha nao confere.", "danger")
                return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)
            if check_password_hash(usuario["senha_hash"], nova_senha):
                flash("A nova senha precisa ser diferente da senha atual.", "warning")
                return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)
            senha_hash_nova = generate_password_hash(nova_senha)

        if senha_hash_nova:
            db.execute(
                """
                UPDATE usuarios
                SET nome = ?, usuario = ?, email = ?, senha_hash = ?
                WHERE id = ?
                """,
                (nome, usuario_login, email, senha_hash_nova, current_user.id),
            )
        else:
            db.execute(
                """
                UPDATE usuarios
                SET nome = ?, usuario = ?, email = ?
                WHERE id = ?
                """,
                (nome, usuario_login, email, current_user.id),
            )

        db.commit()
        registrar_log(f"Usuario atualizou a propria conta: {nome} ({usuario_login})")
        db.commit()
        flash("Usuario atualizado com sucesso.", "success")
        return redirect(url_for("meu_usuario"))

    return render_template("editar_usuario_simples.html", usuario=usuario, eh_proprio_usuario=True, pode_gerenciar_usuarios=False)


@app.route("/logout")
@app.route("/logout/")
@login_required
def logout():
    registrar_log("Logout realizado")
    logout_user()
    if host_eh_igreja():
        return redirect(igreja_path("/"))
    return redirect(url_for("login"))


@app.route("/conectacasa")
@app.route("/conectacasa/")
def conectacasa_publico():
    if not conectacasa_request_permitida():
        abort(404)
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    return render_template("conectacasa_publico.html", config=config)


@app.route("/entrar", methods=["GET", "POST"])
@app.route("/entrar/", methods=["GET", "POST"])
@app.route("/conectacasa/entrar", methods=["GET", "POST"])
@app.route("/conectacasa/entrar/", methods=["GET", "POST"])
def conectacasa_login():
    if not conectacasa_request_permitida():
        abort(404)
    if conectacasa_autenticado():
        return redirect(conectacasa_path("/painel"))

    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    proximo = request.args.get("next") or request.form.get("next") or conectacasa_path("/painel")

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
            if proximo.startswith("/conectacasa") or (host_eh_conectacasa() and proximo.startswith("/")):
                return redirect(proximo)
            return redirect(conectacasa_path("/painel"))

        flash("Usuario ou senha invalidos.", "danger")

    return render_template("conectacasa_login.html", config=config, proximo=proximo)


@app.route("/sair")
@app.route("/sair/")
@app.route("/conectacasa/sair")
@app.route("/conectacasa/sair/")
def conectacasa_logout():
    if not conectacasa_request_permitida():
        abort(404)
    session.pop("conectacasa_auth", None)
    session.pop("conectacasa_user", None)
    return redirect(conectacasa_path("/"))


@app.route("/painel")
@app.route("/painel/")
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
    total_em_orcamento = sum(1 for item in orcamentos_filtrados if item["status"] == "rascunho")
    valor_a_receber = round(
        sum(
            item["valor_total"] or 0
            for item in orcamentos_filtrados
            if item["status"] in {"enviado", "aprovado"}
        ),
        2,
    )
    valor_recebido = round(
        sum(item["valor_total"] or 0 for item in orcamentos_filtrados if item["status"] == "aprovado"),
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


@app.route("/configuracoes", methods=["GET", "POST"])
@app.route("/configuracoes/", methods=["GET", "POST"])
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
            "nome_responsavel": (request.form.get("nome_responsavel") or "").strip(),
            "telefone_empresa": conectacasa_normalizar_telefone(request.form.get("telefone_empresa")),
            "email_empresa": normalizar_email(request.form.get("email_empresa")),
            "endereco_empresa": (request.form.get("endereco_empresa") or "").strip(),
            "cidade_empresa": (request.form.get("cidade_empresa") or "").strip(),
            "estado_empresa": (request.form.get("estado_empresa") or "").strip(),
            "cnpj_cpf": conectacasa_normalizar_telefone(request.form.get("cnpj_cpf")),
            "mensagem_padrao_whatsapp": (request.form.get("mensagem_padrao_whatsapp") or "").strip(),
            "observacao_padrao_orcamento": (request.form.get("observacao_padrao_orcamento") or "").strip(),
            "garantia_padrao": (request.form.get("garantia_padrao") or "").strip(),
            "validade_padrao_orcamento": (request.form.get("validade_padrao_orcamento") or "").strip(),
            "forma_pagamento_padrao": (request.form.get("forma_pagamento_padrao") or "").strip(),
            "pix_nome": (request.form.get("pix_nome") or "").strip(),
            "pix_chave": (request.form.get("pix_chave") or "").strip(),
            "pix_cidade": (request.form.get("pix_cidade") or "").strip(),
            "pix_identificador": (request.form.get("pix_identificador") or "").strip(),
            "pix_descricao": (request.form.get("pix_descricao") or "").strip(),
            "pix_beneficiario": (request.form.get("pix_beneficiario") or "").strip(),
            "acesso_usuario": (request.form.get("acesso_usuario") or config.get("acesso_usuario") or "admin").strip() or "admin",
            "google_client_id": (request.form.get("google_client_id") or "").strip(),
            "google_client_secret": (request.form.get("google_client_secret") or "").strip() or (config.get("google_client_secret") or ""),
            "logo_path": logo_path,
            "pix_imagem_path": pix_imagem_path,
        }
        nova_senha = (request.form.get("acesso_senha") or "").strip()
        senha_hash = generate_password_hash(nova_senha) if nova_senha else config.get("acesso_senha_hash")
        conn.execute(
            """
            UPDATE conectacasa_config
            SET empresa_nome = ?, nome_responsavel = ?, telefone_empresa = ?, email_empresa = ?, endereco_empresa = ?, cidade_empresa = ?, estado_empresa = ?, cnpj_cpf = ?,
                mensagem_padrao_whatsapp = ?, observacao_padrao_orcamento = ?, garantia_padrao = ?, validade_padrao_orcamento = ?, forma_pagamento_padrao = ?,
                logo_path = ?, pix_imagem_path = ?, pix_nome = ?, pix_chave = ?, pix_cidade = ?,
                pix_identificador = ?, pix_descricao = ?, pix_beneficiario = ?, acesso_usuario = ?, acesso_senha_hash = ?, google_client_id = ?, google_client_secret = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                dados["empresa_nome"],
                dados["nome_responsavel"],
                dados["telefone_empresa"],
                dados["email_empresa"],
                dados["endereco_empresa"],
                dados["cidade_empresa"],
                dados["estado_empresa"],
                dados["cnpj_cpf"],
                dados["mensagem_padrao_whatsapp"],
                dados["observacao_padrao_orcamento"],
                dados["garantia_padrao"],
                dados["validade_padrao_orcamento"],
                dados["forma_pagamento_padrao"],
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
                dados["google_client_id"],
                dados["google_client_secret"],
            ),
        )
        conn.commit()
        session["conectacasa_user"] = dados["acesso_usuario"]
        flash("Configuracoes da ConectaCasa atualizadas.", "success")
        return redirect(conectacasa_path("/configuracoes"))

    config = conectacasa_preparar_urls_config(config)
    return render_template(
        "conectacasa_configuracoes.html",
        config=config,
        google_redirect_uri=conectacasa_google_redirect_uri(),
        google_oauth_disponivel=conectacasa_google_oauth_disponivel(),
    )


@app.route("/clientes/google/conectar")
@app.route("/clientes/google/conectar/")
@app.route("/conectacasa/clientes/google/conectar")
@app.route("/conectacasa/clientes/google/conectar/")
@conectacasa_required
def conectacasa_google_conectar():
    conn = get_db()
    config = conectacasa_obter_config(conn)
    if not conectacasa_google_oauth_disponivel():
        flash("As dependencias do Google Contacts nao estao instaladas no servidor.", "danger")
        return redirect(conectacasa_path("/configuracoes"))

    try:
        conectacasa_google_validar_client_config(config)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(conectacasa_path("/configuracoes"))

    state = secrets.token_urlsafe(32)
    session["conectacasa_google_state"] = state
    return redirect(conectacasa_google_authorization_url(config, state))


@app.route("/clientes/google/callback")
@app.route("/clientes/google/callback/")
@app.route("/conectacasa/clientes/google/callback")
@app.route("/conectacasa/clientes/google/callback/")
@conectacasa_required
def conectacasa_google_callback():
    conn = get_db()
    config = conectacasa_obter_config(conn)
    if not conectacasa_google_oauth_disponivel():
        flash("As dependencias do Google Contacts nao estao instaladas no servidor.", "danger")
        return redirect(conectacasa_path("/configuracoes"))

    state = session.get("conectacasa_google_state")
    retorno_state = request.args.get("state") or ""
    erro_google = (request.args.get("error") or "").strip()
    codigo = (request.args.get("code") or "").strip()

    erros_tratados = {
        "access_denied": "O acesso aos contatos do Google foi negado.",
        "invalid_client": "Google Client ID ou Client Secret invalidos.",
        "redirect_uri_mismatch": "A URI de redirecionamento cadastrada no Google nao bate com a da ConectaCasa.",
        "invalid_grant": "O codigo de autorizacao do Google expirou ou ficou invalido. Tente conectar novamente.",
    }

    try:
        conectacasa_google_validar_client_config(config)
        if erro_google:
            flash(erros_tratados.get(erro_google, f"Falha na autenticacao com o Google: {erro_google}"), "danger")
            return redirect(conectacasa_path("/configuracoes"))
        if not state or not retorno_state or retorno_state != state:
            flash("A validacao de seguranca da conexao com o Google falhou. Tente novamente.", "danger")
            return redirect(conectacasa_path("/configuracoes"))
        if not codigo:
            flash("O Google nao retornou o codigo de autorizacao esperado.", "danger")
            return redirect(conectacasa_path("/configuracoes"))

        token_data = conectacasa_google_trocar_code_por_token(config, codigo)
        if not token_data.get("refresh_token"):
            flash("O Google nao retornou refresh token. Tente conectar novamente com consentimento completo.", "warning")

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=(config.get("google_client_id") or "").strip(),
            client_secret=(config.get("google_client_secret") or "").strip(),
            scopes=GOOGLE_CONTACTS_SCOPES,
        )
        try:
            expires_in = int(token_data.get("expires_in") or 0)
            if expires_in > 0:
                creds.expiry = datetime.utcnow() + timedelta(seconds=expires_in)
        except Exception:
            pass
        service = build("people", "v1", credentials=creds, cache_discovery=False)
        perfil = conectacasa_google_obter_perfil(service)
        conectacasa_google_salvar_credentials(conn, creds, perfil=perfil)
        flash("Conta Google conectada.", "success")
    except Exception as exc:
        mensagem = str(exc)
        if "missing code verifier" in mensagem.lower():
            mensagem = "O Google recusou a autenticacao anterior por causa do fluxo PKCE. O sistema foi ajustado. Tente conectar novamente."
        flash(f"Nao foi possivel concluir a conexao com o Google: {mensagem}", "danger")
    finally:
        session.pop("conectacasa_google_state", None)
    return redirect(conectacasa_path("/clientes"))


@app.route("/clientes/google/sincronizar", methods=["POST"])
@app.route("/clientes/google/sincronizar/", methods=["POST"])
@app.route("/conectacasa/clientes/google/sincronizar", methods=["POST"])
@app.route("/conectacasa/clientes/google/sincronizar/", methods=["POST"])
@conectacasa_required
def conectacasa_google_sincronizar():
    conn = get_db()
    config = conectacasa_obter_config(conn)
    try:
        resumo = conectacasa_google_importar_clientes(conn, config)
        flash(
            f"Importacao concluida. {resumo['importados']} cliente(s) novos e {resumo['atualizados']} atualizado(s).",
            "success",
        )
    except Exception as exc:
        flash(f"Nao foi possivel importar os contatos do Google: {exc}", "danger")
    return redirect(conectacasa_path("/clientes"))


@app.route("/clientes/google/desconectar", methods=["POST"])
@app.route("/clientes/google/desconectar/", methods=["POST"])
@app.route("/conectacasa/clientes/google/desconectar", methods=["POST"])
@app.route("/conectacasa/clientes/google/desconectar/", methods=["POST"])
@conectacasa_required
def conectacasa_google_desconectar():
    conn = get_db()
    conectacasa_google_limpar_conexao(conn)
    flash("Conexao com o Google removida da ConectaCasa.", "success")
    return redirect(conectacasa_path("/configuracoes"))


@app.route("/clientes", methods=["GET", "POST"])
@app.route("/clientes/", methods=["GET", "POST"])
@app.route("/conectacasa/clientes", methods=["GET", "POST"])
@app.route("/conectacasa/clientes/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_clientes():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    cliente_id = request.form.get("cliente_id") or request.args.get("editar")
    cliente_edicao = None

    if request.method == "POST":
        acao = (request.form.get("acao") or "salvar").strip()
        if acao == "alternar":
            alvo_id = int(request.form.get("cliente_id") or 0)
            cliente = conectacasa_obter_cliente(conn, alvo_id)
            if not cliente:
                flash("Cliente nao encontrado.", "danger")
            else:
                conn.execute(
                    "UPDATE conectacasa_clientes SET ativo = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (0 if cliente.get("ativo") else 1, alvo_id),
                )
                conn.commit()
                flash("Status do cliente atualizado.", "success")
            return redirect(conectacasa_path("/clientes"))
        if acao == "excluir":
            alvo_id = int(request.form.get("cliente_id") or 0)
            vinculos = conn.execute("SELECT COUNT(1) AS total FROM conectacasa_orcamentos WHERE cliente_id = ?", (alvo_id,)).fetchone()
            if (vinculos["total"] or 0) > 0:
                flash("Este cliente possui orcamentos vinculados e nao pode ser excluido.", "warning")
            else:
                conn.execute("DELETE FROM conectacasa_clientes WHERE id = ?", (alvo_id,))
                conn.commit()
                flash("Cliente excluido com sucesso.", "success")
            return redirect(conectacasa_path("/clientes"))

        alvo_id = int(cliente_id or 0) if str(cliente_id or "").isdigit() else None
        ok, resultado = conectacasa_salvar_cliente(conn, request.form, cliente_id=alvo_id)
        if not ok:
            flash(resultado, "danger")
            cliente_edicao = dict(request.form)
            cliente_edicao["id"] = alvo_id
        else:
            flash("Cliente salvo com sucesso.", "success")
            return redirect(conectacasa_path("/clientes"))

    busca = (request.args.get("q") or "").strip()
    status_filtro = (request.args.get("status") or "ativos").strip()
    ativo = None if status_filtro == "todos" else 1 if status_filtro == "ativos" else 0
    clientes = conectacasa_listar_clientes(conn, busca=busca or None, ativo=ativo)
    if not cliente_edicao and str(cliente_id or "").isdigit():
        cliente_edicao = conectacasa_obter_cliente(conn, int(cliente_id))
    historico_orcamentos = []
    resumo_cliente = None
    if cliente_edicao and cliente_edicao.get("id"):
        historico_orcamentos = [
            dict(item)
            for item in conn.execute(
                """
                SELECT id, codigo, titulo, status, valor_total, data_orcamento, atualizado_em
                FROM conectacasa_orcamentos
                WHERE cliente_id = ?
                ORDER BY atualizado_em DESC, id DESC
                """,
                (cliente_edicao["id"],),
            ).fetchall()
        ]
        for item in historico_orcamentos:
            item["status"] = conectacasa_status_normalizado(item.get("status"))
            item["status_label"] = conectacasa_status_label(item.get("status"))
        resumo_cliente = {
            "total_orcamentos": len(historico_orcamentos),
            "enviados": sum(1 for item in historico_orcamentos if item["status"] == "enviado"),
            "aprovados": sum(1 for item in historico_orcamentos if item["status"] == "aprovado"),
            "recusados": sum(1 for item in historico_orcamentos if item["status"] == "recusado"),
            "valor_total_aprovado": round(sum(float(item.get("valor_total") or 0) for item in historico_orcamentos if item["status"] == "aprovado"), 2),
        }
    return render_template(
        "conectacasa_clientes.html",
        config=config,
        clientes=clientes,
        busca=busca,
        status_filtro=status_filtro,
        cliente_edicao=cliente_edicao,
        historico_orcamentos=historico_orcamentos,
        resumo_cliente=resumo_cliente,
        google_oauth_disponivel=conectacasa_google_oauth_disponivel(),
    )


@app.route("/servicos", methods=["GET", "POST"])
@app.route("/servicos/", methods=["GET", "POST"])
@app.route("/conectacasa/servicos", methods=["GET", "POST"])
@app.route("/conectacasa/servicos/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_servicos():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    servico_id = request.form.get("servico_id") or request.args.get("editar")
    servico_edicao = None

    if request.method == "POST":
        acao = (request.form.get("acao") or "salvar").strip()
        if acao == "alternar":
            alvo_id = int(request.form.get("servico_id") or 0)
            servico = conectacasa_obter_servico_orcamento(conn, alvo_id)
            if not servico:
                flash("Servico nao encontrado.", "danger")
            else:
                conn.execute(
                    "UPDATE servicos_orcamento SET ativo = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (0 if servico.get("ativo") else 1, alvo_id),
                )
                conn.commit()
                flash("Status do servico atualizado.", "success")
            return redirect(conectacasa_path("/servicos"))
        if acao == "excluir":
            alvo_id = int(request.form.get("servico_id") or 0)
            servico = conectacasa_obter_servico_orcamento(conn, alvo_id)
            if not servico:
                flash("Servico nao encontrado.", "danger")
            elif conectacasa_servico_em_uso(conn, alvo_id):
                flash("Este servico ja foi usado em orcamentos e nao pode ser excluido.", "warning")
            else:
                conn.execute("DELETE FROM servicos_orcamento WHERE id = ?", (alvo_id,))
                conn.commit()
                flash("Servico excluido com sucesso.", "success")
            return redirect(conectacasa_path("/servicos"))

        alvo_id = int(servico_id or 0) if str(servico_id or "").isdigit() else None
        ok, erro = conectacasa_salvar_servico_orcamento(conn, request.form, servico_id=alvo_id)
        if not ok:
            flash(erro, "danger")
            servico_edicao = dict(request.form)
            servico_edicao["id"] = alvo_id
        else:
            flash("Servico salvo com sucesso.", "success")
            return redirect(conectacasa_path("/servicos"))

    categoria_filtro = (request.args.get("categoria") or "").strip()
    subcategoria_filtro = (request.args.get("subcategoria") or "").strip()
    unidade_filtro = (request.args.get("unidade") or "").strip()
    regiao_filtro = (request.args.get("regiao") or "").strip()
    busca = (request.args.get("q") or "").strip()
    status_filtro = (request.args.get("status") or "todos").strip()
    ativo = None if status_filtro == "todos" else 1 if status_filtro == "ativos" else 0
    servicos = conectacasa_listar_servicos_orcamento(
        conn,
        categoria=categoria_filtro or None,
        subcategoria=subcategoria_filtro or None,
        unidade=unidade_filtro or None,
        regiao=regiao_filtro or None,
        ativo=ativo,
        busca=busca or None,
    )
    if not servico_edicao and str(servico_id or "").isdigit():
        servico_edicao = conectacasa_obter_servico_orcamento(conn, int(servico_id))
    categorias = [row["categoria"] for row in conn.execute("SELECT DISTINCT categoria FROM servicos_orcamento ORDER BY categoria").fetchall()]
    subcategorias = [row["subcategoria"] or "" for row in conn.execute("SELECT DISTINCT subcategoria FROM servicos_orcamento WHERE COALESCE(subcategoria, '') <> '' ORDER BY subcategoria").fetchall()]
    regioes = [row["regiao"] for row in conn.execute("SELECT DISTINCT regiao FROM servicos_orcamento ORDER BY regiao").fetchall()]
    return render_template(
        "conectacasa_servicos.html",
        config=config,
        servicos=servicos,
        categorias=categorias,
        subcategorias=subcategorias,
        regioes=regioes,
        unidades=conectacasa_unidades_servico(),
        categorias_base=conectacasa_categorias_servico(),
        categoria_filtro=categoria_filtro,
        subcategoria_filtro=subcategoria_filtro,
        unidade_filtro=unidade_filtro,
        regiao_filtro=regiao_filtro,
        busca=busca,
        status_filtro=status_filtro,
        servico_edicao=servico_edicao,
    )


@app.route("/propagandas", methods=["GET", "POST"])
@app.route("/propagandas/", methods=["GET", "POST"])
@app.route("/conectacasa/propagandas", methods=["GET", "POST"])
@app.route("/conectacasa/propagandas/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_propagandas():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))

    if request.method == "POST":
        titulo = (request.form.get("titulo") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        mensagem_whatsapp = (request.form.get("mensagem_whatsapp") or "").strip()
        ativo = 1 if request.form.get("ativo") == "1" else 0
        try:
            ordem = int(request.form.get("ordem") or 0)
        except ValueError:
            ordem = 0

        imagem_path = conectacasa_salvar_promo_imagem(request.files.get("imagem_arquivo"))
        if not titulo:
            flash("Informe um titulo para a propaganda.", "danger")
        elif not imagem_path:
            flash("Envie uma imagem PNG, JPG, JPEG ou WEBP para a propaganda.", "danger")
        else:
            conn.execute(
                """
                INSERT INTO conectacasa_promos (titulo, descricao, mensagem_whatsapp, imagem_path, ativo, ordem)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (titulo, descricao, mensagem_whatsapp, imagem_path, ativo, ordem),
            )
            conn.commit()
            flash("Propaganda salva com sucesso.", "success")
            return redirect(conectacasa_path("/propagandas"))

    promos = conectacasa_listar_promos(conn)
    return render_template("conectacasa_propagandas.html", config=config, promos=promos)


@app.route("/propagandas/<int:promo_id>/excluir", methods=["POST"])
@app.route("/propagandas/<int:promo_id>/excluir/", methods=["POST"])
@app.route("/conectacasa/propagandas/<int:promo_id>/excluir", methods=["POST"])
@app.route("/conectacasa/propagandas/<int:promo_id>/excluir/", methods=["POST"])
@conectacasa_required
def conectacasa_excluir_propaganda(promo_id):
    conn = get_db()
    promo = conn.execute("SELECT imagem_path FROM conectacasa_promos WHERE id = ?", (promo_id,)).fetchone()
    if not promo:
        flash("Propaganda nao encontrada.", "danger")
        return redirect(conectacasa_path("/propagandas"))

    conn.execute("DELETE FROM conectacasa_promos WHERE id = ?", (promo_id,))
    conn.commit()
    igreja_remover_arquivo_relativo(promo["imagem_path"])
    flash("Propaganda removida.", "success")
    return redirect(conectacasa_path("/propagandas"))


@app.route("/novo", methods=["GET", "POST"])
@app.route("/novo/", methods=["GET", "POST"])
@app.route("/conectacasa/novo", methods=["GET", "POST"])
@app.route("/conectacasa/novo/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_novo_orcamento():
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    catalogo_servicos = conectacasa_listar_servicos_orcamento(conn)
    clientes = conectacasa_listar_clientes(conn, ativo=1)
    cliente_preselecionado = None
    cliente_id_query = request.args.get("cliente_id")
    if str(cliente_id_query or "").isdigit():
        cliente_preselecionado = conectacasa_obter_cliente(conn, int(cliente_id_query))
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
                catalogo_servicos=catalogo_servicos,
                clientes=clientes,
                modo="novo",
            )
        flash("Orcamento criado com sucesso.", "success")
        return redirect(conectacasa_path(f"/orcamentos/{orcamento_id}"))

    return render_template(
        "conectacasa_form.html",
        orcamento={
            "status": "rascunho",
            "desconto": 0,
            "subtotal": 0,
            "acrescimo_total": 0,
            "acrescimo_noturno_pct": 0,
            "acrescimo_final_semana_pct": 0,
            "acrescimo_feriado_pct": 0,
            "acrescimo_dificil_pct": 0,
            "acrescimo_emergencia_pct": 0,
            "valor_total": 0,
            "data_orcamento": datetime.now().strftime("%d/%m/%Y"),
            "validade_orcamento": config.get("validade_padrao_orcamento") or "7 dias",
            "forma_pagamento": config.get("forma_pagamento_padrao") or "",
            "garantia": config.get("garantia_padrao") or "",
            "observacoes": config.get("observacao_padrao_orcamento") or "",
            "cliente_id": cliente_preselecionado.get("id") if cliente_preselecionado else "",
            "cliente_nome": cliente_preselecionado.get("nome") if cliente_preselecionado else "",
            "cliente_empresa": cliente_preselecionado.get("empresa") if cliente_preselecionado else "",
            "cliente_email": cliente_preselecionado.get("email") if cliente_preselecionado else "",
            "cliente_telefone": (cliente_preselecionado.get("telefone_whatsapp") or cliente_preselecionado.get("telefone")) if cliente_preselecionado else "",
            "cliente_endereco": cliente_preselecionado.get("endereco") if cliente_preselecionado else "",
            "cliente_cidade": cliente_preselecionado.get("cidade") if cliente_preselecionado else "",
            "cliente_estado": cliente_preselecionado.get("estado") if cliente_preselecionado else "",
            "cliente_observacoes": cliente_preselecionado.get("observacoes") if cliente_preselecionado else "",
        },
        itens=[{"descricao": "", "quantidade": 1, "unidade": "un", "valor_unitario": 0, "total": 0}],
        status_opcoes=conectacasa_status_opcoes(),
        config=config,
        catalogo_servicos=catalogo_servicos,
        clientes=clientes,
        modo="novo",
    )


@app.route("/orcamentos/<int:orcamento_id>")
@app.route("/orcamentos/<int:orcamento_id>/")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/")
@conectacasa_required
def conectacasa_visualizar_orcamento(orcamento_id):
    conn = get_db()
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(conectacasa_path("/painel"))
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    return render_template(
        "conectacasa_visualizar.html",
        orcamento=orcamento,
        config=config,
    )


@app.route("/orcamentos/<int:orcamento_id>/editar", methods=["GET", "POST"])
@app.route("/orcamentos/<int:orcamento_id>/editar/", methods=["GET", "POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/editar", methods=["GET", "POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/editar/", methods=["GET", "POST"])
@conectacasa_required
def conectacasa_editar_orcamento(orcamento_id):
    conn = get_db()
    config = conectacasa_preparar_urls_config(conectacasa_obter_config(conn))
    catalogo_servicos = conectacasa_listar_servicos_orcamento(conn)
    clientes = conectacasa_listar_clientes(conn, ativo=1)
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(conectacasa_path("/painel"))

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
                  catalogo_servicos=catalogo_servicos,
                  clientes=clientes,
                  modo="editar",
              )
        flash("Orcamento atualizado com sucesso.", "success")
        return redirect(conectacasa_path(f"/orcamentos/{orcamento_id}"))

    return render_template(
        "conectacasa_form.html",
        orcamento=orcamento,
        itens=orcamento["itens"],
        status_opcoes=conectacasa_status_opcoes(),
        config=config,
        catalogo_servicos=catalogo_servicos,
        clientes=clientes,
        modo="editar",
    )


@app.route("/orcamentos/<int:orcamento_id>/status", methods=["POST"])
@app.route("/orcamentos/<int:orcamento_id>/status/", methods=["POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/status", methods=["POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/status/", methods=["POST"])
@conectacasa_required
def conectacasa_atualizar_status(orcamento_id):
    conn = get_db()
    orcamento = conn.execute("SELECT id FROM conectacasa_orcamentos WHERE id = ?", (orcamento_id,)).fetchone()
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(conectacasa_path("/painel"))

    status = conectacasa_status_normalizado(request.form.get("status"))
    status_validos = {codigo for codigo, _ in conectacasa_status_opcoes()}
    if status not in status_validos:
        flash("Status invalido.", "danger")
        return redirect(conectacasa_path("/painel"))

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
        return redirect(f"{conectacasa_path('/painel')}?mes={mes}")
    return redirect(conectacasa_path("/painel"))


@app.route("/orcamentos/<int:orcamento_id>/duplicar", methods=["POST"])
@app.route("/orcamentos/<int:orcamento_id>/duplicar/", methods=["POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/duplicar", methods=["POST"])
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/duplicar/", methods=["POST"])
@conectacasa_required
def conectacasa_duplicar_orcamento(orcamento_id):
    conn = get_db()
    original = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not original:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(conectacasa_path("/painel"))

    novo_codigo = conectacasa_gerar_codigo(conn)
    cursor = conn.execute(
        """
        INSERT INTO conectacasa_orcamentos (
            codigo, cliente_id, titulo, cliente_nome, cliente_empresa, cliente_email, cliente_telefone,
            descricao, observacoes, status, data_orcamento, validade_orcamento, forma_pagamento, prazo_execucao, garantia,
            validade_dias, desconto, subtotal, acrescimo_total, acrescimo_noturno_pct, acrescimo_final_semana_pct,
            acrescimo_feriado_pct, acrescimo_dificil_pct, acrescimo_emergencia_pct, valor_total, itens_json, criado_por
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            novo_codigo,
            original.get("cliente_id"),
            f"{original.get('titulo')} (copia)",
            original.get("cliente_nome"),
            original.get("cliente_empresa"),
            original.get("cliente_email"),
            original.get("cliente_telefone"),
            original.get("descricao"),
            original.get("observacoes"),
            "rascunho",
            datetime.now().strftime("%d/%m/%Y"),
            original.get("validade_orcamento"),
            original.get("forma_pagamento"),
            original.get("prazo_execucao"),
            original.get("garantia"),
            original.get("validade_dias") or 7,
            original.get("desconto") or 0,
            original.get("subtotal") or 0,
            original.get("acrescimo_total") or 0,
            original.get("acrescimo_noturno_pct") or 0,
            original.get("acrescimo_final_semana_pct") or 0,
            original.get("acrescimo_feriado_pct") or 0,
            original.get("acrescimo_dificil_pct") or 0,
            original.get("acrescimo_emergencia_pct") or 0,
            original.get("valor_total") or 0,
            json.dumps(original.get("itens") or [], ensure_ascii=False),
            None,
        ),
    )
    conectacasa_sincronizar_itens_orcamento(conn, cursor.lastrowid, original.get("itens") or [])
    conn.commit()
    flash("Orcamento duplicado com sucesso.", "success")
    return redirect(conectacasa_path(f"/orcamentos/{cursor.lastrowid}/editar"))


@app.route("/orcamentos/<int:orcamento_id>/pdf")
@app.route("/orcamentos/<int:orcamento_id>/pdf/")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/pdf")
@app.route("/conectacasa/orcamentos/<int:orcamento_id>/pdf/")
@conectacasa_required
def conectacasa_orcamento_pdf(orcamento_id):
    conn = get_db()
    orcamento = conectacasa_carregar_orcamento(conn, orcamento_id)
    if not orcamento:
        flash("Orcamento nao encontrado.", "danger")
        return redirect(conectacasa_path("/painel"))

    config = conectacasa_obter_config(conn)
    pdf = conectacasa_render_pdf(orcamento, config)
    nome_arquivo = f"{orcamento['codigo']}.pdf"
    return send_file(pdf, as_attachment=True, download_name=nome_arquivo, mimetype="application/pdf")


def render_igreja_publico(pagina_atual="inicio"):
    conn = get_db()
    config = igreja_obter_config(conn)
    apostilas = igreja_listar_materiais(conn, categoria="apostila", somente_ativos=True) if pagina_atual != "pregacoes" else []
    pregacoes = igreja_listar_pregacoes()
    conn.close()
    return render_template(
        "igrejaemboavista_publico.html",
        config=config,
        apostilas=apostilas,
        pregacoes=pregacoes,
        pagina_atual=pagina_atual,
    )


@app.route("/igrejaemboavista")
@app.route("/igrejaemboavista/")
def igreja_publico():
    if not igreja_request_permitida():
        abort(404)
    return render_igreja_publico("inicio")


@app.route("/pregacoes")
@app.route("/pregacoes/")
@app.route("/igrejaemboavista/pregacoes")
@app.route("/igrejaemboavista/pregacoes/")
def igreja_pregacoes():
    if not igreja_request_permitida():
        abort(404)
    return render_igreja_publico("pregacoes")


@app.route("/editar", methods=["GET", "POST"])
@app.route("/editar/", methods=["GET", "POST"])
@app.route("/igrejaemboavista/editar", methods=["GET", "POST"])
@app.route("/igrejaemboavista/editar/", methods=["GET", "POST"])
@login_required
@igreja_edit_required
def igreja_admin():
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()

    if request.method == "POST":
        igreja_salvar_config(conn, request.form)
        conn.close()
        flash("Conteudo do portal atualizado com sucesso.", "success")
        return redirect(igreja_path("/editar"))

    config = igreja_obter_config(conn)
    avisos = []
    apostilas = igreja_listar_materiais(conn, categoria="apostila", somente_ativos=True)
    ensinos = []
    pregacoes = igreja_listar_pregacoes()
    conn.close()
    return render_template(
        "igrejaemboavista_admin.html",
        config=config,
        avisos=avisos,
        apostilas=apostilas,
        ensinos=ensinos,
        pregacoes=pregacoes,
    )


@app.route("/editor/imagem", methods=["POST"])
@app.route("/editor/imagem/", methods=["POST"])
@app.route("/igrejaemboavista/editor/imagem", methods=["POST"])
@app.route("/igrejaemboavista/editor/imagem/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_editor_upload_imagem():
    if not igreja_request_permitida():
        abort(404)
    imagem = request.files.get("imagem")
    imagem_url, erro = igreja_salvar_imagem_conteudo(imagem)
    if erro:
        return {"ok": False, "error": erro}, 400
    return {"ok": True, "url": imagem_url}


@app.route("/pregacoes/salvar", methods=["POST"])
@app.route("/pregacoes/salvar/", methods=["POST"])
@app.route("/igrejaemboavista/pregacoes/salvar", methods=["POST"])
@app.route("/igrejaemboavista/pregacoes/salvar/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_pregacoes_salvar():
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    igreja_salvar_textos_pregacoes(conn, request.form)
    conn.close()
    ok, erro = igreja_salvar_pregacoes(request.form)
    if not ok:
        flash(erro, "danger")
    else:
        flash("Pregações atualizadas com sucesso.", "success")
    return redirect(igreja_path("/editar"))


@app.route("/avisos/novo", methods=["POST"])
@app.route("/avisos/novo/", methods=["POST"])
@app.route("/igrejaemboavista/avisos/novo", methods=["POST"])
@app.route("/igrejaemboavista/avisos/novo/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_novo():
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    igreja_salvar_aviso(conn, request.form)
    conn.close()
    flash("Aviso criado com sucesso.", "success")
    return redirect(igreja_path("/editar"))


@app.route("/avisos/<int:aviso_id>/editar", methods=["POST"])
@app.route("/avisos/<int:aviso_id>/editar/", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/editar", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/editar/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_editar(aviso_id):
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    igreja_salvar_aviso(conn, request.form, aviso_id=aviso_id)
    conn.close()
    flash("Aviso atualizado com sucesso.", "success")
    return redirect(igreja_path("/editar"))


@app.route("/avisos/<int:aviso_id>/excluir", methods=["POST"])
@app.route("/avisos/<int:aviso_id>/excluir/", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/excluir", methods=["POST"])
@app.route("/igrejaemboavista/avisos/<int:aviso_id>/excluir/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_aviso_excluir(aviso_id):
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    conn.execute("DELETE FROM igreja_avisos WHERE id = ?", (aviso_id,))
    conn.commit()
    conn.close()
    flash("Aviso removido com sucesso.", "success")
    return redirect(igreja_path("/editar"))


@app.route("/materiais/novo", methods=["POST"])
@app.route("/materiais/novo/", methods=["POST"])
@app.route("/igrejaemboavista/materiais/novo", methods=["POST"])
@app.route("/igrejaemboavista/materiais/novo/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_material_novo():
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    ok, erro = igreja_salvar_material(conn, request.form, request.files.get("arquivo_pdf"))
    conn.close()
    flash("Material cadastrado com sucesso." if ok else erro, "success" if ok else "warning")
    return redirect(igreja_path("/editar"))


@app.route("/materiais/<int:material_id>/editar", methods=["POST"])
@app.route("/materiais/<int:material_id>/editar/", methods=["POST"])
@app.route("/igrejaemboavista/materiais/<int:material_id>/editar", methods=["POST"])
@app.route("/igrejaemboavista/materiais/<int:material_id>/editar/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_material_editar(material_id):
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    ok, erro = igreja_salvar_material(conn, request.form, request.files.get("arquivo_pdf"), material_id=material_id)
    conn.close()
    flash("Material atualizado com sucesso." if ok else erro, "success" if ok else "warning")
    return redirect(igreja_path("/editar"))


@app.route("/materiais/<int:material_id>/excluir", methods=["POST"])
@app.route("/materiais/<int:material_id>/excluir/", methods=["POST"])
@app.route("/igrejaemboavista/materiais/<int:material_id>/excluir", methods=["POST"])
@app.route("/igrejaemboavista/materiais/<int:material_id>/excluir/", methods=["POST"])
@login_required
@igreja_edit_required
def igreja_material_excluir(material_id):
    if not igreja_request_permitida():
        abort(404)
    conn = get_db()
    removido = igreja_excluir_material(conn, material_id)
    conn.close()
    flash("Material removido com sucesso." if removido else "Material nao encontrado.", "success" if removido else "warning")
    return redirect(igreja_path("/editar"))


@app.route("/")
def home():
    if host_eh_conectacasa():
        return conectacasa_publico()
    if host_eh_igreja():
        return render_igreja_publico("inicio")
    if not current_user.is_authenticated:
        return render_igreja_publico("inicio")
    destino = destino_pos_login(current_user)
    return redirect(destino or url_for("logout"))


# Rota principal - Dashboard
@app.route("/dashboard")
@app.route("/dashboard/")
def dashboard():
    if host_eh_conectacasa():
        return redirect(conectacasa_path("/"))
    if not current_user.is_authenticated:
        return redirect(url_for("login", next=url_for("dashboard")))
    if not usuario_pode_acessar_inventario(current_user):
        destino = destino_pos_login(current_user)
        return redirect(destino or url_for("logout"))

    db = get_db()
    total_itens = db.execute("SELECT COUNT(*) as count FROM itens").fetchone()["count"]
    total_emprestado = db.execute("SELECT COUNT(*) as count FROM emprestimos WHERE data_devolucao IS NULL").fetchone()["count"]
    total_devolvido = db.execute("SELECT COUNT(*) as count FROM emprestimos WHERE data_devolucao IS NOT NULL").fetchone()["count"]
    
    # Dados para grÃ¡fico de itens por grupo
    itens_por_grupo_raw = db.execute("""
        SELECT g.nome as grupo_nome, COUNT(*) as count
        FROM itens i
        JOIN grupos g ON i.grupo_id = g.id
        GROUP BY g.nome
        ORDER BY count DESC
    """).fetchall()
    grupos_labels = [row["grupo_nome"] for row in itens_por_grupo_raw]
    grupos_data = [row["count"] for row in itens_por_grupo_raw]
    
    # Dados para grÃ¡fico de emprÃ©stimos (Ativos vs Devolvidos)
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
                          format_date=format_date # Passando a funÃ§Ã£o format_date
                          )

# Rotas de InventÃ¡rio
@app.route("/inventario")
@app.route("/inventario/")
@login_required
def inventario():
    db = get_db()
    
    # Obter parÃ¢metros de filtro
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
    # Convertendo itens para dicionÃ¡rios
    itens_raw = db.execute(query, params).fetchall()
    itens = [dict(row) for row in itens_raw]

    
    # Obter lista de grupos Ãºnicos para o filtro
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
            flash("DescriÃ§Ã£o e Grupo sÃ£o obrigatÃ³rios.", "danger")
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
                    # Limpar string: remover R$, remover pontos de milhar, trocar vÃ­rgula decimal por ponto
                    cleaned_valor = valor_unitario.replace("R$", "").replace(".", "").replace(",", ".").strip()
                    valor_unitario = float(cleaned_valor)
                except ValueError:
                    db.rollback()
                    flash("Valor unitÃ¡rio invÃ¡lido. Certifique-se de usar apenas nÃºmeros, ponto ou vÃ­rgula.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                valor_unitario = None
                
            # Converter data de aquisiÃ§Ã£o
            if data_aquisicao:
                try:
                    data_aquisicao = datetime.strptime(data_aquisicao, "%Y-%m-%d").date()
                    hoje = datetime.today().date()
                    if data_aquisicao > hoje:
                        db.rollback()
                        flash("A data de aquisiÃ§Ã£o nÃ£o pode ser no futuro.", "danger")
                        grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                        marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                        return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                except ValueError:
                    db.rollback()
                    flash("Data de aquisiÃ§Ã£o invÃ¡lida.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                data_aquisicao = None

            # Gerar prÃ³ximo tombamento automaticamente
            ultimo_tombamento = db.execute("SELECT MAX(CAST(tombamento AS INTEGER)) as max_tomb FROM itens WHERE tombamento REGEXP '^[0-9]+$'").fetchone()
            proximo_numero = (ultimo_tombamento["max_tomb"] or 0) + 1
            tombamento_fmt = str(proximo_numero).zfill(4)
            
            # Verificar se grupo e marca existem
            grupo = db.execute("SELECT * FROM grupos WHERE id = ?", (grupo_id,)).fetchone()
            if not grupo:
                flash("Grupo selecionado nÃ£o existe.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()                
                return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                
            if marca_id:
                marca = db.execute("SELECT * FROM marcas WHERE id = ?", (marca_id,)).fetchone()
                if not marca:
                    flash("Marca selecionada nÃ£o existe.", "danger")
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
    
    # GET request - mostrar formulÃ¡rio
    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
    
    # Gerar prÃ³ximo tombamento para exibir no formulÃ¡rio
    # Buscar todos os tombamentos e filtrar apenas os numÃ©ricos no Python
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
        flash("Item nÃ£o encontrado.", "danger")
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
            flash("DescriÃ§Ã£o e Grupo sÃ£o obrigatÃ³rios.", "danger")
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
                    # Limpar string: remover R$, remover pontos de milhar, trocar vÃ­rgula decimal por ponto
                    cleaned_valor = valor_unitario.replace("R$", "").replace(".", "").replace(",", ".").strip()
                    valor_unitario = float(cleaned_valor)
                except ValueError:
                    db.rollback()
                    flash("Valor unitÃ¡rio invÃ¡lido. Certifique-se de usar apenas nÃºmeros, ponto ou vÃ­rgula.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
            else:
                valor_unitario = None
                
            # Converter data de aquisiÃ§Ã£o
            if data_aquisicao:
                try:
                    data_aquisicao = datetime.strptime(data_aquisicao, "%Y-%m-%d").date()
                    hoje = datetime.today().date()
                    if data_aquisicao > hoje:
                        flash("A data de aquisiÃ§Ã£o nÃ£o pode ser no futuro.", "danger")
                        grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                        marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                        return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
                except ValueError:
                    db.rollback()
                    flash("Data de aquisiÃ§Ã£o invÃ¡lida.", "danger")
                    grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                    marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                    return render_template("novo_item_simples.html", form=request.form, grupos=grupos, marcas=marcas)
            else:
                data_aquisicao = None

            # Verificar se grupo e marca existem
            grupo = db.execute("SELECT * FROM grupos WHERE id = ?", (grupo_id,)).fetchone()
            if not grupo:
                flash("Grupo selecionado nÃ£o existe.", "danger")
                grupos = db.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
                marcas = db.execute("SELECT * FROM marcas ORDER BY nome").fetchall()
                return render_template("editar_item.html", item=item, grupos=grupos, marcas=marcas)
                
            if marca_id:
                marca = db.execute("SELECT * FROM marcas WHERE id = ?", (marca_id,)).fetchone()
                if not marca:
                    flash("Marca selecionada nÃ£o existe.", "danger")
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

    # GET request - mostrar formulÃ¡rio
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
            flash("Item nÃ£o encontrado.", "danger")
            return redirect(url_for("inventario"))
        
        db.execute("DELETE FROM itens WHERE id = ?", (id,))
        db.commit()
        registrar_log(f"Item excluÃ­do: {item['tombamento']} - {item['descricao']}")
        flash("Item excluÃ­do com sucesso!", "success")
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
                    flash("JÃ¡ existe um grupo com este nome.", "danger")
            else:
                flash("Nome do grupo Ã© obrigatÃ³rio.", "danger")
                
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
                    flash("JÃ¡ existe uma marca com este nome.", "danger")
            else:
                flash("Nome da marca Ã© obrigatÃ³rio.", "danger")
                
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
                    flash("JÃ¡ existe um grupo com este nome.", "danger")
            else:
                flash("Dados invÃ¡lidos para ediÃ§Ã£o.", "danger")
                
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
                    flash("JÃ¡ existe uma marca com este nome.", "danger")
            else:
                flash("Dados invÃ¡lidos para ediÃ§Ã£o.", "danger")
                
        elif acao == "excluir_grupo":
            id_grupo = request.form.get("id")
            if id_grupo:
                # Verificar se hÃ¡ itens usando este grupo
                itens_usando = db.execute("SELECT COUNT(*) as count FROM itens WHERE grupo_id = ?", (id_grupo,)).fetchone()
                if itens_usando["count"] > 0:
                    flash("NÃ£o Ã© possÃ­vel excluir o grupo pois hÃ¡ itens cadastrados nele.", "danger")
                else:
                    grupo = db.execute("SELECT nome FROM grupos WHERE id = ?", (id_grupo,)).fetchone()
                    db.execute("DELETE FROM grupos WHERE id = ?", (id_grupo,))
                    db.commit()
                    registrar_log(f"Grupo excluÃ­do: {grupo['nome']}")
                    db.commit()
                    flash("Grupo excluÃ­do com sucesso!", "success")
            else:
                flash("ID do grupo invÃ¡lido.", "danger")
                
        elif acao == "excluir_marca":
            id_marca = request.form.get("id")
            if id_marca:
                # Verificar se hÃ¡ itens usando esta marca
                itens_usando = db.execute("SELECT COUNT(*) as count FROM itens WHERE marca_id = ?", (id_marca,)).fetchone()
                if itens_usando["count"] > 0:
                    flash("NÃ£o Ã© possÃ­vel excluir a marca pois hÃ¡ itens cadastrados nela.", "danger")
                else:
                    marca = db.execute("SELECT nome FROM marcas WHERE id = ?", (id_marca,)).fetchone()
                    db.execute("DELETE FROM marcas WHERE id = ?", (id_marca,))
                    db.commit()
                    registrar_log(f"Marca excluÃ­da: {marca['nome']}")
                    db.commit()
                    flash("Marca excluÃ­da com sucesso!", "success")
            else:
                flash("ID da marca invÃ¡lido.", "danger")
        
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

# Rotas de EmprÃ©stimos
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
            flash("Dados do solicitante sÃ£o obrigatÃ³rios.", "danger")
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
                    flash(f"Item com ID {item_id} nÃ£o encontrado.", "danger")
                    erro_validacao = True
                    break
                
                if item_db["quantidade"] < quantidade:
                    flash(f"Quantidade insuficiente para o item {item_db['tombamento']} ({item_db['descricao']}). DisponÃ­vel: {item_db['quantidade']}", "danger")
                    erro_validacao = True
                    break
                # Evita duplicaÃ§Ã£o do mesmo item_id
                if any(i["id"] == item_id for i in itens_para_emprestar):
                   flash(f"O item {item_db['tombamento']} jÃ¡ foi adicionado ao formulÃ¡rio. Evite duplicar.", "warning")
                   continue
                itens_para_emprestar.append({"id": item_id, "quantidade": quantidade, "tombamento": item_db["tombamento"], "estoque_atual": item_db["quantidade"]})
            
            if erro_validacao:
                 return redirect(url_for("emprestimos"))

            # Criar o registro principal do emprÃ©stimo
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
            
            registrar_log(f"EmprÃ©stimo ID {emprestimo_id} registrado para {nome} - Itens: {', '.join(log_itens_str)}")
            db.commit()
            flash("EmprÃ©stimo registrado com sucesso!", "success")
            return redirect(url_for("emprestimos"))
            
        except ValueError:
            db.rollback()
            flash("Quantidade invÃ¡lida para um dos itens.", "danger")
            return redirect(url_for("emprestimos"))
        except Exception as e:
            db.rollback()
            db.rollback() # Desfaz alteraÃ§Ãµes em caso de erro
            flash(f"Erro ao registrar emprÃ©stimo: {str(e)}", "danger")
            return redirect(url_for("emprestimos"))

    # Listar emprÃ©stimos (GET)
    # Precisa ajustar a consulta para lidar com mÃºltiplos itens
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
        # Verificar se o emprÃ©stimo existe e nÃ£o foi devolvido
        emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
        if not emprestimo:
            flash("EmprÃ©stimo nÃ£o encontrado.", "danger")
            return redirect(url_for("emprestimos"))
        
        if emprestimo["data_devolucao"]:
            flash("Este emprÃ©stimo jÃ¡ foi devolvido.", "warning")
            return redirect(url_for("emprestimos"))
        
        # Buscar todos os itens associados a este emprÃ©stimo
        itens_emprestados = db.execute("""
            SELECT ei.item_id, ei.quantidade, i.tombamento, i.quantidade as estoque_atual
            FROM emprestimo_itens ei
            JOIN itens i ON ei.item_id = i.id
            WHERE ei.emprestimo_id = ?
        """, (id,)).fetchall()
        
        if not itens_emprestados:
             flash("Nenhum item encontrado para este emprÃ©stimo. Contate o administrador.", "danger")
             return redirect(url_for("emprestimos"))

        # Atualizar data de devoluÃ§Ã£o no emprÃ©stimo principal
        db.execute("UPDATE emprestimos SET data_devolucao = ? WHERE id = ?", (datetime.now(), id))
        
        log_itens_str = []
        # Atualizar quantidade de cada item devolvido
        for item_info in itens_emprestados:
            nova_quantidade_estoque = item_info["estoque_atual"] + item_info["quantidade"]
            db.execute("UPDATE itens SET quantidade = ? WHERE id = ?", (nova_quantidade_estoque, item_info["item_id"]))
            log_itens_str.append(f"{item_info['quantidade']}x {item_info['tombamento']}")

        db.commit()
        
        registrar_log(f"DevoluÃ§Ã£o do EmprÃ©stimo ID {id} registrada - Itens: {', '.join(log_itens_str)}")
        db.commit()
        flash("DevoluÃ§Ã£o registrada com sucesso!", "success")
        
    except Exception as e:
        db.rollback()
        flash(f"Erro ao registrar devoluÃ§Ã£o: {str(e)}", "danger")
    
    return redirect(url_for("emprestimos"))

@app.route("/emprestimos/desfazer/<int:id>", methods=["GET", "POST"])
@app.route("/emprestimos/desfazer/<int:id>/", methods=["GET", "POST"])
@login_required
@admin_required
def desfazer_devolucao(id):
    db = get_db()
    # Busca dados do emprÃ©stimo principal
    emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
    
    if not emprestimo:
        flash("EmprÃ©stimo nÃ£o encontrado.", "danger")
        return redirect(url_for("emprestimos"))
    
    if not emprestimo["data_devolucao"]:
        flash("Este emprÃ©stimo ainda nÃ£o foi devolvido.", "warning")
        return redirect(url_for("emprestimos"))

    # Busca os itens associados para exibiÃ§Ã£o no template (mesmo que a lÃ³gica mude)
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
            flash("A justificativa Ã© obrigatÃ³ria.", "danger")
            return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
        
        try:
            # Buscar todos os itens que foram devolvidos neste emprÃ©stimo
            itens_a_reativar = db.execute("""
                SELECT ei.item_id, ei.quantidade, i.tombamento, i.quantidade as estoque_atual
                FROM emprestimo_itens ei
                JOIN itens i ON ei.item_id = i.id
                WHERE ei.emprestimo_id = ?
            """, (id,)).fetchall()

            if not itens_a_reativar:
                 flash("Nenhum item encontrado para este emprÃ©stimo. Contate o administrador.", "danger")
                 return redirect(url_for("emprestimos"))

            # Verificar se hÃ¡ estoque suficiente para remover novamente
            erro_estoque = False
            for item_info in itens_a_reativar:
                if item_info["estoque_atual"] < item_info["quantidade"]:
                    flash(f"Quantidade insuficiente para reativar emprÃ©stimo do item {item_info['tombamento']}. DisponÃ­vel: {item_info['estoque_atual']}", "danger")
                    erro_estoque = True
                    break
            
            if erro_estoque:
                return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)

            # Atualizar emprÃ©stimo principal (remover data de devoluÃ§Ã£o)
            db.execute("UPDATE emprestimos SET data_devolucao = NULL WHERE id = ?", (id,))
            
            log_itens_str = []
            # Atualizar quantidade de cada item (remover do estoque)
            for item_info in itens_a_reativar:
                nova_quantidade_estoque = item_info["estoque_atual"] - item_info["quantidade"]
                db.execute("UPDATE itens SET quantidade = ? WHERE id = ?", (nova_quantidade_estoque, item_info["item_id"]))
                log_itens_str.append(f"{item_info['quantidade']}x {item_info['tombamento']}")
            
            # Registrar justificativa no log
            registrar_log(f"DevoluÃ§Ã£o do EmprÃ©stimo ID {id} desfeita - Itens: {', '.join(log_itens_str)} - Justificativa: {justificativa}")
            
            db.commit()
            
            flash("DevoluÃ§Ã£o desfeita com sucesso!", "success")
            return redirect(url_for("emprestimos"))
            
        except Exception as e:
            db.rollback()
            flash(f"Erro ao desfazer devoluÃ§Ã£o: {str(e)}", "danger")
            return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
    
    # MÃ©todo GET
    return render_template("desfazer_devolucao_simples.html", emprestimo=emprestimo_dict, format_date=format_date)
@app.route("/emprestimos/excluir/<int:id>", methods=["POST"])
@login_required
@admin_required
def excluir_emprestimo(id):
    db = get_db()
    try:
        emprestimo = db.execute("SELECT * FROM emprestimos WHERE id = ?", (id,)).fetchone()
        if not emprestimo:
            flash("EmprÃ©stimo nÃ£o encontrado.", "danger")
            return redirect(url_for("emprestimos"))
        
        # Apagar itens associados
        db.execute("DELETE FROM emprestimo_itens WHERE emprestimo_id = ?", (id,))
        # Apagar o emprÃ©stimo principal
        db.execute("DELETE FROM emprestimos WHERE id = ?", (id,))
        db.commit()
        
        registrar_log(f"EmprÃ©stimo ID {id} excluÃ­do pelo admin.")
        flash("EmprÃ©stimo excluÃ­do com sucesso.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir emprÃ©stimo: {str(e)}", "danger")
    
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
        flash("EmprÃ©stimo nÃ£o encontrado.", "danger")
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
        flash("Nenhum item encontrado para este emprÃ©stimo.", "danger")
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
            corrigir_mojibake_texto(item["tombamento"]),
            corrigir_mojibake_texto(item["descricao"]),
            corrigir_mojibake_texto(item["marca"]),
            corrigir_mojibake_texto(item["item_grupo"]),
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
        ["Nome:", corrigir_mojibake_texto(emprestimo_base["nome"])],
        ["Grupo:", corrigir_mojibake_texto(emprestimo_base["grupo_caseiro"] or "")],
        ["Contato:", corrigir_mojibake_texto(emprestimo_base["contato"] or "")]
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

# Rotas de RelatÃ³rios
@app.route("/relatorios", methods=["GET", "POST"])
@app.route("/relatorios/", methods=["GET", "POST"])
@login_required
def relatorios():
    db = get_db()
    grupo_select = emprestimos_grupo_select_sql(db)
    grupo_join = emprestimos_grupo_join_sql(db)
    
    # Obter parÃ¢metros de filtro
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

    # Filtro para emprÃ©stimos
    where_clauses_emprestimos = []
    params_emprestimos = []

    if filtro_data_inicio:
        where_clauses_emprestimos.append("date(e.data_emprestimo) >= date(?)")
        params_emprestimos.append(filtro_data_inicio)

    if filtro_data_fim:
        where_clauses_emprestimos.append("date(e.data_emprestimo) <= date(?)")
        params_emprestimos.append(filtro_data_fim)

    # Consultar emprÃ©stimos (com itens agrupados)
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
         # âœ… Adicione estas linhas AQUI
        if where_clauses_emprestimos:
            query_emprestimos += " WHERE " + " AND ".join(where_clauses_emprestimos)

        query_emprestimos += " GROUP BY e.id ORDER BY e.data_emprestimo DESC"

        # âœ… Agora execute a query
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

    # Carregar grupos disponÃ­veis
# Carregar grupos disponÃ­veis corretamente da tabela `grupos`
    grupos_disponiveis = [row['nome'] for row in db.execute("SELECT nome FROM grupos WHERE nome IS NOT NULL AND nome != '' ORDER BY nome").fetchall()]

    formato = request.args.get("formato", "")  # âœ… fora do render_template

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
        writer.writerow(["INVENTÃRIO - ITENS"])
        writer.writerow(["Tombamento", "DescriÃ§Ã£o", "Grupo", "Marca", "Valor", "Qtd"])
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

    # Exportar emprÃ©stimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        writer.writerow(["EMPRÃ‰STIMOS"])
        writer.writerow(["Data EmprÃ©stimo", "Data DevoluÃ§Ã£o", "Item (Tombamento)", "DescriÃ§Ã£o", "Qtd", "ResponsÃ¡vel", "Contato", "Status"])
        for e in emprestimos:
            writer.writerow([
                format_date(e["data_emprestimo"]),
                format_date(e["data_devolucao"]) if e["data_devolucao"] else "NÃ£o devolvido",
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
        elements.append(Paragraph(corrigir_mojibake_texto(grupo_nome), ParagraphStyle(name="Grupo", alignment=1, fontSize=12)))
        elements.append(Spacer(1, 0.1*inch))

        # Tabela de itens do grupo
        data = [["Tombamento", "Descrição", "Marca", "Qtd", "Valor (R$)"]]
        total = 0
        for i in itens_grupo:
            valor = i["valor_unitario"] or 0
            subtotal = valor * i["quantidade"]
            data.append([
                corrigir_mojibake_texto(i["tombamento"]),
                Paragraph(corrigir_mojibake_texto(i["descricao"]), descricao_style),
                corrigir_mojibake_texto(i["marca"] or ""),
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
            f"<b>Resumo financeiro:</b> O valor total de todos os itens inventariados neste relatório é de <b>{formata_brl(total_geral)}</b>.",
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
                    "-", "-", "-", corrigir_mojibake_texto(emp["nome"]), "Devolvido" if emp["data_devolucao"] else "Ativo"
                ])
            else:
                for i in range(max_itens):
                    data_emprestimos_pdf.append([
                        format_date(emp["data_emprestimo"]) if i == 0 else "",
                        format_date(emp["data_devolucao"]) if i == 0 and emp["data_devolucao"] else "-" if i == 0 else "",
                        corrigir_mojibake_texto(tombamentos[i] if i < len(tombamentos) else ""),
                        Paragraph(corrigir_mojibake_texto(emp["descricoes"][i] if i < len(emp["descricoes"]) else ""), descricao_style),
                        quantidades[i] if i < len(quantidades) else "",
                        Paragraph(corrigir_mojibake_texto(emp["nome"]), responsavel_style) if i == 0 else "",
                        "Devolvido" if emp["data_devolucao"] else "Ativo" if i == 0 else ""
                    ])

        table_emp = Table(data_emprestimos_pdf, colWidths=[
            1.0*inch, 1.0*inch, 1.0*inch, 2.0*inch, 0.4*inch, 0.8*inch, 0.8*inch
        ])
        table_emp.setStyle(table_style)
        elements.append(table_emp)
        elements.append(Spacer(1, 0.2*inch))

    # Data de geração do documento
    elements.append(Spacer(1, 0.4 * inch))
    elements.append(Paragraph(f"<b>Documento gerado em:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))

    # Assinatura
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
    
    # InformaÃ§Ãµes do filtro
    filtro_info = []
    if filtro_grupo:
        filtro_info.append(f"Grupo: {filtro_grupo}")
    if filtro_tipo != "todos":
        filtro_info.append(f"Tipo: {filtro_tipo.capitalize()}")
    if filtro_data_inicio:
        filtro_info.append(f"Data InÃ­cio: {format_date(filtro_data_inicio)}")
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
                <th>DescriÃ§Ã£o</th>
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

                
    # Exportar emprÃ©stimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        html_content += """
        <h2>EMPRÃ‰STIMOS</h2>
        <table>
            <tr>
                <th>Data Emp.</th>
                <th>Data Dev.</th>
                <th>Item (Tomb.)</th>
                <th>DescriÃ§Ã£o</th>
                <th>Qtd</th>
                <th>ResponsÃ¡vel</th>
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
            
            # RodapÃ©
            html_content += f"""
                <div class="footer">
                    <p>OAIBV â€“ OrganizaÃ§Ã£o e Apoio Ã  Igreja em Boa Vista</p>
                    <p>RelatÃ³rio gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
                </div>
            </body>
            </html>
            """
    
    # Salvar o HTML em um arquivo temporÃ¡rio
    # Usar um nome de arquivo temporÃ¡rio seguro
    temp_fd, temp_html_path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(temp_fd, "wb") as f:
        f.write(html_content.encode("utf-8"))
    
    # Ler o conteÃºdo do arquivo HTML
    with open(temp_html_path, "rb") as f:
        html_data = f.read()
    
    # Limpar o arquivo temporÃ¡rio
    os.unlink(temp_html_path)

# Rotas de UsuÃ¡rios
@app.route("/usuarios")
@app.route("/usuarios/")
@login_required
def usuarios():
    pode_gerenciar_usuarios = usuario_pode_gerenciar_usuarios(current_user)
    if not pode_gerenciar_usuarios:
        return redirect(url_for("meu_usuario"))
    db = get_db()
    usuarios = db.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()
    total_pendentes = sum(1 for usuario in usuarios if not int(usuario["ativo"]))
    return render_template(
        "usuarios_admin.html",
        usuarios=usuarios,
        pode_gerenciar_usuarios=pode_gerenciar_usuarios,
        total_pendentes=total_pendentes,
    )

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


@app.route("/usuarios/limpar-pendentes", methods=["POST"])
@login_required
@admin_required
def limpar_usuarios_pendentes():
    db = get_db()
    try:
        total = db.execute(
            """
            SELECT COUNT(1) AS total
            FROM usuarios
            WHERE ativo = 0 AND lower(usuario) <> 'admin'
            """
        ).fetchone()["total"]
        db.execute(
            """
            DELETE FROM usuarios
            WHERE ativo = 0 AND lower(usuario) <> 'admin'
            """
        )
        db.commit()
        registrar_log(f"Limpeza de usuarios pendentes: {total} registro(s) removido(s)")
        flash(f"{total} usuario(s) pendente(s) removido(s).", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao limpar usuarios pendentes: {str(e)}", "danger")
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
            # Verificar se usuÃ¡rio ou e-mail jÃ¡ existem
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
            
            registrar_log(f"UsuÃ¡rio cadastrado: {nome} ({usuario})")
            db.commit()
            flash("UsuÃ¡rio cadastrado com sucesso!", "success")
            return redirect(url_for("usuarios"))
            
        except Exception as e:
            flash(f"Erro ao cadastrar usuÃ¡rio: {str(e)}", "danger")
    
    return render_template("novo_usuario_simples.html")

@app.route("/usuarios/editar/<int:id>", methods=["GET", "POST"])
@app.route("/usuarios/editar/<int:id>/", methods=["GET", "POST"])
@login_required
@admin_required
def editar_usuario(id):
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (id,)).fetchone()
    eh_proprio_usuario = False

    if not usuario:
        flash("Usuario nao encontrado.", "danger")
        return redirect(url_for("usuarios"))

    if int(usuario["id"]) == int(current_user.id):
        return redirect(url_for("meu_usuario"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        usuario_login = usuario["usuario"]
        email = usuario["email"]
        tipo = "admin" if request.form.get("tipo") == "admin" else "comum"
        pode_acessar_inventario = 1 if request.form.get("pode_acessar_inventario") == "1" else 0
        pode_editar_igreja = 1 if request.form.get("pode_editar_igreja") == "1" else 0

        if not nome:
            flash("O nome do usuario e obrigatorio.", "danger")
            return render_template(
                "editar_usuario_simples.html",
                usuario=usuario,
                eh_proprio_usuario=eh_proprio_usuario,
                pode_gerenciar_usuarios=True,
            )

        try:
            db.execute(
                """
                UPDATE usuarios
                SET nome = ?, usuario = ?, email = ?, tipo = ?, pode_acessar_inventario = ?, pode_editar_igreja = ?
                WHERE id = ?
                """,
                (nome, usuario_login, email, tipo, pode_acessar_inventario, pode_editar_igreja, id),
            )
            db.commit()
            registrar_log(f"Usuario editado: {nome} ({usuario_login})")
            db.commit()
            flash("Usuario atualizado com sucesso.", "success")
            return redirect(url_for("usuarios"))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar usuario: {str(e)}", "danger")

    return render_template(
        "editar_usuario_simples.html",
        usuario=usuario,
        eh_proprio_usuario=eh_proprio_usuario,
        pode_gerenciar_usuarios=True,
    )

@app.route("/usuarios/excluir/<int:id>", methods=["POST"])
@login_required
@admin_required
def excluir_usuario(id):
    db = get_db()
    if id == current_user.id:
        flash("VocÃª nÃ£o pode excluir a si mesmo.", "warning")
        return redirect(url_for("usuarios"))
    try:
        usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (id,)).fetchone()
        if not usuario:
            flash("UsuÃ¡rio nÃ£o encontrado.", "danger")
            return redirect(url_for("usuarios"))

        db.execute("DELETE FROM usuarios WHERE id = ?", (id,))
        db.commit()
        registrar_log(f"UsuÃ¡rio excluÃ­do: {usuario['nome']} ({usuario['usuario']})")
        flash("UsuÃ¡rio excluÃ­do com sucesso!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao excluir usuÃ¡rio: {str(e)}", "danger")
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

# Criar tabelas se nÃ£o existirem
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

    adicionar_coluna_se_faltar(conn, "itens", "valor", "REAL")

    conn.commit()
    conn.close()
    
if __name__ == "__main__":
    # Criar banco de dados e tabelas se nÃ£o existirem
    # A funÃ§Ã£o create_tables agora tambÃ©m cria o admin e adiciona a coluna valor
    with app.app_context():
        create_tables()
    
    pass  # debug run removed for safety

