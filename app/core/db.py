from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        # ВАЖНО: rollback ДО close, иначе любая транзакция, которую
        # endpoint не закоммитил явно (например, GET /categories — там нет
        # commit), остаётся открытой при возврате connection в pool.
        # Connection попадает в pool как "idle in transaction" и держит
        # row-locks, заблокированные неявно через autoflush. Это вызывало
        # зависания preview: новый запрос на SELECT FOR UPDATE на сессии
        # стоял в очереди за такой повисшей транзакцией предыдущего GET.
        try:
            db.rollback()
        finally:
            db.close()
