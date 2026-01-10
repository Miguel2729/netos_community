from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
import sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# Configurações
DATABASE = 'community.db'
UPLOAD_FOLDER = 'community_apps'
ALLOWED_EXTENSIONS = {'html', 'js', 'css', 'json', 'png', 'jpg', 'jpeg'}

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

init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'online',
        'service': 'NetOS Community Apps',
        'timestamp': datetime.now().isoformat()
    })

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
    
    return jsonify({
        'message': 'App uploaded successfully',
        'app_id': app_id
    }), 201

if __name__ == '__main__':
    app.run(debug=False)
