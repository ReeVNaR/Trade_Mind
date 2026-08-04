from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.database.models import Base, PortfolioSnapshot, Position, Trade
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


def _run_migrations():
    with engine.connect() as conn:
        for col in ["highest_price FLOAT", "trailing_stop FLOAT"]:
            try:
                conn.execute(text(f"ALTER TABLE positions ADD COLUMN {col}"))
                conn.commit()
            except Exception:
                pass
        for col in ["stop_loss FLOAT", "take_profit FLOAT"]:
            try:
                conn.execute(text(f"ALTER TABLE signal_logs ADD COLUMN {col}"))
                conn.commit()
            except Exception:
                pass


_run_migrations()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(force_reset: bool = False):
    """Creates database tables and ensures clean portfolio snapshot with auto-reset support."""
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    
    db: Session = SessionLocal()

    try:
        should_reset = force_reset or settings.AUTO_RESET_DB_ON_START
        if should_reset:
            # Self-healing: Clear any stale intraday positions from previous runs/deploys
            open_pos_count = db.query(Position).count()
            if open_pos_count > 0:
                db.query(Position).delete()
                # Close any unclosed trades
                db.query(Trade).filter(Trade.status == "OPEN").update({
                    "status": "CLOSED",
                    "reason": "Session Startup Auto-Reconciled",
                    "closed_at": datetime.utcnow()
                })
                logger.info(f"🧹 Auto-cleared {open_pos_count} stale intraday positions for fresh trading session.")

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
                logger.info(f"Initialized paper trading portfolio with balance: ₹{settings.INITIAL_BALANCE:,.2f}")
            else:
                latest_snapshot.cash_balance = settings.INITIAL_BALANCE
                latest_snapshot.equity = settings.INITIAL_BALANCE
                latest_snapshot.open_positions_count = 0
                latest_snapshot.total_realized_pnl = 0.0
                db.commit()
                logger.info(f"Synchronized fresh session portfolio capital: ₹{settings.INITIAL_BALANCE:,.2f}")
        else:
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
                logger.info(f"Initialized paper trading portfolio with balance: ₹{settings.INITIAL_BALANCE:,.2f}")
            elif db.query(Position).count() == 0 and latest_snapshot.cash_balance != settings.INITIAL_BALANCE:
                latest_snapshot.cash_balance = settings.INITIAL_BALANCE
                latest_snapshot.equity = settings.INITIAL_BALANCE
                db.commit()
                logger.info(f"Synchronized paper trading portfolio balance to: ₹{settings.INITIAL_BALANCE:,.2f}")
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
