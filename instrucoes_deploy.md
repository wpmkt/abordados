# Instruções para Deploy no Render

## 1. Preparação do Código
1. Certifique-se que o repositório no GitHub está atualizado
2. Verifique se o arquivo `requirements.txt` contém todas as dependências:
   ```
   flask==2.3.3
   google-api-python-client==2.97.0
   google-auth-oauthlib==1.0.0
   google-auth-httplib2==0.1.0
   flask-wtf==1.2.1
   wtforms==3.1.1
   Pillow==10.0.0
   python-dotenv==1.0.0
   gunicorn==21.2.0
   ```

3. Verifique se o arquivo `gunicorn_config.py` existe com o conteúdo:
   ```python
   bind = "0.0.0.0:10000"
   workers = 4
   threads = 4
   timeout = 120
   ```

## 2. Configuração no Render

### 2.1. Criar Novo Web Service
1. Acesse render.com
2. Clique em "New +"
3. Selecione "Web Service"
4. Conecte com o repositório GitHub

### 2.2. Configurações Básicas
1. Nome: escolha um nome para o serviço
2. Runtime: Python 3
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn -c gunicorn_config.py app:app`

### 2.3. Variáveis de Ambiente
Configure as seguintes variáveis em "Environment":

1. `PYTHON_VERSION`:
   - Key: `PYTHON_VERSION`
   - Value: `3.9.18`

2. `PORT`:
   - Key: `PORT`
   - Value: `10000`

3. `GOOGLE_CREDENTIALS`:
   - Key: `GOOGLE_CREDENTIALS`
   - Value: (conteúdo do arquivo `credentials.json`)
   - Observação: Cole o conteúdo do seu arquivo `credentials.json` aqui. Não compartilhe essas credenciais publicamente.

4. `GOOGLE_TOKEN`:
   - Key: `GOOGLE_TOKEN`
   - Value: (conteúdo do arquivo `token.pickle` convertido para base64)
   - Observação: Use o conteúdo do arquivo `token_base64.txt` gerado anteriormente. Cole todo o conteúdo em uma única linha, sem quebras.

## 3. Deploy
1. Após configurar todas as variáveis, clique em "Save Changes"
2. Vá para a aba "Deploy"
3. Clique em "Manual Deploy" > "Deploy Latest Commit"
4. Aguarde o deploy completar
5. O site estará disponível no URL fornecido pelo Render

## 4. Verificação
1. Verifique se o site está acessível
2. Teste o login e acesso ao Google Sheets
3. Verifique se as imagens estão sendo salvas corretamente

## 5. Solução de Problemas
- Se houver erro de "Incorrect padding", verifique se o `GOOGLE_TOKEN` está em uma única linha
- Se houver erro de conexão, verifique se a porta (10000) está correta
- Se houver erro com o Google Sheets, verifique as credenciais

## 6. Manutenção
- Mantenha o arquivo `requirements.txt` atualizado
- Faça backup regular das credenciais
- Monitore os logs do Render para identificar possíveis problemas 