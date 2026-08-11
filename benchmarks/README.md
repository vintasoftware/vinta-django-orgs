# Multi-tenancy benchmark

Compares the query performance of this library against the other ways a Django
project can be made multi-tenant, on the same hardware, the same PostgreSQL,
the same Django version and the same data.

Four approaches, each in its own process and its own database:

| Key               | What it is                                                                                     |
| ----------------- | ---------------------------------------------------------------------------------------------- |
| `shared`          | This library. One set of tables, an `organization` column, scoping through the managers.        |
| `manual`          | The same shape written by hand: a `tenant_id` column filtered explicitly at every call site.    |
| `tenants`         | [django-tenants](https://github.com/django-tenants/django-tenants), one PostgreSQL schema per tenant, default settings. |
| `tenants_limited` | django-tenants with `TENANT_LIMIT_SET_CALLS = True`.                                            |

`manual` is the control. It is the same database work as `shared` with none of
the library on top, so the gap between the two is what the library costs, and
the gap between `manual` and `tenants` is what row-level tenancy costs
regardless of library. Without it, every difference looks like it belongs to
whichever library is being blamed.

`tenants_limited` is there because django-tenants issues `SET search_path` on
every cursor by default -- one extra round trip per query. That is what a
project gets out of the box, but it is not the best the approach can do, and
comparing only against the default would be a straw man.

## Running it

```bash
make bench-db     # PostgreSQL 16 in Docker on port 55432
make bench        # all four approaches, default dataset
make bench-db-stop
```

Or directly, for other shapes of dataset:

```bash
uv run --group bench python -m benchmarks.run --tenants 100 --articles 3000 --iterations 500
uv run --group bench python -m benchmarks.run --approaches shared,tenants --only point_lookup,join_safe
uv run --group bench python -m benchmarks.run --out report.md
```

Point it at a different server with `BENCH_PG_HOST`, `BENCH_PG_PORT`,
`BENCH_PG_USER`, `BENCH_PG_PASSWORD`.

Each run drops and recreates its databases so migration and tenant-creation
timings mean something; `--keep-db` and `--reuse-data` skip that when you are
iterating on a scenario. Full results land in `benchmarks/results/` as JSON and
the Markdown report goes to stdout.

## What is measured

The same domain -- authors, articles, comments -- modelled three times
(`benchmarks/apps/`). Scenarios are written once against an adapter API
(`benchmarks/adapters.py`) so no approach can quietly get an easier query.

Reads: point lookup by primary key, a list page, a filtered count, filter +
sort + paginate, an aggregate, three flavours of join, and a filter across a
join. Writes: single insert, `bulk_create` of 100, single update. Tenancy:
binding a different tenant before reading, and one report that spans every
tenant.

Each scenario is warmed up, then timed over N iterations; the report gives
medians. Query counts come from a separate pass with the debug cursor on, so
that instrumentation is not inside the timings.

### Keeping it fair

* **Indexes.** Every shared-schema index is prefixed with the tenant column
  (`(organization_id, status)`, `(organization_id, published_at DESC)`,
  `(organization_id, id)`). Schema-per-tenant gets the equivalent for free
  because each copy of the table holds one tenant's rows. Leaving these off
  would benchmark a misconfiguration.
* **Same key type.** `manual`'s tenant is keyed like
  `organizations.Organization` -- an integer primary key with the slug as a
  unique field -- so the comparison is not measuring the difference between a
  varchar and an integer.
* **`ANALYZE` after seeding**, so no approach is planned against statistics
  that still describe an empty table.
* **One connection, held open.** Connection setup is not what is being
  compared.
* **Idiomatic call sites.** The write scenarios save models the way the
  library's documentation does, not the way that happens to issue the fewest
  queries. Where that costs extra queries, the query-count table shows it.

### What it does not measure

Concurrency (single connection, no contention), connection-pool behaviour under
many tenants, backup/restore, per-tenant schema divergence, and the operational
cost of migrating thousands of schemas beyond the per-tenant creation time
recorded during setup. Numbers come from a single machine and a containerised
PostgreSQL; treat the ratios as the result and the absolute milliseconds as
incidental.

## Reading the results

Three things drive every number in the report:

1. **A tenant predicate is cheap.** With the tenant column leading the index,
   `WHERE organization_id = …` costs about what schema-per-tenant's
   already-narrowed table costs. Shared-schema tenancy is not slow because of
   the extra column.
2. **A `SET search_path` per query is not free.** It is a round trip before
   every statement, and it is django-tenants' default.
3. **Anything that spans tenants is a different story in each direction.** One
   `GROUP BY` against one table, or one query per schema.

Recorded runs at 25 and 100 tenants, and the library-specific findings the
suite surfaces, are in [RESULTS.md](RESULTS.md). Regenerate them after any
change to the managers, the querysets, or `OrganizationSafeForeignKey` -- those
are the code paths it prices.
