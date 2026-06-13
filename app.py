#!/usr/bin/env python3
"""作业打卡 - Flask 后端服务器（支持多学生）"""
import os, sqlite3, uuid
from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'homework.db')
UPLOAD_FOLDER = os.path.join(BASE, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
SUBJECTS = ['语文', '数学', '英语']
STUDENTS = {'chen': '郭雨晨', 'le': '郭雨乐'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn

def migrate_student_column():
    """迁移旧表，添加 student 列并重建主键"""
    conn = get_db()
    try:
        cur = conn.execute("PRAGMA table_info(homework)")
        cols = [row['name'] for row in cur.fetchall()]
        if 'student' not in cols:
            conn.execute("CREATE TABLE homework_v2 (date TEXT NOT NULL, subject TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, student TEXT NOT NULL DEFAULT 'chen', PRIMARY KEY (date, subject, student))")
            conn.execute("INSERT OR IGNORE INTO homework_v2 (date,subject,completed,student) SELECT date,subject,completed,'chen' FROM homework")
            conn.execute("DROP TABLE homework")
            conn.execute("ALTER TABLE homework_v2 RENAME TO homework")
        cur = conn.execute("PRAGMA table_info(photos)")
        cols = [row['name'] for row in cur.fetchall()]
        if 'student' not in cols:
            conn.execute("CREATE TABLE photos_v2 (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, subject TEXT NOT NULL, filename TEXT NOT NULL, student TEXT NOT NULL DEFAULT 'chen', created_at TEXT DEFAULT (datetime('now','localtime')))")
            conn.execute("INSERT OR IGNORE INTO photos_v2 (id,date,subject,filename,student,created_at) SELECT id,date,subject,filename,'chen',created_at FROM photos")
            conn.execute("DROP TABLE photos")
            conn.execute("ALTER TABLE photos_v2 RENAME TO photos")
        conn.commit()
    except Exception as e:
        print(f"[迁移提示] {e}")
    finally:
        conn.close()

def init_db():
    conn = get_db()
    conn.execute("CREATE TABLE IF NOT EXISTS homework (date TEXT NOT NULL, subject TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, student TEXT NOT NULL DEFAULT 'chen', PRIMARY KEY (date, subject, student))")
    conn.execute("CREATE TABLE IF NOT EXISTS photos (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, subject TEXT NOT NULL, filename TEXT NOT NULL, student TEXT NOT NULL DEFAULT 'chen', created_at TEXT DEFAULT (datetime('now','localtime')))")
    conn.commit()
    conn.close()
    migrate_student_column()

# ── 页面路由 ──

@app.route('/')
def index():
    return send_file(os.path.join(BASE, 'index.html'))

@app.route('/chen')
def chen_page():
    return send_file(os.path.join(BASE, 'homework.html'))

@app.route('/le')
def le_page():
    return send_file(os.path.join(BASE, 'homework.html'))

# ── 打卡 API ──

@app.route('/api/data')
def api_get_data():
    student = request.args.get('student', 'chen')
    conn = get_db()
    rows = conn.execute(
        'SELECT date, subject, completed FROM homework WHERE student=?', (student,)
    ).fetchall()
    conn.close()
    data = {}
    for row in rows:
        d = row['date']
        if d not in data:
            data[d] = {}
        data[d][row['subject']] = bool(row['completed'])
    return jsonify(data)

@app.route('/api/toggle', methods=['POST'])
def api_toggle():
    body = request.get_json()
    date, subject = body['date'], body['subject']
    student = body.get('student', 'chen')
    conn = get_db()
    cur = conn.execute(
        'SELECT completed FROM homework WHERE date=? AND subject=? AND student=?',
        (date, subject, student)
    ).fetchone()
    if cur:
        new_val = 0 if cur['completed'] else 1
        conn.execute(
            'UPDATE homework SET completed=? WHERE date=? AND subject=? AND student=?',
            (new_val, date, subject, student)
        )
    else:
        conn.execute(
            'INSERT INTO homework (date,subject,completed,student) VALUES (?,?,?,?)',
            (date, subject, 1, student)
        )
    conn.commit()
    rows = conn.execute(
        'SELECT subject,completed FROM homework WHERE date=? AND student=?',
        (date, student)
    ).fetchall()
    conn.close()
    subjects = {s: False for s in SUBJECTS}
    for row in rows:
        subjects[row['subject']] = bool(row['completed'])
    return jsonify(subjects)

# ── 照片 API ──

@app.route('/api/upload', methods=['POST'])
def api_upload():
    date = request.form.get('date')
    subject = request.form.get('subject')
    student = request.form.get('student', 'chen')
    if not date or not subject:
        return jsonify({'error': '缺少日期或科目'}), 400
    if subject not in SUBJECTS:
        return jsonify({'error': '无效科目'}), 400
    if student not in STUDENTS:
        return jsonify({'error': '无效学生'}), 400

    files = request.files.getlist('photos')
    uploaded = []
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            unique_name = f"{date}_{student}_{subject}_{uuid.uuid4().hex[:8]}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, unique_name))
            conn = get_db()
            conn.execute(
                'INSERT INTO photos (date, subject, filename, student) VALUES (?, ?, ?, ?)',
                (date, subject, unique_name, student)
            )
            conn.commit()
            conn.close()
            uploaded.append({'filename': unique_name, 'url': f'/uploads/{unique_name}'})

    return jsonify({'uploaded': uploaded, 'count': len(uploaded)})

@app.route('/api/photos')
def api_get_photos():
    date = request.args.get('date')
    subject = request.args.get('subject')
    student = request.args.get('student', 'chen')
    if not date or not subject:
        return jsonify({'error': '缺少日期或科目'}), 400

    conn = get_db()
    rows = conn.execute(
        'SELECT id, filename, created_at FROM photos WHERE date=? AND subject=? AND student=? ORDER BY id',
        (date, subject, student)
    ).fetchall()
    conn.close()

    photos = [{
        'id': row['id'],
        'url': f'/uploads/{row["filename"]}',
        'filename': row['filename'],
        'created_at': row['created_at']
    } for row in rows]

    return jsonify(photos)

@app.route('/api/photo/<int:photo_id>', methods=['DELETE'])
def api_delete_photo(photo_id):
    conn = get_db()
    row = conn.execute('SELECT filename FROM photos WHERE id=?', (photo_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '照片不存在'}), 404
    filepath = os.path.join(UPLOAD_FOLDER, row['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)
    conn.execute('DELETE FROM photos WHERE id=?', (photo_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5800))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_ENV') == 'development'
    print(f'🌸 作业打卡服务: http://localhost:{port}')
    app.run(host=host, port=port, debug=debug)
