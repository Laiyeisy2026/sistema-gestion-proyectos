from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "postgresql://postgres:Postgres1234@localhost:5432/Proyectos"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

# 👇 IMPORTA LOS MODELOS
from models import *

# 👇 CREA LAS TABLAS QUE NO EXISTAN
Base.metadata.create_all(bind=engine)