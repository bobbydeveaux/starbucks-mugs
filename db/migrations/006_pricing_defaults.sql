-- Migration: 006 - Create pricing_defaults table
-- golang-migrate up migration
-- Petrol vs EV Cost Comparison Website: fuel and electricity pricing defaults

CREATE TABLE pricing_defaults (
    id                      SERIAL      PRIMARY KEY,
    petrol_ppl              NUMERIC(5,2) NOT NULL,   -- petrol: pence per litre
    diesel_ppl              NUMERIC(5,2) NOT NULL,   -- diesel: pence per litre
    electricity_ppkwh       NUMERIC(5,2) NOT NULL,   -- standard home electricity: pence per kWh
    economy7_ppkwh          NUMERIC(5,2),            -- Economy 7 off-peak rate
    octopus_go_ppkwh        NUMERIC(5,2),            -- Octopus Go EV tariff
    ovo_drive_ppkwh         NUMERIC(5,2),            -- OVO Drive Anytime tariff
    public_slow_ppkwh       NUMERIC(5,2),            -- Public slow charging (3–7 kW)
    public_rapid_ppkwh      NUMERIC(5,2),            -- Public rapid charging (22–50 kW)
    public_ultrarapid_ppkwh NUMERIC(5,2),            -- Public ultra-rapid charging (100+ kW)
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by              TEXT                     -- identifier of the admin who last updated
);
