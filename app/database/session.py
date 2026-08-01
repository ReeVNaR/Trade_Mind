from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.database.models import Base, PortfolioSnapshot
from app.utils.logger import logger

# Normalize Database URL (e.g. Render postgres:// -> postgresql://)
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Configure database engine
connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
engine_kwargs = {"connect_args": connect_args, "echo": False}
if "sqlite" not in db_url:
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(db_url, **engine_kwargs)

# Auto-create tables if they do not exist
Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Creates database tables and ensures initial snapshot exists."""
    Base.metadata.create_all(bind=engine)
    
    # Auto-migrate columns for SQLite if needed
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE signal_logs ADD COLUMN stop_loss FLOAT"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE signal_logs ADD COLUMN take_profit FLOAT"))
            conn.commit()
        except Exception:
            pass
    
    db: Session = SessionLocal()
    try:
        # Check if portfolio snapshot exists; if not, initialize with default balance
        latest_snapshot = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
        if not latest_snapshot:
            initial = PortfolioSnapshot(
                cash_balance=settings.INITIAL_BALANCE,
                equity=settings.INITIAL_BALANCE,
                open_positions_count=0,
                total_realized_pnl=0.0
            )
            db.add(initial)
            db.commit()
            logger.info(f"Initialized paper trading portfolio with balance: ${settings.INITIAL_BALANCE:,.2f}")
    except Exception as e:
        logger.error(f"Error initializing portfolio snapshot: {e}")
        db.rollback()
    finally:
        db.close()


def get_db():
    """Dependency generator for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
