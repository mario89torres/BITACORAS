from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, has_request_context
import sqlite3, csv, io, socket, random, string, os
from datetime import datetime

app = Flask(__name__)
_data_dir = '/data' if os.path.isdir('/data') else os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(_data_dir, 'bitacora.db')

GRUPOS  = [f"{g}°{l}" for g in ['1','2','3'] for l in ['A','B','C','D']]
SALAS   = ['ML-1', 'ML-2', 'ML-3']
ESTADOS = ['✅ Buena', '⚠️ Regular', '🔴 Dañada']

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS sesiones(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            profesor TEXT, grupo TEXT, sala TEXT,
            fecha TEXT, hora TEXT,
            activa INTEGER DEFAULT 1, num_pc INTEGER DEFAULT 30,
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS registros(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid INTEGER REFERENCES sesiones(id),
            alumno TEXT, pc TEXT, estado TEXT, notas TEXT DEFAULT '',
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS devoluciones(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid INTEGER REFERENCES sesiones(id),
            pc TEXT, alumno TEXT,
            estado TEXT,
            notas TEXT DEFAULT '',
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        """)

def mk_code():
    with db() as con:
        while True:
            code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=5))
            if not con.execute("SELECT 1 FROM sesiones WHERE code=?", (code,)).fetchone():
                return code

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
    except: ip = "127.0.0.1"
    return ip

def get_profesores():
    with db() as con:
        rows = con.execute("SELECT DISTINCT profesor FROM sesiones ORDER BY profesor").fetchall()
    return [r['profesor'] for r in rows]

init_db()

@app.route('/')
def index():
    with db() as con:
        sesiones = con.execute("""
            SELECT s.*, COUNT(r.id) as total_reg
            FROM sesiones s LEFT JOIN registros r ON r.sid = s.id
            GROUP BY s.id ORDER BY s.id DESC LIMIT 30
        """).fetchall()
    return render_template('index.html', sesiones=sesiones, ip=local_ip())

@app.route('/nueva', methods=['GET','POST'])
def nueva():
    if request.method == 'POST':
        code = mk_code()
        with db() as con:
            cur = con.execute("""
                INSERT INTO sesiones(code,profesor,grupo,sala,fecha,hora,num_pc)
                VALUES(?,?,?,?,?,?,?)
            """, (code,
                  request.form['profesor'].strip(),
                  request.form['grupo'],
                  request.form['sala'],
                  request.form['fecha'],
                  request.form['hora'],
                  int(request.form.get('num_pc', 30))))
            sid = cur.lastrowid
        return redirect(url_for('sesion', sid=sid))
    now = datetime.now()
    return render_template('nueva.html',
        grupos=GRUPOS, salas=SALAS,
        fecha=now.strftime('%Y-%m-%d'),
        hora=now.strftime('%H:%M'),
        profesores=get_profesores())

@app.route('/sesion/<int:sid>')
def sesion(sid):
    with db() as con:
        s    = con.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
        regs = con.execute("SELECT * FROM registros WHERE sid=? ORDER BY ts", (sid,)).fetchall()
    if not s: return redirect(url_for('index'))
    base = request.host_url.rstrip('/')
    url_alumno = f"{base}/r/{s['code']}"
    return render_template('sesion.html', s=s, regs=regs,
        url_alumno=url_alumno, ip=local_ip())

@app.route('/sesion/<int:sid>/datos')
def sesion_datos(sid):
    with db() as con:
        regs = con.execute(
            "SELECT id,alumno,pc,estado,notas,ts FROM registros WHERE sid=? ORDER BY ts",(sid,)).fetchall()
        s = con.execute("SELECT activa,num_pc FROM sesiones WHERE id=?", (sid,)).fetchone()
    return jsonify({'registros':[dict(r) for r in regs], 'activa': bool(s['activa']), 'num_pc': s['num_pc']})

@app.route('/sesion/<int:sid>/cerrar', methods=['POST'])
def cerrar(sid):
    with db() as con: con.execute("UPDATE sesiones SET activa=0 WHERE id=?", (sid,))
    return redirect(url_for('sesion', sid=sid))

@app.route('/sesion/<int:sid>/reabrir', methods=['POST'])
def reabrir(sid):
    with db() as con: con.execute("UPDATE sesiones SET activa=1 WHERE id=?", (sid,))
    return redirect(url_for('sesion', sid=sid))

@app.route('/sesion/<int:sid>/csv')
def descargar_csv(sid):
    with db() as con:
        s    = con.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
        regs = con.execute("SELECT * FROM registros WHERE sid=? ORDER BY ts", (sid,)).fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Profesor','Grupo','Sala','Fecha','Hora de sesión'])
    w.writerow([s['profesor'], s['grupo'], s['sala'], s['fecha'], s['hora']])
    w.writerow([])
    w.writerow(['#','Alumno','Computadora','Estado','Notas','Hora de registro'])
    for i,r in enumerate(regs,1):
        w.writerow([i, r['alumno'], r['pc'], r['estado'], r['notas'], r['ts']])
    resp = make_response('\ufeff' + out.getvalue())   # BOM for Excel
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=bitacora_{s["grupo"]}_{s["fecha"]}.csv'
    return resp

@app.route('/sesion/<int:sid>/devolucion')
def devolucion(sid):
    with db() as con:
        s    = con.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
        regs = con.execute("SELECT pc, alumno FROM registros WHERE sid=? ORDER BY CAST(pc AS INTEGER)", (sid,)).fetchall()
        devs = con.execute("SELECT pc, estado FROM devoluciones WHERE sid=?", (sid,)).fetchall()
    if not s: return redirect(url_for('index'))
    devs_map = {d['pc']: d['estado'] for d in devs}
    return render_template('devolucion.html', s=s, regs=regs, devs_map=devs_map)

@app.route('/sesion/<int:sid>/devolucion/marcar', methods=['POST'])
def devolucion_marcar(sid):
    pc     = request.json.get('pc', '').strip()
    estado = request.json.get('estado', '').strip()
    notas  = request.json.get('notas', '').strip()
    with db() as con:
        alumno = con.execute("SELECT alumno FROM registros WHERE sid=? AND pc=?", (sid, pc)).fetchone()
        alumno = alumno['alumno'] if alumno else ''
        existing = con.execute("SELECT id FROM devoluciones WHERE sid=? AND pc=?", (sid, pc)).fetchone()
        if existing:
            con.execute("UPDATE devoluciones SET estado=?, notas=?, ts=datetime('now','localtime') WHERE sid=? AND pc=?",
                        (estado, notas, sid, pc))
        else:
            con.execute("INSERT INTO devoluciones(sid, pc, alumno, estado, notas) VALUES(?,?,?,?,?)",
                        (sid, pc, alumno, estado, notas))
    return jsonify({'ok': True, 'pc': pc, 'estado': estado})

@app.route('/sesion/<int:sid>/devolucion/datos')
def devolucion_datos(sid):
    with db() as con:
        devs = con.execute("SELECT pc, estado, notas, ts FROM devoluciones WHERE sid=? ORDER BY ts", (sid,)).fetchall()
    return jsonify([dict(d) for d in devs])

@app.route('/r/<code>', methods=['GET','POST'])
def registro(code):
    with db() as con:
        s = con.execute("SELECT * FROM sesiones WHERE code=?", (code,)).fetchone()
    if not s: return render_template('error.html', msg='Sesión no encontrada.'), 404
    if not s['activa']: return render_template('error.html', msg='Esta sesión ya fue cerrada por el profesor.'), 403
    if request.method == 'POST':
        alumno = request.form.get('alumno','').strip()
        pc     = request.form.get('pc','').strip()
        estado = request.form.get('estado','').strip()
        notas  = request.form.get('notas','').strip()
        if alumno and pc and estado:
            with db() as con:
                con.execute("INSERT INTO registros(sid,alumno,pc,estado,notas) VALUES(?,?,?,?,?)",
                            (s['id'], alumno, pc, estado, notas))
            return render_template('confirmacion.html',
                alumno=alumno, pc=pc, estado=estado, grupo=s['grupo'], sala=s['sala'])
    with db() as con:
        ocupadas = {r['pc']: r['alumno'] for r in con.execute(
            "SELECT pc, alumno FROM registros WHERE sid=?", (s['id'],)).fetchall()}
    return render_template('registro.html', s=s, ocupadas=ocupadas, estados=ESTADOS)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n  Bitacora Lab iniciada en puerto {port}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
