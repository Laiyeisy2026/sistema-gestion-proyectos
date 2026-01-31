from sqlalchemy import create_engine

engine = create_engine(
    "postgresql://postgres:Postgres1234@localhost:5432/Proyectos"
)

conn = engine.connect()
print("✅ Conexión OK")
conn.close()