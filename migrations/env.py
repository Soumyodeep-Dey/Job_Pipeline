from alembic import context
from app.database import Base, engine
from app import models  # Register model metadata for autogeneration.


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    migrate(provided)
else:
    with engine.connect() as connection:
        migrate(connection)
