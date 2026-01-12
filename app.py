from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import uuid
import base64
import threading
import time
from datetime import datetime
import sqlite3
from werkzeug.utils import secure_filename

# Tentar importar GitHub, mas não falhar se não estiver instalado
try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    print("⚠️ PyGithub não instalado. Instale com: pip install PyGithub")
    GITHUB_AVAILABLE = False
    Github = None

app = Flask(__name__)
CORS(app)

# Configurações
DATABASE = 'community.db'
UPLOAD_FOLDER = 'community_apps'
ALLOWED_EXTENSIONS = {'html', 'js', 'css', 'json', 'png', 'jpg', 'jpeg'}

# CONFIGURE AQUI SEU TOKEN DO GITHUB
GITHUB_TOKEN = os.environ.get("TOKEN")  # Variável de ambiente no Render
BACKUP_ENABLED = False
BACKUP_GIST_ID = "0f0c07b79f13ad78b4fdfbffb27cd983"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
    """Inicializa o banco de dados"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id TEXT PRIMARY KEY,
                  username TEXT UNIQUE,
                  email TEXT UNIQUE,
                  password TEXT,
                  created_at TEXT,
                  is_admin INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS apps
                 (id TEXT PRIMARY KEY,
                  name TEXT,
                  description TEXT,
                  author TEXT,
                  version TEXT,
                  category TEXT,
                  tags TEXT,
                  download_count INTEGER DEFAULT 0,
                  rating REAL DEFAULT 0,
                  file_path TEXT,
                  icon_path TEXT,
                  created_at TEXT,
                  updated_at TEXT,
                  is_approved INTEGER DEFAULT 0,
                  user_id TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(id))''')
    
    conn.commit()
    conn.close()
    print("✅ Banco de dados inicializado")

# ============ SISTEMA DE BACKUP GITHUB ============

def initialize_backup_system():
    """Inicializa tudo em ordem correta"""
    global BACKUP_ENABLED, BACKUP_GIST_ID
    
    # 1. Primeiro verificar se GitHub está disponível
    if not GITHUB_AVAILABLE:
        print("⚠️ PyGithub não disponível. Backup desativado.")
        init_db()  # Pelo menos cria o banco
        return
    
    # 2. Verificar se tem token
    if not GITHUB_TOKEN:
        print("⚠️ Token do GitHub não configurado. Backup desativado.")
        init_db()  # Pelo menos cria o banco
        return
    
    try:
        # 3. Conectar ao GitHub
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        print(f"✅ Conectado ao GitHub como: {user.login}")
        BACKUP_ENABLED = True
        
        # 4. Tentar encontrar Gist existente
        for gist in user.get_gists():
            if gist.description and "NetOS Community Backup" in gist.description:
                BACKUP_GIST_ID = gist.id
                print(f"📁 Gist de backup encontrado: {BACKUP_GIST_ID}")
                break
        
        # 5. VERIFICAR SE BANCO EXISTE E TEM DADOS
        should_init_new_db = True
        
        if os.path.exists(DATABASE):
            try:
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                
                # Verificar se tem tabelas
                c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                has_tables = c.fetchone()[0] > 0
                
                if has_tables:
                    # Verificar se tem dados
                    c.execute("SELECT COUNT(*) FROM users")
                    user_count = c.fetchone()[0]
                    
                    if user_count > 0:
                        print("✅ Banco já existe com dados, usando local")
                        should_init_new_db = False
                    else:
                        print("🔄 Banco existe mas vazio, tentando restaurar...")
                else:
                    print("🔄 Banco existe sem tabelas, tentando restaurar...")
                
                conn.close()
            except:
                print("🔄 Erro ao verificar banco, tentando restaurar...")
        
        # 6. Se precisa restaurar ou criar novo
        if should_init_new_db:
            print("🔄 Tentando restaurar do backup GitHub...")
            if restore_from_github():
                print("✅ Banco restaurado do backup!")
            else:
                print("⚠️ Não conseguiu restaurar, criando banco novo")
                init_db()
        else:
            # 7. Se já tem dados, fazer backup inicial
            print("🔄 Fazendo backup inicial dos dados existentes...")
            backup_to_github()
        
        # 8. Iniciar backup automático
        if BACKUP_ENABLED:
            threading.Thread(target=auto_backup_worker, daemon=True).start()
            print("✅ Sistema de backup inicializado com sucesso")
        
    except Exception as e:
        print(f"❌ Erro ao inicializar backup: {str(e)[:100]}")
        BACKUP_ENABLED = False
        init_db()  # Fallback

def is_database_empty():
    """Verifica se o banco está vazio"""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        has_tables = c.fetchone()[0] > 0
        
        if not has_tables:
            conn.close()
            return True
        
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM apps")
        app_count = c.fetchone()[0]
        
        conn.close()
        return user_count == 0 and app_count == 0
        
    except sqlite3.Error as e:
        print(f"❌ Erro ao verificar banco: {e}")
        return True

def backup_to_github():
    global BACKUP_GIST_ID
    """Faz backup do banco para GitHub Gist"""
    if not BACKUP_ENABLED or not GITHUB_AVAILABLE:
        return False
    
    try:
        # Verificar se há dados para backup
        if not os.path.exists(DATABASE):
            print("⚠️ Banco não existe para backup")
            return False
        
        if is_database_empty():
            print("⚠️ Banco vazio, pulando backup")
            return False
        
        # Ler banco de dados
        with open(DATABASE, 'rb') as f:
            db_content = f.read()
        
        # Converter para base64
        db_base64 = base64.b64encode(db_content).decode('utf-8')
        
        # Preparar dados do backup
        backup_data = {
            "database": db_base64,
            "timestamp": datetime.now().isoformat(),
            "size": len(db_content),
            "tables": get_table_counts()
        }
        
        # Criar/atualizar Gist
        g = Github(GITHUB_TOKEN)
        
        files = {"community_backup.json": {"content": json.dumps(backup_data, indent=2)}}
        
        if BACKUP_GIST_ID:
            try:
                gist = g.get_gist(BACKUP_GIST_ID)
                gist.edit(
                    description=f"NetOS Community Backup - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                    files=files
                )
                print(f"📤 Backup atualizado no Gist: {BACKUP_GIST_ID}")
            except Exception as e:
                print(f"⚠️ Não conseguiu atualizar Gist existente, criando novo: {e}")
                create_new_gist(g, files)
        else:
            create_new_gist(g, files)
        
        return True
        
    except Exception as e:
        print(f"❌ Erro no backup para GitHub: {str(e)[:100]}")
        return False

def create_new_gist(g, files):
    """Cria um novo Gist de backup"""
    global BACKUP_GIST_ID
    try:
        user = g.get_user()
        new_gist = user.create_gist(
            public=False,
            files=files,
            description=f"NetOS Community Backup - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        BACKUP_GIST_ID = new_gist.id
        print(f"📤 Novo backup criado: {BACKUP_GIST_ID}")
    except Exception as e:
        print(f"❌ Erro ao criar novo Gist: {e}")

def restore_from_github():
    """Restaura banco do backup do GitHub"""
    if not BACKUP_ENABLED or not GITHUB_AVAILABLE:
        return False
    
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        
        # Procurar Gist de backup
        target_gist = None
        gist_id_to_use = BACKUP_GIST_ID
        
        # Se não tem ID salvo, procurar
        if not gist_id_to_use:
            for gist in user.get_gists():
                if gist.description and "NetOS Community Backup" in gist.description:
                    target_gist = gist
                    gist_id_to_use = gist.id
                    break
        
        # Se tem ID, tentar carregar
        elif gist_id_to_use:
            try:
                target_gist = g.get_gist(gist_id_to_use)
            except:
                target_gist = None
        
        if not target_gist:
            print("⚠️ Nenhum backup encontrado no GitHub")
            return False
        
        # Baixar backup
        for filename, file_info in target_gist.files.items():
            if "backup" in filename.lower() and filename.endswith('.json'):
                try:
                    file_content = file_info.content
                    backup_data = json.loads(file_content)
                    
                    if "database" in backup_data:
                        db_bytes = base64.b64decode(backup_data["database"])
                        
                        # Salvar banco
                        with open(DATABASE, 'wb') as f:
                            f.write(db_bytes)
                        
                        # Atualizar ID do Gist
                        global BACKUP_GIST_ID
                        BACKUP_GIST_ID = target_gist.id
                        
                        print(f"✅ Banco restaurado (backup de {backup_data.get('timestamp', 'data desconhecida')})")
                        return True
                except Exception as e:
                    print(f"❌ Erro ao processar arquivo de backup: {e}")
        
        print("⚠️ Arquivo de backup não encontrado no Gist")
        return False
        
    except Exception as e:
        print(f"❌ Erro na restauração do GitHub: {str(e)[:100]}")
        return False

def get_table_counts():
    """Retorna contagem de registros por tabela"""
    counts = {}
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = c.fetchall()
        
        for table in tables:
            table_name = table[0]
            try:
                c.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = c.fetchone()[0]
                counts[table_name] = count
            except:
                counts[table_name] = 0
        
        conn.close()
    except Exception as e:
        print(f"⚠️ Erro ao obter contagens: {e}")
    
    return counts

def auto_backup_worker():
    """Faz backup automático periodicamente"""
    while BACKUP_ENABLED:
        time.sleep(12)  # 1 hora = 3600 segundos
        print("⏰ Executando backup automático...")
        backup_to_github()

def trigger_backup():
    """Dispara backup em segundo plano"""
    if BACKUP_ENABLED:
        threading.Thread(target=backup_to_github).start()

# ============ INICIALIZAÇÃO DO SISTEMA ============

# Inicializar tudo
initialize_backup_system()

# ============ ROTAS DA API ============

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online',
        'service': 'NetOS Community Apps',
        'timestamp': datetime.now().isoformat(),
        'backup': {
            'enabled': BACKUP_ENABLED,
            'gist_id': BACKUP_GIST_ID,
            'github_available': GITHUB_AVAILABLE,
            'token_configured': bool(GITHUB_TOKEN)
        },
        'database': {
            'exists': os.path.exists(DATABASE),
            'tables': get_table_counts()
        }
    })

@app.route('/api/backup', methods=['POST'])
def manual_backup():
    """Rota para fazer backup manual"""
    if backup_to_github():
        return jsonify({'message': 'Backup realizado com sucesso'}), 200
    else:
        return jsonify({'error': 'Falha no backup'}), 500

@app.route('/api/restore', methods=['POST'])
def manual_restore():
    """Rota para restaurar manualmente"""
    if restore_from_github():
        return jsonify({'message': 'Banco restaurado com sucesso'}), 200
    else:
        return jsonify({'error': 'Falha na restauração'}), 500

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not all([username, email, password]):
        return jsonify({'error': 'Missing fields'}), 400
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    c.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
    if c.fetchone():
        conn.close()
        return jsonify({'error': 'Username or email already exists'}), 400
    
    user_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, email, password, created_at, 0))
    
    conn.commit()
    conn.close()
    
    # Disparar backup após registro
    trigger_backup()
    
    return jsonify({
        'message': 'User registered successfully',
        'user': {'id': user_id, 'username': username, 'email': email}
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not all([username, password]):
        return jsonify({'error': 'Missing credentials'}), 400
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, username, email, is_admin FROM users WHERE username = ? AND password = ?",
              (username, password))
    user = c.fetchone()
    conn.close()
    
    if user:
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'is_admin': bool(user[3])
            }
        }), 200
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/apps', methods=['GET'])
def get_apps():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT * FROM apps WHERE is_approved = 1")
    apps = c.fetchall()
    
    app_list = []
    for app in apps:
        app_list.append({
            'id': app[0],
            'name': app[1],
            'description': app[2],
            'author': app[3],
            'version': app[4],
            'category': app[5],
            'tags': app[6].split(',') if app[6] else [],
            'download_count': app[7],
            'rating': app[8],
            'file_path': app[9],
            'icon_path': app[10],
            'created_at': app[11],
            'updated_at': app[12]
        })
    
    conn.close()
    return jsonify(app_list), 200

@app.route('/api/apps/upload', methods=['POST'])
def upload_app():
    if 'user_id' not in request.form:
        return jsonify({'error': 'User ID required'}), 401
    
    user_id = request.form['user_id']
    
    if 'app_file' not in request.files:
        return jsonify({'error': 'No app file provided'}), 400
    
    app_file = request.files['app_file']
    
    if app_file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not name or not description:
        return jsonify({'error': 'Name and description required'}), 400
    
    app_id = str(uuid.uuid4())
    app_dir = os.path.join(UPLOAD_FOLDER, app_id)
    os.makedirs(app_dir, exist_ok=True)
    
    filename = secure_filename(app_file.filename)
    file_path = os.path.join(app_dir, filename)
    app_file.save(file_path)
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    now = datetime.now().isoformat()
    
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    author = user[0] if user else "Anonymous"
    
    c.execute("""INSERT INTO apps 
                 (id, name, description, author, version, category, tags, 
                  file_path, icon_path, created_at, updated_at, user_id, is_approved)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (app_id, name, description, author, '1.0.0', 'utility', '',
               file_path, '', now, now, user_id, 1))
    
    conn.commit()
    conn.close()
    
    # Disparar backup após upload
    trigger_backup()
    
    return jsonify({
        'message': 'App uploaded successfully',
        'app_id': app_id
    }), 201

if __name__ == '__main__':
    app.run(debug=False)
