# databases — Signature School Products

Code behind the Signature School Products catalog databases and Shopify prototype.
The spreadsheets themselves live in Gack's workspace (supplier spreadsheet = single
source of truth; the customer-facing product database is generated from it).

## Layout
- `suppliers/artcobell/` — scrapers for the Artcobell List Pricer (Feb 15, 2025):
  pilot (44 Shape Table Tops), expansion, and the complete-products build (100 rows).
- `suppliers/madebymarco/` — WooCommerce Store API scraper for madebymarco.net (100 rows).
- `suppliers/officestogo/` — scraper for officestogo.com (100 rows).
- `product-db/build_product_database.py` — builds the customer-facing product
  database (layer 2) from the master supplier spreadsheet: SSP SKUs, customer
  categories, room tags, grade levels, show-price / quote-only / publish flags, slugs.
- `shopify/` — Shopify test import of 12 sample products, the SSP metafield +
  Get-a-Quote prototype scripts, and the patched Horizon theme blocks
  (`theme/blocks_price.liquid`, `theme/blocks_buy-buttons.liquid`) that hide the
  price and swap Add to Cart for a Get a Quote button on quote-only products.
