#!/usr/bin/env python3
"""作业打卡 - Flask 后端（支持多学生、媒体上传、OSS、连续打卡）"""
import os, sqlite3, uuid
from flask import Flask, request, jsonify, send_file, send_from_directory
from datetime import datetime, timedelta, date

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'homework.db')
UPLOAD_FOLDER = os.path.join(BASE, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
SUBJECTS = ['语文', '数学', '英语']
STUDENTS = {'chen': '郭雨晨', 'le': '郭雨乐'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── OSS（纯 Python HMAC-SHA1 实现，零外部依赖）──
OSS_ENABLED = all(os.environ.get(k) for k in ['OSS_ENDPOINT','OSS_BUCKET','OSS_KEY_ID','OSS_KEY_SECRET'])

import hmac, hashlib, base64, time, email.utils
from urllib.request import Request, urlopen
from urllib.parse import quote

def _oss_sign(verb, oss_key, headers=None, expires=None):
    key_secret = os.environ['OSS_KEY_SECRET']
    bucket = os.environ['OSS_BUCKET']
    resource = '/' + bucket + '/' + oss_key
    if expires:
        string_to_sign = f"{verb}\n\n\n{expires}\n{resource}"
    else:
        d = headers.get('Date', '')
        ct = headers.get('Content-Type', '')
        string_to_sign = f"{verb}\n\n{ct}\n{d}\n{resource}"
    h = hmac.new(key_secret.encode(), string_to_sign.encode(), hashlib.sha1)
    return base64.b64encode(h.digest()).decode()

def _oss_url(oss_key):
    return f"https://{os.environ['OSS_BUCKET']}.{os.environ['OSS_ENDPOINT']}/{quote(oss_key, safe='')}"

def upload_to_oss(file_path, oss_key):
    url = _oss_url(oss_key)
    date_str = email.utils.formatdate(usegmt=True)
    headers = {'Date': date_str, 'Content-Type': 'application/octet-stream'}
    sig = _oss_sign('PUT', oss_key, headers)
    headers['Authorization'] = f"OSS {os.environ['OSS_KEY_ID']}:{sig}"
    with open(file_path, 'rb') as f:
        data = f.read()
    req = Request(url, data=data, headers=headers, method='PUT')
    urlopen(req)
    return True

def oss_signed_url(oss_key, expires=3600):
    expire_time = int(time.time()) + expires
    sig = _oss_sign('GET', oss_key, expires=str(expire_time))
    return f"https://{os.environ['OSS_BUCKET']}.{os.environ['OSS_ENDPOINT']}/{quote(oss_key, safe='')}?OSSAccessKeyId={os.environ['OSS_KEY_ID']}&Expires={expire_time}&Signature={quote(sig, safe='')}"

def delete_oss(oss_key):
    url = _oss_url(oss_key)
    date_str = email.utils.formatdate(usegmt=True)
    headers = {'Date': date_str}
    sig = _oss_sign('DELETE', oss_key, headers)
    headers['Authorization'] = f"OSS {os.environ['OSS_KEY_ID']}:{sig}"
    req = Request(url, headers=headers, method='DELETE')
    urlopen(req)
    return True

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn

def today_str():
    return date.today().isoformat()

# ── 数据库 ──

def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS homework (
        date TEXT NOT NULL, subject TEXT NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        student TEXT NOT NULL DEFAULT 'chen',
        PRIMARY KEY (date, subject, student)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, subject TEXT NOT NULL,
        student TEXT NOT NULL DEFAULT 'chen',
        type TEXT NOT NULL DEFAULT 'photo',
        filename TEXT NOT NULL, oss_key TEXT,
        duration INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS rewards (
        student TEXT NOT NULL, date TEXT NOT NULL,
        stars INTEGER NOT NULL DEFAULT 0,
        bonus_stars INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (student, date)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS notes (
        date TEXT NOT NULL,
        subject TEXT NOT NULL,
        student TEXT NOT NULL DEFAULT 'chen',
        content TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (date, subject, student)
    )""")
    conn.commit()
    conn.close()
    migrate_photos()

def migrate_photos():
    conn = get_db()
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='photos'")
        if cur.fetchone():
            rows = conn.execute("SELECT id,date,subject,filename,student,created_at FROM photos").fetchall()
            for r in rows:
                s = r['student'] or 'chen'
                conn.execute("INSERT OR IGNORE INTO media (id,date,subject,filename,student,type,created_at) VALUES (?,?,?,?,?,'photo',?)",
                            (r['id'],r['date'],r['subject'],r['filename'],s,r['created_at']))
            conn.execute("DROP TABLE photos")
            conn.commit()
    except: pass
    finally: conn.close()

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
    rows = conn.execute("SELECT date,subject,completed FROM homework WHERE student=?", (student,)).fetchall()
    conn.close()
    data = {}
    for row in rows:
        d = row['date']
        if d not in data: data[d] = {}
        data[d][row['subject']] = bool(row['completed'])
    return jsonify(data)

@app.route('/api/toggle', methods=['POST'])
def api_toggle():
    body = request.get_json()
    ds, sub, stu = body['date'], body['subject'], body.get('student', 'chen')
    conn = get_db()
    cur = conn.execute("SELECT completed FROM homework WHERE date=? AND subject=? AND student=?", (ds, sub, stu)).fetchone()
    if cur:
        nv = 0 if cur['completed'] else 1
        conn.execute("UPDATE homework SET completed=? WHERE date=? AND subject=? AND student=?", (nv, ds, sub, stu))
    else:
        conn.execute("INSERT INTO homework (date,subject,completed,student) VALUES (?,?,1,?)", (ds, sub, stu))
    conn.commit()
    rows = conn.execute("SELECT subject,completed FROM homework WHERE date=? AND student=?", (ds, stu)).fetchall()
    conn.close()
    subs = {s: False for s in SUBJECTS}
    for r in rows: subs[r['subject']] = bool(r['completed'])
    if all(subs.values()): award_stars(ds, stu)
    return jsonify(subs)

def award_stars(ds, stu):
    conn = get_db()
    r = conn.execute("SELECT stars FROM rewards WHERE student=? AND date=?", (stu, ds)).fetchone()
    if not r:
        conn.execute("INSERT INTO rewards (student,date,stars,bonus_stars) VALUES (?,?,1,0)", (stu, ds))
        conn.commit()
    conn.close()

# ── 连续打卡 & 星星 ──

@app.route('/api/streaks')
def api_get_streaks():
    stu = request.args.get('student', 'chen')
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT date FROM homework WHERE student=? AND completed=1 ORDER BY date", (stu,)).fetchall()
    all_dates = sorted(set(r['date'] for r in rows))
    # 哪些天全部完成
    full = []
    for ds in all_dates:
        subs = conn.execute("SELECT subject,completed FROM homework WHERE student=? AND date=?", (stu, ds)).fetchall()
        if all(s['completed'] for s in subs): full.append(ds)
    # 当前连续
    streak = 0
    now = date.today()
    for i in range(366):
        ds = (now - timedelta(days=i)).isoformat()
        if ds in full: streak += 1
        else:
            if i == 0: continue  # today not done yet, check from yesterday
            else: break
    if streak == 0 and len(full) > 0 and full[-1] == (now - timedelta(days=1)).isoformat():
        # yesterday was done but today isn't
        for i in range(366):
            ds = (now - timedelta(days=1+i)).isoformat()
            if ds in full: streak += 1
            else: break
    # 星星
    row = conn.execute("SELECT COALESCE(SUM(stars+bonus_stars),0) as t FROM rewards WHERE student=?", (stu,)).fetchone()
    total = row['t'] if row else 0
    conn.close()
    return jsonify({'current_streak': streak, 'total_stars': total, 'full_days': full})

# ── 媒体上传 ──

@app.route('/api/upload', methods=['POST'])
def api_upload():
    ds = request.form.get('date')
    sub = request.form.get('subject')
    stu = request.form.get('student', 'chen')
    mtype = request.form.get('type', 'photo')
    if not ds or not sub: return jsonify({'error': '缺少日期或科目'}), 400
    if sub not in SUBJECTS: return jsonify({'error': '无效科目'}), 400
    if stu not in STUDENTS: return jsonify({'error': '无效学生'}), 400

    files = request.files.getlist('media')
    uploaded = []
    for f in files:
        if f and f.filename:
            ext = f.filename.rsplit('.',1)[1].lower() if '.' in f.filename else 'webm'
            name = f"{ds}_{stu}_{sub}_{uuid.uuid4().hex[:8]}.{ext}"
            oss_key = f"{stu}/{ds}/{sub}/{name}"
            local = os.path.join(UPLOAD_FOLDER, name)
            f.save(local)
            oss_url = None
            if OSS_ENABLED:
                upload_to_oss(local, oss_key)
                oss_url = oss_signed_url(oss_key)
                os.remove(local)
            conn = get_db()
            conn.execute("INSERT INTO media (date,subject,filename,student,type,oss_key) VALUES (?,?,?,?,?,?)",
                        (ds, sub, name, stu, mtype, oss_key if OSS_ENABLED else None))
            conn.commit()
            conn.close()
            uploaded.append({'filename': name, 'url': oss_url or f'/uploads/{name}', 'type': mtype})
    return jsonify({'uploaded': uploaded, 'count': len(uploaded)})

@app.route('/api/media')
def api_get_media():
    ds = request.args.get('date')
    sub = request.args.get('subject')
    stu = request.args.get('student', 'chen')
    if not ds or not sub: return jsonify({'error': '缺少日期或科目'}), 400
    conn = get_db()
    rows = conn.execute("SELECT id,filename,type,oss_key,duration,created_at FROM media WHERE date=? AND subject=? AND student=? ORDER BY id",
                       (ds, sub, stu)).fetchall()
    conn.close()
    items = []
    for r in rows:
        url = oss_signed_url(r['oss_key']) if r['oss_key'] else f'/uploads/{r["filename"]}'
        items.append({'id': r['id'], 'url': url, 'filename': r['filename'], 'type': r['type'],
                      'duration': r['duration'], 'created_at': r['created_at']})
    return jsonify(items)

@app.route('/api/media/<int:mid>', methods=['DELETE'])
def api_delete_media(mid):
    conn = get_db()
    r = conn.execute("SELECT filename,oss_key FROM media WHERE id=?", (mid,)).fetchone()
    if not r: return jsonify({'error': '不存在'}), 404
    if r['oss_key']: delete_oss(r['oss_key'])
    else:
        fp = os.path.join(UPLOAD_FOLDER, r['filename'])
        if os.path.exists(fp): os.remove(fp)
    conn.execute("DELETE FROM media WHERE id=?", (mid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ── 学习备注 ──

@app.route('/api/notes', methods=['GET', 'POST'])
def api_notes():
    stu = request.args.get('student') or request.form.get('student') or 'chen'

    if request.method == 'GET':
        date_s = request.args.get('date', '')
        conn = get_db()
        rows = conn.execute(
            "SELECT subject, content FROM notes WHERE date=? AND student=?",
            (date_s, stu)
        ).fetchall()
        conn.close()
        result = {}
        for row in rows:
            result[row['subject']] = row['content']
        return jsonify(result)

    # POST
    body = request.get_json()
    if not body:
        return jsonify({'error': '缺少请求体'}), 400
    ds = body.get('date')
    sub = body.get('subject')
    content = body.get('notes', '')
    if not ds or not sub:
        return jsonify({'error': '缺少日期或科目'}), 400
    if sub not in SUBJECTS:
        return jsonify({'error': '无效科目'}), 400
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO notes (date, subject, student, content) VALUES (?,?,?,?)",
        (ds, sub, stu, content)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5800))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_ENV') == 'development'
    print(f'🌸 作业打卡服务: http://localhost:{port}')
    print(f'📦 OSS: {"已启用" if OSS_ENABLED else "未配置，使用本地存储"}')
    app.run(host=host, port=port, debug=debug)
