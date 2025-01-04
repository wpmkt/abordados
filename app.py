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
        if file and allowed_file(file.filename):
            print(f"DEBUG - Salvando arquivo: {file.filename}")
            # Gera um nome único para o arquivo
            filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
            print(f"DEBUG - Nome gerado para o arquivo: {filename}")
            
            # Cria diretório se não existir
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
                print(f"DEBUG - Diretório criado: {app.config['UPLOAD_FOLDER']}")
            
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            print(f"DEBUG - Caminho completo do arquivo: {filepath}")
            
            # Salva o arquivo
            file.save(filepath)
            print(f"DEBUG - Arquivo salvo com sucesso em: {filepath}")
            
            # Retorna o caminho relativo para o arquivo usando barras normais
            return '/static/uploads/' + filename
        else:
            print(f"DEBUG - Arquivo inválido: {file.filename if file else 'None'}")
            return None
    except Exception as e:
        print(f"ERRO ao salvar arquivo: {str(e)}")
        import traceback
        print(f"Traceback completo: {traceback.format_exc()}")
        return None

@app.route('/upload_foto', methods=['POST'])
def upload_foto():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
    
    filepath = save_uploaded_file(file)
    if filepath:
        return jsonify({'url': filepath})
    
    return jsonify({'error': 'Tipo de arquivo não permitido'}), 400

# Configuração do Google Sheets
SPREADSHEET_ID = '1zFWzO-5Gz8HLazjM1k8FoybW5OqX3LCM28pcdmQWQHw'
RANGE_NAME = 'Abordados!A:Z'

# Se modificar esses escopos, delete o arquivo token.pickle
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds = None
    # O arquivo token.pickle armazena os tokens de acesso e atualização do usuário
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # Se não houver credenciais válidas disponíveis, deixe o usuário fazer login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Salva as credenciais para a próxima execução
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('sheets', 'v4', credentials=creds)

def converter_url_drive(url):
    if not url:
        return url
        
    # Remove possíveis espaços em branco
    url = url.strip()
    
    # Verifica se é uma URL do Google Drive
    if 'drive.google.com' in url:
        # Tenta encontrar o ID do arquivo em diferentes formatos de URL do Drive
        file_id = None
        
        # Formato: /file/d/ID/
        file_match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if file_match:
            file_id = file_match.group(1)
            
        # Formato: id=ID
        if not file_id:
            id_match = re.search(r'id=([a-zA-Z0-9_-]+)', url)
            if id_match:
                file_id = id_match.group(1)
                
        # Formato: /d/ID/
        if not file_id:
            d_match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
            if d_match:
                file_id = d_match.group(1)
        
        if file_id:
            # Remove qualquer parâmetro adicional do ID
            file_id = file_id.split('?')[0].split('/')[0]
            # Retorna URL de visualização direta
            return f'https://lh3.googleusercontent.com/d/{file_id}'
    
    return url

def get_abordados_relacionados(abordado_id):
    try:
        # Tentar obter do cache primeiro
        cache_key = f'relacionados_{abordado_id}'
        cached_data = sheets_cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordagens!A:D'  # ID, Data/hora, Local, Abordados
        ).execute()
        
        if not result.get('values'):
            return []
            
        abordagens = result.get('values')[1:]
        abordados_relacionados = []
        
        for abordagem in abordagens:
            if len(abordagem) >= 4:
                abordados_ids = abordagem[3].split(';')
                if str(abordado_id) in abordados_ids:
                    data_hora = abordagem[1] if len(abordagem) > 1 else ''
                    local = abordagem[2] if len(abordagem) > 2 else ''
                    for outro_id in abordados_ids:
                        if outro_id and outro_id != str(abordado_id):
                            try:
                                index = int(outro_id) + 1
                                result = sheet.values().get(
                                    spreadsheetId=SPREADSHEET_ID,
                                    range=f'Abordados!A{index}:J{index}'
                                ).execute()
                                
                                if result.get('values'):
                                    abordado_data = result.get('values')[0]
                                    abordados_relacionados.append({
                                        'id': abordado_data[0],
                                        'nome': abordado_data[1],
                                        'foto_perfil': abordado_data[9] if len(abordado_data) > 9 else '',
                                        'data_hora': data_hora,
                                        'local': local
                                    })
                            except Exception as e:
                                print(f'Erro ao buscar dados do abordado {outro_id}: {str(e)}')
                                continue

        # Salvar no cache
        sheets_cache.set(cache_key, abordados_relacionados)
        return abordados_relacionados
        
    except Exception as e:
        print(f'ERRO ao buscar abordados relacionados: {str(e)}')
        return []

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
        for row in result.get('values')[1:]:  # Pula a primeira linha (cabeçalho)
            if row and len(row) >= 2 and row[0].strip() and row[1].strip():
                foto_original = row[9] if len(row) > 9 else ''
                foto_convertida = foto_original.replace('\\', '/') if foto_original else ''
                
                abordado = {
                    'ID': row[0],
                    'Nome': row[1],
                    'Mae': row[2] if len(row) > 2 else '',
                    'Pai': row[3] if len(row) > 3 else '',
                    'Nascimento': row[4] if len(row) > 4 else '',
                    'RG': row[5] if len(row) > 5 else '',
                    'CPF': row[6] if len(row) > 6 else '',
                    'Endereço': row[7] if len(row) > 7 else '',
                    'Fotos': row[8] if len(row) > 8 else '',
                    'Foto Perfil': foto_convertida,
                    'Anotações': row[11] if len(row) > 11 else '',
                    'Parentes': [],  # Lista vazia para manter compatibilidade
                    'Veiculos': [],  # Lista vazia para manter compatibilidade
                    'Abordados Relacionados': []  # Vamos carregar sob demanda
                }
                
                abordados.append(abordado)

        # Salvar no cache
        sheets_cache.set('abordados', abordados)
        return abordados
        
    except Exception as e:
        print(f'ERRO ao buscar abordados: {str(e)}')
        return []

def adicionar_abordado(dados):
    try:
        result = adicionar_abordado_interno(dados)
        if result:
            # Invalidar cache após adicionar
            sheets_cache.invalidate('abordados')
            # Forçar uma nova leitura para atualizar o cache
            get_abordados()
        return result
    except Exception as e:
        print(f'ERRO ao adicionar abordado: {str(e)}')
        return None

def adicionar_abordado_interno(dados):
    try:
        print("DEBUG - Iniciando adição de abordado")
        print("DEBUG - Dados recebidos:", dados)
        
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Buscar todos os IDs existentes
        print("DEBUG - Buscando último ID")
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordados!A:A'  # Coluna A contém os IDs
        ).execute()
        
        valores = result.get('values', [])
        if not valores:
            proximo_id = "1"
        else:
            # Encontrar o último ID numérico válido
            ultimo_id = 0
            for row in valores[1:]:  # Pula o cabeçalho
                if row and row[0].isdigit():
                    id_atual = int(row[0])
                    if id_atual > ultimo_id:
                        ultimo_id = id_atual
            proximo_id = str(ultimo_id + 1)
        
        print("DEBUG - Próximo ID:", proximo_id)
        
        # Preparar os dados para inserção
        valores = [[
            proximo_id,
            dados.get('nome', ''),
            dados.get('mae', ''),
            dados.get('pai', ''),
            dados.get('nascimento', ''),
            dados.get('rg', ''),
            dados.get('cpf', ''),
            dados.get('endereco', ''),
            dados.get('fotos', ''),
            dados.get('foto_perfil', ''),
            dados.get('telefone', ''),
            dados.get('anotacoes', '')
        ]]
        
        print("DEBUG - Valores preparados para inserção:", valores)
        
        try:
            # Inserir na próxima linha disponível
            result = sheet.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='Abordados!A2',  # Começa após o cabeçalho
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body={'values': valores}
            ).execute()
            
            print("DEBUG - Resultado da inserção:", result)
            
            # Verificar se a inserção foi bem-sucedida
            if 'updates' in result and result['updates']['updatedRows'] > 0:
                print(f"DEBUG - Abordado inserido com sucesso. ID: {proximo_id}")
                return proximo_id
            else:
                print("DEBUG - Falha ao inserir abordado. Nenhuma linha atualizada.")
                return None
                
        except Exception as e:
            print(f"DEBUG - Erro ao inserir abordado: {str(e)}")
            import traceback
            print(f"Traceback completo: {traceback.format_exc()}")
            return None
        
    except Exception as e:
        print(f'ERRO DETALHADO ao adicionar abordado: {str(e)}')
        print(f'Tipo do erro: {type(e).__name__}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return None

@app.route('/')
def index():
    abordados = get_abordados()
    return render_template('index.html', abordados=abordados)

@app.route('/novo', methods=['GET', 'POST'])
def novo_abordado():
    form = AbordadoForm()
    return_to = request.args.get('return_to')
    
    if form.validate_on_submit():
        try:
            print("DEBUG - Iniciando processamento do formulário")
            
            # Processar foto de perfil
            foto_perfil_url = ''
            if 'foto_perfil' in request.files:
                file = request.files['foto_perfil']
                if file and file.filename != '':
                    print("DEBUG - Processando foto de perfil:", file.filename)
                    foto_perfil_url = save_uploaded_file(file, is_profile=True)
                    foto_perfil_url = foto_perfil_url.replace('\\', '/')
                    print("DEBUG - URL da foto de perfil:", foto_perfil_url)
            
            # Processar fotos adicionais
            fotos_urls = []
            if 'fotos' in request.files:
                files = request.files.getlist('fotos')
                print("DEBUG - Número de fotos adicionais:", len(files))
                for file in files:
                    if file and file.filename != '':
                        print("DEBUG - Processando foto adicional:", file.filename)
                        url = save_uploaded_file(file)
                        if url:
                            url = url.replace('\\', '/')
                            fotos_urls.append(url)
                            print("DEBUG - URL da foto adicional:", url)
            
            # A data já vem formatada do formulário
            dados = {
                'nome': form.nome.data,
                'mae': form.mae.data,
                'pai': form.pai.data,
                'nascimento': form.nascimento.data,  # Já está no formato correto
                'rg': form.rg.data,
                'cpf': form.cpf.data,
                'endereco': form.endereco.data,
                'fotos': ';'.join(fotos_urls) if fotos_urls else '',
                'foto_perfil': foto_perfil_url,
                'telefone': form.telefone.data,
                'anotacoes': form.anotacoes.data
            }
            
            print("DEBUG - Dados preparados para salvar:", dados)
            
            # Adicionar abordado e obter o ID
            abordado_id = adicionar_abordado(dados)
            if abordado_id:
                print(f"DEBUG - Abordado criado com ID: {abordado_id}")
                
                # Processar veículos
                marcas = request.form.getlist('veiculo_marca[]')
                modelos = request.form.getlist('veiculo_modelo[]')
                cores = request.form.getlist('veiculo_cor[]')
                placas = request.form.getlist('veiculo_placa[]')
                
                for i in range(len(marcas)):
                    # Só adiciona o veículo se todos os campos estiverem preenchidos
                    if marcas[i] and modelos[i] and cores[i] and placas[i]:
                        veiculo_dados = {
                            'marca': marcas[i],
                            'modelo': modelos[i],
                            'cor': cores[i],
                            'placa': placas[i],
                            'abordado_relacionado': str(abordado_id)
                        }
                        print(f"DEBUG - Adicionando veículo para abordado {abordado_id}:", veiculo_dados)
                        adicionar_veiculo_planilha(veiculo_dados)
                
                flash('Abordado cadastrado com sucesso!', 'success')
                
                # Se houver return_to, redirecionar para a página apropriada
                if return_to == 'nova_abordagem':
                    print(f"DEBUG - Redirecionando para nova_abordagem com abordado_id: {abordado_id}")
                    return redirect(url_for('nova_abordagem', selected_id=abordado_id))
                
                return redirect(url_for('index'))
            else:
                flash('Erro ao cadastrar abordado.', 'error')
                
        except Exception as e:
            print(f"ERRO ao processar o formulário: {str(e)}")
            import traceback
            print(f"Traceback completo: {traceback.format_exc()}")
            flash('Erro ao processar o formulário. Por favor, tente novamente.', 'error')
    
    return render_template('novo.html', form=form, return_to=return_to)

@app.route('/adicionar_veiculo/<int:abordado_id>', methods=['GET', 'POST'])
def adicionar_veiculo(abordado_id):
    if not abordado_id:
        flash('ID do abordado inválido.', 'error')
        return redirect(url_for('index'))
        
    form = VeiculoForm()
    if form.validate_on_submit():
        try:
            print(f"DEBUG - Adicionando veículo para o abordado ID: {abordado_id}")
            # Preparar dados do veículo
            dados_veiculo = {
                'marca': form.marca.data,
                'modelo': form.modelo.data,
                'cor': form.cor.data,
                'placa': form.placa.data,
                'abordado_relacionado': str(abordado_id)  # Convertido para string
            }
            
            print("DEBUG - Dados do veículo preparados:", dados_veiculo)
            print("DEBUG - ID do abordado relacionado:", dados_veiculo['abordado_relacionado'])
            
            # Adicionar veículo na aba Veículos
            if adicionar_veiculo_planilha(dados_veiculo):
                flash('Veículo adicionado com sucesso!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Erro ao adicionar veículo.', 'error')
                
        except Exception as e:
            print(f'ERRO ao adicionar veículo: {str(e)}')
            flash('Erro ao adicionar veículo.', 'error')
    
    return render_template('adicionar_veiculo.html', form=form)

def get_parentes():
    try:
        # Tentar obter do cache primeiro
        cached_data = sheets_cache.get('parentes')
        if cached_data is not None:
            return cached_data

        print("DEBUG - Iniciando busca de parentes")
        service = get_google_sheets_service()
        print("DEBUG - Serviço do Google Sheets obtido")
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Parentes!A:L'
        ).execute()
        print("DEBUG - Dados obtidos da planilha")
        
        values = result.get('values', [])
        if not values:
            print('Nenhum dado encontrado.')
            return []
            
        parentes = []
        for row in values[1:]:
            row_data = row + [''] * (12 - len(row)) if len(row) < 12 else row
            
            parente = {
                'id': row_data[0],
                'nome': row_data[1],
                'mae': row_data[2],
                'pai': row_data[3],
                'nascimento': row_data[4],
                'rg': row_data[5],
                'cpf': row_data[6],
                'endereco': row_data[7],
                'fotos': row_data[8],
                'foto_perfil': row_data[9],
                'anotacoes': row_data[10],
                'abordado_relacionado': row_data[11]
            }
            
            # Processa URLs de fotos
            if parente['foto_perfil']:
                parente['foto_perfil'] = converter_url_drive(parente['foto_perfil'])
            
            if parente['fotos']:
                fotos = parente['fotos'].split(';')
                parente['fotos'] = ';'.join(converter_url_drive(foto.strip()) for foto in fotos if foto.strip())
            
            print("DEBUG - Parente processado:", parente)
            parentes.append(parente)

        # Salvar no cache
        sheets_cache.set('parentes', parentes)
        return parentes
        
    except Exception as e:
        print(f'ERRO ao buscar parentes: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return []

def adicionar_parente_planilha(dados):
    try:
        result = adicionar_parente_interno(dados)
        if result:
            # Invalidar cache após adicionar
            sheets_cache.invalidate('parentes')
        return result
    except Exception as e:
        print(f'ERRO ao adicionar parente: {str(e)}')
        return False

def adicionar_parente_interno(dados):
    # Código existente da função adicionar_parente_planilha
    pass  # Mantenha o código original aqui

@app.route('/adicionar_parente/<int:abordado_id>', methods=['GET', 'POST'])
def adicionar_parente(abordado_id):
    if not abordado_id or abordado_id < 0:
        flash('ID do abordado inválido.', 'error')
        return redirect(url_for('index'))
        
    form = ParenteForm()
    if form.validate_on_submit():
        try:
            # Preparar dados do parente
            dados_parente = {
                'nome': form.nome.data,
                'parentesco': form.parentesco.data,
                'telefone': form.telefone.data,
                'endereco': form.endereco.data,
                'abordado_relacionado': str(abordado_id)  # Convertido para string
            }
            
            # Adicionar parente na planilha
            if adicionar_parente_planilha(dados_parente):
                flash('Parente adicionado com sucesso!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Erro ao adicionar parente.', 'error')
                
        except Exception as e:
            print(f'ERRO ao adicionar parente: {str(e)}')
            flash('Erro ao adicionar parente.', 'error')
    
    return render_template('adicionar_parente.html', form=form)

def get_veiculos():
    try:
        # Tentar obter do cache primeiro
        cached_data = sheets_cache.get('veiculos')
        if cached_data is not None:
            return cached_data

        print("DEBUG - Iniciando busca de veículos")
        service = get_google_sheets_service()
        print("DEBUG - Serviço do Google Sheets obtido")
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Veículos!A:F'
        ).execute()
        print("DEBUG - Dados obtidos da planilha")
        
        values = result.get('values', [])
        if not values:
            print('Nenhum dado encontrado.')
            return []
            
        veiculos = []
        for row in values[1:]:
            row_data = row + [''] * (6 - len(row)) if len(row) < 6 else row
            
            veiculo = {
                'id': row_data[0],
                'marca': row_data[1],
                'modelo': row_data[2],
                'cor': row_data[3],
                'placa': row_data[4],
                'abordado_relacionado': row_data[5]
            }
            
            print("DEBUG - Veículo processado:", veiculo)
            veiculos.append(veiculo)
        
        # Salvar no cache
        sheets_cache.set('veiculos', veiculos)    
        return veiculos
        
    except Exception as e:
        print(f'ERRO ao buscar veículos: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return []

def adicionar_veiculo_planilha(dados):
    try:
        result = adicionar_veiculo_interno(dados)
        if result:
            # Invalidar cache após adicionar
            sheets_cache.invalidate('veiculos')
        return result
    except Exception as e:
        print(f'ERRO ao adicionar veículo: {str(e)}')
        return False

def adicionar_veiculo_interno(dados):
    # Código existente da função adicionar_veiculo_planilha
    pass  # Mantenha o código original aqui

@app.route('/delete_photo', methods=['POST'])
def delete_photo():
    try:
        data = request.get_json()
        photo_url = data.get('photo_url')
        abordado_id = data.get('abordado_id')
        
        if not photo_url or not abordado_id:
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
            
        print(f"DEBUG - Tentando deletar foto: {photo_url} do abordado: {abordado_id}")
        
        # Buscar dados atuais do abordado
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Abordados!A{int(abordado_id)+1}:I{int(abordado_id)+1}'
        ).execute()
        
        if not result.get('values'):
            return jsonify({'success': False, 'error': 'Abordado não encontrado'}), 404
            
        fotos_atuais = result.get('values')[0][8] if len(result.get('values')[0]) > 8 else ''
        print(f"DEBUG - Fotos atuais: {fotos_atuais}")
        
        if not fotos_atuais:
            return jsonify({'success': False, 'error': 'Nenhuma foto encontrada'}), 404
        
        # Remover a foto da lista
        fotos_lista = [f.strip() for f in fotos_atuais.split(';') if f.strip()]
        print(f"DEBUG - Lista de fotos antes da remoção: {fotos_lista}")
        
        # Normalizar o caminho da foto para comparação
        photo_url_normalized = photo_url.replace('\\', '/').strip()
        fotos_lista = [f.replace('\\', '/').strip() for f in fotos_lista]
        
        # Remover a foto exata da lista
        if photo_url_normalized in fotos_lista:
            fotos_lista.remove(photo_url_normalized)
            print(f"DEBUG - Foto removida: {photo_url_normalized}")
        else:
            print(f"DEBUG - Foto não encontrada na lista: {photo_url_normalized}")
            return jsonify({'success': False, 'error': 'Foto não encontrada na lista'}), 404
            
        novas_fotos = ';'.join(fotos_lista)
        print(f"DEBUG - Novas fotos após remoção: {novas_fotos}")
        
        # Atualizar na planilha
        body = {
            'values': [[novas_fotos]]
        }
        
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Abordados!I{int(abordado_id)+1}',
            valueInputOption='RAW',
            body=body
        ).execute()
        
        # Tentar deletar o arquivo físico se ele existir
        if photo_url.startswith('/static/uploads/'):
            file_path = os.path.join(app.root_path, photo_url.lstrip('/'))
            file_path = file_path.replace('\\', '/')
            print(f"DEBUG - Tentando deletar arquivo físico: {file_path}")
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"DEBUG - Arquivo físico deletado com sucesso: {file_path}")
                else:
                    print(f"DEBUG - Arquivo físico não encontrado: {file_path}")
            except Exception as e:
                print(f"ERRO ao deletar arquivo físico: {str(e)}")
                # Não retornamos erro aqui pois a foto já foi removida da planilha
        
        return jsonify({'success': True})
            
    except Exception as e:
        print(f'ERRO ao deletar foto: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/delete_veiculo', methods=['POST'])
def delete_veiculo():
    try:
        data = request.get_json()
        veiculo_id = data.get('veiculo_id')
        
        if not veiculo_id:
            return jsonify({'success': False, 'error': 'ID do veículo não fornecido'}), 400
        
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Buscar todos os veículos
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Veículos!A:F'
        ).execute()
        
        if not result.get('values'):
            return jsonify({'success': False, 'error': 'Nenhum veículo encontrado'}), 404
        
        # Encontrar o índice do veículo
        veiculo_index = None
        for i, row in enumerate(result.get('values')):
            if row and row[0] == veiculo_id:
                veiculo_index = i + 1  # +1 porque o índice da planilha começa em 1
                break
        
        if veiculo_index is None:
            return jsonify({'success': False, 'error': 'Veículo não encontrado'}), 404
        
        # Limpar a linha do veículo
        sheet.values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Veículos!A{veiculo_index}:F{veiculo_index}'
        ).execute()
        
        # Invalidar cache após deletar
        sheets_cache.invalidate('veiculos')
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f'ERRO ao deletar veículo: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/editar_veiculo/<veiculo_id>', methods=['GET', 'POST'])
def editar_veiculo(veiculo_id):
    form = VeiculoForm()
    
    try:
        # Buscar dados do veículo
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Veículos!A:F'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            flash('Veículo não encontrado.', 'error')
            return redirect(url_for('index'))
            
        # Encontrar o veículo pelo ID
        veiculo_data = None
        veiculo_index = None
        for i, row in enumerate(values):
            if row[0] == veiculo_id:
                veiculo_data = {
                    'id': row[0],
                    'marca': row[1],
                    'modelo': row[2],
                    'cor': row[3],
                    'placa': row[4],
                    'abordado_relacionado': row[5]
                }
                veiculo_index = i + 1  # +1 porque o índice da planilha começa em 1
                break
                
        if not veiculo_data:
            flash('Veículo não encontrado.', 'error')
            return redirect(url_for('index'))
            
        if form.validate_on_submit():
            # Atualizar dados do veículo
            valores = [[
                veiculo_data['id'],                # A - ID
                form.marca.data,                   # B - Marca
                form.modelo.data,                  # C - Modelo
                form.cor.data,                     # D - Cor
                form.placa.data,                   # E - Placa
                veiculo_data['abordado_relacionado'] # F - ID_Abordado
            ]]
            
            body = {
                'values': valores
            }
            
            sheet.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f'Veículos!A{veiculo_index}:F{veiculo_index}',
                valueInputOption='RAW',
                body=body
            ).execute()
            
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('index'))
            
        # Preencher o formulário com os dados atuais
        form.marca.data = veiculo_data['marca']
        form.modelo.data = veiculo_data['modelo']
        form.cor.data = veiculo_data['cor']
        form.placa.data = veiculo_data['placa']
        
        return render_template('editar_veiculo.html', form=form, veiculo=veiculo_data)
        
    except Exception as e:
        print(f'ERRO ao editar veículo: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        flash('Erro ao editar veículo.', 'error')
        return redirect(url_for('index'))

@app.route('/delete_parente', methods=['POST'])
def delete_parente():
    try:
        data = request.get_json()
        parente_id = data.get('parente_id')
        
        if not parente_id:
            return jsonify({'success': False, 'error': 'ID do parente não fornecido'}), 400
        
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Buscar dados do parente
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Parentes!A{int(parente_id)+1}:L{int(parente_id)+1}'
        ).execute()
        
        if not result.get('values'):
            return jsonify({'success': False, 'error': 'Parente não encontrado'}), 404
            
        parente_data = result.get('values')[0]
        
        # Deletar fotos do parente
        deleted_files = []
        failed_files = []
        
        # Foto de perfil
        if len(parente_data) > 9 and parente_data[9]:
            foto_perfil = parente_data[9]
            if foto_perfil.startswith('/static/uploads/'):
                file_path = os.path.join(app.root_path, foto_perfil.lstrip('/'))
                file_path = file_path.replace('\\', '/')
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_files.append(file_path)
                except Exception as e:
                    failed_files.append(file_path)
                    print(f"ERRO ao deletar foto de perfil: {str(e)}")
        
        # Fotos adicionais
        if len(parente_data) > 8 and parente_data[8]:
            fotos = [f.strip() for f in parente_data[8].split(';') if f.strip()]
            for foto in fotos:
                if foto.startswith('/static/uploads/'):
                    file_path = os.path.join(app.root_path, foto.lstrip('/'))
                    file_path = file_path.replace('\\', '/')
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            deleted_files.append(file_path)
                    except Exception as e:
                        failed_files.append(file_path)
                        print(f"ERRO ao deletar foto: {str(e)}")
        
        # Limpar a linha do parente
        sheet.values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Parentes!A{int(parente_id)+1}:L{int(parente_id)+1}'
        ).execute()
        
        # Invalidar cache após deletar
        sheets_cache.invalidate('parentes')
        
        return jsonify({
            'success': True,
            'deleted_files': deleted_files,
            'failed_files': failed_files
        })
        
    except Exception as e:
        print(f'ERRO ao deletar parente: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/editar_parente/<parente_id>', methods=['GET', 'POST'])
def editar_parente(parente_id):
    form = ParenteForm()
    
    try:
        # Buscar dados do parente
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Parentes!A:L'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            flash('Parente não encontrado.', 'error')
            return redirect(url_for('index'))
            
        # Encontrar o parente pelo ID
        parente_data = None
        parente_index = None
        for i, row in enumerate(values):
            if row[0] == parente_id:
                parente_data = {
                    'id': row[0],                    # A - ID
                    'nome': row[1],                  # B - Nome
                    'mae': row[2],                   # C - Mae
                    'pai': row[3],                   # D - Pai
                    'nascimento': row[4],            # E - Nascimento
                    'rg': row[5],                    # F - RG
                    'cpf': row[6],                   # G - CPF
                    'endereco': row[7],              # H - Endereço
                    'fotos': row[8] if len(row) > 8 else '',  # I - Fotos
                    'foto_perfil': row[9] if len(row) > 9 else '',  # J - Foto Perfil
                    'anotacoes': row[10] if len(row) > 10 else '',  # K - Anotações
                    'abordado_relacionado': row[11] if len(row) > 11 else ''  # L - ID_Abordado
                }
                parente_index = i + 1  # +1 porque o índice da planilha começa em 1
                break
                
        if not parente_data:
            flash('Parente não encontrado.', 'error')
            return redirect(url_for('index'))
            
        if form.validate_on_submit():
            try:
                # Processar foto de perfil
                foto_perfil_url = parente_data['foto_perfil']
                if 'foto_perfil' in request.files:
                    file = request.files['foto_perfil']
                    if file and file.filename != '':
                        # Se houver uma nova foto, deletar a antiga
                        if foto_perfil_url and foto_perfil_url.startswith('/static/uploads/'):
                            old_file_path = os.path.join(app.root_path, foto_perfil_url.lstrip('/'))
                            old_file_path = old_file_path.replace('\\', '/')
                            try:
                                if os.path.exists(old_file_path):
                                    os.remove(old_file_path)
                                    print(f"DEBUG - Foto de perfil antiga deletada: {old_file_path}")
                            except Exception as e:
                                print(f"ERRO ao deletar foto de perfil antiga: {str(e)}")
                        
                        foto_perfil_url = save_uploaded_file(file, is_profile=True)
                        if foto_perfil_url:
                            foto_perfil_url = foto_perfil_url.replace('\\', '/')
                            print(f"DEBUG - Nova foto de perfil salva: {foto_perfil_url}")
                
                # Processar fotos adicionais
                fotos_urls = []
                if parente_data['fotos']:
                    fotos_urls = [f.strip() for f in parente_data['fotos'].split(';') if f.strip()]
                
                if 'fotos' in request.files:
                    files = request.files.getlist('fotos')
                    for file in files:
                        if file and file.filename != '':
                            url = save_uploaded_file(file)
                            if url:
                                url = url.replace('\\', '/')
                                fotos_urls.append(url)
                                print(f"DEBUG - Nova foto adicional salva: {url}")
                
                # Converter a data para string no formato dd/mm/yyyy
                nascimento = ''
                if form.nascimento.data:
                    nascimento = form.nascimento.data.strftime('%d/%m/%Y')
                
                # Atualizar dados do parente
                valores = [[
                    parente_data['id'],                # A - ID
                    form.nome.data,                    # B - Nome
                    form.mae.data,                     # C - Mae
                    form.pai.data,                     # D - Pai
                    nascimento,                        # E - Nascimento
                    form.rg.data,                      # F - RG
                    form.cpf.data,                   # G - CPF
                    form.endereco.data,            # H - Endereço
                    ';'.join(fotos_urls),            # I - Fotos
                    foto_perfil_url,                 # J - Foto Perfil
                    form.anotacoes.data,               # K - Anotações
                    parente_data['abordado_relacionado'] # L - ID_Abordado
                ]]
                
                body = {
                    'values': valores
                }
                
                # Atualizar na planilha
                sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Parentes!A{parente_index}:L{parente_index}',
                    valueInputOption='RAW',
                    body=body
                ).execute()
                
                print(f"DEBUG - Parente ID {parente_id} atualizado com sucesso")
                flash('Parente atualizado com sucesso!', 'success')
                return redirect(url_for('index'))
                
            except Exception as e:
                print(f"ERRO ao atualizar dados: {str(e)}")
                flash('Erro ao atualizar dados do parente.', 'error')
                return render_template('editar_parente.html', form=form, parente=parente_data)
        
        # Preencher o formulário com os dados atuais
        form.nome.data = parente_data['nome']
        form.mae.data = parente_data['mae']
        form.pai.data = parente_data['pai']
        if parente_data['nascimento']:
            try:
                form.nascimento.data = datetime.strptime(parente_data['nascimento'], '%d/%m/%Y')
            except:
                form.nascimento.data = None
        form.rg.data = parente_data['rg']
        form.cpf.data = parente_data['cpf']
        form.endereco.data = parente_data['endereco']
        form.anotacoes.data = parente_data['anotacoes']
        
        return render_template('editar_parente.html', form=form, parente=parente_data)
        
    except Exception as e:
        print(f'ERRO ao editar parente: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        flash('Erro ao editar parente.', 'error')
        return redirect(url_for('index'))

@app.route('/delete_abordado', methods=['POST'])
def delete_abordado():
    try:
        result = delete_abordado_interno()
        if result.get('success'):
            # Invalidar cache após deletar
            sheets_cache.invalidate()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def delete_abordado_interno():
    try:
        data = request.get_json()
        abordado_id = data.get('abordado_id')
        
        if not abordado_id:
            return jsonify({'success': False, 'error': 'ID do abordado não fornecido'}), 400
            
        print(f"DEBUG - Tentando deletar abordado ID: {abordado_id}")
        
        # Buscar dados atuais do abordado
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Buscar dados do abordado
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Abordados!A{int(abordado_id)+1}:M{int(abordado_id)+1}'
        ).execute()
        
        if not result.get('values'):
            return jsonify({'success': False, 'error': 'Abordado não encontrado'}), 404
            
        abordado_data = result.get('values')[0]
        
        # Deletar fotos do abordado
        deleted_files = []
        failed_files = []
        
        # Foto de perfil
        if len(abordado_data) > 9 and abordado_data[9]:  # Índice 9 é a coluna J - Foto Perfil
            foto_perfil = abordado_data[9]
            if foto_perfil.startswith('/static/uploads/'):
                file_path = os.path.join(app.root_path, foto_perfil.lstrip('/'))
                file_path = file_path.replace('\\', '/')
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_files.append(file_path)
                except Exception as e:
                    failed_files.append(file_path)
                    print(f"ERRO ao deletar foto de perfil: {str(e)}")
        
        # Fotos adicionais
        if len(abordado_data) > 8 and abordado_data[8]:  # Índice 8 é a coluna I - Fotos
            fotos = [f.strip() for f in abordado_data[8].split(';') if f.strip()]
            for foto in fotos:
                if foto.startswith('/static/uploads/'):
                    file_path = os.path.join(app.root_path, foto.lstrip('/'))
                    file_path = file_path.replace('\\', '/')
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            deleted_files.append(file_path)
                    except Exception as e:
                        failed_files.append(file_path)
                        print(f"ERRO ao deletar foto: {str(e)}")
        
        # Buscar e deletar veículos associados
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Veículos!A:F'
        ).execute()
        
        deleted_veiculos = []
        if result.get('values'):
            veiculos = result.get('values')[1:]  # Pular cabeçalho
            for i, veiculo in enumerate(veiculos, 2):  # Começar do índice 2 por causa do cabeçalho
                if len(veiculo) > 5 and veiculo[5] == abordado_id:  # Índice 5 é a coluna F - ID_Abordado
                    # Limpar linha do veículo
                    sheet.values().clear(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f'Veículos!A{i}:F{i}'
                    ).execute()
                    deleted_veiculos.append(veiculo[0])  # Guardar ID do veículo deletado
                    print(f"DEBUG - Veículo ID {veiculo[0]} deletado")
        
        # Buscar e deletar parentes associados
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Parentes!A:L'
        ).execute()
        
        deleted_parentes = []
        if result.get('values'):
            parentes = result.get('values')[1:]  # Pular cabeçalho
            for i, parente in enumerate(parentes, 2):  # Começar do índice 2 por causa do cabeçalho
                if len(parente) > 11 and parente[11] == abordado_id:  # Índice 11 é a coluna L - ID_Abordado
                    # Deletar fotos do parente
                    if len(parente) > 9 and parente[9]:  # Foto de perfil
                        foto_perfil = parente[9]
                        if foto_perfil.startswith('/static/uploads/'):
                            file_path = os.path.join(app.root_path, foto_perfil.lstrip('/'))
                            file_path = file_path.replace('\\', '/')
                            try:
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                    deleted_files.append(file_path)
                                    print(f"DEBUG - Foto de perfil do parente deletada: {file_path}")
                            except Exception as e:
                                failed_files.append(file_path)
                                print(f"ERRO ao deletar foto de perfil do parente: {str(e)}")
                    
                    if len(parente) > 8 and parente[8]:  # Fotos adicionais
                        fotos = [f.strip() for f in parente[8].split(';') if f.strip()]
                        for foto in fotos:
                            if foto.startswith('/static/uploads/'):
                                file_path = os.path.join(app.root_path, foto.lstrip('/'))
                                file_path = file_path.replace('\\', '/')
                                try:
                                    if os.path.exists(file_path):
                                        os.remove(file_path)
                                        deleted_files.append(file_path)
                                        print(f"DEBUG - Foto adicional do parente deletada: {file_path}")
                                except Exception as e:
                                    failed_files.append(file_path)
                                    print(f"ERRO ao deletar foto adicional do parente: {str(e)}")
                    
                    # Limpar linha do parente
                    sheet.values().clear(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f'Parentes!A{i}:L{i}'
                    ).execute()
                    deleted_parentes.append(parente[0])  # Guardar ID do parente deletado
                    print(f"DEBUG - Parente ID {parente[0]} deletado")
        
        # Finalmente, deletar o abordado
        sheet.values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Abordados!A{int(abordado_id)+1}:M{int(abordado_id)+1}'
        ).execute()
        
        print(f"DEBUG - Abordado ID {abordado_id} deletado com sucesso")
        print(f"DEBUG - Arquivos deletados: {deleted_files}")
        if failed_files:
            print(f"DEBUG - Arquivos que falharam ao deletar: {failed_files}")
        print(f"DEBUG - Veículos deletados: {deleted_veiculos}")
        print(f"DEBUG - Parentes deletados: {deleted_parentes}")
        
        return jsonify({
            'success': True,
            'deleted_files': deleted_files,
            'failed_files': failed_files,
            'deleted_veiculos': deleted_veiculos,
            'deleted_parentes': deleted_parentes
        })
        
    except Exception as e:
        print(f'ERRO ao deletar abordado: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/editar_abordado/<abordado_id>', methods=['GET', 'POST'])
def editar_abordado(abordado_id):
    form = AbordadoForm()
    return_to = request.args.get('return_to')
    
    try:
        if request.method == 'POST':
            # Se for POST e sucesso, invalidar cache
            sheets_cache.invalidate()
        # Resto do código existente
        pass
    except Exception as e:
        flash(f'Erro ao editar abordado: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/search_abordados')
def search_abordados():
    try:
        query = request.args.get('q', '').strip().lower()
        if not query:
            return jsonify([])
        
        # Usar abordados do cache
        abordados = get_abordados()
        
        # Filtrar abordados que correspondem à pesquisa
        resultados = []
        for abordado in abordados:
            if (query in abordado['Nome'].lower() or
                query in abordado['RG'].lower() or
                query in abordado['CPF'].lower()):
                
                resultados.append({
                    'id': abordado['ID'],
                    'nome': abordado['Nome'],
                    'mae': abordado['Mae'],
                    'pai': abordado['Pai'],
                    'foto_perfil': abordado['Foto Perfil']
                })
        
        return jsonify(resultados)
        
    except Exception as e:
        print(f'ERRO ao pesquisar abordados: {str(e)}')
        return jsonify([])

def adicionar_abordagem_planilha(dados):
    try:
        print("DEBUG - Iniciando adição de abordagem")
        print("DEBUG - Dados recebidos:", dados)
        
        service = get_google_sheets_service()
        sheet = service.spreadsheets()
        
        # Pegar o próximo ID disponível
        print("DEBUG - Buscando próximo ID")
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordagens!A:A'
        ).execute()
        
        valores = result.get('values', [])
        # Encontrar o maior ID atual e adicionar 1
        maior_id = 0
        for row in valores:
            if row and row[0].isdigit():  # Verifica se é um número
                id_atual = int(row[0])
                if id_atual > maior_id:
                    maior_id = id_atual
        
        proximo_id = str(maior_id + 1)
        print("DEBUG - Próximo ID:", proximo_id)
        
        # Preparar os dados para inserção
        valores = [[
            proximo_id,                    # A - ID
            dados.get('data_hora', ''),    # B - Data/hora
            dados.get('local', ''),        # C - Local
            dados.get('abordados', ''),    # D - Abordados
            dados.get('anotacao', '')      # E - Anotação
        ]]
        
        print("DEBUG - Valores preparados para inserção:", valores)
        
        body = {
            'values': valores
        }
        
        # Inserir na planilha
        print("DEBUG - Tentando inserir na planilha")
        result = sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Abordagens!A:E',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        print("DEBUG - Resultado da inserção:", result)
        return True
        
    except Exception as e:
        print(f'ERRO ao adicionar abordagem: {str(e)}')
        import traceback
        print(f'Traceback completo: {traceback.format_exc()}')
        return False

@app.route('/nova_abordagem', methods=['GET', 'POST'])
def nova_abordagem():
    form = AbordagemForm()
    selected_ids = request.args.get('selected_ids', '')
    selected_id = request.args.get('selected_id', '')  # ID do novo abordado
    selected_abordados = []
    
    # Se tiver um novo ID selecionado, adicionar à lista de IDs
    if selected_id:
        print(f"DEBUG - Novo abordado selecionado com ID: {selected_id}")
        if not selected_ids:
            selected_ids = selected_id
        elif selected_id not in selected_ids.split(','):
            selected_ids = f"{selected_ids},{selected_id}"
        print(f"DEBUG - Lista atualizada de IDs: {selected_ids}")
    
    if selected_ids:
        try:
            # Usar o cache para buscar os dados
            abordados_cache = get_abordados()
            
            # Buscar dados de cada abordado selecionado
            for abordado_id in selected_ids.split(','):
                if not abordado_id:  # Pular IDs vazios
                    continue
                    
                print(f"DEBUG - Buscando dados do abordado ID: {abordado_id}")
                
                # Primeiro tentar encontrar no cache
                abordado_encontrado = False
                for abordado in abordados_cache:
                    if abordado['ID'] == abordado_id:
                        selected_abordados.append({
                            'id': abordado['ID'],
                            'nome': abordado['Nome'],
                            'mae': abordado['Mae'],
                            'pai': abordado['Pai'],
                            'foto_perfil': abordado['Foto Perfil']
                        })
                        abordado_encontrado = True
                        break
                
                # Se não encontrou no cache, buscar diretamente da planilha
                if not abordado_encontrado:
                    service = get_google_sheets_service()
                    sheet = service.spreadsheets()
                    result = sheet.values().get(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f'Abordados!A{int(abordado_id)+1}:M{int(abordado_id)+1}'
                    ).execute()
                    
                    if result.get('values'):
                        abordado_data = result.get('values')[0]
                        print(f"DEBUG - Dados encontrados para abordado {abordado_id}: {abordado_data}")
                        selected_abordados.append({
                            'id': abordado_data[0],
                            'nome': abordado_data[1],
                            'mae': abordado_data[2],
                            'pai': abordado_data[3],
                            'foto_perfil': abordado_data[9] if len(abordado_data) > 9 else ''
                        })
                    else:
                        print(f"DEBUG - Nenhum dado encontrado para abordado {abordado_id}")
        except Exception as e:
            print(f'ERRO ao buscar abordados selecionados: {str(e)}')
            import traceback
            print(f'Traceback completo: {traceback.format_exc()}')
    
    if form.validate_on_submit():
        try:
            # Preparar dados da abordagem
            dados_abordagem = {
                'data_hora': form.data_hora.data,
                'local': form.local.data,
                'abordados': request.form.get('abordados_ids', '').replace(',', ';'),  # Converter vírgulas para ponto e vírgula
                'anotacao': form.anotacao.data
            }
            
            print("DEBUG - Dados da abordagem preparados:", dados_abordagem)
            
            # Adicionar abordagem na planilha
            if adicionar_abordagem_planilha(dados_abordagem):
                flash('Abordagem registrada com sucesso!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Erro ao registrar abordagem.', 'error')
                
        except Exception as e:
            print(f'ERRO ao registrar abordagem: {str(e)}')
            flash('Erro ao registrar abordagem.', 'error')
    
    return render_template('nova_abordagem.html', form=form, selected_abordados=selected_abordados)

@app.route('/get_abordado/<id>')
def get_abordado(id):
    try:
        abordado = buscar_abordado_por_id(id)
        if abordado:
            return jsonify(abordado)
        return jsonify({'error': 'Abordado não encontrado'}), 404
    except Exception as e:
        print(f"Erro ao buscar abordado {id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

def buscar_abordado_por_id(id):
    try:
        # Tentar encontrar nos dados em cache primeiro
        abordados = get_abordados()
        for abordado in abordados:
            if abordado['ID'] == id:
                return {
                    'id': abordado['ID'],
                    'nome': abordado['Nome'],
                    'mae': abordado['Mae'],
                    'pai': abordado['Pai'],
                    'foto_perfil': abordado['Foto Perfil']
                }
        
        # Se não encontrar no cache, buscar diretamente
        service = get_google_sheets_service()
        linha = int(id) + 1
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Abordados!A{linha}:M{linha}'
        ).execute()
        
        if 'values' in result and result['values']:
            dados = result['values'][0]
            return {
                'id': dados[0],
                'nome': dados[1],
                'mae': dados[2],
                'pai': dados[3],
                'foto_perfil': dados[9] if len(dados) > 9 else ''
            }
        return None
    except Exception as e:
        print(f"Erro ao buscar abordado {id}: {str(e)}")
        return None

if __name__ == '__main__':
    app.run(debug=True) 