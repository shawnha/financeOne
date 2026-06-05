"""ssart_customers / ssart_products — SIMS 거래처·제품 마스터 (SsArt OpenAPI).

자료: /v2/customer/get/ (거래처 1283), /v2/product/get/ (제품 81).
거래처: BIZ_NO, 요양기관번호(MEDI_CD), 업태/업종, 주소, 구분(제조사/매입/매출).
제품: 제조사, 성분코드, 보험코드, 표준코드(barcode), 보험약가, UDI.
마스터 — (entity_id, *_code) UNIQUE, UPSERT.

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op


revision: str = "l8m9n0o1p2q3"
down_revision: Union[str, None] = "k7l8m9n0o1p2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.ssart_customers (
            id                  SERIAL PRIMARY KEY,
            entity_id           INTEGER NOT NULL REFERENCES financeone.entities(id),
            customer_code       TEXT NOT NULL,
            customer_gu         TEXT,
            customer_name       TEXT,
            customer_print_name TEXT,
            owner_name          TEXT,
            biz_no              TEXT,
            business_status     TEXT,
            business_item       TEXT,
            tel                 TEXT,
            fax                 TEXT,
            kind_code           TEXT,
            kind_name           TEXT,
            medi_code           TEXT,
            zip_code            TEXT,
            addr                TEXT,
            mod_date            DATE,
            source              TEXT,
            raw_row             JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, customer_code)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ssart_cust_name "
        "ON financeone.ssart_customers (entity_id, customer_name);"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financeone.ssart_products (
            id                 SERIAL PRIMARY KEY,
            entity_id          INTEGER NOT NULL REFERENCES financeone.entities(id),
            product_code       TEXT NOT NULL,
            product_type       TEXT,
            product_name       TEXT,
            product_print_name TEXT,
            spec               TEXT,
            unit               TEXT,
            insu_price         NUMERIC(18,2),
            insu_code          TEXT,
            standard_code      TEXT,
            ingredient_code    TEXT,
            ingredient_name    TEXT,
            maker_name         TEXT,
            order_vendor_name  TEXT,
            product_group      TEXT,
            udi_code           TEXT,
            use_yn             TEXT,
            mod_date           DATE,
            source             TEXT,
            raw_row            JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, product_code)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ssart_prod_name "
        "ON financeone.ssart_products (entity_id, product_name);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financeone.ssart_products;")
    op.execute("DROP TABLE IF EXISTS financeone.ssart_customers;")
