import pandas as pd
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Tarea

# 1. Leer el Excel
df = pd.read_excel("Proyecto.xlsx")  # <-- tu archivo

db: Session = SessionLocal()

for _, fila in df.iterrows():
    tarea = Tarea(
        nombre=fila["Nombre"],
        tipo=fila["Tipo"],
        nivel_real=int(fila["Nivel real"]),
        wbs_project=str(fila["Número de esquema"]),  # 👈 AQUÍ ESTÁ LA CLAVE
        fecha_inicio=fila["Inicio"],
        fecha_fin=fila["Fin"],
        duracion_texto=fila["Duración"]
    )

    db.add(tarea)

db.commit()
db.close()

print("Tareas cargadas correctamente")