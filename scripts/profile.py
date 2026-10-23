import duckdb
D = "data/torob-dataset"
c = duckdb.connect()
for t in ["shops", "products", "offers"]:
    c.execute(f"create view {t} as select * from read_csv_auto('{D}/{t}.csv', header=true, all_varchar=true, max_line_size=20000000)")
def q(s):
    print(">>", s.strip()[:120]); print(c.sql(s).fetchall()[:30] if False else c.sql(s)); 
for t in ["shops", "products", "offers"]:
    q(f"select count(*) from {t}")
q("""select count(*) total, count(*) filter (where lat<>'null' and lat is not null) n_lat,
 count(*) filter (where weekly_hours<>'null' and weekly_hours is not null) n_hours,
 count(*) filter (where payment_options<>'[]' and payment_options<>'null') n_pay,
 count(*) filter (where supports_fast_delivery<>'null') n_fast,
 count(*) filter (where instagram<>'null') n_ig, count(*) filter (where website_url<>'null') n_web,
 count(*) filter (where contacts<>'[]' and contacts<>'null') contacts from shops""")
q("select payment_options, count(*) n from shops group by 1 order by n desc limit 15")
q("select supports_fast_delivery, count(*) from shops group by 1")
q("select location_label, count(*) n from shops group by 1 order by n desc limit 25")
q("select min(lat::double),max(lat::double),min(lon::double),max(lon::double) from shops where lat<>'null'")
q("select category_name, count(*) n from products group by 1 order by n desc limit 30")
q("select count(distinct category_name), count(distinct brand_name) from products")
q("""select count(*) n, count(distinct product_id) prods, count(distinct shop_id) shops,
 count(*) filter (where warranty<>'null') n_warr, count(*) filter (where description is not null and description<>'') n_desc,
 min(last_price_changed_at), max(last_price_changed_at),
 quantile_cont(try_cast(price_toman as double), [0.01,0.5,0.99]) qs, count(*) filter (where try_cast(price_toman as double) is null or price_toman='0') badprice
 from offers""")
q("select warranty, count(*) n from offers group by 1 order by n desc limit 10")
q("select product_id, count(*) n from offers group by 1 order by n desc limit 5")
q("select n, count(*) from (select product_id, count(*) n from offers group by 1) group by 1 order by 1 limit 12")
q("select count(*) from shops s where not exists (select 1 from offers o where o.shop_id=s.shop_id)")
q("select weekly_hours from shops where weekly_hours<>'null' limit 1")
q("select contacts from shops where contacts like '%whats%' or contacts like '%bale%' limit 3")
q("select address, location_label from shops where address like '%پاساژ%' limit 5")
q("select count(*) filter (where address like '%پاساژ%' or address like '%مرکز خرید%' or address like '%مجتمع%') mall, count(*) filter (where address like '%طبقه%') floor, count(*) filter (where address like '%واحد%' or address like '%پلاک%') unit from shops")
