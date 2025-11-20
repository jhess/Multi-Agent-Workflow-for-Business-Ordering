import pandas as pd
import re
from datetime import datetime
from smolagents import (
    ToolCallingAgent,
    OpenAIServerModel,
    tool,
)
from lib.dbhelpers import check_item, create_transaction, get_stock_level, get_unit_price, search_quote_history, get_supplier_delivery_date

# Tools for inventory agent

@tool
def get_inventory_level(item: str) -> str:
    """Check the stock level of an item.

    Args:
        item (str): The item to check the stock level for.

    Returns:
        str: A message indicating the stock level of the item.
    """
    date = datetime.now().isoformat()

    if not check_item(item):  # Check if item exists in inventory
        # No match found - Return a message indicating item not found
        print(f"WARNING: Item '{item}' not found in inventory or product catalog")
        return f"Item '{item}' not found in inventory."

    result = get_stock_level(item, date)
    
    stock_level = result["current_stock"].iloc[0]

    return f"The stock level for {item} is {stock_level}."

@tool
def reorder_inventory_item(item: str, quantity: int, price: float) -> str:
    """Reorder an item from the stock inventory.

    Args:
        item (str): The item to reorder.
        quantity (int): The quantity to purchase.
        price (float): The price that it costs to reorder the item.

    Returns:
        str: A message indicating whether the item was reordered successfully.
    """
    date = datetime.now().isoformat()

    trans_id = create_transaction(item, "stock_orders", quantity, price, date)
    return f"{quantity} of {item} reordered successfully."

# Tools for quoting agent

@tool
def get_discount_info(search_terms: str) -> bool:
    """
    Retrieve a bulk discount info using historical quotes matching the given search terms.
    Use this tool when you need past quotes to determine if a bulk discount can be applied to an order.
    Args:
        search_terms: A string with keywords from the customer's request (will be split into words).
    Returns:
        (bool) If a bulk discount should be applied or not from matching quotes.
    """
    # Always split the string into a list of words
    request = search_terms.split() if search_terms else []
    # Fetch historical quotes
    result_history = search_quote_history(request)

    bulk_discount = False

    if result_history:
        # Check for bulk discount in explanations
        for q in result_history:
            explanation = q.get('quote_explanation', '').lower()
            if 'bulk' in explanation or 'discount' in explanation:
                bulk_discount = True
                break

    return bulk_discount

@tool
def get_item_price(item_name: str, quantity: int) -> float:
    """Calculate the total cost for a given item based on its quantity and unit price from an inventory list.

    Args:
        item_name (str): The item to check the unit price for.
        quantity (int): The number of units to calculate the total cost for.

    Returns:
        float: A total price for the given quantity of the item. Returns 0.0 if item not found.
    """
    date = datetime.now().isoformat()

    # Try exact match first
    result = get_unit_price(item_name, date)
    
    # If no exact match, try fuzzy matching with inventory
    if result.empty:
        # Get all inventory items
        inventory_df = pd.read_sql("SELECT item_name, unit_price FROM inventory", db_engine)
        
        # Try to find partial match (case-insensitive) in inventory
        item_lower = item_name.lower()
        match = next(
            (row for _, row in inventory_df.iterrows() 
             if item_lower in row["item_name"].lower() or row["item_name"].lower() in item_lower),
            None
        )
        
        if match is not None:
            return match["unit_price"] * quantity
        
        # If still no match, check paper_supplies as fallback
        match = next(
            (supply_item for supply_item in paper_supplies 
             if item_lower in supply_item["item_name"].lower() or supply_item["item_name"].lower() in item_lower),
            None
        )
        
        if match is not None:
            return match["unit_price"] * quantity
        
        # No match found - Return 0.0 to signal item not found (agent can check for this)
        print(f"WARNING: Item '{item_name}' not found in inventory or product catalog")
        return 0.0
    
    unit_price = result.at[0, "unit_price"]
    total_cost = unit_price * quantity

    return total_cost

# Tools for ordering/sales agent

# A tool that fulfills orders by updating the system database
@tool
def sell_inventory_item(item: str, quantity: int, price: float) -> str:
    """Sell an item from the stock inventory.

    Args:
        item (str): The item to sell.
        quantity (int): The quantity to sell.
        price (float): The price to sell the item for.

    Returns:
        str: A message indicating whether the item was sold successfully.
    """
    date = datetime.now().isoformat()
    
    trans_id = create_transaction(item, "sales", quantity, price, date)
    return f"{quantity} of {item} sold successfully."

# A tool that checks the timeline for delivery of an item from the supplier
@tool
def check_delivery_timeline(start_date: str, quantity: int) -> str:
    """Get for a delivery timeline date for a given start date and a quantity of item.

    Args:
        start_date (str): The starting date in ISO format (YYYY-MM-DD).
        quantity (int): The number of units in the order.

    Returns:
        str: An estimated delivery date in a string in ISO format (YYYY-MM-DD).
    """
    return get_supplier_delivery_date(start_date, quantity)

# Sales finalization Agent (e.g., processing orders, updating database)
# Finalize sales transactions, considering inventory levels and delivery timelines
class SalesFinalizationAgent(ToolCallingAgent):
    """Agent for finalizing sales."""

    def __init__(self, model: OpenAIServerModel):
        super().__init__(
            tools=[sell_inventory_item, check_delivery_timeline],
            model=model,
            name="sales_agent",
            description="Agent for finalizing sales. Process orders, update database.",
        )

def build_search_terms(raw: str):
    """
    Tokenize into clean terms:
    - Keep words, numbers, simple hyphenated tokens, and units like A4
    - Strip trailing punctuation
    - Remove empties
    """
    # Split on any whitespace
    rough = re.split(r"\s+", raw.strip())
    cleaned = []
    for tok in rough:
        tok = tok.strip()
        if not tok:
            continue
        # Remove surrounding punctuation while keeping inner hyphens/numbers
        tok = re.sub(r"^[^\w$%#@]+|[^\w%$#@]+$", "", tok)  # allow $, %, #, @ in case
        if tok:
            cleaned.append(tok)
    return cleaned