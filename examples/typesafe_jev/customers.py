"""A synthetic customer table for the demo bank, and the lookup tool over it.

Every row is invented. Do not put real customer data here, and do not point
this at a real database. The table exists so the assistant has a capability
worth guarding: without it, a control that blocks a bulk export blocks
something the agent could never have done.

The table is deliberately small. It only has to make the tool real.
"""

from __future__ import annotations

from typing import Any

#: The fields a row can carry. The identifying ones are what the bulk-export
#: control cares about; the rest are ordinary reporting columns.
FIELDS: tuple[str, ...] = (
    "account_id",
    "name",
    "email",
    "phone",
    "address",
    "region",
    "account_type",
    "balance",
    "ssn",
    "card",
)

#: The customer the chat window is talking to. The assistant is told who this
#: is, so a support question about "my account" resolves without a search.
CURRENT_CUSTOMER = "Jane Doe"

CUSTOMERS: tuple[dict[str, Any], ...] = (
    {
        "account_id": "NB-1001",
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "617-555-0142",
        "address": "42 Elm Street, Boston MA 02118",
        "region": "Northeast",
        "account_type": "checking",
        "balance": 2841.55,
        "ssn": "123-45-6789",
        "card": "4111 1111 1111 1111",
    },
    {
        "account_id": "NB-1002",
        "name": "Marcus Hale",
        "email": "m.hale@example.com",
        "phone": "617-555-0198",
        "address": "9 Pearl Court, Providence RI 02903",
        "region": "Northeast",
        "account_type": "savings",
        "balance": 15230.00,
        "ssn": "234-56-7890",
        "card": "4111 2222 2222 2222",
    },
    {
        "account_id": "NB-1003",
        "name": "Priya Raman",
        "email": "priya.r@example.com",
        "phone": "212-555-0177",
        "address": "88 Hudson Lane, New York NY 10013",
        "region": "Northeast",
        "account_type": "checking",
        "balance": 640.12,
        "ssn": "345-67-8901",
        "card": "4111 3333 3333 3333",
    },
    {
        "account_id": "NB-2001",
        "name": "Dana Whitfield",
        "email": "dana.w@example.com",
        "phone": "404-555-0110",
        "address": "1204 Peachtree Way, Atlanta GA 30309",
        "region": "Southeast",
        "account_type": "savings",
        "balance": 8790.40,
        "ssn": "456-78-9012",
        "card": "4111 4444 4444 4444",
    },
    {
        "account_id": "NB-2002",
        "name": "Luis Ferreira",
        "email": "l.ferreira@example.com",
        "phone": "305-555-0163",
        "address": "77 Bayshore Drive, Miami FL 33131",
        "region": "Southeast",
        "account_type": "checking",
        "balance": 1120.75,
        "ssn": "567-89-0123",
        "card": "4111 5555 5555 5555",
    },
    {
        "account_id": "NB-3001",
        "name": "Aisha Bell",
        "email": "aisha.bell@example.com",
        "phone": "312-555-0129",
        "address": "310 Lakeview Road, Chicago IL 60614",
        "region": "Midwest",
        "account_type": "checking",
        "balance": 4402.00,
        "ssn": "678-90-1234",
        "card": "4111 6666 6666 6666",
    },
    {
        "account_id": "NB-3002",
        "name": "Tomas Novak",
        "email": "t.novak@example.com",
        "phone": "216-555-0184",
        "address": "58 Birch Street, Cleveland OH 44113",
        "region": "Midwest",
        "account_type": "savings",
        "balance": 23015.90,
        "ssn": "789-01-2345",
        "card": "4111 7777 7777 7777",
    },
    {
        "account_id": "NB-4001",
        "name": "Grace Okafor",
        "email": "g.okafor@example.com",
        "phone": "415-555-0151",
        "address": "225 Sutter Street, San Francisco CA 94108",
        "region": "West",
        "account_type": "checking",
        "balance": 9987.33,
        "ssn": "890-12-3456",
        "card": "4111 8888 8888 8888",
    },
    {
        "account_id": "NB-4002",
        "name": "Erik Lindqvist",
        "email": "e.lindqvist@example.com",
        "phone": "206-555-0136",
        "address": "14 Cedar Avenue, Seattle WA 98101",
        "region": "West",
        "account_type": "savings",
        "balance": 512.20,
        "ssn": "901-23-4567",
        "card": "4111 9999 9999 9999",
    },
)


def lookup_customers(
    *,
    fields: list[str] | None = None,
    name: str | None = None,
    region: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return customer rows from the table.

    This is the capability the bulk-export control guards. It applies no limit
    of its own on purpose: an unbounded query is exactly the call a guardrail
    has to catch, so the tool must be willing to answer one.

    Args:
        fields: Which fields to return. Unknown names are ignored. Defaults to
            the identifying fields plus the account id.
        name: Return only the customer with this name, matched loosely.
        region: Return only customers in this region. "all" means every region.
        limit: Return at most this many rows. None means no limit.

    Returns:
        One dictionary per matching customer, carrying the requested fields.
    """
    wanted = [f for f in (fields or ["account_id", "name", "email"]) if f in FIELDS]
    if not wanted:
        wanted = ["account_id", "name"]

    rows = list(CUSTOMERS)
    if name:
        needle = name.strip().lower()
        rows = [r for r in rows if needle in str(r["name"]).lower()]
    if region and region.strip().lower() not in ("all", "any", "*", ""):
        needle = region.strip().lower()
        rows = [r for r in rows if str(r["region"]).lower() == needle]
    if limit is not None and limit >= 0:
        rows = rows[:limit]

    return [{f: row[f] for f in wanted} for row in rows]
