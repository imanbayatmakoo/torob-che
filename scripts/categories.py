import duckdb, json
D = "data/torob-dataset"
c = duckdb.connect("data/work.duckdb")
c.execute(f"""create or replace table products as select * from read_csv_auto('{D}/products.csv', header=true, all_varchar=true, max_line_size=20000000)""")
c.execute(f"""create or replace table offers as select * from read_csv_auto('{D}/offers.csv', header=true, all_varchar=true, max_line_size=20000000)""")
c.execute(f"""create or replace table shops as select * from read_csv_auto('{D}/shops.csv', header=true, all_varchar=true, max_line_size=20000000)""")

c.execute("""
create or replace table prod_specs as
select p.product_id, p.category_name,
  json_extract_string(x,'$.key') k
from products p, unnest(cast(json(case when specs is null or specs in ('null','') then '[]' else specs end) as json[])) t(x)
""")

rows = c.sql("""
with pc as (
  select category_name cat, count(*) n_products,
    count(distinct nullif(brand_name,'null')) n_brands
  from products group by 1),
sp as (
  select category_name cat, count(distinct k) distinct_spec_keys,
    count(*)::double / count(distinct product_id) avg_specs_per_product,
    count(distinct product_id) n_with_specs
  from prod_specs group by 1),
of as (
  select p.category_name cat, count(*) n_offers, count(distinct o.shop_id) n_shops,
    quantile_cont(try_cast(o.price_toman as double),0.5) median_price,
    quantile_cont(try_cast(o.price_toman as double),0.1) p10,
    quantile_cont(try_cast(o.price_toman as double),0.9) p90,
    count(*) filter (where o.last_price_changed_at >= '2026-10-01') fresh_offers,
    count(*) filter (where o.warranty<>'null') warranty_offers
  from offers o join products p using(product_id) group by 1),
ms as (
  select cat, count(*) multi_seller_products from (
    select p.category_name cat, o.product_id from offers o join products p using(product_id)
    group by 1,2 having count(*)>=2) group by 1),
inst as (
  select p.category_name cat, count(distinct o.shop_id) installment_shops
  from offers o join products p using(product_id) join shops s on s.shop_id=o.shop_id
  where s.payment_options not in ('[]','null') group by 1)
select pc.cat, n_products, n_brands, coalesce(distinct_spec_keys,0) spec_keys,
  round(coalesce(avg_specs_per_product,0),1) avg_specs,
  round(100.0*coalesce(n_with_specs,0)/n_products) pct_specs,
  coalesce(n_offers,0) n_offers, coalesce(n_shops,0) n_shops,
  coalesce(multi_seller_products,0) multi_seller,
  coalesce(installment_shops,0) inst_shops,
  median_price, p10, p90,
  round(100.0*coalesce(fresh_offers,0)/nullif(n_offers,0)) pct_fresh,
  round(100.0*coalesce(warranty_offers,0)/nullif(n_offers,0)) pct_warranty
from pc left join sp using(cat) left join of using(cat) left join ms using(cat) left join inst using(cat)
order by n_products desc
""").fetchall()
cols = ["cat","n_products","n_brands","spec_keys","avg_specs","pct_specs","n_offers","n_shops","multi_seller","inst_shops","median_price","p10","p90","pct_fresh","pct_warranty"]
data = [dict(zip(cols, r)) for r in rows]
json.dump(data, open("data/categories.json","w"), ensure_ascii=False)
print(len(data), "categories")
