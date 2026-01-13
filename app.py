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

try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    print("⚠️ PyGithub não instalado.")
    GITHUB_AVAILABLE = False
    Github = None

app = Flask(__name__)
CORS(app)

# Configurações
DATABASE = 'community.db'
UPLOAD_FOLDER = 'community_apps'
ALLOWED_EXTENSIONS = {'html', 'js', 'css', 'json', 'png', 'jpg', 'jpeg'}

# Variáveis do Render
GITHUB_TOKEN = os.environ.get("TOKEN")
BACKUP_ENABLED = False
BACKUP_GIST_ID = "0f0c07b79f13ad78b4fdfbffb27cd983"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ============ FUNÇÕES AUXILIARES ============

def get_table_counts():
    """Retorna contagem de registros por tabela"""
    counts = {}
    try:
        if not os.path.exists(DATABASE):
            return counts
            
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

def is_database_empty():
    """Verifica se o banco está vazio"""
    try:
        if not os.path.exists(DATABASE):
            return True
            
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        # Verificar se tem tabelas
        c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        has_tables = c.fetchone()[0] > 0
        
        if not has_tables:
            conn.close()
            return True
        
        # Verificar se tem dados
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        
        conn.close()
        return user_count == 0
        
    except:
        return True

# ============ BACKUP/RESTORE ============

def test_github():
    """Testa conexão com GitHub"""
    global BACKUP_ENABLED
    
    if not GITHUB_AVAILABLE or not GITHUB_TOKEN:
        BACKUP_ENABLED = False
        return False
    
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        print(f"✅ GitHub: {user.login}")
        BACKUP_ENABLED = True
        return True
    except Exception as e:
        print(f"❌ GitHub falhou: {e}")
        BACKUP_ENABLED = False
        return False

def restore_database():
    """Tenta restaurar do backup"""
    if not BACKUP_ENABLED:
        print("❌ Backup desativado")
        return False
    
    print(f"🔄 Buscando Gist ID: {BACKUP_GIST_ID}")
    
    try:
        # 1. Conecta ao GitHub
        g = Github(GITHUB_TOKEN)
        
        # 2. Tenta pegar o Gist
        try:
            gist = g.get_gist(BACKUP_GIST_ID)
            print(f"✅ Gist acessado: {gist.description}")
        except Exception as e:
            print(f"❌ Não achou Gist {BACKUP_GIST_ID}: {e}")
            return False
        
        # 3. LISTA TODOS OS ARQUIVOS (DEBUG)
        print("📁 Arquivos encontrados:")
        file_found = False
        target_filename = None
        
        for filename in gist.files.keys():
            print(f"  • {filename}")
            if filename == "community_backup.json":
                file_found = True
                target_filename = filename
        
        if not file_found:
            print("❌ Arquivo 'community_backup.json' NÃO encontrado!")
            print("💡 Arquivos disponíveis:", list(gist.files.keys()))
            return False
        
        print(f"✅ Arquivo encontrado: {target_filename}")
        
        # 4. Tenta ler o arquivo
        file_info = gist.files[target_filename]
        
        try:
            data = json.loads(file_info.content)
            print(f"✅ JSON parseado, tamanho: {len(file_info.content)} chars")
            
            if "database" not in data:
                print("❌ JSON não tem campo 'database'")
                print(f"📊 Campos disponíveis: {list(data.keys())}")
                return False
            
            if not data["database"]:
                print("❌ Campo 'database' está vazio")
                return False
            
            # 5. Restaura
            db_bytes = base64.b64decode(data["database"])
            
            with open(DATABASE, 'wb') as f:
                f.write(db_bytes)
            
            print(f"✅ Banco restaurado! Data: {data.get('timestamp', 'N/A')}")
            print(f"📊 Dados: {data.get('tables', {})}")
            return True
            
        except json.JSONDecodeError as e:
            print(f"❌ Erro ao parsear JSON: {e}")
            print(f"📄 Primeiros 200 chars: {file_info.content[:200]}")
            return False
            
        except Exception as e:
            print(f"❌ Erro na restauração: {e}")
            return False
        
    except Exception as e:
        print(f"❌ Erro geral: {e}")
        return False

def create_backup():
    """Cria backup no GitHub"""
    if not BACKUP_ENABLED:
        return False
    
    # Verifica se há dados
    if not os.path.exists(DATABASE) or is_database_empty():
        print("⚠️ Nada para backup (banco vazio)")
        return False
    
    try:
        # Lê o banco
        with open(DATABASE, 'rb') as f:
            db_bytes = f.read()
        
        # Prepara dados
        backup_data = {
            "database": base64.b64encode(db_bytes).decode('utf-8'),
            "timestamp": datetime.now().isoformat(),
            "size": len(db_bytes),
            "tables": get_table_counts()
        }
        
        # Envia para GitHub
        g = Github(GITHUB_TOKEN)
        
        try:
            gist = g.get_gist(BACKUP_GIST_ID)
            gist.edit(
                description=f"NetOS Backup - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                files={"backup.json": {"content": json.dumps(backup_data, indent=2)}}
            )
            print(f"📤 Backup enviado: {BACKUP_GIST_ID}")
            return True
        except Exception as e:
            print(f"❌ Erro ao enviar backup: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Backup falhou: {e}")
        return False

def init_db_tables():
    """Apenas cria as tabelas se não existirem"""
    try:
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
        print("✅ Tabelas OK")
    except Exception as e:
        print(f"❌ Erro nas tabelas: {e}")

# ============ INICIALIZAÇÃO CORRETA ============

print("🚀 Iniciando NetOS no Render...")

# 1. Testa GitHub primeiro
github_ok = test_github()

# 2. LOGICA CORRETA: Se GitHub OK, tenta restaurar
restored = False
if github_ok:
    restored = restore_database()

# 3. Se não restaurou, cria tabelas (não banco vazio!)
if not restored:
    print("📝 Inicializando banco...")
    init_db_tables()

# 4. Se tem GitHub, inicia backup automático
if BACKUP_ENABLED:
    print("✅ Backup ativado")
    
    def backup_worker():
        while True:
            time.sleep(3600)  # 1 hora
            create_backup()
    
    threading.Thread(target=backup_worker, daemon=True).start()
else:
    print("⚠️ Backup desativado")

print("✅ Servidor pronto!")

# ============ ROTAS ============

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online',
        'service': 'NetOS Community',
        'timestamp': datetime.now().isoformat(),
        'backup': {
            'enabled': BACKUP_ENABLED,
            'gist_id': BACKUP_GIST_ID,
            'github_ok': bool(GITHUB_TOKEN and GITHUB_AVAILABLE)
        },
        'database': {
            'exists': os.path.exists(DATABASE),
            'empty': is_database_empty(),
            'tables': get_table_counts()
        }
    })

@app.route('/api/backup', methods=['POST'])
def manual_backup():
    if create_backup():
        return jsonify({'message': 'Backup feito'}), 200
    else:
        return jsonify({'error': 'Falha no backup'}), 500

@app.route('/api/restore', methods=['POST'])
def manual_restore():
    if restore_database():
        return jsonify({'message': 'Restaurado'}), 200
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
    
    # Backup após registro
    if BACKUP_ENABLED:
        threading.Thread(target=create_backup, daemon=True).start()
    
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
    
    # Backup após upload
    if BACKUP_ENABLED:
        threading.Thread(target=create_backup, daemon=True).start()
    
    return jsonify({
        'message': 'App uploaded successfully',
        'app_id': app_id
    }), 201

if __name__ == '__main__':
    app.run(debug=False)
