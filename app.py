from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
import os
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import shutil

app = Flask(__name__)
app.secret_key = "110lab_competition_ultimate_2026"
app.permanent_session_lifetime = timedelta(hours=2)
UPLOAD_FOLDER = "uploads"
BACKUP_FOLDER = "backup"
ALLOWED_EXTENSIONS = {"pdf", "docx", "zip"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def init_db():
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('student','admin','judge')))''')
    c.execute('''CREATE TABLE IF NOT EXISTS teams
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  team_name TEXT NOT NULL,
                  leader_name TEXT NOT NULL,
                  member2 TEXT, member3 TEXT,
                  group_type TEXT NOT NULL,
                  status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approve','reject')),
                  upload_deadline TEXT DEFAULT '',
                  UNIQUE(team_name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS files
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  team_id INTEGER NOT NULL,
                  file_type TEXT NOT NULL,
                  filename TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  upload_time TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS judge_assign
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  judge_name TEXT NOT NULL,
                  team_id INTEGER NOT NULL,
                  UNIQUE(judge_name, team_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS scores
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  team_id INTEGER NOT NULL,
                  judge_name TEXT NOT NULL,
                  score REAL NOT NULL CHECK(score BETWEEN 0 AND 100),
                  UNIQUE(team_id, judge_name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS operation_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user TEXT NOT NULL,
                  ip TEXT NOT NULL,
                  action TEXT NOT NULL,
                  time TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notice
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  content TEXT NOT NULL,
                  create_time TEXT NOT NULL)''')
    conn.commit()
    conn.close()

init_db()

def get_client_ip():
    return request.remote_addr

def add_log(user, action):
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip = get_client_ip()
    c.execute("INSERT INTO operation_log (user,ip,action,time) VALUES (?,?,?,?)", (user, ip, action, now))
    conn.commit()
    conn.close()

def safe_upload_name(filename):
    name, ext = os.path.splitext(filename)
    return secure_filename(f"{name}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS

def calc_final_score(score_list, judge_mode=5):
    if not score_list:
        return None
    if len(score_list) <= 2:
        return round(sum(score_list)/len(score_list), 2)
    score_list.sort()
    cut = 1 if judge_mode == 3 else 2
    return round(sum(score_list[cut:-cut])/(len(score_list)-cut*2), 2)

def backup_db():
    src = "competition.db"
    dst = os.path.join(BACKUP_FOLDER, f"competition_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    shutil.copy(src, dst)

def init_demo_data():
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    c = conn.cursor()
    for user, pwd, role in [("admin", "123456", "admin"), ("stu1", "123456", "student"), ("judgeA", "123456", "judge")]:
        try:
            c.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)", (user, generate_password_hash(pwd), role))
        except: pass
    for i in range(1,6):
        try:
            c.execute("INSERT INTO teams (team_name,leader_name,member2,member3,group_type,status) VALUES (?,?,?,?,?,?)",
                     (f"测试队伍{i}", "stu1", "成员2", "成员3", "本科生组", "approve"))
        except: pass
    for tid in range(1,6):
        try:
            c.execute("INSERT INTO judge_assign (judge_name,team_id) VALUES (?,?)", ("judgeA", tid))
        except: pass
    for tid in range(1,6):
        try:
            c.execute("INSERT INTO scores (team_id,judge_name,score) VALUES (?,?,?)", (tid, "judgeA", 80+tid))
        except: pass
    conn.commit()
    conn.close()

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        user = request.form["username"].strip()
        pwd = request.form["password"]
        role = request.form["role"]
        conn = sqlite3.connect("competition.db", check_same_thread=False)
        row = conn.execute("SELECT password FROM users WHERE username=?",(user,)).fetchone()
        conn.close()
        if not row:
            conn = sqlite3.connect("competition.db", check_same_thread=False)
            conn.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)",
                         (user, generate_password_hash(pwd), role))
            conn.commit()
            conn.close()
        elif not check_password_hash(row[0], pwd):
            flash("❌ 账号或密码错误")
            return redirect(url_for("login"))
        session.permanent = True
        session["user"] = user
        session["role"] = role
        add_log(user, f"登录系统，身份：{role}")
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    user = session.get("user", "未知用户")
    session.clear()
    add_log(user, "退出登录")
    flash("✅ 已安全退出")
    return redirect(url_for("login"))

@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    user = session["user"]
    role = session["role"]
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    notices = conn.execute("SELECT * FROM notice ORDER BY create_time DESC LIMIT 3").fetchall()
    if role == "judge":
        my_teams = conn.execute('''SELECT t.* FROM teams t
                                   JOIN judge_assign ja ON t.id=ja.team_id
                                   WHERE ja.judge_name=?''', (user,)).fetchall()
        conn.close()
        return render_template("index.html", user=user, role=role, my_teams=my_teams, notices=notices)
    elif role == "student":
        my_teams = conn.execute("SELECT * FROM teams WHERE leader_name=?", (user,)).fetchall()
        conn.close()
        return render_template("index.html", user=user, role=role, my_teams=my_teams, notices=notices)
    conn.close()
    return render_template("index.html", user=user, role=role, notices=notices)

@app.route("/team_signup", methods=["GET","POST"])
def team_signup():
    if session["role"] != "student":
        flash("仅学生可报名")
        return redirect(url_for("index"))
    if request.method=="POST":
        tn = request.form["team_name"].strip()
        ln = session["user"]
        m2 = request.form["member2"].strip()
        m3 = request.form["member3"].strip()
        gt = request.form["group_type"]
        deadline = request.form["upload_deadline"]
        try:
            conn = sqlite3.connect("competition.db", check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO teams (team_name,leader_name,member2,member3,group_type,upload_deadline) VALUES (?,?,?,?,?,?)", (tn,ln,m2,m3,gt,deadline))
            conn.commit()
            add_log(session["user"], f"完成团队报名：{tn}")
            flash("✅ 报名成功！")
        except sqlite3.IntegrityError:
            flash("❌ 队伍名称已存在")
        finally:
            conn.close()
        return redirect(url_for("index"))
    return render_template("team_signup.html")

@app.route("/upload_file/<int:team_id>", methods=["GET","POST"])
def upload_file(team_id):
    if session["role"] != "student":
        flash("仅学生可上传")
        return redirect(url_for("index"))
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    team = conn.execute("SELECT leader_name,status,upload_deadline FROM teams WHERE id=?",(team_id,)).fetchone()
    if not team or team[0] != session["user"] or team[1] != "approve":
        conn.close()
        flash("❌ 无权限或队伍未审核")
        return redirect(url_for("index"))
    now = datetime.now().strftime("%Y-%m-%d")
    if team[2] and now > team[2]:
        conn.close()
        flash("❌ 已过上传截止时间")
        return redirect(url_for("index"))
    if request.method=="POST":
        f = request.files["file"]
        ftype = request.form["file_type"]
        if f and allowed_file(f.filename):
            fn = safe_upload_name(f.filename)
            fp = os.path.join(UPLOAD_FOLDER, fn)
            f.save(fp)
            c = conn.cursor()
            c.execute("INSERT INTO files (team_id,file_type,filename,file_path,upload_time) VALUES (?,?,?,?,?)",
                      (team_id,ftype,fn,fp,datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            add_log(session["user"], f"上传{ftype}文件：{fn}")
            flash("✅ 上传成功")
    files = conn.execute("SELECT * FROM files WHERE team_id=?",(team_id,)).fetchall()
    conn.close()
    return render_template("upload_file.html", team=team, files=files)

@app.route("/preview/<filename>")
def preview(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    return send_file(path)

@app.route("/admin_audit", methods=["GET","POST"])
def admin_audit():
    if session["role"] != "admin":
        flash("仅管理员可操作")
        return redirect(url_for("index"))
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    if request.method=="POST":
        tid = request.form["team_id"]
        status = request.form["status"]
        c = conn.cursor()
        c.execute("UPDATE teams SET status=? WHERE id=?",(status,tid))
        conn.commit()
        add_log(session["user"], f"审核队伍{tid}：{status}")
    teams = conn.execute("SELECT * FROM teams").fetchall()
    conn.close()
    return render_template("admin_audit.html", teams=teams)

@app.route("/batch_assign", methods=["GET","POST"])
def batch_assign():
    if session["role"] != "admin":
        flash("仅管理员可操作")
        return redirect(url_for("index"))
    if request.method=="POST":
        judges = request.form.getlist("judges")
        teams = request.form.getlist("teams")
        conn = sqlite3.connect("competition.db", check_same_thread=False)
        c = conn.cursor()
        for j in judges:
            for t in teams:
                try:
                    c.execute("INSERT INTO judge_assign (judge_name,team_id) VALUES (?,?)",(j,t))
                except: pass
        conn.commit()
        conn.close()
        add_log(session["user"], f"批量分配专家：{judges}")
        flash("✅ 分配完成")
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    teams = conn.execute("SELECT * FROM teams WHERE status='approve'").fetchall()
    conn.close()
    judge_list = ["评委A","评委B","评委C","评委D","评委E"]
    return render_template("batch_assign.html", teams=teams, judges=judge_list)

@app.route("/judge_score/<int:team_id>", methods=["GET","POST"])
def judge_score(team_id):
    if session["role"] != "judge":
        flash("仅评审可打分")
        return redirect(url_for("index"))
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    bind = conn.execute("SELECT 1 FROM judge_assign WHERE judge_name=? AND team_id=?",(session["user"],team_id)).fetchone()
    status = conn.execute("SELECT status FROM teams WHERE id=?",(team_id,)).fetchone()
    if not bind or not status or status[0] != "approve":
        conn.close()
        flash("❌ 您未分配该队伍")
        return redirect(url_for("index"))
    if request.method=="POST":
        score = float(request.form["score"])
        jn = session["user"]
        try:
            c = conn.cursor()
            c.execute("INSERT INTO scores (team_id, judge_name, score) VALUES (?,?,?)",(team_id,jn,score))
            conn.commit()
            add_log(jn, f"为队伍{team_id}打分：{score}")
            flash("✅ 打分成功")
        except sqlite3.IntegrityError:
            flash("❌ 已完成打分")
        finally:
            conn.close()
    return render_template("judge_score.html", team_id=team_id)

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    total = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    pass_cnt = conn.execute("SELECT COUNT(*) FROM teams WHERE status='approve'").fetchone()[0]
    reject_cnt = conn.execute("SELECT COUNT(*) FROM teams WHERE status='reject'").fetchone()[0]
    pending_cnt = conn.execute("SELECT COUNT(*) FROM teams WHERE status='pending'").fetchone()[0]
    score_cnt = conn.execute("SELECT COUNT(DISTINCT team_id) FROM scores").fetchone()[0]
    ug = conn.execute("SELECT COUNT(*) FROM teams WHERE group_type='本科生组'").fetchone()[0]
    pg = conn.execute("SELECT COUNT(*) FROM teams WHERE group_type='研究生组'").fetchone()[0]
    conn.close()
    add_log(session["user"], "访问数据看板")
    return render_template("dashboard.html", total=total, pass_cnt=pass_cnt, reject_cnt=reject_cnt, pending_cnt=pending_cnt, score_cnt=score_cnt, ug=ug, pg=pg)

@app.route("/log_view")
def log_view():
    if session["role"] != "admin":
        flash("仅管理员可查看日志")
        return redirect(url_for("index"))
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    logs = conn.execute("SELECT * FROM operation_log ORDER BY time DESC").fetchall()
    conn.close()
    return render_template("log_view.html", logs=logs)

@app.route("/export_log")
def export_log():
    if session["role"] != "admin": abort(403)
    backup_db()
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    df = pd.read_sql("SELECT * FROM operation_log ORDER BY time DESC", conn)
    fname = f"系统操作日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(fname, index=False)
    conn.close()
    add_log(session["user"], "导出日志并备份数据库")
    return send_file(fname, as_attachment=True)

@app.route("/score_public")
def score_public():
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    team_list = conn.execute("SELECT id,team_name,group_type FROM teams WHERE status='approve'").fetchall()
    res = []
    for tid,name,gtype in team_list:
        scores = [s[0] for s in conn.execute("SELECT score FROM scores WHERE team_id=?",(tid,)).fetchall()]
        final = calc_final_score(scores,5)
        res.append({"队伍名称":name,"组别":gtype,"最终平均分":final})
    df = pd.DataFrame(res).sort_values("最终平均分", ascending=False, na_position="last")
    conn.close()
    return render_template("score_public.html", data=df.to_dict("records"))

@app.route("/export_excel/<int:judge_mode>")
def export_excel(judge_mode):
    if session["role"] != "admin": abort(403)
    backup_db()
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    team_list = conn.execute("SELECT id,team_name,group_type,status FROM teams").fetchall()
    res = []
    for tid,name,gtype,status in team_list:
        scores = [s[0] for s in conn.execute("SELECT score FROM scores WHERE team_id=?",(tid,)).fetchall()]
        final = calc_final_score(scores, judge_mode)
        res.append({"队伍名称":name,"组别":gtype,"状态":status,"最终平均分":final})
    df = pd.DataFrame(res).sort_values("最终平均分", ascending=False, na_position="last")
    fname = f"竞赛成绩_{judge_mode}评委_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(fname, index=False)
    conn.close()
    add_log(session["user"], f"导出{judge_mode}评委成绩")
    return send_file(fname, as_attachment=True)

@app.route("/notice", methods=["GET","POST"])
def notice():
    if session["role"] != "admin":
        flash("仅管理员可发布公告")
        return redirect(url_for("index"))
    if request.method=="POST":
        content = request.form["content"].strip()
        conn = sqlite3.connect("competition.db", check_same_thread=False)
        conn.execute("INSERT INTO notice (content,create_time) VALUES (?,?)", (content, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        add_log(session["user"], "发布公告")
        flash("✅ 公告发布成功")
    conn = sqlite3.connect("competition.db", check_same_thread=False)
    notices = conn.execute("SELECT * FROM notice ORDER BY create_time DESC").fetchall()
    conn.close()
    return render_template("notice.html", notices=notices)

@app.route("/init_demo")
def init_demo():
    if session["role"] != "admin": abort(403)
    init_demo_data()
    flash("✅ 演示数据初始化完成")
    return redirect(url_for("index"))

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", msg="权限不足"),403
@app.errorhandler(404)
def notfound(e):
    return render_template("error.html", msg="页面不存在"),404

if __name__=="__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)