#!/usr/bin/env python3
"""作业打卡 - Flask 后端服务器"""
import os, sqlite3
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'homework.db')
SUBJECTS = ['语文', '数学', '英语']

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS homework (
        date TEXT NOT NULL, subject TEXT NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (date, subject)
    )''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return send_file(os.path.join(BASE, 'homework.html'))

@app.route('/api/data')
def api_get_data():
    conn = get_db()
    rows = conn.execute('SELECT date, subject, completed FROM homework').fetchall()
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
    conn = get_db()
    cur = conn.execute('SELECT completed FROM homework WHERE date=? AND subject=?',
                       (date, subject)).fetchone()
    if cur:
        new_val = 0 if cur['completed'] else 1
        conn.execute('UPDATE homework SET completed=? WHERE date=? AND subject=?',
                     (new_val, date, subject))
    else:
        conn.execute('INSERT INTO homework (date,subject,completed) VALUES (?,?,1)',
                     (date, subject))
    conn.commit()
    rows = conn.execute('SELECT subject,completed FROM homework WHERE date=?',
                        (date,)).fetchall()
    conn.close()
    subjects = {s: False for s in SUBJECTS}
    for row in rows:
        subjects[row['subject']] = bool(row['completed'])
    return jsonify(subjects)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5800))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_ENV') == 'development'
    print(f'🌸 作业打卡服务: http://localhost:{port}')
    app.run(host=host, port=port, debug=debug)
