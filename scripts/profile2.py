import duckdb
D = "data/torob-dataset"
c = duckdb.connect()
for t in ["shops", "products", "offers"]:
    c.execute(f"create view {t} as select * from read_csv_auto('{D}/{t}.csv', header=true, all_varchar=true, max_line_size=20000000)")
def q(s): print(">>", s[:100]); print(c.sql(s))
q("select json_extract_string(x,'$.channel') ch, count(*) from shops, unnest(cast(json(contacts) as json[])) t(x) group by 1")
q("select json_extract_string(x,'$.provider_name') p, json_extract_string(x,'$.channel') ch, count(*) n from shops, unnest(cast(json(payment_options) as json[])) t(x) group by 1,2 order by n desc")
q("select json_extract_string(weekly_hours,'$.sat.status') s, count(*) from shops group by 1")
q("select count(*) filter (where price_toman='null' or price_toman is null) nullp, count(*) filter (where price_toman='0') zero, count(*) filter (where last_price_changed_at='null') nodate from offers")
q("select substr(last_price_changed_at,1,7) m, count(*) n from offers group by 1 order by 1 desc limit 14")
q("select count(*) filter (where image_urls<>'[]' and image_urls<>'null') img, count(*) filter (where specs<>'[]' and specs<>'null') specs, count(*) filter (where brand_name<>'null') brand from products")
q("select count(*) filter (where image_urls<>'[]' and image_urls<>'null') from shops") if False else None
q("select persian_title, category_name from products using sample 12")
