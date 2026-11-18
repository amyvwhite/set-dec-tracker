import dataclasses
from datetime import datetime
from typing import Optional

@dataclasses.dataclass
class Receipt:
    file_path: str
    file_hash: str
    id: Optional[int] = None
    set_number: Optional[str] = None
    special_tab: Optional[str] = None
    buyer_name: Optional[str] = None
    description: Optional[str] = None
    vendor: Optional[str] = None
    subtotal: Optional[float] = None
    shipping: Optional[float] = None
    import_fees: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    payment_method: Optional[str] = None
    date: Optional[str] = None
    reference_number: Optional[str] = None
    po_number: Optional[str] = None
    is_rental: bool = False
    rental_end_date: Optional[str] = None
    is_greens: bool = False
    is_craft: bool = False
    is_gas: bool = False
    is_parking: bool = False
    is_usd: bool = False
    is_asset: bool = False
    exchange_rate: Optional[float] = None
    craft_people: Optional[int] = None
    episode_code: Optional[str] = None
    notes: Optional[str] = None
    # Expense specific fields
    co_code: Optional[str] = "01"
    loc_code: Optional[str] = "01"
    account_code: Optional[str] = "2716"
    tax_code: Optional[str] = "40"
    hst_account: Optional[str] = None
    expense_only: bool = False
    status: str = 'PENDING'
    created_at: Optional[str] = None
