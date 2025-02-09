# models.py
from datetime import datetime
from decimal import Decimal
from extensions import db


class TimestampMixin:
    """
    Mixin to add automatic timestamping to models.
    Includes:
      - created_at: The timestamp when the record was created.
      - updated_at: The timestamp when the record was last updated.
    """
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Record creation timestamp"
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Record update timestamp"
    )


class Receipt(db.Model, TimestampMixin):
    """
    Represents a receipt record.
    Stores metadata extracted from the receipt such as the merchant name, date,
    monetary amounts, and associated OCR text.
    """
    __tablename__ = 'receipts'

    id = db.Column(db.Integer, primary_key=True)
    bill_no = db.Column(db.String(50), nullable=True, comment="Bill or Invoice number")
    merchant = db.Column(db.String(120), nullable=False, index=True, comment="Merchant name")
    date_time = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Date and time of the receipt"
    )
    total_amount = db.Column(
        db.Numeric(precision=10, scale=2),
        nullable=True,
        comment="Total amount of the receipt"
    )
    tax = db.Column(
        db.Numeric(precision=10, scale=2),
        nullable=True,
        comment="Tax amount"
    )
    discount = db.Column(
        db.Numeric(precision=10, scale=2),
        nullable=True,
        comment="Discount amount"
    )
    ocr_text = db.Column(
        db.Text,
        nullable=True,
        comment="Full OCR text extracted from the receipt"
    )
    category = db.Column(
        db.String(50),
        nullable=True,
        index=True,
        comment="Expense category"
    )
    location = db.Column(
        db.String(120),
        nullable=True,
        comment="Merchant location or other geographical info"
    )

    # Define relationship to ReceiptItem with cascade deletion.
    items = db.relationship(
        'ReceiptItem',
        backref='receipt',
        lazy=True,
        cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """
        Serialize the receipt object to a dictionary.
        Useful for JSON responses or API output.
        """
        return {
            'id': self.id,
            'bill_no': self.bill_no,
            'merchant': self.merchant,
            'date_time': self.date_time.isoformat() if self.date_time else None,
            'total_amount': float(self.total_amount) if self.total_amount is not None else None,
            'tax': float(self.tax) if self.tax is not None else None,
            'discount': float(self.discount) if self.discount is not None else None,
            'ocr_text': self.ocr_text,
            'category': self.category,
            'location': self.location,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'items': [item.to_dict() for item in self.items] if self.items else []
        }

    def update_from_dict(self, data: dict) -> None:
        """
        Update model fields based on the provided dictionary.
        Only updates fields that are present in the data dictionary.
        """
        for field in ['bill_no', 'merchant', 'date_time', 'total_amount', 'tax', 'discount',
                      'ocr_text', 'category', 'location']:
            if field in data:
                setattr(self, field, data[field])

    def __repr__(self) -> str:
        date_str = self.date_time.strftime('%Y-%m-%d %H:%M:%S') if self.date_time else "N/A"
        return (
            f"<Receipt id={self.id} merchant='{self.merchant}' "
            f"date_time='{date_str}' total_amount={self.total_amount}>"
        )


class ReceiptItem(db.Model, TimestampMixin):
    """
    Represents an individual item on a receipt.
    """
    __tablename__ = 'receipt_items'

    id = db.Column(db.Integer, primary_key=True)
    receipt_id = db.Column(
        db.Integer,
        db.ForeignKey('receipts.id', ondelete='CASCADE'),
        nullable=False,
        comment="Foreign key linking to the parent receipt"
    )
    name = db.Column(
        db.String(200),
        nullable=False,
        comment="Item name/description"
    )
    amount = db.Column(
        db.Numeric(precision=10, scale=2),
        nullable=True,
        comment="Monetary amount for the item"
    )

    def to_dict(self) -> dict:
        """
        Serialize the receipt item to a dictionary.
        """
        return {
            'id': self.id,
            'receipt_id': self.receipt_id,
            'name': self.name,
            'amount': float(self.amount) if self.amount is not None else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def update_from_dict(self, data: dict) -> None:
        """
        Update model fields based on the provided dictionary.
        """
        for field in ['name', 'amount']:
            if field in data:
                setattr(self, field, data[field])

    def __repr__(self) -> str:
        return f"<ReceiptItem id={self.id} name='{self.name}' amount={self.amount}>"
