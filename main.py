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

from pathlib import Path

from dotenv import load_dotenv

import requests
from urllib.parse import quote

load_dotenv()

from decimal import Decimal

from database import SessionLocal, engine
from models import (
    Base, Proyecto, Operario, Tarea, AsignacionOperario,
    FaseRecurso, PQR, TorreProyecto,
    DocumentoProyecto, PolizaProyecto, LluviaProyecto,
    AnticipoProyecto, CorteProyecto, CorteCostoProyecto, ComiteProyecto,
    Bitacora, InformeComite, MemoriaCalculo
)

app = FastAPI()

from fastapi.staticfiles import StaticFiles
from pathlib import Path

UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app.mount(
    "/uploads",
    StaticFiles(directory=str(UPLOADS_DIR)),
    name="uploads"
)


# =========================
# CONEXIÓN CON ONEDRIVE
# =========================

MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
ONEDRIVE_USER = os.getenv("ONEDRIVE_USER")
ONEDRIVE_ROOT_FOLDER = os.getenv(
    "ONEDRIVE_ROOT_FOLDER",
    "INTERVENTORIA_APP"
)


def obtener_token_onedrive():
    """Obtiene un token de acceso para Microsoft Graph."""

    if not all([
        MS_TENANT_ID,
        MS_CLIENT_ID,
        MS_CLIENT_SECRET,
        ONEDRIVE_USER
    ]):
        raise RuntimeError(
            "Faltan variables de configuración de OneDrive en .env"
        )

    respuesta = requests.post(
        f"https://login.microsoftonline.com/"
        f"{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        },
        timeout=30
    )

    if respuesta.status_code != 200:
        raise RuntimeError(
            f"Error de autenticación OneDrive: {respuesta.text}"
        )

    return respuesta.json()["access_token"]


def subir_archivo_onedrive(
    archivo,
    nombre_archivo,
    carpeta="PROYECTOS"
):
    """Sube un archivo a la carpeta configurada de OneDrive."""

    token = obtener_token_onedrive()

    ruta = (
        f"{ONEDRIVE_ROOT_FOLDER}/"
        f"{carpeta}/{nombre_archivo}"
    )

    ruta_codificada = "/".join(
        quote(parte, safe="")
        for parte in ruta.split("/")
    )
    respuesta = requests.put(
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(ONEDRIVE_USER, safe='')}/drive/root:"
        f"/{ruta_codificada}:/content",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream"
        },
        data=archivo,
        timeout=120
    )

    if respuesta.status_code not in (200, 201):
        raise RuntimeError(
            f"Error al subir archivo a OneDrive: {respuesta.text}"
        )

    return respuesta.json()["id"]

@app.on_event("startup")
def startup():
    print("App iniciando correctamente")


from fastapi.responses import Response


@app.get("/onedrive/files/{item_id}")
def consultar_archivo_onedrive(
    item_id: str,
    request: Request
):
    redir = verificar_sesion(request)
    if redir:
        return redi
    """Recupera un archivo privado de OneDrive."""

    token = obtener_token_onedrive()

    respuesta = requests.get(
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(ONEDRIVE_USER, safe='')}/drive/items/"
        f"{quote(item_id, safe='')}/content",
        headers={
            "Authorization": f"Bearer {token}"
        },
        allow_redirects=True,
        timeout=120,
    )

    if respuesta.status_code != 200:
        raise HTTPException(
            status_code=respuesta.status_code,
            detail="No fue posible consultar el archivo en OneDrive.",
        )

    return Response(
        content=respuesta.content,
        media_type=respuesta.headers.get(
            "Content-Type",
            "application/octet-stream",
        ),
        headers={
            "Content-Disposition": "inline"
        },
    )

# =========================
# USUARIOS (LOGIN SIMPLE)
# =========================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

INTERVENTORIA_USERNAME = os.getenv("INTERVENTORIA_USERNAME")
INTERVENTORIA_PASSWORD = os.getenv("INTERVENTORIA_PASSWORD")

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")

if not all([
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    INTERVENTORIA_USERNAME,
    INTERVENTORIA_PASSWORD,
    SESSION_SECRET_KEY
]):
    raise RuntimeError("Faltan variables de seguridad en el archivo .env")

USUARIOS = {
    ADMIN_USERNAME: {
        "password": ADMIN_PASSWORD
    },
    INTERVENTORIA_USERNAME: {
        "password": INTERVENTORIA_PASSWORD
    }
}

def enviar_alerta_tarea(tarea, proyecto):

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
    secret_key=SESSION_SECRET_KEY,
    max_age=60 * 60,
    same_site="lax",
    https_only=False
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
        .order_by(Tarea.posicion, Tarea.id)
        .all()
    )

    tareas_wbs = []
    total_variacion = 0   # 👈 suma total

    for item in generar_wbs_project(tareas):
        tarea_item = item["tarea"]

        item["estado_cumplimiento"] = calcular_estado_cumplimiento(tarea_item)
        item["valor_avance"] = calcular_valor_avance(tarea_item)
        item["variacion_dias"] = calcular_variacion_dias(tarea_item)

        # 👇 SUMAMOS LOS DÍAS
        if item["variacion_dias"] is not None:
            total_variacion += item["variacion_dias"]

        item["fin_plan"] = to_date(tarea_item.fecha_fin)
        item["fin_real"] = to_date(tarea_item.fecha_fin_real)

        tareas_wbs.append(item)

    return templates.TemplateResponse(
        "tareas.html",
        {
            "request": request,
            "proyecto": proyecto,   # ✅ CLAVE
            "tareas": tareas_wbs,
            "total_variacion": total_variacion
        }
    )

from sqlalchemy import func

@app.post("/proyectos/{proyecto_id}/tareas/nueva")
def crear_tarea_proyecto(
    proyecto_id: int,
    request: Request,
    nombre: str = Form(...),
    tipo: str = Form(...),
    id_padre: int | None = Form(None),
    fecha_inicio: str | None = Form(None),
    fecha_fin: str | None = Form(None),
    porcentaje_completado: Decimal = Form(0),
    valor_total: float | None = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    # 🔹 NIVEL SEGÚN PADRE
    if id_padre:
        padre = db.query(Tarea).filter(Tarea.id == id_padre).first()
        nivel = padre.nivel_esquema + 1 if padre else 1
    else:
        nivel = TIPO_A_NIVEL.get(tipo, 1)

    # 🔹 POSICIÓN AL FINAL
    max_pos = db.query(func.max(Tarea.posicion))\
        .filter(Tarea.proyecto_id == proyecto_id)\
        .scalar()

    posicion = (max_pos or 0) + 1

    tarea = Tarea(
        proyecto_id=proyecto_id,
        nombre=nombre,
        tipo=tipo,
        nivel_esquema=nivel,
        nivel_real=nivel,
        id_padre=id_padre,
        posicion=posicion,
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        porcentaje_completado=porcentaje_completado,
        valor_total=valor_total,
        creado_en=datetime.now()
    )

    db.add(tarea)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/tareas",
        status_code=303
    )

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
            "tarea_editando": tarea,
            "total_variacion": 0       # 🔴 CLAVE
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

@app.get("/proyectos/{proyecto_id}/pqr/editar/{pqr_id}", response_class=HTMLResponse)
def editar_pqr(
    proyecto_id: int,
    pqr_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).get(proyecto_id)

    pqr_list = (
        db.query(PQR)
        .filter(PQR.proyecto_id == proyecto_id)
        .order_by(PQR.fecha_requerimiento.desc())
        .all()
    )

    pqr_editando = db.query(PQR).get(pqr_id)

    return templates.TemplateResponse(
        "pqr.html",
        {
            "request": request,
            "proyecto": proyecto,
            "pqr_list": pqr_list,
            "pqr_editando": pqr_editando,
            "en_proyecto": True
        }
    )


@app.post("/proyectos/{proyecto_id}/pqr/editar/{pqr_id}")
def actualizar_pqr(
    proyecto_id: int,
    pqr_id: int,
    request: Request,
    solucion: str = Form(None),
    fecha_solucion: str = Form(None),
    observacion: str = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    pqr = db.query(PQR).filter(
        PQR.id == pqr_id,
        PQR.proyecto_id == proyecto_id
    ).first()

    if pqr:
        pqr.solucion = solucion
        pqr.fecha_solucion = parse_date(fecha_solucion) if fecha_solucion else None
        pqr.observacion = observacion

        if pqr.fecha_solucion:
            pqr.estado = "cerrado"
        else:
            pqr.estado = "pendiente"

        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/pqr",
        status_code=303
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
    observacion: str = Form(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    estado = "cerrado" if fecha_solucion else "pendiente"

    pqr = PQR(
        proyecto_id=proyecto_id,
        fecha_requerimiento=parse_date(fecha_requerimiento),
        problema=problema,
        solucion=solucion,
        ubicacion=ubicacion,
        fecha_solucion=fecha_solucion or None,
        observacion=observacion,
        estado=estado
    )

    db.add(pqr)
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

    # 💰 ANTICIPOS
    anticipos = db.query(AnticipoProyecto)\
        .filter(AnticipoProyecto.proyecto_id == proyecto_id)\
        .order_by(AnticipoProyecto.fecha.desc())\
        .all()

    total_porcentaje = sum(a.porcentaje for a in anticipos)
    total_valor = sum(a.valor for a in anticipos)

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

    comites = db.query(ComiteProyecto).filter(
        ComiteProyecto.proyecto_id == proyecto_id
    ).order_by(ComiteProyecto.fecha.desc()).all()

    informes_comite = db.query(InformeComite).filter(
        InformeComite.proyecto_id == proyecto_id
    ).order_by(InformeComite.fecha.desc()).all()

    memorias_calculo = db.query(MemoriaCalculo).filter(
        MemoriaCalculo.proyecto_id == proyecto_id
    ).order_by(MemoriaCalculo.fecha.desc()).all()

    # ✂️ CORTES
    cortes = db.query(CorteProyecto)\
        .filter(CorteProyecto.proyecto_id == proyecto_id)\
        .order_by(CorteProyecto.numero_corte.asc())\
        .all()

    # 💰 AVANCE DE OBRA - COSTO
    cortes_costo = db.query(CorteCostoProyecto)\
        .filter(CorteCostoProyecto.proyecto_id == proyecto_id)\
        .order_by(CorteCostoProyecto.numero_corte)\
        .all()


# 🌧️ LLUVIAS
    lluvias = (
        db.query(LluviaProyecto)
        .filter(LluviaProyecto.proyecto_id == proyecto_id)
        .order_by(
            LluviaProyecto.fecha.desc(),
            LluviaProyecto.hora_inicio.desc()
        )
        .all()
    )

    total_lluvias = len(lluvias)

    total_minutos = 0

    for l in lluvias:
        if l.hora_inicio and l.hora_fin:
            inicio = datetime.combine(date.today(), l.hora_inicio)
            fin = datetime.combine(date.today(), l.hora_fin)

            diferencia = (fin - inicio).total_seconds()

            # Si la hora final es menor, se asume que terminó al día siguiente
            if diferencia < 0:
                diferencia += 24 * 3600

            total_minutos += round(diferencia / 60)

    horas = total_minutos // 60
    minutos = total_minutos % 60

    total_horas_lluvia = f"{horas}h {minutos}m"


    return templates.TemplateResponse(
        "informacion_general.html",
        {
            "request": request,
            "proyecto": proyecto,
            "documentos": documentos,
            "cortes": cortes,
            "cortes_costo": cortes_costo,
            "polizas": polizas_data,
            "anticipos": anticipos,
            "total_porcentaje": total_porcentaje,
            "total_valor": total_valor,
            "torres": torres,
            "total_apartamentos": total_apartamentos,
            "total_entregados": total_entregados,
            "porcentaje_entregados": porcentaje_entregados,
            "lluvias": lluvias,
            "total_horas_lluvia": total_horas_lluvia,
            "comites": comites,
            "informes_comite": informes_comite,
            "memorias_calculo": memorias_calculo
        }
    )


@app.post("/proyectos/{proyecto_id}/informacion")
def guardar_informacion_general(
    proyecto_id: int,
    request: Request,
    fecha_firma_contrato: str | None = Form(None),
    contratista_nombre: str | None = Form(None),
    contratista_nit: str | None = Form(None),
    contratista_representante: str | None = Form(None),
    contratista_telefono: str | None = Form(None),
    contratista_correo: str | None = Form(None),
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
    proyecto.contratista_nombre = contratista_nombre or None
    proyecto.contratista_nit = contratista_nit or None
    proyecto.contratista_representante = contratista_representante or None
    proyecto.contratista_telefono = contratista_telefono or None
    proyecto.contratista_correo = contratista_correo or None
    proyecto.anticipo_fecha = anticipo_fecha or None
    proyecto.anticipo_valor = anticipo_valor
    proyecto.poliza_inicio = poliza_inicio or None
    proyecto.poliza_fin = poliza_fin or None

    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/comites/nuevo")
def agregar_comite(
    proyecto_id: int,
    request: Request,
    fecha: str = Form(...),
    titulo: str = Form(...),
    documento: UploadFile = File(None),
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

    url_documento = None

    if documento and documento.filename:
        url_documento = guardar_archivo_supabase(
            proyecto_id,
            documento,
            "actas_comite"
        )

    nuevo_comite = ComiteProyecto(
        proyecto_id=proyecto_id,
        fecha=fecha,
        titulo=titulo,
        documento=url_documento
    )

    db.add(nuevo_comite)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )


@app.post("/proyectos/{proyecto_id}/comites/{comite_id}/eliminar")
def eliminar_comite(
    proyecto_id: int,
    comite_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    comite = db.query(ComiteProyecto).filter(
        ComiteProyecto.id == comite_id,
        ComiteProyecto.proyecto_id == proyecto_id
    ).first()

    if comite:
        db.delete(comite)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/informes-comite/nuevo")
def agregar_informe_comite(
    proyecto_id: int,
    request: Request,
    fecha: str = Form(...),
    titulo: str = Form(...),
    documento: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    url_documento = None

    if documento and documento.filename:
        url_documento = guardar_archivo_supabase(
            proyecto_id, documento, "informes_comite"
        )

    nuevo = InformeComite(
        proyecto_id=proyecto_id,
        fecha=fecha,
        titulo=titulo,
        documento=url_documento
    )

    db.add(nuevo)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )


@app.post("/proyectos/{proyecto_id}/memorias-calculo/nuevo")
def agregar_memoria_calculo(
    proyecto_id: int,
    request: Request,
    fecha: str = Form(...),
    titulo: str = Form(...),
    documento: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    url_documento = None

    if documento and documento.filename:
        url_documento = guardar_archivo_supabase(
            proyecto_id, documento, "memorias_calculo"
        )

    nueva = MemoriaCalculo(
        proyecto_id=proyecto_id,
        fecha=fecha,
        titulo=titulo,
        documento=url_documento
    )

    db.add(nueva)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/informes-comite/{informe_id}/eliminar")
def eliminar_informe_comite(
    proyecto_id: int,
    informe_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    informe = db.query(InformeComite).filter(
        InformeComite.id == informe_id,
        InformeComite.proyecto_id == proyecto_id
    ).first()

    if informe:
        db.delete(informe)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )


@app.post("/proyectos/{proyecto_id}/memorias-calculo/{memoria_id}/eliminar")
def eliminar_memoria_calculo(
    proyecto_id: int,
    memoria_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    memoria = db.query(MemoriaCalculo).filter(
        MemoriaCalculo.id == memoria_id,
        MemoriaCalculo.proyecto_id == proyecto_id
    ).first()

    if memoria:
        db.delete(memoria)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )


def obtener_o_crear_carpeta_proyecto(token, proyecto_id):
    """Obtiene o crea la carpeta de un proyecto en OneDrive."""

    from urllib.parse import quote

    encabezados = {
        "Authorization": f"Bearer {token}"
    }

    carpeta_base = (
        f"{ONEDRIVE_ROOT_FOLDER}/PROYECTOS"
    )

    nombre_carpeta = f"Proyecto_{proyecto_id}"

    ruta_carpeta = (
        f"{carpeta_base}/{nombre_carpeta}"
    )

    ruta_codificada = "/".join(
        quote(parte, safe="")
        for parte in ruta_carpeta.split("/")
    )

    url_carpeta = (
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(ONEDRIVE_USER, safe='')}/drive/root:"
        f"/{ruta_codificada}"
    )

    # Verificar si la carpeta ya existe
    respuesta = requests.get(
        url_carpeta,
        headers=encabezados,
        timeout=30
    )

    if respuesta.status_code == 200:
        return f"PROYECTOS/{nombre_carpeta}"

    if respuesta.status_code != 404:
        raise RuntimeError(
            "Error al consultar la carpeta en OneDrive: "
            f"{respuesta.status_code} - {respuesta.text}"
        )

    # Crear la carpeta si todavía no existe
    ruta_base_codificada = "/".join(
        quote(parte, safe="")
        for parte in carpeta_base.split("/")
    )

    url_padre = (
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(ONEDRIVE_USER, safe='')}/drive/root:"
        f"/{ruta_base_codificada}:/children"
    )

    respuesta = requests.post(
        url_padre,
        headers={
            **encabezados,
            "Content-Type": "application/json"
        },
        json={
            "name": nombre_carpeta,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail"
        },
        timeout=30
    )

    if respuesta.status_code not in (200, 201):
        raise RuntimeError(
            "Error al crear la carpeta del proyecto en OneDrive: "
            f"{respuesta.status_code} - {respuesta.text}"
        )

    return f"PROYECTOS/{nombre_carpeta}"


def guardar_archivo_supabase(
    proyecto_id: int,
    archivo: UploadFile,
    subcarpeta: str
) -> str | None:

    if not archivo or not archivo.filename:
        return None

    import os
    import uuid
    from urllib.parse import quote

    # Conservar la extensión del archivo
    extension = os.path.splitext(archivo.filename)[1]
    nombre_archivo = f"{uuid.uuid4()}{extension}"

    # Obtener o crear la carpeta del proyecto en OneDrive
    token = obtener_token_onedrive()
    carpeta_onedrive = obtener_o_crear_carpeta_proyecto(
        token,
        proyecto_id
    )

    # Construir la ruta completa
    ruta = (
        f"{ONEDRIVE_ROOT_FOLDER}/"
        f"{carpeta_onedrive}/{nombre_archivo}"
    )

    ruta_codificada = "/".join(
        quote(parte, safe="")
        for parte in ruta.split("/")
    )

    # Subir el archivo a OneDrive
    archivo.file.seek(0)

    respuesta = requests.put(
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(ONEDRIVE_USER, safe='')}/drive/root:"
        f"/{ruta_codificada}:/content",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": (
                archivo.content_type
                or "application/octet-stream"
            ),
        },
        data=archivo.file,
        timeout=120,
    )

    if respuesta.status_code not in (200, 201):
        raise RuntimeError(
            "Error al guardar el documento en OneDrive: "
            f"{respuesta.status_code} - {respuesta.text}"
        )

    # Devolver la ruta interna para abrir el archivo desde la aplicación
    archivo_subido = respuesta.json()
    return f"/onedrive/files/{archivo_subido['id']}"

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


@app.post("/proyectos/{proyecto_id}/torres/crear-multiples")
def crear_torres_multiples(
    proyecto_id: int,
    request: Request,
    nombre_torre: list[str] = Form(...),
    cantidad_apartamentos: list[int] = Form(...),
    observaciones: list[str] = Form([]),
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    if len(nombre_torre) != len(cantidad_apartamentos):
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/informacion",
            status_code=303
        )

    proyecto = db.query(Proyecto).filter(
        Proyecto.id == proyecto_id
    ).first()

    if not proyecto or not nombre_torre:
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/informacion",
            status_code=303
        )

    for i, nombre in enumerate(nombre_torre):
        nombre = nombre.strip()

        if not nombre or cantidad_apartamentos[i] <= 0:
            continue

        observacion = (
            observaciones[i].strip()
            if i < len(observaciones)
            else ""
        )

        torre = TorreProyecto(
            proyecto_id=proyecto_id,
            nombre_torre=nombre,
            cantidad_apartamentos=cantidad_apartamentos[i],
            apartamentos_entregados=0,
            observaciones=observacion or None
        )

        db.add(torre)

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

@app.get("/debug-session")
def debug_session(request: Request):
    return {
        "session_data": dict(request.session)
    }

from sqlalchemy import func

@app.get("/proyectos/{proyecto_id}/tareas/nueva")
def nueva_tarea_desde_boton(
    proyecto_id: int,
    hija_de: int | None = None,
    db: Session = Depends(get_db)
):
    if hija_de:
        padre = db.query(Tarea).filter(Tarea.id == hija_de).first()

        if not padre:
            return RedirectResponse(
                f"/proyectos/{proyecto_id}/tareas",
                status_code=303
            )

        # insertar justo después del padre
        posicion = padre.posicion + 1

        # mover las siguientes hacia abajo
        db.query(Tarea).filter(
            Tarea.proyecto_id == proyecto_id,
            Tarea.posicion >= posicion
        ).update(
            {Tarea.posicion: Tarea.posicion + 1},
            synchronize_session=False
        )

        nivel = padre.nivel_esquema + 1

    else:
        # nueva principal al final
        max_pos = db.query(func.max(Tarea.posicion)).filter(
            Tarea.proyecto_id == proyecto_id
        ).scalar()

        posicion = (max_pos or 0) + 1
        nivel = 1

    tarea = Tarea(
        proyecto_id=proyecto_id,
        nombre="Nueva actividad",
        tipo="ACTIVIDAD",
        nivel_esquema=nivel,
        nivel_real=nivel,
        posicion=posicion,
        creado_en=datetime.now()
    )

    db.add(tarea)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/tareas/editar/{tarea.id}",
        status_code=303
    )

from fastapi import Form

from datetime import time

@app.post("/proyectos/{proyecto_id}/lluvia")
def agregar_lluvia(
    proyecto_id: int,
    fecha: date = Form(...),
    hora_inicio: time = Form(...),
    hora_fin: time = Form(...),
    observacion: str = Form(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    lluvia = LluviaProyecto(
        proyecto_id=proyecto_id,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        observacion=observacion
    )

    db.add(lluvia)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/lluvias/{lluvia_id}/eliminar")
def eliminar_lluvia(
    proyecto_id: int,
    lluvia_id: int,
    db: Session = Depends(get_db)
):
    lluvia = db.query(LluviaProyecto).filter(
        LluviaProyecto.id == lluvia_id
    ).first()

    if lluvia:
        db.delete(lluvia)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

from fastapi import Form
from starlette.responses import RedirectResponse

@app.post("/proyectos/{proyecto_id}/anticipos/nuevo")
def crear_anticipo(
    proyecto_id: int,
    fecha: str = Form(...),
    porcentaje: float = Form(...),
    valor: float = Form(...),
    db: Session = Depends(get_db)
):
    nuevo = AnticipoProyecto(
        proyecto_id=proyecto_id,
        fecha=fecha,
        porcentaje=porcentaje,
        valor=valor
    )

    db.add(nuevo)
    db.commit()

    return RedirectResponse(
        url=f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/anticipos/{anticipo_id}/eliminar")
def eliminar_anticipo(
    proyecto_id: int,
    anticipo_id: int,
    db: Session = Depends(get_db)
):
    anticipo = db.query(AnticipoProyecto).filter(
        AnticipoProyecto.id == anticipo_id,
        AnticipoProyecto.proyecto_id == proyecto_id
    ).first()

    if anticipo:
        db.delete(anticipo)
        db.commit()

    return RedirectResponse(
        url=f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/cortes/nuevo")
def crear_corte(
    proyecto_id: int,
    numero_corte: int = Form(...),
    fecha: date = Form(...),
    porcentaje: float = Form(...),
    db: Session = Depends(get_db)
):
    nuevo = CorteProyecto(
        proyecto_id=proyecto_id,
        numero_corte=numero_corte,
        fecha=fecha,
        porcentaje=porcentaje
    )

    db.add(nuevo)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/cortes/{corte_id}/eliminar")
def eliminar_corte(
    proyecto_id: int,
    corte_id: int,
    db: Session = Depends(get_db)
):
    corte = db.query(CorteProyecto).get(corte_id)

    if corte:
        db.delete(corte)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/cortes/{corte_id}/editar")
def editar_corte(
    proyecto_id: int,
    corte_id: int,
    numero_corte: int = Form(...),
    fecha: date = Form(...),
    porcentaje: float = Form(...),
    db: Session = Depends(get_db)
):
    corte = db.query(CorteProyecto).get(corte_id)

    if corte:
        corte.numero_corte = numero_corte
        corte.fecha = fecha
        corte.porcentaje = porcentaje
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

from fastapi import Form

@app.post("/proyectos/{proyecto_id}/cortes-costo/nuevo")
def crear_corte_costo(
    proyecto_id: int,
    numero_corte: int = Form(...),
    porcentaje: float = Form(...),
    valor: float = Form(...),
    db: Session = Depends(get_db)
):
    nuevo = CorteCostoProyecto(
        proyecto_id=proyecto_id,
        numero_corte=numero_corte,
        porcentaje=porcentaje,
        valor=valor
    )

    db.add(nuevo)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/cortes-costo/{corte_id}/editar")
def editar_corte_costo(
    proyecto_id: int,
    corte_id: int,
    numero_corte: int = Form(...),
    porcentaje: float = Form(...),
    valor: float = Form(...),
    db: Session = Depends(get_db)
):
    corte = db.query(CorteCostoProyecto).get(corte_id)

    if corte:
        corte.numero_corte = numero_corte
        corte.porcentaje = porcentaje
        corte.valor = valor
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

@app.post("/proyectos/{proyecto_id}/cortes-costo/{corte_id}/eliminar")
def eliminar_corte_costo(
    proyecto_id: int,
    corte_id: int,
    db: Session = Depends(get_db)
):
    corte = db.query(CorteCostoProyecto).get(corte_id)

    if corte:
        db.delete(corte)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )


@app.post("/proyectos/{proyecto_id}/torres/{torre_id}/observaciones")
def guardar_observaciones_torre(
    proyecto_id: int,
    request: Request,
    torre_id: int,
    observaciones: str = Form(""),
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

    torre.observaciones = observaciones.strip() or None
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/informacion",
        status_code=303
    )

# =====================================================
# BITÁCORA DEL PROYECTO
# =====================================================

@app.get("/proyectos/{proyecto_id}/bitacora", response_class=HTMLResponse)
def ver_bitacora(
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

    registros = db.query(Bitacora).filter(
        Bitacora.proyecto_id == proyecto_id
    ).order_by(Bitacora.fecha.desc(), Bitacora.id.desc()).all()

    return templates.TemplateResponse(
        "bitacora.html",
        {
            "request": request,
            "proyecto": proyecto,
            "registros": registros,
            "hoy": date.today().isoformat(),
            "en_proyecto": True
        }
    )


@app.post("/proyectos/{proyecto_id}/bitacora/nueva")
def crear_registro_bitacora(
    proyecto_id: int,
    request: Request,
    fecha: date = Form(...),
    personal: str = Form(...),
    actividades: str = Form(...),
    observaciones: str = Form(""),
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

    if personal not in ("Administrativo", "Operativo"):
        return RedirectResponse(
            f"/proyectos/{proyecto_id}/bitacora",
            status_code=303
        )

    registro = Bitacora(
        proyecto_id=proyecto_id,
        fecha=fecha,
        personal=personal,
        actividades=actividades.strip(),
        observaciones=observaciones.strip() or None
    )

    db.add(registro)
    db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/bitacora",
        status_code=303
    )


@app.post("/proyectos/{proyecto_id}/bitacora/eliminar/{registro_id}")
def eliminar_registro_bitacora(
    proyecto_id: int,
    registro_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    registro = db.query(Bitacora).filter(
        Bitacora.id == registro_id,
        Bitacora.proyecto_id == proyecto_id
    ).first()

    if registro:
        db.delete(registro)
        db.commit()

    return RedirectResponse(
        f"/proyectos/{proyecto_id}/bitacora",
        status_code=303
    )


from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)


@app.get("/proyectos/{proyecto_id}/resumen/pdf")
def generar_pdf_resumen_proyecto(
    proyecto_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    redir = verificar_sesion(request)
    if redir:
        return redir

    proyecto = db.query(Proyecto).filter(
        Proyecto.id == proyecto_id
    ).first()

    if not proyecto:
        raise HTTPException(
            status_code=404,
            detail="Proyecto no encontrado",
        )

    tareas = db.query(Tarea).filter(
        Tarea.proyecto_id == proyecto_id
    ).order_by(Tarea.id).all()

    documentos = db.query(DocumentoProyecto).filter(
        DocumentoProyecto.proyecto_id == proyecto_id
    ).order_by(DocumentoProyecto.id).all()

    polizas = db.query(PolizaProyecto).filter(
        PolizaProyecto.proyecto_id == proyecto_id
    ).order_by(PolizaProyecto.id).all()


    # Actas e informes de comité
    comites = db.query(ComiteProyecto).filter(
        ComiteProyecto.proyecto_id == proyecto_id
    ).order_by(ComiteProyecto.fecha).all()

    informes_comite = db.query(InformeComite).filter(
        InformeComite.proyecto_id == proyecto_id
    ).order_by(InformeComite.fecha).all()

    # Bitácora del proyecto
    bitacoras = db.query(Bitacora).filter(
        Bitacora.proyecto_id == proyecto_id
    ).order_by(Bitacora.fecha).all()

    # Anticipos y cortes
    anticipos = db.query(AnticipoProyecto).filter(
        AnticipoProyecto.proyecto_id == proyecto_id
    ).order_by(AnticipoProyecto.fecha).all()

    cortes = db.query(CorteProyecto).filter(
        CorteProyecto.proyecto_id == proyecto_id
    ).order_by(CorteProyecto.numero_corte).all()

    cortes_costos = db.query(CorteCostoProyecto).filter(
        CorteCostoProyecto.proyecto_id == proyecto_id
    ).order_by(CorteCostoProyecto.numero_corte).all()

    # PQR
    pqrs = db.query(PQR).filter(
        PQR.proyecto_id == proyecto_id
    ).order_by(PQR.fecha_requerimiento).all()

    # Torres y apartamentos
    torres = db.query(TorreProyecto).filter(
        TorreProyecto.proyecto_id == proyecto_id
    ).order_by(TorreProyecto.id).all()

    # Registro de lluvias
    lluvias = db.query(LluviaProyecto).filter(
        LluviaProyecto.proyecto_id == proyecto_id
    ).order_by(LluviaProyecto.id).all()

    # Memorias de cálculo
    memorias = db.query(MemoriaCalculo).filter(
        MemoriaCalculo.proyecto_id == proyecto_id
    ).order_by(MemoriaCalculo.fecha).all()

    buffer = BytesIO()

    pdf = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    estilos = getSampleStyleSheet()

    titulo = ParagraphStyle(
        "TituloProyecto",
        parent=estilos["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=18,
    )

    elementos = []


    # LOGO DEL INFORME
    ruta_logo = Path(__file__).resolve().parent / "static" / "logo.jpeg"

    if ruta_logo.exists():
        logo = Image(str(ruta_logo), width=3.5 * cm, height=1.5 * cm)
        logo.hAlign = "CENTER"
        elementos.append(logo)
        elementos.append(Spacer(1, 10))

    def texto(valor):
        if valor is None or str(valor).strip() == "":
            return "No registrado"
        return escape(str(valor))

    def fecha(valor):
        if not valor:
            return "No registrada"
        if hasattr(valor, "strftime"):
            return valor.strftime("%d/%m/%Y")
        return texto(valor)

    def agregar_tabla(encabezados, filas):
        datos = [
            [Paragraph(f"<b>{texto(c)}</b>", estilos["BodyText"])
             for c in encabezados]
        ]

        for fila in filas:
            datos.append([
                Paragraph(texto(c), estilos["BodyText"])
                for c in fila
            ])

        tabla = Table(
            datos,
            repeatRows=1,
            hAlign="LEFT",
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             colors.HexColor("#666666")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))

        elementos.append(tabla)
        elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        "RESUMEN GENERAL DEL PROYECTO",
        titulo,
    ))

    elementos.append(Paragraph(
        f"<b>Proyecto:</b> {texto(proyecto.nombre)}",
        estilos["Normal"],
    ))
    elementos.append(Paragraph(
        f"<b>ID:</b> {proyecto.id}",
        estilos["Normal"],
    ))
    elementos.append(Paragraph(
        f"<b>Descripción:</b> {texto(proyecto.descripcion)}",
        estilos["Normal"],
    ))
    elementos.append(Paragraph(
        f"<b>Fecha de inicio:</b> {fecha(proyecto.fecha_inicio)}",
        estilos["Normal"],
    ))
    elementos.append(Paragraph(
        f"<b>Fecha de finalización:</b> {fecha(proyecto.fecha_fin)}",
        estilos["Normal"],
    ))
    elementos.append(Paragraph(
        f"<b>Informe generado:</b> "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}",
        estilos["Normal"],
    ))
    elementos.append(Spacer(1, 18))


    # DATOS DEL CONTRATISTA Y DEL CONTRATO
    elementos.append(Paragraph(
        "DATOS DEL CONTRATISTA Y DEL CONTRATO",
        estilos["Heading2"],
    ))

    agregar_tabla(
        ["Campo", "Información"],
        [
            ["Contratista", proyecto.contratista_nombre],
            ["NIT", proyecto.contratista_nit],
            ["Representante legal", proyecto.contratista_representante],
            ["Teléfono", proyecto.contratista_telefono],
            ["Correo electrónico", proyecto.contratista_correo],
            ["Fecha de firma del contrato",
             fecha(proyecto.fecha_firma_contrato)],
            ["Duración del contrato (días)",
             proyecto.duracion_contrato_dias],
            ["Fecha del acta de inicio",
             fecha(proyecto.fecha_acta_inicio)],
            ["Archivo del contrato",
             proyecto.contrato_archivo],
            ["Archivo del acta de inicio",
             proyecto.acta_inicio_archivo],
        ],
    )

    elementos.append(Paragraph(
        f"ACTIVIDADES Y TAREAS ({len(tareas)})",
        estilos["Heading2"],
    ))


    if tareas:
        agregar_tabla(
            [
                "Actividad",
                "Tipo",
                "Inicio planificado",
                "Fin planificado",
                "Inicio real",
                "Fin real",
                "Duración (días)",
                "Avance (%)",
                "Valor",
            ],
            [
                [
                    tarea.nombre,
                    tarea.tipo,
                    fecha(tarea.fecha_inicio),
                    fecha(tarea.fecha_fin),
                    fecha(tarea.fecha_inicio_real),
                    fecha(tarea.fecha_fin_real),
                    tarea.duracion_dias,
                    tarea.porcentaje_completado,
                    tarea.valor_total,
                ]
                for tarea in tareas
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay actividades registradas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        f"DOCUMENTOS REGISTRADOS ({len(documentos)})",
        estilos["Heading2"],
    ))

    if documentos:
        agregar_tabla(
            ["Tipo", "Descripción", "Fecha", "Valor"],
            [
                [
                    documento.tipo,
                    documento.descripcion,
                    fecha(documento.fecha),
                    documento.valor,
                ]
                for documento in documentos
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay documentos registrados en este módulo.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        f"PÓLIZAS ({len(polizas)})",
        estilos["Heading2"],
    ))

    if polizas:
        agregar_tabla(
            ["Tipo", "Aseguradora", "Inicio", "Vencimiento"],
            [
                [
                    poliza.tipo_poliza,
                    poliza.aseguradora,
                    fecha(poliza.fecha_inicio),
                    fecha(poliza.fecha_fin),
                ]
                for poliza in polizas
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay pólizas registradas.",
            estilos["Normal"],
        ))


    # ACTAS DE COMITÉ
    elementos.append(Paragraph(
        f"ACTAS DE COMITÉ ({len(comites)})",
        estilos["Heading2"],
    ))

    if comites:
        agregar_tabla(
            ["Fecha", "Título", "Documento"],
            [
                [
                    fecha(comite.fecha),
                    comite.titulo,
                    comite.documento,
                ]
                for comite in comites
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay actas de comité registradas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # INFORMES DE COMITÉ
    elementos.append(Paragraph(
        f"INFORMES DE COMITÉ ({len(informes_comite)})",
        estilos["Heading2"],
    ))

    if informes_comite:
        agregar_tabla(
            ["Fecha", "Título", "Documento"],
            [
                [
                    fecha(informe.fecha),
                    informe.titulo,
                    informe.documento,
                ]
                for informe in informes_comite
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay informes de comité registrados.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # BITÁCORA DEL PROYECTO
    elementos.append(Paragraph(
        f"BITÁCORA DEL PROYECTO ({len(bitacoras)})",
        estilos["Heading2"],
    ))

    if bitacoras:
        agregar_tabla(
            ["Fecha", "Personal", "Actividades", "Observaciones"],
            [
                [
                    fecha(bitacora.fecha),
                    bitacora.personal,
                    bitacora.actividades,
                    bitacora.observaciones,
                ]
                for bitacora in bitacoras
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay registros en la bitácora.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))


    # ANTICIPOS
    elementos.append(Paragraph(
        f"ANTICIPOS ({len(anticipos)})",
        estilos["Heading2"],
    ))

    if anticipos:
        agregar_tabla(
            ["Fecha", "Porcentaje (%)", "Valor"],
            [
                [
                    fecha(anticipo.fecha),
                    anticipo.porcentaje,
                    anticipo.valor,
                ]
                for anticipo in anticipos
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay anticipos registrados.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # CORTES DE OBRA
    elementos.append(Paragraph(
        f"CORTES DE OBRA ({len(cortes)})",
        estilos["Heading2"],
    ))

    if cortes:
        agregar_tabla(
            ["Número de corte", "Fecha", "Porcentaje (%)"],
            [
                [
                    corte.numero_corte,
                    fecha(corte.fecha),
                    corte.porcentaje,
                ]
                for corte in cortes
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay cortes de obra registrados.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # CORTES DE COSTOS
    elementos.append(Paragraph(
        f"CORTES DE COSTOS ({len(cortes_costos)})",
        estilos["Heading2"],
    ))

    if cortes_costos:
        agregar_tabla(
            ["Número de corte", "Porcentaje (%)", "Valor"],
            [
                [
                    corte.numero_corte,
                    corte.porcentaje,
                    corte.valor,
                ]
                for corte in cortes_costos
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay cortes de costos registrados.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))


    # PQR DEL PROYECTO
    elementos.append(Paragraph(
        f"PQR DEL PROYECTO ({len(pqrs)})",
        estilos["Heading2"],
    ))

    if pqrs:
        agregar_tabla(
            [
                "Fecha requerimiento",
                "Problema",
                "Solución",
                "Ubicación",
                "Fecha solución",
                "Estado",
                "Observaciones",
            ],
            [
                [
                    fecha(pqr.fecha_requerimiento),
                    pqr.problema,
                    pqr.solucion,
                    pqr.ubicacion,
                    fecha(pqr.fecha_solucion),
                    pqr.estado,
                    pqr.observacion,
                ]
                for pqr in pqrs
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay PQR registradas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # TORRES Y APARTAMENTOS
    elementos.append(Paragraph(
        f"TORRES Y APARTAMENTOS ({len(torres)})",
        estilos["Heading2"],
    ))

    if torres:
        agregar_tabla(
            [
                "Torre",
                "Cantidad de apartamentos",
                "Apartamentos entregados",
                "Observaciones",
            ],
            [
                [
                    torre.nombre_torre,
                    torre.cantidad_apartamentos,
                    torre.apartamentos_entregados,
                    torre.observaciones,
                ]
                for torre in torres
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay torres registradas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # REGISTRO DE LLUVIAS
    elementos.append(Paragraph(
        f"REGISTRO DE LLUVIAS ({len(lluvias)})",
        estilos["Heading2"],
    ))

    if lluvias:
        agregar_tabla(
            ["Fecha", "Hora de inicio", "Hora de fin", "Observación"],
            [
                [
                    fecha(lluvia.fecha),
                    lluvia.hora_inicio,
                    lluvia.hora_fin,
                    lluvia.observacion,
                ]
                for lluvia in lluvias
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay registros de lluvias.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    # MEMORIAS DE CÁLCULO
    elementos.append(Paragraph(
        f"MEMORIAS DE CÁLCULO ({len(memorias)})",
        estilos["Heading2"],
    ))

    if memorias:
        agregar_tabla(
            ["Fecha", "Título", "Documento"],
            [
                [
                    fecha(memoria.fecha),
                    memoria.titulo,
                    memoria.documento,
                ]
                for memoria in memorias
            ],
        )
    else:
        elementos.append(Paragraph(
            "No hay memorias de cálculo registradas.",
            estilos["Normal"],
        ))
        elementos.append(Spacer(1, 12))

    pdf.build(elementos)
    buffer.seek(0)

    from fastapi.responses import StreamingResponse

    nombre_pdf = f"resumen_proyecto_{proyecto.id}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="{nombre_pdf}"'
        },
    )
