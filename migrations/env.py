from alembic import context
from src.database import engine, Base
import src.models

if context.is_offline_mode():
    context.configure(url=engine.url.render_as_string(hide_password=False), target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
