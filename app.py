from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json
import os
from forms import AbordadoForm, VeiculoForm, ParenteForm, AbordagemForm
import re
from werkzeug.utils import secure_filename
import uuid
import pickle
import os.path
from datetime import datetime, timedelta
from threading import Lock
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua-chave-secreta-aqui'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

# Criar pasta de uploads se não existir
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class SheetsCache:
    def __init__(self, cache_duration=300):  # 5 minutos de cache por padrão
        self.cache = {}
        self.cache_duration = cache_duration
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                data, timestamp = self.cache[key]
                if datetime.now() - timestamp < timedelta(seconds=self.cache_duration):
                    return data
                else:
                    del self.cache[key]
            return None

    def set(self, key, data):
        with self.lock:
            self.cache[key] = (data, datetime.now())

    def invalidate(self, key=None):
        with self.lock:
            if key is None:
                self.cache.clear()
            elif key in self.cache:
                del self.cache[key]

# Instanciar o cache global
sheets_cache = SheetsCache()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file, is_profile=False):
    try:
        # Ler o arquivo como base64
        file_content = file.read()
        base64_content = base64.b64encode(file_content).decode('utf-8')
        
        # Obter o tipo MIME do arquivo
        mime_type = file.content_type
        
        # Retornar a URL de dados base64
        return f'data:{mime_type};base64,{base64_content}'
        
    except Exception as e:
        print(f'ERRO ao converter arquivo para base64: {str(e)}')
        return None

# Configurações do Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1S5N-VtBnzHV_Iq4eYDzvGSo3YnTqmWDDnZF_BLBqxAE'

def get_google_sheets_service():
    creds = None
    try:
        # Tentar carregar credenciais do ambiente
        token_str = os.environ.get('GOOGLE_TOKEN')
        if not token_str:
            print("ERRO: Variável GOOGLE_TOKEN não encontrada no ambiente")
            return None
            
        try:
            # Remover possíveis espaços em branco
            token_str = token_str.strip()
            
            # Tentar decodificar o token base64
            token_bytes = base64.b64decode(token_str)
            creds = pickle.loads(token_bytes)
            print("Token carregado com sucesso do formato base64/pickle")
            
        except Exception as e:
            print(f"ERRO ao decodificar token base64: {str(e)}")
            print(f"Primeiros 100 caracteres do token: {token_str[:100]}")
            return None
            
        if not creds or not isinstance(creds, Credentials):
            print(f"ERRO: Token inválido. Tipo recebido: {type(creds)}")
            return None
            
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                print("Credenciais expiradas, tentando renovar...")
                try:
                    creds.refresh(Request())
                    print("Credenciais renovadas com sucesso")
                except Exception as e:
                    print(f"ERRO ao renovar credenciais: {str(e)}")
                    return None
            else:
                print("ERRO: Credenciais inválidas e não foi possível renovar")
                return None
                
        try:
            service = build('sheets', 'v4', credentials=creds)
            print("Serviço do Google Sheets criado com sucesso")
            return service
        except Exception as e:
            print(f"ERRO ao criar serviço do Google Sheets: {str(e)}")
            return None
        
    except Exception as e:
        print(f"ERRO ao configurar serviço do Google Sheets: {str(e)}")
        return None

@app.route('/')
def index():
    abordados = get_abordados()
    return render_template('index.html', abordados=abordados)

@app.route('/novo_abordado')
def novo_abordado():
    form = AbordadoForm()
    return render_template('novo.html', form=form)

@app.route('/nova_abordagem')
def nova_abordagem():
    form = AbordagemForm()
    return render_template('nova_abordagem.html', form=form)

@app.route('/adicionar_veiculo/<int:abordado_id>')
def adicionar_veiculo(abordado_id):
    form = VeiculoForm()
    return render_template('adicionar_veiculo.html', form=form, abordado_id=abordado_id)

@app.route('/adicionar_parente/<int:abordado_id>')
def adicionar_parente(abordado_id):
    form = ParenteForm()
    return render_template('adicionar_parente.html', form=form, abordado_id=abordado_id)

@app.route('/editar_abordado/<int:abordado_id>')
def editar_abordado(abordado_id):
    form = AbordadoForm()
    abordado = buscar_abordado_por_id(abordado_id)
    if abordado:
        return render_template('editar_abordado.html', form=form, abordado=abordado)
    return redirect(url_for('index'))

def buscar_abordado_por_id(abordado_id):
    try:
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordados!A:M'
        ).execute()
        
        if not result.get('values'):
            return None
            
        for row in result.get('values')[1:]:
            if row and row[0] == str(abordado_id):
                return {
                    'ID': row[0],
                    'Nome': row[1],
                    'Mae': row[2] if len(row) > 2 else '',
                    'Pai': row[3] if len(row) > 3 else '',
                    'Nascimento': row[4] if len(row) > 4 else '',
                    'RG': row[5] if len(row) > 5 else '',
                    'CPF': row[6] if len(row) > 6 else '',
                    'Endereço': row[7] if len(row) > 7 else '',
                    'Telefone': row[8] if len(row) > 8 else '',
                    'Foto Perfil': row[9] if len(row) > 9 else '',
                    'Fotos': row[10].split(';') if len(row) > 10 and row[10] else [],
                    'Anotações': row[12] if len(row) > 12 else ''
                }
        return None
        
    except Exception as e:
        print(f'ERRO ao buscar abordado: {str(e)}')
        return None

def get_abordados():
    try:
        # Tentar obter do cache primeiro
        cached_data = sheets_cache.get('abordados')
        if cached_data is not None:
            return cached_data

        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordados!A:M'
        ).execute()
        
        if not result.get('values'):
            return []
            
        # Pular o cabeçalho
        abordados = []
        for row in result.get('values')[1:]:
            if row and len(row) >= 2 and row[0].strip() and row[1].strip():
                foto_perfil = row[9] if len(row) > 9 else ''
                fotos = row[10] if len(row) > 10 else ''
                
                # Tratar as fotos - dividir por ponto e vírgula
                fotos_lista = [f.strip() for f in fotos.split(';')] if fotos else []
                
                abordado = {
                    'ID': row[0],
                    'Nome': row[1],
                    'Mae': row[2] if len(row) > 2 else '',
                    'Pai': row[3] if len(row) > 3 else '',
                    'Nascimento': row[4] if len(row) > 4 else '',
                    'RG': row[5] if len(row) > 5 else '',
                    'CPF': row[6] if len(row) > 6 else '',
                    'Endereço': row[7] if len(row) > 7 else '',
                    'Telefone': row[8] if len(row) > 8 else '',
                    'Foto Perfil': foto_perfil,
                    'Fotos': fotos_lista,
                    'Anotações': row[12] if len(row) > 12 else '',
                    'Parentes': [],
                    'Veiculos': [],
                    'Abordagens': []
                }
                
                abordados.append(abordado)

        # Salvar no cache
        sheets_cache.set('abordados', abordados)
        return abordados
        
    except Exception as e:
        print(f'ERRO ao buscar abordados: {str(e)}')
        return [] 