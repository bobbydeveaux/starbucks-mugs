-- Migration: 005 - Create vehicles table
-- golang-migrate up migration
-- Petrol vs EV Cost Comparison Website: vehicle catalog

CREATE TABLE vehicles (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    make             TEXT        NOT NULL,
    model            TEXT        NOT NULL,
    year             SMALLINT    NOT NULL,
    variant          TEXT,
    fuel_type        TEXT        NOT NULL,           -- 'petrol'|'diesel'|'ev'|'hybrid'|'phev'
    mpg_combined     NUMERIC(5,2),                   -- ICE only: combined MPG
    mpg_city         NUMERIC(5,2),                   -- ICE only: city MPG
    mpg_motorway     NUMERIC(5,2),                   -- ICE only: motorway MPG
    efficiency_mpkwh NUMERIC(5,3),                   -- EV: miles per kWh
    battery_kwh      NUMERIC(5,1),                   -- EV/PHEV: usable battery capacity
    wltp_range_mi    SMALLINT,                       -- EV/PHEV: WLTP range in miles
    co2_gkm          SMALLINT,                       -- WLTP CO2 g/km for ICE; NULL for pure EV
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vehicles_make_model_year_fuel ON vehicles (make, model, year, fuel_type);
