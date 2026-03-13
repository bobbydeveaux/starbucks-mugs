-- Migration 006: Create pricing_defaults table
-- Single-row config table holding current UK fuel and electricity pricing.
-- Used by GET /api/pricing; updated via PUT /api/admin/pricing (auth-gated).

CREATE TABLE pricing_defaults (
    id                      SERIAL       PRIMARY KEY,
    petrol_ppl              NUMERIC(5,2) NOT NULL,   -- petrol: pence per litre
    diesel_ppl              NUMERIC(5,2) NOT NULL,   -- diesel: pence per litre
    electricity_ppkwh       NUMERIC(5,2) NOT NULL,   -- standard home electricity: pence per kWh
    economy7_ppkwh          NUMERIC(5,2),            -- Economy 7 off-peak rate
    octopus_go_ppkwh        NUMERIC(5,2),            -- Octopus Go EV tariff
    ovo_drive_ppkwh         NUMERIC(5,2),            -- OVO Drive Anytime tariff
    public_slow_ppkwh       NUMERIC(5,2),            -- Public slow charging (3–7 kW)
    public_rapid_ppkwh      NUMERIC(5,2),            -- Public rapid charging (22–50 kW)
    public_ultrarapid_ppkwh NUMERIC(5,2),            -- Public ultra-rapid charging (100+ kW)
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_by              TEXT                     -- identifier of the admin who last updated
);

-- Seed the initial pricing row with representative UK values (March 2026)
INSERT INTO pricing_defaults (
    petrol_ppl,
    diesel_ppl,
    electricity_ppkwh,
    economy7_ppkwh,
    octopus_go_ppkwh,
    ovo_drive_ppkwh,
    public_slow_ppkwh,
    public_rapid_ppkwh,
    public_ultrarapid_ppkwh,
    updated_by
) VALUES (
    145.2,   -- petrol p/litre
    151.4,   -- diesel p/litre
    24.5,    -- standard electricity p/kWh
    13.0,    -- Economy 7 off-peak p/kWh
    7.5,     -- Octopus Go p/kWh
    9.0,     -- OVO Drive Anytime p/kWh
    30.0,    -- public slow p/kWh
    55.0,    -- public rapid p/kWh
    79.0,    -- public ultra-rapid p/kWh
    'seed'
);
