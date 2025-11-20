import re
import json
from typing import Dict, Any
from smolagents import ToolCallingAgent, OpenAIServerModel
from lib.tools import check_delivery_timeline, get_discount_info, get_inventory_level, get_item_price, reorder_inventory_item, sell_inventory_item

# Inventory management Agent (e.g., checking stock, assessing reorder needs)
# Answer inventory queries accurately, including deciding when to reorder supplies
class InventoryAgent(ToolCallingAgent):
    """Agent for managing inventory."""

    def __init__(self, model: OpenAIServerModel):
        super().__init__(
            tools=[get_inventory_level, reorder_inventory_item],
            model=model,
            name="inventory_agent",
            description="Agent for managing inventory. Check stock levels, reorder stock levels, and sell items.",
        )

# Quoting Agent (e.g., generating prices, considering discounts)
# Generate quotes efficiently, applying bulk discounts strategically to encourage sales
class QuoteManagementAgent(ToolCallingAgent):
    """Agent for managing quotes."""

    def __init__(self, model: OpenAIServerModel):
        super().__init__(
            tools=[get_discount_info, get_item_price],
            model=model,
            name="quote_management",
            description="Agent for managing and generating quotes for customers. Generate prices, considering discounts.",
        )

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

class Orchestrator(ToolCallingAgent):
    """Orchestrator agent for managing the Munder Difflin paper company."""

    def __init__(self, model: OpenAIServerModel):
        super().__init__(
            tools=[],
            model=model,
            name="orchestrator",
            description="Orchestrator agent for managing the Munder Difflin paper company. Handles customer requests and delegates to other agents.",
        )
        self.inventory = InventoryAgent(model)
        self.quote_management = QuoteManagementAgent(model)
        self.sales = SalesFinalizationAgent(model)

    def extract_order(self, request: str) -> Dict[str, Any]:
        """
        Parses a customer request string to extract order items and date.
        Handles both bullet-point format and comma-separated inline format.
        
        Args:
            request: Full request string with items and date
            
        Returns:
            dict: {
                'order': List of dicts with 'quantity', 'name', and 'type' for each item,
                'request_date': ISO formatted date string (YYYY-MM-DD),
            }
        """
        # Extract date using regex
        date_match = re.search(r"\(Date of request:\s*(\d{4}-\d{2}-\d{2})\)", request)
        request_date_str = date_match.group(1) if date_match else ""
        
        # Get the request text before the date
        request_text = request.split("(Date of request:")[0] if "(Date of request:" in request else request
        
        # Extract items, each match goes up until "\n"
        units = r"(?:sheets|packets|reams|table napkins|poster boards|cards|rolls)"
        item_pattern = fr"- (\d+) {units} of (.+?)(?:\n|$)"
        
        matches = re.findall(item_pattern, request_text)

        order_result = []

        for quantity, description in matches:
            item_type = "paper" if "paper" in description.lower() or "cardstock" in description.lower() else "product"

            item_order = {         
                "quantity" : int(quantity),
                "name" : description.strip(),
                "type" : item_type
            }

            order_result.append(item_order)

        return {
            "order": order_result,
            "request_date": request_date_str,
        }

    def process_order_details(self, request_with_date: str) -> str:
        """
        Extract order details from a customer's order request's response.
        
        Args:
            request_with_date: The customer's request with requested date.
            
        Returns:
            String with order details with requested item, quantity, total price,
            discount info, estimated delivery date, etc.
        """

        # Step 1: Extract order details - process one quote order request
        order_details = self.extract_order(request_with_date)
        order = order_details["order"]
        request_date = order_details["request_date"]

        if not order:
            inventory_response = self.inventory.run(
                    f"""
                    We have an order of several items listed in the request: {request_with_date}.
                    First, parse the request and identify each item name and quantity to be ordered.
                    For each item, do the following steps:
                        - Check to verify we have enough quantity of the requested item in inventory using get_inventory_level.
                        - If get_inventory_level indicates that the item does not exist, add it to a list of missing items in your response.
                        - Calculate if we have enough quantity of the item to fulfill this order.
                        - If not, place and order to restock using reorder_inventory_item to update the quantity for the item in the database.
                        Do NOT call reorder_inventory_item for an item that is missing - only call it if the item exists but there is not enough quantity.
   
                    At the end of your response, list any items that do not exist in the database as:
                    MISSING ITEMS: item1, item2, item3
                    """
                )

        # Extract paper or product by looking for known shapes first
        for item in order:

            product = item["name"]

            product_words = product.strip().split()  # Split product into words
            # if not any(any(word.lower() in d.get("item_name").lower() for word in product_words) for d in paper_supplies):           
            if not any(
                word.lower() in (d.get("item_name", "").lower())
                for word in product_words
                for d in paper_supplies
            ):
                return f"I'm sorry, I couldn't identify which item you want. We offer: {', '.join(item['item_name'] for item in paper_supplies)}. Please specify one of these items."

            # Step 2: Check each item's availability
            
            quantity = item["quantity"]
            product_type = item["type"]
            
            inventory_response = ''
            try:    
                inventory_response = self.inventory.run(
                    f"""
                    We have an order for type {product_type} {quantity} of {product}.
                    Check to verify we have enough quantity of the requested item in inventory using get_inventory_level.
                    Calculate if we have enough quantity of the item to fulfill this order.
                    If not, place and order to restock using reorder_inventory_item to update the quantity for the item in the database.
                    Do NOT call reorder_inventory_item for an item that is missing - only call it if the item exists but there is not enough quantity.

                    At the end of your response, list any items that do not exist in the database as:
                    MISSING ITEMS: item1, item2, item3
                    """
                )
            except Exception as e:
                print("Error during Inventory Agent run:", e)
        
            # Check if inventory has enough - look for negative signals
            inventory_issue = any(term in inventory_response.lower() for term in 
                                ["not enough", "insufficient", "low", "out of", "don't have"])
            
            # Add this to putput and test_results.csv if order cannot be fulfilled
            if inventory_issue:
                return f"I'm sorry, we don't have enough in stock to fulfill your order for {quantity} of {product} at this time."

        # Parse missing items from response
        if "MISSING ITEMS:" in inventory_response:
            missing_part = inventory_response.split("MISSING ITEMS:")[1]
            missing_items = [item.strip() for item in missing_part.split(",")]
            missing_items = [item for item in missing_items if item]  # Remove empty strings
            
            if missing_items:
                return f"I'm sorry, the following items are not available in our catalog: {', '.join(missing_items)}. Please check our available products."
                
        # Step 3: Quoting
        # Now that we can continue and inventory manager has determined if we have enough quantity of the requested items,
        # Call the Quote agent to generate a price and if bulk discount or not using get_all_quotes tool and inputting
        # the list of words in the request field by callling split(" ")
        details = "\n".join([
            f"- {item['quantity']} {'sheets' if item['type'] == 'paper' else item['type']} of Item: {item['name']}"
            for item in order
        ])

        request = request_with_date.split("(Date of request:")[0]
        # terms = build_search_terms(req)
        # terms_literal = json.dumps(terms[:-3], ensure_ascii=False)
        
        instruction = f"""
        Calculate a price quote for this order using your available tools.

        Do NOT perform any of the following steps for a missing item from the order that does not exist.
        MISSING ITEMS: {', '.join(missing_items) if 'missing_items' in locals() else 'None'}

        ORDER DETAILS:
        {details if details else request}

        TASK:
        1. First, use get_discount_info with search_terms="{request}" to check if a bulk discount applies
        2. Then, for each line item above, use get_item_price to get the price (call it once per item)
        3. Sum all the item prices to get the subtotal
        4. If bulk discount applies, reduce the subtotal by 10%
        5. Return your final answer as a JSON string in this exact format:
        {{"final_total_price": <number>, "bulk_discount_applied": <true or false>}}

        Make sure to actually call both tools and calculate the correct total.
        """

        # Step 1: Get boolean if bulk discount can be applied or not (if None, no discount)
        quote_response = ''
        try:
            quote_response = self.quote_management.run(instruction)      
            # print("Quote Agent response:", quote_response)
        except Exception as e:
            print("Error during Quote Agent run:", e)
            return f"I apologize, but we encountered an issue processing your quote request. Please try again or contact customer service."
        
        # Parse the JSON response from the agent
        try:
            # Check if it's already a dict
            if isinstance(quote_response, dict):
                quote_data = quote_response
                total_price = quote_data.get("final_total_price", 0)
                bulk = quote_data.get("bulk_discount_applied", False)
            elif isinstance(quote_response, str):
                # Try to parse as JSON first
                quote_data = json.loads(quote_response)
                total_price = quote_data.get("final_total_price", 0)
                bulk = quote_data.get("bulk_discount_applied", False)
            else:
                raise TypeError(f"Unexpected response type: {type(quote_response)}")
        except (json.JSONDecodeError, TypeError):
            print("ERROR: Could not parse quote response")
            return "I apologize, but we encountered an issue processing your quote. Please try again."

        # Step 4: Finalize sale using parsed order details from step 1 and appended total price and discount
        sales_order_response = self.sales.run(
            f"""
            Finalize a sales transaction with the following details:
            {details if details else request}

            Do NOT perform any of the following steps for a missing item from the order that does not exist.
            MISSING ITEMS: {', '.join(missing_items) if 'missing_items' in locals() else 'None'}

            The final price will be ${total_price} for the order and there will be {"no" if bulk else "a"} bulk discount.

            Use sell_inventory_item to add the transcation to the database. Use check_delivery_timeline to determine
            when the delivery date will be expected and if it can arrive by the customer's requested delivery date.
            
            Return the estimated delivery date, and if a bulk discount was applied, along with the total sales order in dollars in your response.
            Format your response in a message that summarizes the order, total price, if a discount was applied, and personalize it to the customer's order.
            """
        )

        return sales_order_response