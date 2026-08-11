# Benchmark results

Two runs of `benchmarks/run.py`, at 25 and at 100 tenants, holding the data per
tenant constant (3,000 articles and 9,000 comments each) so the second run
isolates what changes as tenants are added.

**Both runs are against the current code.** The library changed as a result of
this benchmark; the measurements that motivated those changes are kept at the
bottom under [History](#history-what-this-benchmark-changed) and are labelled
as such. Nothing above that heading is a "before" number.

Python 3.13.13, Django 6.1, django-tenants 3.14.0, PostgreSQL 16.14 in Docker,
Apple Silicon, single connection, no concurrency. 300 timed iterations per
scenario after 30 warm-up calls; medians. Reproduce with:

```bash
make bench-db
uv run --group bench python -m benchmarks.run --tenants 25  --articles 3000 --iterations 300 --warmup 30
uv run --group bench python -m benchmarks.run --tenants 100 --articles 3000 --iterations 300 --warmup 30
```

Absolute milliseconds are specific to this machine, and run-to-run variance on
the sub-millisecond scenarios is roughly ±20% -- differences smaller than that
are not differences. The ratios, and anything that changes with scale, are the
result.

## Median ms per operation

`shared` is this library, `manual` the same shape hand-written without it,
`tenants` django-tenants on its defaults, `tenants+limit` django-tenants with
`TENANT_LIMIT_SET_CALLS = True`.

| Scenario            | 25 shared | 25 manual | 25 tenants | 25 tenants+limit | 100 shared | 100 manual | 100 tenants | 100 tenants+limit |
| ------------------- | --------- | --------- | ---------- | ---------------- | ---------- | ---------- | ----------- | ----------------- |
| point_lookup        | 0.439     | 0.513     | 0.521      | 0.366            | 0.408      | 0.399      | 0.562       | 0.362             |
| list_recent         | 0.924     | 0.674     | 0.692      | 0.529            | 0.614      | 0.592      | 0.689       | 0.507             |
| filter_count        | 0.805     | 0.798     | 0.591      | 0.400            | 0.484      | 0.666      | 0.583       | 0.448             |
| filter_page         | 0.960     | 0.780     | 0.744      | 0.567            | 0.888      | 1.339      | 0.753       | 0.602             |
| aggregate           | 0.769     | 0.704     | 0.676      | 0.503            | 0.724      | 0.633      | 0.673       | 0.585             |
| join_plain          | 1.345     | 0.959     | 0.943      | 0.837            | 1.203      | 1.265      | 0.998       | 0.816             |
| join_safe           | 1.602     | --        | --         | --               | 1.568      | --         | --          | --                |
| agg_join_plain      | 5.771     | 6.029     | 1.620      | 1.610            | 11.997     | 11.774     | 1.669       | 1.543             |
| agg_join_safe       | 2.052     | --        | --         | --               | 2.351      | --         | --          | --                |
| join_filter         | 2.125     | 0.764     | 0.871      | 0.611            | 2.684      | 0.844      | 0.966       | 0.825             |
| insert              | 0.522     | 0.433     | 0.519      | 0.361            | 0.481      | 0.381      | 0.586       | 0.469             |
| bulk_insert         | 4.145     | 4.769     | 3.680      | 3.580            | 4.624      | 5.080      | 3.594       | 3.269             |
| update              | 0.457     | 0.486     | 0.517      | 0.384            | 0.800      | 0.505      | 0.566       | 0.480             |
| tenant_switch       | 0.418     | 0.449     | 0.573      | 0.559            | 0.497      | 0.474      | 0.553       | 0.603             |
| cross_tenant_report | 7.483     | 7.884     | 15.239     | 15.428           | 15.256     | 15.426     | 66.877      | 69.178            |

Queries per operation:

| Scenario            | shared | manual | tenants      | tenants+limit |
| ------------------- | ------ | ------ | ------------ | ------------- |
| everything above    | 1      | 1      | 2            | 1             |
| tenant_switch       | 1      | 1      | 2            | 2             |
| cross_tenant_report | 1      | 1      | 2 per tenant | 2 per tenant  |

Setup and storage, 100 tenants:

| Approach      | Migrate (s) | Per tenant (s) | Seed (s) | Tables  | Indexes  | Total    |
| ------------- | ----------- | -------------- | -------- | ------- | -------- | -------- |
| shared        | 0.60        | 0.001          | 45.71    | 98.3 MB | 127.6 MB | 225.9 MB |
| manual        | 0.49        | 0.001          | 32.45    | 91.5 MB | 113.0 MB | 204.5 MB |
| tenants       | 0.61        | 0.088          | 28.15    | 87.5 MB | 68.0 MB  | 155.5 MB |
| tenants+limit | 0.85        | 0.064          | 28.49    | 87.5 MB | 68.0 MB  | 155.5 MB |

## What the numbers say

**A tenant column is not what costs.** On ordinary scoped reads -- point lookup,
list page, count, aggregate, plain join -- `shared` tracks `manual` closely, and
both land within roughly 20-40% of a tuned django-tenants. Writes are level
too: one query each, and `bulk_insert` is faster than the no-library control at
both scales. The overhead of row-level tenancy is the extra predicate and a
taller index, not a different shape of query.

**Anything spanning tenants favours the shared schema, increasingly so.**
`cross_tenant_report` costs `shared` one `GROUP BY` at any tenant count:
7.5 ms at 25 tenants, 15.3 ms at 100. django-tenants pays one query per schema
-- 15.2 ms, then 66.9 ms. The gap is 2x at 25 tenants and 4.4x at 100, and it
keeps going.

**Binding a tenant is free here and is not there.** `tenant_switch` costs
`shared` a contextvar assignment; django-tenants issues `SET search_path`, a
round trip, even with `TENANT_LIMIT_SET_CALLS` on. On its defaults it issues
that `SET` before *every* statement, which is the entire difference between the
`tenants` and `tenants+limit` columns -- roughly 0.2 ms and one round trip per
query. Comparing against the default alone would be measuring an untuned
configuration.

**Creating a tenant costs ~90x more under schema-per-tenant** (0.088 s vs
0.001 s), and that is only the creation. Every future migration runs once per
schema.

**Storage is ~1.45x** (225.9 MB against 155.5 MB at 100 tenants), nearly all of
it in the indexes: 127.6 MB against 68.0 MB. That is the tenant-leading
composite indexes existing at all -- schema-per-tenant needs no tenant column to
index, because each copy of a table holds one tenant's rows.

## The organization-safe relation

`OrganizationSafeForeignKey` is the library's headline safety feature, and it
is also the single biggest performance variable in the suite. It cuts both
ways, and **which way depends on the shape of the query and on how many tenants
you have.**

### On unbounded joins it wins, and wins harder as you grow

| Scenario         | 25 tenants           | 100 tenants           |
| ---------------- | -------------------- | --------------------- |
| `agg_join_safe`  | 2.052                | 2.351                 |
| `agg_join_plain` | 5.771                | 11.997                |
| advantage        | **2.8x**             | **5.1x**              |

The organization equality lets PostgreSQL infer `article.organization_id = 51`
by transitivity and touch only that tenant's articles. A plain foreign key has
no such predicate and scans every tenant's:

```
--- plain_article
Hash Join  ->  Seq Scan on shared_app_article  (rows=300000)   <- all 100 tenants
--- article (safe)
Hash Join  ->  Index Scan using …organization_id  (rows=3000)  <- one tenant
```

The plain join's cost is proportional to `tenants x rows_per_tenant`; the safe
join's is proportional to `rows_per_tenant`. This is a real performance
feature, not only a safety one, and it is the strongest argument for the
relation.

### On paged joins it loses, and loses harder as you grow

| Scenario                        | 25 tenants | 100 tenants |
| ------------------------------- | ---------- | ----------- |
| `join_safe`, joined directly    | 1.333      | 3.690       |
| `join_plain`                    | 1.345      | 1.203       |
| `join_safe`, as the library now runs it | 1.602 | 1.568   |

Joined directly, the two are level at 25 tenants and the safe relation is 3.1x
slower at 100 -- a planner estimate that degrades as tenants are added. The
bottom row is what `AUTO_DEFER_SAFE_JOINS` produces: flat across scale, at the
price of being slightly slower than the join where the join was still fine. The
two-column `ON` clause makes PostgreSQL multiply the key selectivity by the
organization selectivity as though they were independent -- they are not, the
organization match is implied by the key match -- and the organization
selectivity is roughly `1/tenants`:

| Tenants | Estimated join rows | Actual | Plan chosen                    |
| ------- | ------------------- | ------ | ------------------------------ |
| 25      | 366                 | 9,000  | nested loop, exits at row 50   |
| 100     | 100                 | 9,000  | hash join + top-N sort, no exit|

Once the estimate is low enough, a hash join over the whole tenant plus a sort
looks cheaper than an ordered walk, so PostgreSQL stops using the
`(organization, pk)` index that would have let it stop at the 50th row. **The
underestimate grows linearly with tenant count**, so this gets worse, not
better, at scale.

Removing Django's redundant single-column index on the organization column
(now the library's default) is what buys the parity at 25 tenants; it does not
survive to 100. What does survive is not joining in the first place. Measured
at 100 tenants, where the problem is worst:

| Approach for a paged join        | 100 tenants |
| -------------------------------- | ----------- |
| `select_related` (safe)          | 3.768       |
| `prefetch_related` (safe)        | 1.609       |
| `select_related` (plain FK)      | 1.047       |
| `LIMIT` in a subquery, then join | 0.373       |

Both mitigations are plan-independent: the same two measured 1.594 ms and
0.389 ms back at 25 tenants, so unlike `select_related` they do not degrade as
tenants are added.

**This is now automatic.** `SHARED_SCHEMA_ORGANIZATIONS['AUTO_DEFER_SAFE_JOINS']`
(default on) makes a *paged* `select_related` over a safe relation collect its
page in a subquery before joining --
`WHERE pk IN (SELECT pk … ORDER BY … LIMIT n)` -- so the planner is handed a set
of rows rather than an estimate. Measured at 100 tenants, through the benchmark:

| Scenario         | joined | deferred | queries |
| ---------------- | ------ | -------- | ------- |
| `join_safe`      | 3.690  | 1.568    | 1       |
| `join_plain`     | 1.231  | 1.231    | 1       |
| `agg_join_safe`  | 1.996  | 1.996    | 1       |
| `point_lookup`   | 0.412  | 0.412    | 1       |

Only the paged safe-relation join changes; plain foreign keys, unpaged reads
and aggregates take the ordinary path, and the query count does not change, so
no existing test that counts queries has to be rewritten. On MySQL, which sets
`allow_sliced_subqueries_with_in = False`, it falls back to fetching the related
rows in a second query (1.708 ms) -- a round trip more, equally free of the
estimate.

Two things it deliberately does not cover. At small tenant counts the join is
still the better plan -- at 25 tenants `select_related` was 1.333 ms against
about 1.59 for the deferred form -- so this trades roughly 0.25 ms there for
2 ms at 100 tenants and more beyond. And a *filter* across a safe relation
(`join_filter`, 2.114 ms) has to join, because the predicate is on the far
side; only the fetch can be deferred, not the filter.

`prefetch_related` costs two queries and stays organization-checked (verified:
every row's article belongs to the bound organization). Applying the `LIMIT` in
a subquery before the join is the fastest of all, because it hands the planner
50 rows instead of an estimate -- but Django will not emit that from
`select_related`, so it needs library support.

**Practical guidance today:** use the safe relation freely for aggregates,
counts and filters; for a paged list that needs the related row, reach for
`prefetch_related` rather than `select_related`.

Two things that do *not* work, tested: adding an explicit constant
`article.organization_id = 51` to the `ON` clause (PostgreSQL folds it into the
same equivalence class and produces an identical plan), and adding more indexes
without removing the redundant one (the planner keeps choosing the narrow
index).

## History: what this benchmark changed

Three costs it surfaced were the library's own, not properties of shared-schema
tenancy -- `manual` does the same database work without them. All three are
fixed. The numbers in this section are **before** measurements, at 25 tenants
x 3,000 articles.

### 1. One `SELECT` per instantiation, another per `save()` (fixed)

`insert` cost 3 queries against `manual`'s 1, and `bulk_insert` of 100 rows
cost **101 queries** -- 42.2 ms against 4.9 ms.

* `organization` was declared `default=get_default_organization`, a callable
  that queries. Django evaluates field defaults in `Model.__init__` for
  anything not passed as a keyword, so every `Article(...)` without an explicit
  `organization=` ran a `SELECT`. Rows loaded from the database were
  unaffected -- `from_db` passes values positionally and skips defaults.
* `save()` began `if not hasattr(self, 'organization')`. Reading the relation
  goes through the forward descriptor, which fetches the row whenever the id is
  set but no instance is cached.

Now: the default is gone and `save()` resolves the organization itself, testing
`organization_id` rather than the relation. `insert` 1.211 -> 0.522 ms,
`bulk_insert` 42.223 -> 4.145 ms, both at one query.

This also fixed a correctness bug. The default was applied at *construction*,
so a project that actually had an organization named `DEFAULT_ORGANIZATION_SLUG`
stamped every model built without an explicit `organization=` with that one and
saved it there, ignoring the organization bound to the request. The bound
organization now wins; the default is only a fallback.

### 2. A redundant index on the organization column (fixed)

Django's automatic single-column index on the foreign key is a prefix of the
`(organization, pk)` composite, so it can answer nothing the composite cannot
-- but the planner picked it and then sorted. Dropping it, measured directly:

| Workload             | before | after  | change    |
| -------------------- | ------ | ------ | --------- |
| `join_safe` LIMIT 50 | 3.990  | 1.082  | **0.27x** |
| `join_plain` LIMIT50 | 1.301  | 1.193  | 0.92x     |
| point_lookup         | 0.511  | 0.475  | 0.93x     |
| filter_page          | 0.661  | 0.672  | 1.02x     |
| index bytes          | 38.1MB | 35.9MB | 0.94x     |

Now: `organization` carries `db_index=False`, and every scoped model is given
an `(organization, pk)` index automatically (`add_organization_index` in
`organizations/mixins.py`). As the section above records, this fixes the paged
join at 25 tenants but is outgrown by the estimate problem by 100.

### 3. A `varchar(255)` tenant key (fixed)

Every scoped index repeated the organization slug. Measured directly on 1M
rows with the same two composite indexes, a `varchar(255)` key against a
`bigint` one cost 67 MB vs 58 MB of indexes and 65 MB vs 57 MB of table --
about 16%. `Organization` now has an integer primary key with the slug as a
unique field, and `manual` was moved to the same shape so the control is not
carrying a wider key than the library it controls for. Total shared storage at
100 tenants went from 259.3 MB to 225.9 MB.

## Closed and shipped

Everything the benchmark surfaced has now been acted on. Beyond the mixin and
queryset changes recorded above:

* **Tenant resolution caching** -- `CACHE_ORGANIZATION_RETRIEVAL`, off by
  default, removes the one query per request that maps a site to its
  organization. Invalidated on writes to either model and bounded by a timeout.
* **A session write on every request** -- `ADD_ORGANIZATION_TO_SESSION` assigned
  the slug unconditionally, marking the session modified and making
  `SessionMiddleware` save it. Now written only when it changes.
* **Uncached permission checks** -- a `has_perm()` the user did *not* have fell
  through to `OrganizationSpecificTablesBackend`, which cached nothing: 4
  queries, on every call, with the relationship fetched twice. Now 4 once and 0
  thereafter.
* **Admin changelists** -- `OrganizationMembership.__str__` reads the user, the
  organization and every group, and nothing prefetched them: 3 queries per row.
  Now 2 queries for the page.

## Still open

* **Filters across a safe relation under a `LIMIT`.** `AUTO_DEFER_SAFE_JOINS`
  handles the fetch; a predicate on the far side still needs the join and still
  meets the bad estimate (`join_filter`, 2.114 ms against `manual`'s 0.844).
  Every formulation the ORM can express -- `pk__in=Subquery(...)`, a semi-join
  on the concrete column, a correlated `Exists()` -- is normalised by
  PostgreSQL into a byte-identical plan (same 3520.52 cost, estimating 114 rows
  where 3,000 arrive), so this cannot be routed around by rewriting the query.

  What does change the plan is an optimisation fence (`OFFSET 0` inside the
  `EXISTS`), which stops the subquery being pulled up and gives the ordered
  walk over `(organization, pk)` with an early exit. It is not safe as a
  default, because it inverts with the selectivity of the filter -- the walk
  has to scan the whole organization before it can conclude that fewer than a
  page of rows match:

  | Filter matches      | join  | fenced |
  | ------------------- | ----- | ------ |
  | 1 in 3 articles     | 1.854 | 0.382  |
  | ~1 in 100           | 0.508 | 0.306  |
  | ~1 in 1000          | 0.507 | 6.345  |
  | nothing             | 0.668 | 6.579  |

  PostgreSQL's hash join is hedging against that last row, and it is right to:
  its join-cardinality estimate is wrong, but its risk assessment is not.

  Shipped as ``filter_related_without_join()`` -- opt in per query, never a
  default. Through the ORM on the benchmark data it takes `join_filter` from
  2.463 ms to 1.274 ms.
* **A derived table in `FROM`.** The fastest form measured -- 0.373 ms, against
  1.568 ms for the subquery the ORM can express -- is
  `SELECT … FROM (SELECT … LIMIT n) JOIN …`, and Django has no way to select
  *from* a subquery. It would need raw SQL, and it is the only shape here that
  genuinely does.
* **Document the join-shape trade-off** in the usage docs. The library
  currently presents `OrganizationSafeForeignKey` as a safety feature only,
  which undersells it on aggregates and oversells it on paged lists.
* **A system check** warning when a scoped model declares indexes that do not
  lead with `organization`. The mixin now guarantees `(organization, pk)`, but
  a model that adds `(status, published_at)` and expects it to be used is still
  on its own.
* ~~**Composite indexes for the safe relation's concrete column.**~~ Measured
  and rejected. Adding `(organization, <name>_fk)` alongside Django's
  single-column index makes most things *slower* and the table bigger --
  the narrower index is the better one for reverse lookups, and offering the
  planner both leads it to the wrong choice:

  | Workload                      | with composite | single only |
  | ----------------------------- | -------------- | ----------- |
  | reverse relation              | 2.618          | 2.053       |
  | filter by relation            | 0.601          | 0.405       |
  | aggregate across the relation | 1.388          | 1.693       |
  | paged join                    | 1.804          | 1.655       |
  | comment table index           | 23.0 MB        | 18.8 MB     |

  Only the aggregate benefits. Dropping the single-column index instead is
  worse still -- unscoped reads through the relation went from 0.379 ms to
  19.4 ms. The current layout is the right one.

## Choosing between the approaches

Neither approach dominates:

* Per-tenant reads favour a tuned django-tenants by roughly 20-40%.
* Aggregates and filters across an organization-safe relation favour this
  library, by a margin that grows with tenant count.
* Paged joins across one favour django-tenants, by a margin that also grows
  with tenant count, unless the join is avoided (see above).
* Anything spanning tenants favours the shared schema, growing linearly.
* Tenant creation, migration and storage favour the shared schema by a large
  constant factor.
