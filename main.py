# =========================
# IMPORTS (ÚNICOS Y LIMPIOS)
# =========================
from fastapi import (
    FastAPI, Depends, Request, Form,
    UploadFile, File, HTTPException
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from datetime import datetime, date
import os
import uuid

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from dotenv import load_dotenv
from supabase import create_client

from decimal import Decimal

from database import SessionLocal, engine
from models import (
    Base, Proyecto, Operario, Tarea, AsignacionOperario,
    FaseRecurso, PQR, TorreProyecto,
    DocumentoProyecto, PolizaProyecto
)

# =========================
# ENV & SUPABASE
# =========================
load_dotenv()

print("SENDGRID_API_KEY:", os.getenv("SENDGRID_API_KEY"))
print("SENDGRID_FROM_EMAIL:", os.getenv("SENDGRID_FROM_EMAIL"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "documentos")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Supabase env vars no configuradas")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI()

@app.on_event("startup")
def startup():
    print("App iniciando correctamente")

# =========================
# USUARIOS (LOGIN SIMPLE)
# =========================
USUARIOS = {
    "AdminLaiyeisy": {
        "password": "Violeta2026**"
    },
    "interventoria2026": {
        "password": "Obras2026#"
    }
}

import os

def enviar_alerta_tarea(tarea, proyecto):

    print("SENDGRID_API_KEY:", os.getenv("SENDGRID_API_KEY"))
    print("SENDGRID_FROM_EMAIL:", os.getenv("SENDGRID_FROM_EMAIL"))

    mensaje = Mail(
        from_email=os.getenv("SENDGRID_FROM_EMAIL"),
        to_emails="interventoriapyb2025@gmail.com",
        subject=f"⚠️ Actividad fuera de plazo – Proyecto {proyecto.nombre}",
        plain_text_content=f"""
La siguiente actividad se encuentra en ejecución fuera del tiempo establecido:

Proyecto: {proyecto.nombre}
Tarea: {tarea.nombre}
Fecha inicio planificada: {tarea.fecha_inicio}
Fecha inicio real: {tarea.fecha_inicio_real}
Porcentaje avance: {tarea.porcentaje_completado or 0} %

Por favor revisar.
"""
    )

    try:
        sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
        response = sg.send(mensaje)
        print("STATUS SENDGRID:", response.status_code)
        print("HEADERS SENDGRID:", response.headers)
    except Exception as e:
        print("Error enviando correo SendGrid:", e)

# 🔧 carpetas necesarias
os.makedirs("static", exist_ok=True)
os.makedirs("static/proyectos", exist_ok=True)
os.makedirs("static/dashboards", exist_ok=True)

app.add_middleware(
    SessionMiddleware,
    secret_key="clave-super-secreta-cambiala",
    max_age=30 * 60,
    same_site="none",
    https_only=True
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def formato_moneda(valor):
    if valor is None:
        return "—"
    try:
        return f"${int(valor):,}".replace(",", ".")
    except Exception:
        return "—"

templates.env.filters["moneda"] = formato_moneda

# 👇👇👇 AQUÍ 👇👇👇

def verificar_sesion(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login", status_code=303)

def to_date(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    return valor

def estado_poliza(fecha_fin):
    fecha_fin = to_date(fecha_fin)
    if not fecha_fin:
        return "gris"

    hoy = date.today()
    dias = (fecha_fin - hoy).days

    if dias < 0:
        return "rojo"
    elif dias <= 30:
        return "amarillo"
    else:
        return "verde"

# =========================
# DB
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =====================================================
# ROOT → PROYECTOS (NUEVO, SOLO VISUAL)
# =====================================================
@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, db: Session = Depends(get_db)):

    redir = verificar_sesion(request)
    if redir:
        return redir

    proyectos = db.query(Proyecto).order_by(Proyecto.id).all()
    return templates.TemplateResponse(
        "proyectos.html",
        {"request": request, "proyectos": proyectos}
    )

@app.get("/proyectos/nuevo", response_class=HTMLResponse)
def nuevo_proyecto_form(request: Request):

    redir = verificar_sesion(request)
    if redir:
        return redir

    return templates.TemplateResponse(
        "proyecto_form.html",
        {"request": request}
    )

@app.post("/proyectos/nuevo")
def crear_proyecto(
    request: Request,
    nombre: str = Form(...),
    descripcion: str = Form(None),
    fecha_inicio: str | None = Form(None),
    fecha_fin: str | None = Form(None),
    imagen: UploadFile = File(None),
    dashboard_pdf: UploadFile = File(None),   # 👈 AÑADIR
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    ruta_imagen = None
    ruta_dashboard = None

    if imagen and imagen.filename:
        ext = os.path.splitext(imagen.filename)[1]
        nombre_archivo = f"{uuid.uuid4()}{ext}"
        ruta_fisica = os.path.join("static/proyectos", nombre_archivo)
        with open(ruta_fisica, "wb") as f:
            f.write(imagen.file.read())
        ruta_imagen = f"/static/proyectos/{nombre_archivo}"

    if dashboard_pdf and dashboard_pdf.filename:
        ext = os.path.splitext(dashboard_pdf.filename)[1]
        nombre_archivo = f"{uuid.uuid4()}{ext}"
        ruta_fisica = os.path.join("static/dashboards", nombre_archivo)
        with open(ruta_fisica, "wb") as f:
            f.write(dashboard_pdf.file.read())
        ruta_dashboard = f"/static/dashboards/{nombre_archivo}"

    proyecto = Proyecto(
        nombre=nombre,
        descripcion=descripcion,
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        creado_en=datetime.now(),
        imagen=ruta_imagen,
        dashboard_pdf=ruta_dashboard   # 👈 GUARDADO
    )

    db.add(proyecto)
    db.commit()

    return RedirectResponse("/", status_code=303)


@app.get("/proyectos/editar/{proyecto_id}", response_class=HTMLResponse)
def editar_proyecto_form(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "proyecto_form.html",
        {
            "request": request,
            "proyecto": proyecto
        }
    )

@app.post("/proyectos/editar/{proyecto_id}")
def guardar_edicion_proyecto(
    proyecto_id: int,
    nombre: str = Form(...),
    descripcion: str = Form(None),
    fecha_inicio: str | None = Form(None),
    fecha_fin: str | None = Form(None),
    imagen: UploadFile = File(None),
    dashboard_pdf: UploadFile = File(None),   # 👈 AÑADIR
    db: Session = Depends(get_db)
):
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        return RedirectResponse("/", status_code=303)

    proyecto.nombre = nombre
    proyecto.descripcion = descripcion
    proyecto.fecha_inicio = fecha_inicio or None
    proyecto.fecha_fin = fecha_fin or None

    if imagen and imagen.filename:
        ext = os.path.splitext(imagen.filename)[1]
        nombre_archivo = f"{uuid.uuid4()}{ext}"
        ruta_fisica = os.path.join("static/proyectos", nombre_archivo)
        with open(ruta_fisica, "wb") as f:
            f.write(imagen.file.read())
        proyecto.imagen = f"/static/proyectos/{nombre_archivo}"

    if dashboard_pdf and dashboard_pdf.filename:
        ext = os.path.splitext(dashboard_pdf.filename)[1]
        nombre_archivo = f"{uuid.uuid4()}{ext}"
        ruta_fisica = os.path.join("static/dashboards", nombre_archivo)
        with open(ruta_fisica, "wb") as f:
            f.write(dashboard_pdf.file.read())
        proyecto.dashboard_pdf = f"/static/dashboards/{nombre_archivo}"

    db.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/proyectos/{proyecto_id}", response_class=HTMLResponse)
def dashboard_proyecto(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir
    
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "proyecto": proyecto,
            "dashboard_pdf": proyecto.dashboard_pdf,
            "en_proyecto": True
        }
    )

# =====================================================
# WBS (NO TOCAR)
# =====================================================
def generar_wbs_project(tareas):
    contadores = {}
    resultado = []

    for tarea in tareas:
        nivel = tarea.nivel_esquema

        # inicializar contadores hasta el nivel actual
        for n in range(1, nivel + 1):
            contadores.setdefault(n, 0)

        # incrementar SOLO el nivel actual
        contadores[nivel] += 1

        # resetear niveles inferiores
        for n in list(contadores.keys()):
            if n > nivel:
                contadores[n] = 0

        # construir WBS COMPLETO hasta el nivel
        wbs = ".".join(
            str(contadores[n]) for n in range(1, nivel + 1)
        )

        resultado.append({
            "wbs": wbs,
            "tarea": tarea
        })

    return resultado

TIPO_A_NIVEL = {
    "PRINCIPAL": 1,
    "FASE": 2,
    "ACTIVIDAD": 3,
    "SUBACTIVIDAD": 4
}

def calcular_estado_cumplimiento(tarea: Tarea) -> str:
    hoy = date.today()

    def to_date(valor):
        if not valor:
            return None
        if isinstance(valor, datetime):
            return valor.date()
        return valor  # ya es date

    fecha_inicio = to_date(tarea.fecha_inicio)
    fecha_fin = to_date(tarea.fecha_fin)
    inicio_real = to_date(tarea.fecha_inicio_real)
    fin_real = to_date(tarea.fecha_fin_real)

    # 1️⃣ SI YA TERMINÓ
    if fin_real:
        if fecha_fin:
            if fin_real < fecha_fin:
                return "Cumplida antes del plazo"
            elif fin_real > fecha_fin:
                return "Cumplida fuera del plazo"
            else:
                return "Cumplida a tiempo"
        return "Cumplida (sin fecha planificada)"

    # 2️⃣ EN EJECUCIÓN
    if fecha_inicio and inicio_real:
        if inicio_real > fecha_inicio:
            return "En ejecución fuera del tiempo establecido"
        elif inicio_real < fecha_inicio:
            return "En ejecución antes de lo previsto"
        else:
            return "En ejecución (a tiempo)"

    # 3️⃣ SOLO PLAN
    if fecha_inicio and hoy >= to_date(fecha_inicio):
        return "En ejecución (sin inicio real)"

    return "Sin fecha planificada"

def calcular_variacion_dias(tarea: Tarea):
    if not tarea.fecha_fin or not tarea.fecha_fin_real:
        return None

    def to_date(valor):
        if isinstance(valor, datetime):
            return valor.date()
        return valor

    fecha_plan = to_date(tarea.fecha_fin)
    fecha_real = to_date(tarea.fecha_fin_real)

    return (fecha_real - fecha_plan).days

def calcular_valor_avance(tarea: Tarea) -> float:
    if not tarea.valor_total:
        return 0.0

    if not tarea.porcentaje_completado:
        return 0.0

    return float(tarea.valor_total) * (float(tarea.porcentaje_completado) / 100)

# =====================================================
# TAREAS POR PROYECTO (FUNCIONA)
# =====================================================
@app.get("/proyectos/{proyecto_id}/tareas", response_class=HTMLResponse)
def ver_tareas_proyecto(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    tareas = (
        db.query(Tarea)
        .filter(Tarea.proyecto_id == proyecto_id)
        .order_by(Tarea.id)
        .all()
    )

    tareas_wbs = []
    for item in generar_wbs_project(tareas):
        tarea_item = item["tarea"]
        
        item["estado_cumplimiento"] = calcular_estado_cumplimiento(tarea_item)
        item["valor_avance"] = calcular_valor_avance(tarea_item)
        item["variacion_dias"] = calcular_variacion_dias(tarea_item)

        item["fin_plan"] = to_date(tarea_item.fecha_fin)
        item["fin_real"] = to_date(tarea_item.fecha_fin_real)
        
        tareas_wbs.append(item)

    return templates.TemplateResponse(
        "tareas.html",
        {
            "request": request,
            "proyecto": proyecto,   # ✅ CLAVE
            "tareas": tareas_wbs
        }
    )

@app.post("/proyectos/{proyecto_id}/tareas/nueva")
def crear_tarea_proyecto(
    proyecto_id: int,
    request: Request,
    nombre: str = Form(...),
    tipo: str = Form(...),
    fecha_inicio: str | None = Form(None),
    fecha_fin: str | None = Form(None),
    porcentaje_completado: Decimal = Form(0),
    valor_total: float | None = Form(None),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    nivel = TIPO_A_NIVEL.get(tipo, 1)
    tarea = Tarea(
        proyecto_id=proyecto_id,
        nombre=nombre,
        tipo=tipo,
        nivel_esquema=nivel,
        nivel_real=nivel,
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        porcentaje_completado=porcentaje_completado,
        valor_total=valor_total,
        creado_en=datetime.now()
    )
    db.add(tarea)
    db.commit()
    return RedirectResponse(f"/proyectos/{proyecto_id}/tareas", status_code=303)

# =====================================================
# TAREAS – RUTAS ORIGINALES (NO TOCADAS)
# =====================================================
@app.get("/tareas", response_class=HTMLResponse)
def ver_tareas(request: Request, db: Session = Depends(get_db)):

    redir = verificar_sesion(request)
    if redir:
        return redir

    tareas = db.query(Tarea).all()
    tareas_wbs = []
    for item in generar_wbs_project(tareas):
        item["estado_cumplimiento"] = calcular_estado_cumplimiento(item["tarea"])
        tareas_wbs.append(item)

    return templates.TemplateResponse(
        "tareas.html",
        {"request": request, "tareas": tareas_wbs}
    )

# =====================================================
# TAREAS – ELIMINAR
# =====================================================
@app.get("/tareas/eliminar/{tarea_id}")
def eliminar_tarea(
    tarea_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    db.query(AsignacionOperario).filter(
        AsignacionOperario.tarea_id == tarea_id
    ).delete(synchronize_session=False)

    tarea = db.query(Tarea).filter(Tarea.id == tarea_id).first()
    if tarea:
        db.delete(tarea)
        db.commit()

    return RedirectResponse("/tareas", status_code=303)

@app.get("/proyectos/{proyecto_id}/tareas/editar/{tarea_id}", response_class=HTMLResponse)
def editar_tarea(
    proyecto_id: int,
    tarea_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    tarea = db.query(Tarea).filter(Tarea.id == tarea_id).first()

    if not proyecto or not tarea:
        return RedirectResponse("/", status_code=303)

    tareas = (
        db.query(Tarea)
        .filter(Tarea.proyecto_id == proyecto_id)
        .order_by(Tarea.id)
        .all()
    )

    tareas_wbs = []
    for item in generar_wbs_project(tareas):
        tarea_item = item["tarea"]

        item["estado_cumplimiento"] = calcular_estado_cumplimiento(item["tarea"])
        item["valor_avance"] = calcular_valor_avance(tarea)
        item["variacion_dias"] = calcular_variacion_dias(tarea_item)
        tareas_wbs.append(item)

    return templates.TemplateResponse(
        "tareas.html",
        {
            "request": request,
            "proyecto": proyecto,          # 🔴 CLAVE
            "tareas": tareas_wbs,
            "tarea_editando": tarea        # 🔴 CLAVE
        }
    )

@app.post("/proyectos/{proyecto_id}/tareas/editar/{tarea_id}")
def guardar_edicion_tarea(
    proyecto_id: int,
    tarea_id: int,
    request: Request,
    nombre: str = Form(...),
    tipo: str = Form(...),
    fecha_inicio: str | None = Form(None),
    fecha_fin: str | None = Form(None),
    fecha_inicio_real: str | None = Form(None),   # 👈 NUEVO
    fecha_fin_real: str | None = Form(None),      # 👈 NUEVO
    porcentaje_completado: Decimal = Form(0),
    valor_total: float | None = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    tarea = db.query(Tarea).filter(Tarea.id == tarea_id).first()

    if tarea:
        tarea.nombre = nombre
        tarea.tipo = tipo
        tarea.nivel_esquema = TIPO_A_NIVEL.get(tipo, 1)
        tarea.nivel_real = tarea.nivel_esquema
        tarea.fecha_inicio = parse_date(fecha_inicio)
        tarea.fecha_fin = parse_date(fecha_fin)
        tarea.fecha_inicio_real = parse_date(fecha_inicio_real)
        tarea.fecha_fin_real = parse_date(fecha_fin_real)

        tarea.porcentaje_completado = porcentaje_completado
        tarea.valor_total = valor_total
                # 🔔 ALERTA POR CORREO SI VA FUERA DE TIEMPO
        estado = calcular_estado_cumplimiento(tarea)

        if estado == "En ejecución fuera del tiempo establecido":
            proyecto = db.query(Proyecto).filter(
                Proyecto.id == proyecto_id
            ).first()

            if proyecto:
                enviar_alerta_tarea(tarea, proyecto)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/tareas",
        status_code=303
    )

@app.get("/proyectos/{proyecto_id}/tareas/eliminar/{tarea_id}")
def eliminar_tarea_proyecto(
    proyecto_id: int,
    tarea_id: int,
    db: Session = Depends(get_db)
):
    # eliminar asignaciones primero (integridad)
    db.query(AsignacionOperario)\
        .filter(AsignacionOperario.tarea_id == tarea_id)\
        .delete(synchronize_session=False)

    tarea = db.query(Tarea).filter(Tarea.id == tarea_id).first()
    if tarea:
        db.delete(tarea)

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/tareas",
        status_code=303
    )

# =====================================================
# OPERARIOS (SIN CAMBIOS)
# =====================================================
# =====================================================
@app.get("/operarios", response_class=HTMLResponse)
def ver_operarios(request: Request, db: Session = Depends(get_db)):

    redir = verificar_sesion(request)
    if redir:
        return redir

    operarios = db.query(Operario).all()
    proyecto = db.query(Proyecto).first()

    tareas_principales = (
        db.query(Tarea)
        .filter(Tarea.tipo == "PRINCIPAL")
        .order_by(Tarea.nombre)
        .all()
    )

    todas_las_tareas = [
    {
        "id": t.id,
        "nombre": t.nombre,
        "tipo": t.tipo,
        "nivel": t.nivel_esquema,
        "proyecto_id": t.proyecto_id
    }
    for t in db.query(Tarea)
        .filter(Tarea.proyecto_id == proyecto.id)
        .order_by(Tarea.nivel_esquema, Tarea.nombre)
        .all()
        ]

    fases = (
        db.query(FaseRecurso)
        .filter(FaseRecurso.proyecto_id == proyecto.id)
        .all()
    )

    return templates.TemplateResponse(
        "operarios.html",
        {
            "request": request,
            "operarios": operarios,
            "proyecto": proyecto,
            "principales": tareas_principales,
            "todas_las_tareas": todas_las_tareas,
            "fases": fases
        }
    )

@app.post("/operarios/nuevo")
def crear_operario(
    request: Request,
    nombre: str = Form(...),
    actividad: str = Form(...),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    db.add(Operario(nombre=nombre, actividad=actividad))
    db.commit()
    return RedirectResponse("/operarios", status_code=303)

@app.get("/operarios/eliminar/{operario_id}")
def eliminar_operario(
    operario_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    operario = db.query(Operario).filter(Operario.id == operario_id).first()
    if operario:
        db.delete(operario)
        db.commit()
    return RedirectResponse("/operarios", status_code=303)

# =====================================================
# OPERARIOS – NUEVO (FORMULARIO)
# =====================================================
@app.get("/operarios/nuevo", response_class=HTMLResponse)
def nuevo_operario_form(
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).first()  # proyecto activo

    return templates.TemplateResponse(
        "operario_form.html",
        {
            "request": request,
            "operario": None,
            "proyecto": proyecto,
            "en_proyecto": True
        }
    )

# =====================================================
# OPERARIOS – EDITAR (FORMULARIO)
# =====================================================
@app.get("/operarios/editar/{operario_id}", response_class=HTMLResponse)
def editar_operario_form(
    operario_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    operario = db.query(Operario).filter(Operario.id == operario_id).first()

    if not operario:
        return RedirectResponse("/operarios", status_code=303)

    return templates.TemplateResponse(
        "operario_form.html",
        {
            "request": request,
            "operario": operario
        }
    )

# =====================================================
# OPERARIOS – EDITAR (GUARDAR)
# =====================================================
@app.post("/operarios/editar/{operario_id}")
def editar_operario(
    operario_id: int,
    request: Request,
    nombre: str = Form(...),
    actividad: str = Form(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    operario = db.query(Operario).filter(Operario.id == operario_id).first()

    if not operario:
        return RedirectResponse("/operarios", status_code=303)

    operario.nombre = nombre
    operario.actividad = actividad
    db.commit()

    return RedirectResponse("/operarios", status_code=303)

# =====================================================
# ASIGNACIONES – CRUD COMPLETO
# =====================================================

@app.get("/asignaciones", response_class=HTMLResponse)
def ver_asignaciones(request: Request, db: Session = Depends(get_db)):

    redir = verificar_sesion(request)
    if redir:
        return redir


    proyecto = db.query(Proyecto).first()

    asignaciones = (
        db.query(AsignacionOperario, Tarea)
        .join(Tarea, AsignacionOperario.tarea_id == Tarea.id)
        .filter(Tarea.proyecto_id == proyecto.id)
        .order_by(AsignacionOperario.id)
        .all()
    )

    filas = []

    for a, principal in asignaciones:
        actividad = None

        if a.actividad_id:
            actividad = db.query(Tarea).filter(
                Tarea.id == a.actividad_id
            ).first()

        filas.append({
            "id": a.id,
            "principal": principal.nombre,
            "actividad": actividad.nombre if actividad else None,
            "horas": a.horas_asignadas or "—",
            "estado": a.estado
        })

    return templates.TemplateResponse(
        "asignaciones.html",
        {
            "request": request,
            "filas": filas,
            "proyecto": proyecto
        }
    )

def liberar_operario(
    asignacion_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if asignacion:
        asignacion.operario_id = None
        asignacion.actividad_id = None   # 🔴 ESTA ES LA CLAVE
        asignacion.horas_asignadas = None
        asignacion.estado = "libre"
        db.commit()

    return RedirectResponse("/asignaciones", status_code=303)

# =====================================================
# ASIGNACIONES – EDITAR (FORMULARIO)
# =====================================================
@app.get("/asignaciones/editar/{asignacion_id}", response_class=HTMLResponse)
def editar_asignacion_form(
    asignacion_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    asignaciones = (
        db.query(AsignacionOperario, Operario, Tarea)
        .join(Operario, AsignacionOperario.operario_id == Operario.id)
        .join(Tarea, AsignacionOperario.tarea_id == Tarea.id)
        .all()
    )

    asignacion = db.query(AsignacionOperario)\
        .filter(AsignacionOperario.id == asignacion_id)\
        .first()

    operarios = db.query(Operario).order_by(Operario.nombre).all()
    tareas = db.query(Tarea).order_by(Tarea.nombre).all()

    if not asignacion:
        return RedirectResponse("/asignaciones", status_code=303)

    return templates.TemplateResponse(
        "asignaciones.html",
        {
            "request": request,
            "asignaciones": asignaciones,
            "asignacion_editando": asignacion,
            "operarios": operarios,
            "tareas": tareas
        }
    )

# =====================================================
# ASIGNACIONES – EDITAR (GUARDAR)
# =====================================================
@app.post("/asignaciones/editar/{asignacion_id}")
def guardar_edicion_asignacion(
    asignacion_id: int,
    request: Request,
    operario_id: int = Form(...),
    tarea_id: int = Form(...),
    horas_asignadas: float = Form(...),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    asignacion = db.query(AsignacionOperario)\
        .filter(AsignacionOperario.id == asignacion_id)\
        .first()

    if not asignacion:
        return RedirectResponse("/asignaciones", status_code=303)

    asignacion.operario_id = operario_id
    asignacion.tarea_id = tarea_id
    asignacion.horas_asignadas = horas_asignadas
    db.commit()

    return RedirectResponse("/asignaciones", status_code=303)

@app.post("/operarios/principal")
def guardar_operarios_por_fase(
    request: Request,
    tarea_id: int = Form(...),
    cantidad: int = Form(...),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    # 1️⃣ Buscar la tarea (fase)
    tarea = db.query(Tarea).filter(Tarea.id == tarea_id).first()
    if not tarea:
        return RedirectResponse("/operarios", status_code=303)

    proyecto_id = tarea.proyecto_id

    # 2️⃣ Guardar o actualizar FaseRecurso
    fase = db.query(FaseRecurso).filter(
        FaseRecurso.proyecto_id == proyecto_id,
        FaseRecurso.nombre_fase == tarea.nombre
    ).first()

    if fase:
        fase.cantidad_operarios = cantidad
    else:
        fase = FaseRecurso(
            proyecto_id=proyecto_id,
            nombre_fase=tarea.nombre,
            cantidad_operarios=cantidad
        )
        db.add(fase)

    db.commit()

    # 3️⃣ Contar cupos ya existentes
    existentes = db.query(AsignacionOperario).filter(
        AsignacionOperario.tarea_id == tarea.id
    ).count()

    # 4️⃣ Crear cupos libres faltantes
    faltantes = cantidad - existentes

    for _ in range(faltantes):
        db.add(AsignacionOperario(
            tarea_id=tarea.id,
            operario_id=None,
            horas_asignadas=None,
            estado="libre"
        ))

    db.commit()

    return RedirectResponse("/operarios", status_code=303)

@app.get("/operarios/fase/eliminar/{fase_id}")
def eliminar_fase_recurso(
    fase_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    fase = db.query(FaseRecurso).filter(FaseRecurso.id == fase_id).first()

    if not fase:
        return RedirectResponse("/operarios", status_code=303)

    # 1️⃣ Buscar la tarea principal asociada
    tarea = db.query(Tarea).filter(
        Tarea.proyecto_id == fase.proyecto_id,
        Tarea.nombre == fase.nombre_fase,
        Tarea.tipo == "PRINCIPAL"
    ).first()

    if tarea:
        # 2️⃣ Eliminar TODOS los cupos de esa principal
        db.query(AsignacionOperario).filter(
            AsignacionOperario.tarea_id == tarea.id
        ).delete(synchronize_session=False)

    # 3️⃣ Eliminar la definición de recursos
    db.delete(fase)
    db.commit()

    return RedirectResponse("/operarios", status_code=303)

@app.get("/operarios/fase/editar/{fase_id}", response_class=HTMLResponse)
def editar_fase_recurso_form(
    fase_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    fase = db.query(FaseRecurso).filter(FaseRecurso.id == fase_id).first()

    if not fase:
        return RedirectResponse("/operarios", status_code=303)

    return templates.TemplateResponse(
        "operarios_fase_form.html",
        {
            "request": request,
            "fase": fase
        }
    )

@app.post("/operarios/fase/editar/{fase_id}")
def guardar_edicion_fase_recurso(
    fase_id: int,
    cantidad_operarios: int = Form(...),
    db: Session = Depends(get_db)
):
    fase = db.query(FaseRecurso).filter(FaseRecurso.id == fase_id).first()

    if fase:
        fase.cantidad_operarios = cantidad_operarios
        db.commit()

    return RedirectResponse("/operarios", status_code=303)

@app.get("/asignaciones/cupo/editar/{cupo_index}", response_class=HTMLResponse)
def editar_cupo_form(
    cupo_index: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    tareas = db.query(Tarea).order_by(Tarea.tipo, Tarea.nombre).all()

    return templates.TemplateResponse(
        "asignaciones_cupo_form.html",
        {
            "request": request,
            "tareas": tareas
        }
    )

@app.get("/asignaciones/asignar/{asignacion_id}", response_class=HTMLResponse)
def asignar_actividad_form(
    asignacion_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    # 1️⃣ Cupo
    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if not asignacion:
        return RedirectResponse("/asignaciones", status_code=303)

    # 2️⃣ Tarea principal del cupo
    tarea_principal = db.query(Tarea).filter(
        Tarea.id == asignacion.tarea_id
    ).first()

    if not tarea_principal:
        return RedirectResponse("/asignaciones", status_code=303)

    # 3️⃣ TODAS las tareas del proyecto (igual que TAREAS)
    tareas = (
        db.query(Tarea)
        .filter(Tarea.proyecto_id == tarea_principal.proyecto_id)
        .order_by(Tarea.id)
        .all()
    )

    # 4️⃣ Generar WBS (MISMA FUNCIÓN, NO TOCADA)
    tareas_wbs = generar_wbs_project(tareas)

    # 5️⃣ Filtrar por jerarquía real (sin asumir contigüidad)
    tareas_filtradas = []
    incluir = False
    nivel_principal = tarea_principal.nivel_esquema

    for item in tareas_wbs:
        tarea = item["tarea"]

        if tarea.id == tarea_principal.id:
            incluir = True
            continue

        if incluir:
            # si aparece otra principal, se corta
            if tarea.nivel_esquema <= nivel_principal:
                break

            tareas_filtradas.append(tarea)

    return templates.TemplateResponse(
        "asignar_actividad.html",
        {
            "request": request,
            "asignacion": asignacion,
            "tareas": tareas_filtradas,
            "principal": tarea_principal
        }
    )

@app.post("/asignaciones/asignar/{asignacion_id}")
def guardar_asignacion_actividad(
    asignacion_id: int,
    request: Request,
    tarea_id: int = Form(...),
    horas_asignadas: float = Form(...),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if not asignacion:
        return RedirectResponse("/asignaciones", status_code=303)

    asignacion.actividad_id = tarea_id      # 👈 ESTA ES LA CLAVE
    asignacion.horas_asignadas = horas_asignadas
    asignacion.estado = "ocupado"

    db.commit()
    return RedirectResponse("/asignaciones", status_code=303)

@app.get("/proyectos/{proyecto_id}/operarios", response_class=HTMLResponse)
def ver_operarios_proyecto(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    tareas_principales = (
        db.query(Tarea)
        .filter(
            Tarea.proyecto_id == proyecto_id,
            Tarea.tipo == "PRINCIPAL"
        )
        .order_by(Tarea.nombre)
        .all()
    )

    fases = (
        db.query(FaseRecurso)
        .filter(FaseRecurso.proyecto_id == proyecto_id)
        .all()
    )

    return templates.TemplateResponse(
        "operarios.html",
        {
            "request": request,
            "proyecto": proyecto,
            "principales": tareas_principales,
            "fases": fases,
            "en_proyecto": True
        }
    )

@app.get("/proyectos/{proyecto_id}/asignaciones", response_class=HTMLResponse)
def ver_asignaciones_proyecto(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    asignaciones = (
        db.query(AsignacionOperario, Tarea)
        .join(Tarea, AsignacionOperario.tarea_id == Tarea.id)
        .filter(Tarea.proyecto_id == proyecto_id)
        .order_by(AsignacionOperario.id)
        .all()
    )

    filas = []

    for a, principal in asignaciones:
        actividad = None

        if a.actividad_id:
            actividad = db.query(Tarea).filter(
                Tarea.id == a.actividad_id
            ).first()

        filas.append({
            "id": a.id,
            "principal": principal.nombre,
            "actividad": actividad.nombre if actividad else None,
            "horas": a.horas_asignadas or "—",
            "estado": a.estado
        })

    return templates.TemplateResponse(
        "asignaciones.html",
        {
            "request": request,
            "proyecto": proyecto,
            "filas": filas,
            "en_proyecto": True
        }
    )

@app.post("/proyectos/{proyecto_id}/operarios/principal")
def guardar_operarios_por_fase_proyecto(
    proyecto_id: int,
    request: Request,
    tarea_id: int = Form(...),
    cantidad: int = Form(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    # 1️⃣ Buscar tarea
    tarea = db.query(Tarea).filter(
        Tarea.id == tarea_id,
        Tarea.proyecto_id == proyecto_id
    ).first()

    if not tarea:
        return RedirectResponse(f"/proyectos/{proyecto_id}/operarios", status_code=303)

    # 2️⃣ Guardar / actualizar fase
    fase = db.query(FaseRecurso).filter(
        FaseRecurso.proyecto_id == proyecto_id,
        FaseRecurso.nombre_fase == tarea.nombre
    ).first()

    if fase:
        fase.cantidad_operarios = cantidad
    else:
        fase = FaseRecurso(
            proyecto_id=proyecto_id,
            nombre_fase=tarea.nombre,
            cantidad_operarios=cantidad
        )
        db.add(fase)

    db.commit()

    # 3️⃣ Cupos
    existentes = db.query(AsignacionOperario).filter(
        AsignacionOperario.tarea_id == tarea.id
    ).count()

    faltantes = cantidad - existentes

    for _ in range(faltantes):
        db.add(AsignacionOperario(
            tarea_id=tarea.id,
            estado="libre"
        ))

    db.commit()

    # 🔴 REDIRECT CORRECTO
    return RedirectResponse(
        f"/proyectos/{proyecto_id}/operarios",
        status_code=303
    )

@app.get(
    "/proyectos/{proyecto_id}/asignaciones/asignar/{asignacion_id}",
    response_class=HTMLResponse
)
def asignar_actividad_form_proyecto(
    proyecto_id: int,
    asignacion_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    # 1️⃣ Proyecto
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        return RedirectResponse("/", status_code=303)

    # 2️⃣ Cupo
    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if not asignacion:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/asignaciones",
            status_code=303
        )

    # 3️⃣ Tarea principal
    tarea_principal = db.query(Tarea).filter(
        Tarea.id == asignacion.tarea_id,
        Tarea.proyecto_id == proyecto_id
    ).first()

    if not tarea_principal:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/asignaciones",
            status_code=303
        )

    # 4️⃣ Tareas del proyecto
    tareas = (
        db.query(Tarea)
        .filter(Tarea.proyecto_id == proyecto_id)
        .order_by(Tarea.id)
        .all()
    )

    tareas_wbs = generar_wbs_project(tareas)

    tareas_filtradas = []
    incluir = False
    nivel_principal = tarea_principal.nivel_esquema

    for item in tareas_wbs:
        tarea = item["tarea"]

        if tarea.id == tarea_principal.id:
            incluir = True
            continue

        if incluir:
            if tarea.nivel_esquema <= nivel_principal:
                break
            tareas_filtradas.append(tarea)

    return templates.TemplateResponse(
        "asignar_actividad.html",
        {
            "request": request,
            "proyecto": proyecto,
            "asignacion": asignacion,
            "tareas": tareas_filtradas,
            "principal": tarea_principal,
            "en_proyecto": True
        }
    )

@app.post("/proyectos/{proyecto_id}/asignaciones/asignar/{asignacion_id}")
def guardar_asignacion_actividad_proyecto(
    proyecto_id: int,
    request: Request,
    asignacion_id: int,
    tarea_id: int = Form(...),
    horas_asignadas: float = Form(...),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if not asignacion:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/asignaciones",
            status_code=303
        )

    # ✅ guardar datos
    asignacion.actividad_id = tarea_id
    asignacion.horas_asignadas = horas_asignadas
    asignacion.estado = "ocupado"

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/asignaciones",
        status_code=303
    )

@app.get(
    "/proyectos/{proyecto_id}/operarios/fase/editar/{fase_id}",
    response_class=HTMLResponse
)
def editar_fase_recurso_form_proyecto(
    proyecto_id: int,
    fase_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        return RedirectResponse("/", status_code=303)

    fase = db.query(FaseRecurso).filter(
        FaseRecurso.id == fase_id,
        FaseRecurso.proyecto_id == proyecto_id
    ).first()

    if not fase:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/operarios",
            status_code=303
        )

    return templates.TemplateResponse(
        "operarios_fase_form.html",
        {
            "request": request,
            "proyecto": proyecto,
            "fase": fase,
            "en_proyecto": True
        }
    )

@app.post("/proyectos/{proyecto_id}/operarios/fase/editar/{fase_id}")
def guardar_edicion_fase_recurso_proyecto(
    proyecto_id: int,
    fase_id: int,
    cantidad_operarios: int = Form(...),
    db: Session = Depends(get_db)
):
    fase = db.query(FaseRecurso).filter(
        FaseRecurso.id == fase_id,
        FaseRecurso.proyecto_id == proyecto_id
    ).first()

    if not fase:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/operarios",
            status_code=303
        )

    # 1️⃣ Buscar tarea principal asociada
    tarea = db.query(Tarea).filter(
        Tarea.proyecto_id == proyecto_id,
        Tarea.nombre == fase.nombre_fase,
        Tarea.tipo == "PRINCIPAL"
    ).first()

    if not tarea:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/operarios",
            status_code=303
        )

    # 2️⃣ Actualizar cantidad
    fase.cantidad_operarios = cantidad_operarios
    db.commit()

    # 3️⃣ Contar cupos actuales
    cupos_actuales = db.query(AsignacionOperario).filter(
        AsignacionOperario.tarea_id == tarea.id
    ).all()

    diferencia = cantidad_operarios - len(cupos_actuales)

    # 4️⃣ Si faltan cupos → crear
    if diferencia > 0:
        for _ in range(diferencia):
            db.add(AsignacionOperario(
                tarea_id=tarea.id,
                estado="libre"
            ))

    # 5️⃣ Si sobran cupos → eliminar SOLO libres
    elif diferencia < 0:
        cupos_libres = [
            c for c in cupos_actuales if c.estado == "libre"
        ]

        for c in cupos_libres[:abs(diferencia)]:
            db.delete(c)

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/operarios",
        status_code=303
    )

@app.get("/proyectos/{proyecto_id}/operarios/fase/eliminar/{fase_id}")
def eliminar_fase_recurso_proyecto(
    proyecto_id: int,
    request: Request,
    fase_id: int,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    fase = db.query(FaseRecurso).filter(
        FaseRecurso.id == fase_id,
        FaseRecurso.proyecto_id == proyecto_id
    ).first()

    if not fase:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/operarios",
            status_code=303
        )

    # 🔴 buscar la tarea principal asociada
    tarea = db.query(Tarea).filter(
        Tarea.proyecto_id == proyecto_id,
        Tarea.nombre == fase.nombre_fase,
        Tarea.tipo == "PRINCIPAL"
    ).first()

    if tarea:
        # eliminar cupos
        db.query(AsignacionOperario).filter(
            AsignacionOperario.tarea_id == tarea.id
        ).delete(synchronize_session=False)

    # eliminar fase
    db.delete(fase)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/operarios",
        status_code=303
    )

@app.get("/proyectos/{proyecto_id}/asignaciones/liberar/{asignacion_id}")
def liberar_operario_proyecto(
    proyecto_id: int,
    request: Request,
    asignacion_id: int,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    asignacion = db.query(AsignacionOperario).filter(
        AsignacionOperario.id == asignacion_id
    ).first()

    if asignacion:
        asignacion.operario_id = None
        asignacion.actividad_id = None
        asignacion.horas_asignadas = None
        asignacion.estado = "libre"
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/asignaciones",
        status_code=303
    )

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )

@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = USUARIOS.get(username)

    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Usuario o contraseña incorrectos"
            }
        )

    # ✅ guardar sesión
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/proyectos/{proyecto_id}/pqr", response_class=HTMLResponse)
def ver_pqr(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        return RedirectResponse("/", status_code=303)

    pqr_list = (
        db.query(PQR)
        .filter(PQR.proyecto_id == proyecto_id)
        .order_by(PQR.fecha_requerimiento.desc())
        .all()
    )

    return templates.TemplateResponse(
        "pqr.html",
        {
            "request": request,
            "proyecto": proyecto,
            "pqr_list": pqr_list,
            "en_proyecto": True
        }
    )

@app.post("/proyectos/{proyecto_id}/pqr")
def guardar_pqr(
    proyecto_id: int,
    request: Request,
    fecha_requerimiento: str = Form(...),
    problema: str = Form(...),
    solucion: str = Form(None),
    ubicacion: str = Form(None),
    fecha_solucion: str = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    estado = "cerrado" if fecha_solucion else "abierto"

    pqr = PQR(
        proyecto_id=proyecto_id,
        fecha_requerimiento=fecha_requerimiento,
        problema=problema,
        solucion=solucion,
        ubicacion=ubicacion,
        fecha_solucion=fecha_solucion,
        estado=estado
    )

    db.add(pqr)
    db.commit()

    # ✅ REDIRECT CORRECTO
    return RedirectResponse(
        f"/proyectos/{proyecto_id}/pqr",
        status_code=303
    )

@app.get("/proyectos/{proyecto_id}/pqr/editar/{pqr_id}", response_class=HTMLResponse)
def editar_pqr_form(
    proyecto_id: int,
    pqr_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    pqr = db.query(PQR).filter(PQR.id == pqr_id).first()

    if not proyecto or not pqr:
        return RedirectResponse(f"/proyectos/{proyecto_id}/pqr", status_code=303)

    pqr_list = (
        db.query(PQR)
        .filter(PQR.proyecto_id == proyecto_id)
        .order_by(PQR.fecha_requerimiento.desc())
        .all()
    )

    return templates.TemplateResponse(
        "pqr.html",
        {
            "request": request,
            "proyecto": proyecto,
            "pqr_list": pqr_list,
            "pqr_editando": pqr,
            "en_proyecto": True
        }
    )

@app.post("/proyectos/{proyecto_id}/pqr/editar/{pqr_id}")
def guardar_edicion_pqr(
    proyecto_id: int,
    request: Request,
    pqr_id: int,
    solucion: str = Form(None),
    fecha_solucion: str = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    pqr = db.query(PQR).filter(PQR.id == pqr_id).first()

    if pqr:
        pqr.solucion = solucion
        pqr.fecha_solucion = fecha_solucion or None
        pqr.estado = "cerrado" if fecha_solucion else "abierto"
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/pqr",
        status_code=303
    )

@app.get("/proyectos/{proyecto_id}/informacion", response_class=HTMLResponse)
def informacion_general(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(
        Proyecto.id == proyecto_id
    ).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    # 📄 DOCUMENTOS
    documentos = db.query(DocumentoProyecto).filter(
        DocumentoProyecto.proyecto_id == proyecto_id
    ).all()

    # 🛡 PÓLIZAS

    polizas = db.query(PolizaProyecto).filter(
        PolizaProyecto.proyecto_id == proyecto_id
    ).all()

    polizas_data = []
    
    for p in polizas:
        polizas_data.append({
            "poliza": p,
            "estado": estado_poliza(p.fecha_fin)
            
            })


    # 🆕🏢 TORRES / APARTAMENTOS
    torres = db.query(TorreProyecto).filter(
        TorreProyecto.proyecto_id == proyecto_id
    ).order_by(TorreProyecto.id).all()

    total_apartamentos = sum(
        t.cantidad_apartamentos for t in torres
    )

    total_entregados = sum(
        t.apartamentos_entregados for t in torres
    )

    porcentaje_entregados = (
        (total_entregados / total_apartamentos) * 100
        if total_apartamentos > 0 else 0
    )

    return templates.TemplateResponse(
        "informacion_general.html",
        {
            "request": request,
            "proyecto": proyecto,
            "documentos": documentos,        # 👈 EXISTENTE
            "polizas": polizas_data,              # 👈 EXISTENTE

            # 🆕 NUEVO (NO rompe nada)
            "torres": torres,
            "total_apartamentos": total_apartamentos,
            "total_entregados": total_entregados,
            "porcentaje_entregados": porcentaje_entregados
        }
    )

@app.post("/proyectos/{proyecto_id}/informacion")
def guardar_informacion_general(
    proyecto_id: int,
    request: Request,
    fecha_firma_contrato: str | None = Form(None),
    anticipo_fecha: str | None = Form(None),
    anticipo_valor: float | None = Form(None),
    poliza_inicio: str | None = Form(None),
    poliza_fin: str | None = Form(None),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir
   
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    proyecto.fecha_firma_contrato = fecha_firma_contrato or None
    proyecto.anticipo_fecha = anticipo_fecha or None
    proyecto.anticipo_valor = anticipo_valor
    proyecto.poliza_inicio = poliza_inicio or None
    proyecto.poliza_fin = poliza_fin or None

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

def guardar_archivo_proyecto(
    proyecto_id: int,
    archivo,
    subcarpeta: str
):
    """
    Guarda un archivo en:
    static/documentos/proyecto_{id}/{subcarpeta}/
    """

    if not archivo or not archivo.filename:
        return None

    # carpeta base
    base_path = f"static/documentos/proyecto_{proyecto_id}/{subcarpeta}"
    os.makedirs(base_path, exist_ok=True)

    # nombre único
    ext = os.path.splitext(archivo.filename)[1]
    nombre_archivo = f"{uuid.uuid4()}{ext}"

    ruta_fisica = os.path.join(base_path, nombre_archivo)

    with open(ruta_fisica, "wb") as f:
        f.write(archivo.file.read())

    # ruta pública
    return "/" + ruta_fisica.replace("\\", "/")

from fastapi import UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi import Form, Depends

@app.post("/proyectos/{proyecto_id}/informacion/contrato")
def guardar_contrato(
    proyecto_id: int,
    request: Request,
    fecha_firma_contrato: str = Form(None),
    duracion_contrato_dias: int = Form(None),
    contrato_archivo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(
        Proyecto.id == proyecto_id
    ).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    # guardar fecha
    proyecto.fecha_firma_contrato = fecha_firma_contrato or None

    proyecto.duracion_contrato_dias = duracion_contrato_dias

    # guardar archivo si viene
    if contrato_archivo and contrato_archivo.filename:
        url = guardar_archivo_supabase(
            proyecto_id,
            contrato_archivo,
            "contrato"
        )
        proyecto.contrato_archivo = url

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

from fastapi import UploadFile, File
from models import PolizaProyecto

@app.post("/proyectos/{proyecto_id}/polizas/nueva")
def agregar_poliza(
    proyecto_id: int,
    request: Request,
    tipo_poliza: str = Form(...),
    aseguradora: str = Form(None),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    ruta_archivo = guardar_archivo_supabase(
        proyecto_id,
        archivo,
        "polizas"
    )

    poliza = PolizaProyecto(
        proyecto_id=proyecto_id,
        tipo_poliza=tipo_poliza,
        aseguradora=aseguradora,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        archivo=ruta_archivo
    )

    db.add(poliza)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

from models import DocumentoProyecto

@app.post("/proyectos/{proyecto_id}/documentos/nuevo")
def agregar_documento(
    proyecto_id: int,
    request: Request,
    tipo: str = Form(...),
    descripcion: str = Form(None),
    fecha: str = Form(None),
    valor: float = Form(None),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    ruta_archivo = guardar_archivo_supabase(
        proyecto_id,
        archivo,
        "documentos"
    )

    documento = DocumentoProyecto(
        proyecto_id=proyecto_id,
        tipo=tipo,
        descripcion=descripcion,
        fecha=fecha,
        valor=valor,
        archivo=ruta_archivo
    )

    db.add(documento)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/informacion/acta-inicio")
def guardar_acta_inicio(
    proyecto_id: int,
    fecha_acta_inicio: str = Form(None),
    acta_inicio_archivo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    proyecto = db.query(Proyecto).filter(
        Proyecto.id == proyecto_id
    ).first()

    if not proyecto:
        return RedirectResponse("/", status_code=303)

    # guardar fecha
    proyecto.fecha_acta_inicio = fecha_acta_inicio or None

    # guardar archivo
    if acta_inicio_archivo and acta_inicio_archivo.filename:
        url = guardar_archivo_supabase(
            proyecto_id,
            acta_inicio_archivo,
            "acta_inicio"
        )
        proyecto.acta_inicio_archivo = url

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/torres/{torre_id}/editar")
def editar_torre_apartamentos(
    proyecto_id: int,
    request: Request,
    torre_id: int,
    apartamentos_entregados: int = Form(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    torre = db.query(TorreProyecto).filter(
        TorreProyecto.id == torre_id,
        TorreProyecto.proyecto_id == proyecto_id
    ).first()

    if not torre:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/informacion",
            status_code=303
        )

    # 🔒 VALIDACIONES
    if apartamentos_entregados < 0:
        apartamentos_entregados = 0

    if apartamentos_entregados > torre.cantidad_apartamentos:
        apartamentos_entregados = torre.cantidad_apartamentos

    torre.apartamentos_entregados = apartamentos_entregados
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/torres/nueva")
def crear_torre(
    proyecto_id: int,
    request: Request,
    nombre_torre: str = Form(...),
    cantidad_apartamentos: int = Form(...),
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    if cantidad_apartamentos <= 0:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/informacion",
            status_code=303
        )

    torre = TorreProyecto(
        proyecto_id=proyecto_id,
        nombre_torre=nombre_torre,
        cantidad_apartamentos=cantidad_apartamentos,
        apartamentos_entregados=0
    )

    db.add(torre)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/torres/{torre_id}/eliminar")
def eliminar_torre(
    proyecto_id: int,
    request: Request,
    torre_id: int,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    torre = db.query(TorreProyecto).filter(
        TorreProyecto.id == torre_id,
        TorreProyecto.proyecto_id == proyecto_id
    ).first()

    if torre:
        db.delete(torre)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

from fastapi.responses import RedirectResponse

@app.get("/proyectos")
def proyectos():
    return RedirectResponse("/", status_code=302)

@app.get("/proyectos/{proyecto_id}/dashboard", response_class=HTMLResponse)
def ver_dashboard(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()

    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "proyecto": proyecto
        }
    )

from datetime import datetime

def parse_date(fecha_str):
    if not fecha_str:
        return None
    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        if fecha.year > 9999:
            return None
        return fecha
    except ValueError:
        return None

def guardar_archivo_supabase(
    proyecto_id: int,
    archivo: UploadFile,
    subcarpeta: str
) -> str | None:
    """
    Sube un archivo a Supabase Storage y retorna la URL pública
    Ruta: documentos/proyecto_{id}/{subcarpeta}/uuid.ext
    """

    if not archivo or not archivo.filename:
        return None

    # extensión
    ext = os.path.splitext(archivo.filename)[1]

    # nombre único
    nombre_archivo = f"{uuid.uuid4()}{ext}"

    # ruta en el bucket
    ruta_storage = f"proyecto_{proyecto_id}/{subcarpeta}/{nombre_archivo}"

    # leer contenido
    contenido = archivo.file.read()

    # subir a Supabase
    supabase.storage.from_(SUPABASE_BUCKET).upload(
        ruta_storage,
        contenido,
        file_options={
            "content-type": archivo.content_type,
            "upsert": True
        }
    )

    # obtener URL pública
    url_publica = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(
        ruta_storage
    )

    return url_publica

@app.get("/test-email")
def test_email():
    mensaje = Mail(
        from_email=os.getenv("SENDGRID_FROM_EMAIL"),
        to_emails="interventoriapyb2025@gmail.com",
        subject="PRUEBA SENDGRID OK",
        plain_text_content="Este es un correo de prueba enviado desde FastAPI."
    )

    sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
    response = sg.send(mensaje)

    return {"status_code": response.status_code}