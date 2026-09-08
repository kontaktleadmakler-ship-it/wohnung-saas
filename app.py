from __future__ import annotations
import os, threading, logging
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
import db, scraper as worker
from scrapers.registry import list_sources
from scrapers.regions import BUNDESLAENDER

app=Flask(__name__)
app.secret_key=os.getenv('SECRET_KEY') or 'change-me-in-production'
APP_PASSWORD=os.getenv('APP_PASSWORD')
log=logging.getLogger('web')
scan_thread=None
scan_lock=threading.Lock()


def auth(view):
 @wraps(view)
 def wrapper(*a,**kw):
  if APP_PASSWORD and not session.get('logged_in'): return redirect(url_for('login',next=request.path))
  return view(*a,**kw)
 return wrapper

@app.before_request
def ensure_db():
 if request.endpoint!='static':
  try: db.init_db()
  except Exception: log.exception('DB-Initialisierung fehlgeschlagen')

@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  if not APP_PASSWORD or request.form.get('password','')==APP_PASSWORD:
   session['logged_in']=True; return redirect(request.args.get('next') or url_for('home'))
  return render_template('login.html',error='Falsches Passwort')
 return render_template('login.html',error=None)
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@auth
def home():
 try: rows=db.get_dashboard_rows(int(request.args.get('min_score',0)),request.args.get('profile_id') or None)
 except Exception: rows=[]; flash('Datenbank konnte nicht gelesen werden.')
 return render_template('dashboard.html',rows=rows,profiles=db.get_active_profiles(),min_score=int(request.args.get('min_score',0)),selected_profile=request.args.get('profile_id') or '',scan_running=bool(scan_thread and scan_thread.is_alive()))

@app.route('/scan/run',methods=['POST'])
@auth
def run_scan():
 global scan_thread
 with scan_lock:
  if scan_thread and scan_thread.is_alive(): flash('Scan läuft bereits.'); return redirect(url_for('home'))
  scan_thread=threading.Thread(target=_manual_scan,daemon=True); scan_thread.start()
 flash('Scan gestartet. Der PostgreSQL-Lock verhindert parallele Scans auch zwischen Web und Worker.')
 return redirect(url_for('home'))

def _manual_scan():
 try: worker.run_once()
 except Exception: log.exception('Manueller Scan fehlgeschlagen')

@app.route('/profiles',methods=['GET','POST'])
@auth
def profiles():
 if request.method=='POST':
  data=_profile_form(); pid=db.add_profile(data); db.set_profile_sources(pid,request.form.getlist('sources')); db.set_profile_regions(pid,request.form.getlist('regions')); flash('Profil angelegt.'); return redirect(url_for('profiles'))
 return render_template('profiles.html',profiles=[db.get_profile(p['id']) for p in db.get_active_profiles()],available_sources=list_sources(),available_regions=BUNDESLAENDER)

@app.route('/profiles/<int:pid>/edit',methods=['POST'])
@auth
def edit_profile(pid):
 data=_profile_form(); data['active']=request.form.get('active')=='1'; db.update_profile(pid,data); db.set_profile_sources(pid,request.form.getlist('sources')); db.set_profile_regions(pid,request.form.getlist('regions')); flash('Profil gespeichert.'); return redirect(url_for('profiles'))

@app.route('/profiles/<int:pid>/delete',methods=['POST'])
@auth
def delete_profile(pid): db.delete_profile(pid); flash('Profil gelöscht.'); return redirect(url_for('profiles'))

@app.route('/healthz')
def healthz():
 try: db.init_db(); return {'ok':True},200
 except Exception as e: return {'ok':False,'error':str(e)},503

def _profile_form():
 def num(name,default=0):
  v=request.form.get(name,'').strip(); return float(v) if v else default
 return {'name':request.form.get('name','').strip(),'min_price':num('min_price'),'max_price':num('max_price'),'min_rooms':num('min_rooms'),'max_rooms':(float(request.form['max_rooms']) if request.form.get('max_rooms') else None),'min_size':num('min_size'),'districts':request.form.get('districts',''),'keywords_exclude':request.form.get('keywords_exclude',''),'active':True}

if __name__=='__main__':
 db.init_db(); app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))
