# Workflow and Diagram Description


# Input to Orchestrator 
First, the request is processed using extract_order to be fed into the Orchestrator. It tries to parse the items in the request text if it is in bullet form. The output of that is a list of dictionaries, one for each item to be ordered in the request. The request by date is also inputted as a string to the orchestrator, along with the original reqest text (later used for the quote agent as input).

The database is also created using the paper_supplies dictionary.

# Inventory Agent

If the order dictionary was not successfully parsed, the inventory agent is then prompted with the request text and ask it to parse it to find the items and respective quantities to be ordered.

Otherwise, the Orchestrator then prompts the inventory agent for each item that includes the item quantity, type and name from the order dictionary. The inventory agent calls the get_inventory_level tool for each item prompt, and its response is primarily used if any of the requested items are out of stock. If they are, it calls the reorder_inventory_item tool. get_inventory_level also checks if the item exists in the database. These tools create transcations in the database to check item levels and reorders them using 'stock_orders' if they are out of stock.

The agent is also prompted to include any missing items that do not exist in the database (different than items that exist with the 'item_name' field in the inventory table but are low or have 0 for their quantity) in its response. The agent is instructed to not call reorder_inventory_item if the item is missing. This will then be used later so the missing items are not included in the quoting or sales finalization.

# Quote Management Agent

The Orchestrator then prompts the Quote management agent using text from the original request by parsing its text before the request by date, and uses several terms (but not too many which would cause the database calls to return no results when comparing the quotes and quote_requests tables for LIKE calls) to see if a bulk discount is appropriate or not and also to get the total price using the get_discount_info tool. It then is instructed to call the get_unit_price tool for each item. It returns a total price by calculating it from each item in the order and also looks for similar past quotes to see if a bulk discount should be applied. It is instructed to not call either tool for missing items that were found by the inventory agent.

# Sales Agent

The sales agent then creates a transcation to sell each item that was quoted. It uses the sell_inventory_item tool to create a sales transcation for each item with the given quantity and price. It then calls the check_delivery_timeline to check if the sales order can be finalized and have the items delivered by the requested delivery date and includes that in its final response.