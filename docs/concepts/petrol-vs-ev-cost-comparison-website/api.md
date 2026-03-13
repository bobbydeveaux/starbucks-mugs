# API Reference: Petrol vs EV Cost Comparison

Serverless functions live in `api/` at the repository root and are deployed
as Vercel Functions. All endpoints return `application/json`.

---

## GET /api/pricing

Returns the current default fuel and electricity pricing used to seed the
cost-comparison calculator.

### Response `200 OK`

```json
{
  "petrol_ppl": 145.2,
  "diesel_ppl": 151.4,
  "electricity_ppkwh": 24.5,
  "tariffs": {
    "economy7": 13.0,
    "octopus_go": 7.5,
    "ovo_drive": 9.0
  },
  "public_charging": {
    "slow": 30.0,
    "rapid": 55.0,
    "ultra_rapid": 79.0
  },
  "updated_at": "2026-03-10T12:00:00Z"
}
```

All `tariffs` and `public_charging` sub-fields are nullable — they are `null`
when no value has been configured in the database.

### Caching

```
Cache-Control: public, max-age=3600, s-maxage=3600
```

Responses are valid for 1 hour at the CDN edge and in shared caches.

### Error responses

| Status | Body | Cause |
|--------|------|-------|
| `404` | `{"error":"No pricing data found"}` | `pricing_defaults` table is empty |
| `405` | `{"error":"Method Not Allowed"}` | Non-GET HTTP method |
| `500` | `{"error":"Internal Server Error"}` | Database unreachable or query failure |

### Source

`api/pricing.ts` — queries the most recent row from `pricing_defaults`
(see `db/migrations/006_pricing_defaults.up.sql` for the schema).

### Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Vercel project setting) |

---

## Planned: GET /api/vehicles

Search the vehicle catalog. *(Not yet implemented — Sprint 2 backlog.)*

## Planned: PUT /api/admin/pricing

Auth-gated endpoint to update pricing defaults. *(Not yet implemented.)*

For the full API contract see `HLD.md § 4. API Contracts`.
