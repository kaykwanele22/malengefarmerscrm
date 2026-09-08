"""add cooperative hierarchy

Revision ID: f6cafff77dfb
Revises: b9e86099bb3a
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa

revision = 'f6cafff77dfb'
down_revision = 'b9e86099bb3a'
branch_labels = None
depends_on = None

COOPERATIVE_TABLES = [
    'audit_log', 'contribution', 'crop', 'customer', 'equipment',
    'expense', 'farm', 'farmer', 'farmer_interaction', 'harvest',
    'inventory_item', 'inventory_transaction', 'membership', 'payment',
    'sale', 'supplier', 'task', 'user_access'
]

def fk_name(table_name):
    return f'fk_{table_name}_cooperative_id_cooperative'

def upgrade():
    # Create cooperative table
    op.create_table(
        'cooperative',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('cooperative_type', sa.String(length=30), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('registration_number', sa.String(length=120), nullable=True),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['cooperative.id'], name='fk_cooperative_parent_id_cooperative'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_cooperative_name'),
    )

    # Add cooperative_id column to all related tables
    for table_name in COOPERATIVE_TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(sa.Column('cooperative_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                fk_name(table_name),
                'cooperative',
                ['cooperative_id'],
                ['id'],
            )

def downgrade():
    # Remove cooperative_id from all tables (reverse order)
    for table_name in reversed(COOPERATIVE_TABLES):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_constraint(fk_name(table_name), type_='foreignkey')
            batch_op.drop_column('cooperative_id')

    op.drop_table('cooperative')