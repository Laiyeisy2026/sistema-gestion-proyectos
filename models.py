from database import Base
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Numeric,
    Boolean,
    ForeignKey,
    Float
)

from datetime import datetime
from sqlalchemy.orm import relationship


# =========================
# OPERARIOS
# =========================
class Operario(Base):
    __tablename__ = "operarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    actividad = Column(String)

class FaseRecurso(Base):
    __tablename__ = "fase_recursos"

    id = Column(Integer, primary_key=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"), nullable=False)
    nombre_fase = Column(String, nullable=False)
    cantidad_operarios = Column(Integer, nullable=False, default=0)

# =========================
# TAREAS
# =========================
from sqlalchemy import Numeric

class Tarea(Base):
    __tablename__ = "tarea"

    id = Column(Integer, primary_key=True, index=True)

    # Proyecto
    proyecto_id = Column(Integer)

    # Datos básicos
    nombre = Column(Text)
    tipo = Column(Text)

    # Jerarquía
    nivel_esquema = Column(Integer)
    nivel_real = Column(Integer)
    id_padre = Column(Integer)

    posicion = Column(Integer, default=0)

    # Duración
    duracion_texto = Column(Text)
    duracion_dias = Column(Integer)

    # =========================
    # FECHAS PLANIFICADAS
    # =========================
    fecha_inicio = Column(DateTime)
    fecha_fin = Column(DateTime)

    # =========================
    # FECHAS REALES (NUEVO)
    # =========================
    fecha_inicio_real = Column(DateTime, nullable=True)
    fecha_fin_real = Column(DateTime, nullable=True)

    # Avance
    porcentaje_completado = Column(Numeric)
    valor_total = Column(Numeric(14, 2), nullable=True)

    # Otros
    es_hito = Column(Boolean)
    estado_id = Column(Integer)
    creado_en = Column(DateTime)


# =========================
# ASIGNACIONES
# =========================
from sqlalchemy import String

class AsignacionOperario(Base):
    __tablename__ = "asignacion_operario"

    id = Column(Integer, primary_key=True)

    tarea_id = Column(Integer, ForeignKey("tarea.id"))        # 👈 PRINCIPAL
    actividad_id = Column(Integer, ForeignKey("tarea.id"), nullable=True)  # 👈 NUEVO

    operario_id = Column(Integer, ForeignKey("operarios.id"), nullable=True)
    horas_asignadas = Column(Float)
    estado = Column(String)

from sqlalchemy import Column, Integer, Text, DateTime, String, Date
from datetime import datetime

class Proyecto(Base):
    __tablename__ = "proyecto"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(Text, nullable=False)
    descripcion = Column(Text, nullable=True)

    fecha_inicio = Column(DateTime, nullable=True)
    fecha_fin = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, default=datetime.now)

    imagen = Column(String, nullable=True)

    # ⬇️ LEGACY (PDF antiguo, puedes dejarlo por ahora)
    dashboard_pdf = Column(String, nullable=True)

    # ⬇️ NUEVO: Power BI Service
    dashboard_powerbi_url = Column(Text, nullable=True)

    fecha_firma_contrato = Column(Date, nullable=True)
    contrato_archivo = Column(String, nullable=True)

    duracion_contrato_dias = Column(Integer, nullable=True)

    fecha_acta_inicio = Column(Date, nullable=True)
    acta_inicio_archivo = Column(String, nullable=True)

    torres = relationship(
        "TorreProyecto",
        back_populates="proyecto",
        cascade="all, delete-orphan"
        )

    
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey

class PQR(Base):
    __tablename__ = "pqr"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"))

    fecha_requerimiento = Column(Date, nullable=False)
    problema = Column(Text, nullable=False)
    solucion = Column(Text)
    ubicacion = Column(String(255))
    fecha_solucion = Column(Date)

    estado = Column(String(20), default="abierto")
    creado_en = Column(DateTime, default=datetime.now)

from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from datetime import datetime

class PolizaProyecto(Base):
    __tablename__ = "poliza_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"))

    tipo_poliza = Column(String(100))          # Cumplimiento, RC, etc.
    aseguradora = Column(String(150))

    fecha_inicio = Column(Date)
    fecha_fin = Column(Date)

    archivo = Column(String(255))               # ruta del PDF
    creado_en = Column(DateTime, default=datetime.now)


from sqlalchemy import Float, Text

class DocumentoProyecto(Base):
    __tablename__ = "documento_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"))

    tipo = Column(String(50))                  # anticipo, costo, factura, otro
    descripcion = Column(Text)

    fecha = Column(Date)
    valor = Column(Float, nullable=True)

    archivo = Column(String(255))               # ruta del archivo
    creado_en = Column(DateTime, default=datetime.now)

class TorreProyecto(Base):
    __tablename__ = "torre_apartamentos"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"), nullable=False)

    nombre_torre = Column(String, nullable=False)
    cantidad_apartamentos = Column(Integer, nullable=False)
    apartamentos_entregados = Column(Integer, default=0)

    proyecto = relationship(
        "Proyecto",
        back_populates="torres"
        )

from sqlalchemy import Time

class LluviaProyecto(Base):
    __tablename__ = "lluvias_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"))

    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)

    observacion = Column(String, nullable=True)

from sqlalchemy import Column, Integer, Date, ForeignKey, Numeric
from database import Base

class AnticipoProyecto(Base):
    __tablename__ = "anticipos_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"), nullable=False)

    fecha = Column(Date, nullable=False)
    porcentaje = Column(Numeric(5,2), nullable=False)
    valor = Column(Numeric(14,2), nullable=False)

class CorteProyecto(Base):
    __tablename__ = "cortes_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"), nullable=False)

    numero_corte = Column(Integer, nullable=False)
    fecha = Column(Date, nullable=False)
    porcentaje = Column(Numeric(5,2), nullable=False)

class CorteCostoProyecto(Base):
    __tablename__ = "cortes_costo_proyecto"

    id = Column(Integer, primary_key=True, index=True)
    proyecto_id = Column(Integer, ForeignKey("proyecto.id"))
    numero_corte = Column(Integer, nullable=False)
    porcentaje = Column(Numeric(5,2), nullable=False)
    valor = Column(Numeric(14,2), nullable=False)