from database import engine, Base
from models import *
import sqlalchemy as sa

try:
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        tables = sa.inspect(engine).get_table_names()
        print(f"? Database connected")
        print(f"? Tables found: {tables}")
except Exception as e:
    print(f"? Database error: {e}")
