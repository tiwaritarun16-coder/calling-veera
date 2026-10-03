import csv
import io
import os
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func, text
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
db_url = os.environ.get("DATABASE_URL", "sqlite:///calling_veera.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "1") == "1"
db = SQLAlchemy(app)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Caller(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(40), default="")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caller_id = db.Column(db.Integer, db.ForeignKey("caller.id", ondelete="CASCADE"), nullable=False)
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(40), default="Pending", nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text, default="")
    last_called_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    caller = db.relationship("Caller", backref=db.backref("assignments", cascade="all, delete-orphan"))
    lead = db.relationship("Lead", backref=db.backref("assignments", cascade="all, delete-orphan"))
    __table_args__ = (UniqueConstraint("caller_id", "lead_id", name="uq_caller_lead"),)


class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, default="")


def init_db():
    with app.app_context():
        db.create_all()
        defaults = {
            "whatsapp_template": "Hello {name}, this is from our team. I wanted to connect with you.",
            "whatsapp_country_code": "91",
        }
        for k, v in defaults.items():
            if db.session.get(Setting, k) is None:
                db.session.add(Setting(key=k, value=v))
        db.session.commit()


def get_setting(key, default=""):
    row = db.session.get(Setting, key)
    return row.value if row else default


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


def current_role():
    return session.get("role")


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You do not have access to that page.", "error")
                return redirect(url_for("home"))
            return fn(*args, **kwargs)
        return wrapper
    return deco


def normalize_whatsapp(phone):
    raw = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    if raw.startswith("+"):
        return raw[1:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    prefix = get_setting("whatsapp_country_code", "91")
    if prefix and not digits.startswith(prefix):
        digits = prefix + digits
    return digits


def parse_csv(file_storage):
    text = file_storage.read().decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@app.context_processor
def inject_globals():
    return {"role": current_role(), "user_name": session.get("user_name", "")}


@app.route("/")
def home():
    if not Admin.query.count():
        return redirect(url_for("setup"))
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return redirect(url_for("admin_dashboard" if session.get("role") == "admin" else "caller_dashboard"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if Admin.query.count():
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not username or len(password) < 6:
            flash("Enter a name, username, and a password of at least 6 characters.", "error")
        else:
            db.session.add(Admin(name=name, username=username, password_hash=generate_password_hash(password)))
            db.session.commit()
            flash("Admin created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "caller")
        user = None
        if role == "admin":
            user = Admin.query.filter_by(username=username).first()
        else:
            user = Caller.query.filter_by(username=username, active=True).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session["role"] = role
            session["user_name"] = user.name
            return redirect(url_for("admin_dashboard" if role == "admin" else "caller_dashboard"))
        flash("Invalid login details.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    callers = Caller.query.order_by(Caller.name).all()
    total_leads = Lead.query.count()
    total_assignments = Assignment.query.count()
    completed = Assignment.query.filter_by(status="Completed").count()
    pending = Assignment.query.filter_by(status="Pending").count()
    unreachable = Assignment.query.filter_by(status="Not reachable").count()
    call_again = Assignment.query.filter_by(status="Call again").count()
    stats = []
    for c in callers:
        q = Assignment.query.filter_by(caller_id=c.id)
        stats.append({
            "caller": c,
            "total": q.count(),
            "completed": q.filter_by(status="Completed").count(),
            "pending": q.filter_by(status="Pending").count(),
            "unreachable": q.filter_by(status="Not reachable").count(),
            "call_again": q.filter_by(status="Call again").count(),
            "attempts": db.session.query(func.coalesce(func.sum(Assignment.attempts), 0)).filter(Assignment.caller_id == c.id).scalar() or 0,
        })
    return render_template("admin.html", callers=callers, stats=stats, total_leads=total_leads,
                           total_assignments=total_assignments, completed=completed, pending=pending,
                           unreachable=unreachable, call_again=call_again,
                           template=get_setting("whatsapp_template"), country=get_setting("whatsapp_country_code", "91"),
                           admins=Admin.query.order_by(Admin.name).all())


@app.route("/admin/callers/add", methods=["POST"])
@login_required("admin")
def add_caller():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    phone = request.form.get("phone", "").strip()
    if not name or not username or len(password) < 6:
        flash("Caller needs name, username and a password of at least 6 characters.", "error")
    elif Caller.query.filter_by(username=username).first() or Admin.query.filter_by(username=username).first():
        flash("That username is already in use.", "error")
    else:
        db.session.add(Caller(name=name, username=username, password_hash=generate_password_hash(password), phone=phone))
        db.session.commit()
        flash("Caller created.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/callers/import", methods=["POST"])
@login_required("admin")
def import_callers():
    file = request.files.get("file")
    if not file:
        flash("Choose a caller CSV file.", "error")
        return redirect(url_for("admin_dashboard"))
    rows = parse_csv(file)
    added = 0
    skipped = 0
    for row in rows:
        name = (row.get("Name") or row.get("name") or "").strip()
        username = (row.get("Username") or row.get("username") or "").strip().lower()
        password = (row.get("Password") or row.get("password") or "").strip()
        phone = (row.get("Phone") or row.get("phone") or "").strip()
        if not name or not username or len(password) < 6 or Caller.query.filter_by(username=username).first() or Admin.query.filter_by(username=username).first():
            skipped += 1
            continue
        db.session.add(Caller(name=name, username=username, password_hash=generate_password_hash(password), phone=phone))
        added += 1
    db.session.commit()
    flash(f"Caller import complete: {added} added, {skipped} skipped.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/leads/add", methods=["POST"])
@login_required("admin")
def add_lead():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    if not name or not phone:
        flash("Lead needs a name and phone number.", "error")
    else:
        db.session.add(Lead(name=name, phone=phone))
        db.session.commit()
        flash("Lead added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/leads/import", methods=["POST"])
@login_required("admin")
def import_leads():
    file = request.files.get("file")
    if not file:
        flash("Choose a lead CSV file.", "error")
        return redirect(url_for("admin_dashboard"))
    rows = parse_csv(file)
    added = 0
    for row in rows:
        name = (row.get("Name") or row.get("name") or "").strip()
        phone = (row.get("Phone") or row.get("phone") or "").strip()
        if name and phone:
            db.session.add(Lead(name=name, phone=phone))
            added += 1
    db.session.commit()
    flash(f"Lead import complete: {added} leads added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/assign", methods=["POST"])
@login_required("admin")
def assign_leads():
    mode = request.form.get("mode", "all")
    caller_ids = [int(x) for x in request.form.getlist("caller_ids") if x.isdigit()]
    leads = Lead.query.order_by(Lead.id).all()
    if not caller_ids:
        flash("Select at least one caller.", "error")
        return redirect(url_for("admin_dashboard"))
    if not leads:
        flash("Import leads first.", "error")
        return redirect(url_for("admin_dashboard"))
    created = 0
    if mode == "all":
        pairs = [(cid, lead.id) for cid in caller_ids for lead in leads]
    else:
        pairs = [(caller_ids[i % len(caller_ids)], lead.id) for i, lead in enumerate(leads)]
    for cid, lid in pairs:
        if not Assignment.query.filter_by(caller_id=cid, lead_id=lid).first():
            db.session.add(Assignment(caller_id=cid, lead_id=lid))
            created += 1
    db.session.commit()
    flash(f"Assignment complete: {created} new assignments created.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/settings", methods=["POST"])
@login_required("admin")
def settings():
    template = request.form.get("template", "").strip()
    country = "".join(ch for ch in request.form.get("country", "91") if ch.isdigit())
    set_setting("whatsapp_template", template)
    set_setting("whatsapp_country_code", country)
    flash("WhatsApp settings saved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/admins/add", methods=["POST"])
@login_required("admin")
def add_admin():
    if Admin.query.count() >= 3:
        flash("Maximum 3 admins allowed.", "error")
        return redirect(url_for("admin_dashboard"))
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    if not name or not username or len(password) < 6:
        flash("Admin needs name, username and a password of at least 6 characters.", "error")
    elif Admin.query.filter_by(username=username).first() or Caller.query.filter_by(username=username).first():
        flash("That username is already in use.", "error")
    else:
        db.session.add(Admin(name=name, username=username, password_hash=generate_password_hash(password)))
        db.session.commit()
        flash("Admin created.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/clear", methods=["POST"])
@login_required("admin")
def clear_all():
    Assignment.query.delete()
    Lead.query.delete()
    db.session.commit()
    flash("All leads and assignments were cleared. Caller and admin accounts were kept.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/export.csv")
@login_required("admin")
def admin_export():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Caller", "Lead", "Phone", "Status", "Attempts", "Notes", "Last Called"])
    for a in Assignment.query.order_by(Assignment.id).all():
        writer.writerow([a.caller.name, a.lead.name, a.lead.phone, a.status, a.attempts, a.notes or "", a.last_called_at or ""])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=calling_veera_results.csv"})


@app.route("/caller")
@login_required("caller")
def caller_dashboard():
    status = request.args.get("status", "all")
    q = request.args.get("q", "").strip()
    query = Assignment.query.filter_by(caller_id=session["user_id"])
    if status != "all":
        query = query.filter_by(status=status)
    assignments = query.order_by(Assignment.id.desc()).all()
    if q:
        ql = q.lower()
        assignments = [a for a in assignments if ql in a.lead.name.lower() or ql in a.lead.phone.lower()]
    return render_template("caller.html", assignments=assignments, status=status, q=q,
                           template=get_setting("whatsapp_template"), country=get_setting("whatsapp_country_code", "91"))


@app.route("/caller/assignment/<int:assignment_id>/update", methods=["POST"])
@login_required("caller")
def update_assignment(assignment_id):
    a = Assignment.query.filter_by(id=assignment_id, caller_id=session["user_id"]).first_or_404()
    status = request.form.get("status", a.status)
    if status not in {"Pending", "Completed", "Call again", "Not reachable"}:
        status = a.status
    a.status = status
    a.notes = request.form.get("notes", "").strip()
    if request.form.get("called") == "1":
        a.attempts += 1
        a.last_called_at = datetime.utcnow()
    db.session.commit()
    flash("Lead updated.", "success")
    return redirect(url_for("caller_dashboard"))


@app.route("/caller/assignment/<int:assignment_id>/call")
@login_required("caller")
def caller_call(assignment_id):
    a = Assignment.query.filter_by(id=assignment_id, caller_id=session["user_id"]).first_or_404()
    a.attempts += 1
    a.last_called_at = datetime.utcnow()
    db.session.commit()
    return redirect("tel:" + quote(a.lead.phone, safe="+0123456789-() "))


@app.route("/caller/assignment/<int:assignment_id>/whatsapp")
@login_required("caller")
def caller_whatsapp(assignment_id):
    a = Assignment.query.filter_by(id=assignment_id, caller_id=session["user_id"]).first_or_404()
    msg = get_setting("whatsapp_template", "Hello {name}").replace("{name}", a.lead.name)
    number = normalize_whatsapp(a.lead.phone)
    return redirect(f"https://wa.me/{number}?text={quote(msg)}")


@app.route("/caller/export.csv")
@login_required("caller")
def caller_export():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Phone", "Status", "Attempts", "Notes", "Last Called"])
    for a in Assignment.query.filter_by(caller_id=session["user_id"]).order_by(Assignment.id).all():
        writer.writerow([a.lead.name, a.lead.phone, a.status, a.attempts, a.notes or "", a.last_called_at or ""])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=my_calling_results.csv"})


@app.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}, 500


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False)
