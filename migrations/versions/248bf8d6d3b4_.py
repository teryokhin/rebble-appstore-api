"""empty message

Revision ID: 248bf8d6d3b4
Revises: b42fcf431ada
Create Date: 2018-06-20 06:57:21.199455

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '248bf8d6d3b4'
down_revision = 'b42fcf431ada'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('companion_app', sa.Column('url', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('companion_app', 'url')
    # ### end Alembic commands ###
