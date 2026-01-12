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
from github import Github  # pip install PyGithub

app = Flask(__name__)
CORS(app)

# Configurações
DATABASE = 'community.db'
UPLOAD_FOLDER = 'community_apps'
ALLOWED_EXTENSIONS = {'html', 'js', 'css', 'json', 'png', 'jpg', 'jpeg'}

# CONFIGURE AQUI SEU TOKEN DO GITHUB
GITHUB_TOKEN = os.environ.get("TOKEN") # obtenha em: https://github.com/settings/tokens
BACKUP_ENABLED = False
BACKUP_GIST_ID = None

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
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

# ============ SISTEMA DE BACKUP GITHUB ============

def setup_backup():
    """Configura o sistema de backup"""
    global BACKUP_ENABLED, BACKUP_GIST_ID
    
    if not GITHUB_TOKEN or GITHUB_TOKEN == "SEU_TOKEN_GITHUB_AQUI":
        print("⚠️ Token do GitHub não configurado. Backup desativado.")
        return
    
    try:
        # Testar token
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        print(f"✅ Conectado ao GitHub como: {user.login}")
        BACKUP_ENABLED = True
        
        # Tentar encontrar Gist existente
        for gist in user.get_gists():
            if gist.description and "NetOS Community Backup" in gist.description:
                BACKUP_GIST_ID = gist.id
                print(f"📁 Gist de backup encontrado: {BACKUP_GIST_ID}")
                break
        
        # Se o banco existe, fazer backup inicial
        if os.path.exists(DATABASE) and not is_database_empty():
            print("🔄 Fazendo backup inicial...")
            backup_to_github()
        
        # Iniciar backup automático (a cada hora)
        threading.Thread(target=auto_backup_worker, daemon=True).start()
        
    except Exception as e:
        print(f"❌ Erro ao configurar backup: {e}")
        BACKUP_ENABLED = False

def is_database_empty():
    """Verifica se o banco está vazio"""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM apps")
        app_count = c.fetchone()[0]
        
        conn.close()
        return user_count == 0 and app_count == 0
    except:
        return True

def backup_to_github():
    """Faz backup do banco para GitHub Gist"""
    if not BACKUP_ENABLED:
        return False
    
    try:
        # Verificar se há dados para backup
        if not os.path.exists(DATABASE) or is_database_empty():
            print("⚠️ Nenhum dado para backup")
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
        user = g.get_user()
        
        global BACKUP_GIST_ID
        
        files = {"community_backup.json": {"content": json.dumps(backup_data, indent=2)}}
        
        if BACKUP_GIST_ID:
            try:
                gist = g.get_gist(BACKUP_GIST_ID)
                gist.edit(
                    description=f"NetOS Community Backup - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                    files=files
                )
                print(f"📤 Backup atualizado")
            except:
                # Se não encontrar, cria novo
                create_new_gist(g, user, files)
        else:
            create_new_gist(g, user, files)
        
        return True
        
    except Exception as e:
        print(f"❌ Erro no backup: {e}")
        return False

def create_new_gist(g, user, files):
    """Cria um novo Gist de backup"""
    global BACKUP_GIST_ID
    new_gist = user.create_gist(
        public=False,
        files=files,
        description=f"NetOS Community Backup - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    BACKUP_GIST_ID = new_gist.id
    print(f"📤 Novo backup criado: {BACKUP_GIST_ID}")

def restore_from_github():
    """Restaura banco do backup do GitHub"""
    if not BACKUP_ENABLED:
        return False
    
    try:
        g = Github(GITHUB_TOKEN)
        
        # Procurar Gist de backup
        if not BACKUP_GIST_ID:
            user = g.get_user()
            for gist in user.get_gists():
                if gist.description and "NetOS Community Backup" in gist.description:
                    BACKUP_GIST_ID = gist.id
                    break
        
        if not BACKUP_GIST_ID:
            print("⚠️ Nenhum backup encontrado")
            return False
        
        # Baixar backup
        gist = g.get_gist(BACKUP_GIST_ID)
        
        for filename, file_info in gist.files.items():
            if "backup" in filename.lower():
                backup_data = json.loads(file_info.content)
                db_bytes = base64.b64decode(backup_data["database"])
                
                # Salvar banco
                with open(DATABASE, 'wb') as f:
                    f.write(db_bytes)
                
                print(f"✅ Banco restaurado (backup de {backup_data['timestamp']})")
                return True
        
        return False
        
    except Exception as e:
        print(f"❌ Erro na restauração: {e}")
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
    except:
        pass
    
    return counts

def auto_backup_worker():
    """Faz backup automático periodicamente"""
    while BACKUP_ENABLED:
        time.sleep(3600)  # 1 hora
        print("⏰ Backup automático...")
        backup_to_github()

def trigger_backup():
    """Dispara backup em segundo plano"""
    if BACKUP_ENABLED:
        threading.Thread(target=backup_to_github).start()

# ============ INICIALIZAÇÃO DO BACKUP ============

init_db()
setup_backup()

# Tentar restaurar se o banco estiver vazio
if os.path.exists(DATABASE) and is_database_empty():
    print("🔄 Banco vazio, tentando restaurar do backup...")
    restore_from_github()

# ============ ROTAS EXISTENTES (inalteradas) ============

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online',
        'service': 'NetOS Community Apps',
        'timestamp': datetime.now().isoformat(),
        'backup': BACKUP_ENABLED,
        'gist_id': BACKUP_GIST_ID
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
