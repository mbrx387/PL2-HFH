BEGIN;

CREATE TEMP TABLE centers_import (
    unsere_id text,
    zqp_id text,
    name text,
    adresse text,
    plz text,
    ort text,
    bundesland text,
    email text,
    telefon text,
    website text,
    latitude text,
    longitude text,
    pflegestuetzpunkt text,
    pflegeberatung text,
    wohnberatung text,
    demenzberatung text,
    angehoerigenberatung text,
    betreuungsberatung text,
    leistungen text,
    updated_at text
) ON COMMIT DROP;

\copy centers_import FROM '/tmp/pflegestellen.csv' WITH (FORMAT csv, HEADER true, DELIMITER ';', ENCODING 'UTF8')

-- Issue #85: Manuell gepflegte Datensaetze (Sperrvermerk manuell_gepflegt)
-- duerfen vom Import weder veraendert noch dupliziert werden. Alle Kollisionen
-- werden VOR dem Upsert aus der Temp-Tabelle aufgeloest, damit keine
-- UNIQUE-Verletzung (zqp_id) den Import abbrechen laesst -- mit ON_ERROR_STOP
-- rollt sonst die gesamte Transaktion zurueck.
-- Autor: Gabriel Pfuner (github.com/3mg4)

-- 0) Guard: IDs ab 1.000.000 gehoeren manuell angelegten Einrichtungen. Eine
--    solche ID in der Import-CSV ist ein Fehler -> kompletter Abbruch. Feuert
--    nie woechentlich: Der ETL-Guard in validate_records() (GetDataFromAPI)
--    faengt solche CSVs schon im validate-Job des PRs ab.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM centers_import WHERE btrim(unsere_id)::integer >= 1000000) THEN
        RAISE EXCEPTION 'Import abgebrochen: unsere_id >= 1000000 in der CSV (manueller ID-Bereich)';
    END IF;
END $$;

-- 1) Sperrfilter: Import-Zeilen, die einen gesperrten Eintrag matchen (ueber
--    id, zqp_id ODER den LOCAL-Key name|adresse|plz|ort), werden entfernt.
--    Felder und Angebote gesperrter Eintraege bleiben unberuehrt; die Anzahl
--    landet per NOTICE im Log des Import-Schritts (Workflow- bzw. Server-Log).
DO $$
DECLARE
    skipped integer;
BEGIN
    DELETE FROM centers_import AS ci
    WHERE EXISTS (
        SELECT 1
        FROM centers AS c
        WHERE c.manuell_gepflegt
          AND (
            c.id = btrim(ci.unsere_id)::integer
            OR (btrim(ci.zqp_id) <> '' AND c.zqp_id = btrim(ci.zqp_id))
            OR (
                lower(btrim(c.name)) || '|' || lower(btrim(c.adresse)) || '|' || btrim(c.plz) || '|' || lower(btrim(c.ort))
                =
                lower(btrim(COALESCE(ci.name, ''))) || '|' || lower(btrim(COALESCE(ci.adresse, ''))) || '|' || btrim(COALESCE(ci.plz, '')) || '|' || lower(btrim(COALESCE(ci.ort, '')))
            )
          )
    );
    GET DIAGNOSTICS skipped = ROW_COUNT;
    RAISE NOTICE 'Import uebersprungen (manuell gesperrt): %', skipped;
END $$;

-- 2) zqp_id-Kollision mit einem NICHT gesperrten Eintrag (andere ID): unsere_id
--    auf die bestehende DB-ID umbiegen. Der Upsert aktualisiert dann denselben
--    Datensatz, statt ein Duplikat anzulegen oder die UNIQUE-Constraint auf
--    zqp_id zu verletzen.
UPDATE centers_import AS ci
SET unsere_id = c.id::text
FROM centers AS c
WHERE btrim(ci.zqp_id) <> ''
  AND c.zqp_id = btrim(ci.zqp_id)
  AND NOT c.manuell_gepflegt
  AND c.id <> btrim(ci.unsere_id)::integer;

INSERT INTO centers (
    id,
    zqp_id,
    name,
    adresse,
    plz,
    ort,
    bundesland,
    email,
    telefon,
    website,
    latitude,
    longitude,
    quelle_updated_at,
    updated_at
)
SELECT
    btrim(unsere_id)::integer,
    NULLIF(btrim(zqp_id), ''),
    COALESCE(name, ''),
    COALESCE(adresse, ''),
    COALESCE(plz, ''),
    COALESCE(ort, ''),
    COALESCE(bundesland, ''),
    COALESCE(email, ''),
    COALESCE(telefon, ''),
    COALESCE(website, ''),
    NULLIF(btrim(latitude), '')::double precision,
    NULLIF(btrim(longitude), '')::double precision,
    NULLIF(btrim(updated_at), '')::timestamp,
    now()
FROM centers_import
ON CONFLICT (id) DO UPDATE SET
    zqp_id = EXCLUDED.zqp_id,
    name = EXCLUDED.name,
    adresse = EXCLUDED.adresse,
    plz = EXCLUDED.plz,
    ort = EXCLUDED.ort,
    bundesland = EXCLUDED.bundesland,
    email = EXCLUDED.email,
    telefon = EXCLUDED.telefon,
    website = EXCLUDED.website,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    quelle_updated_at = EXCLUDED.quelle_updated_at,
    updated_at = now();

DELETE FROM center_services AS cs
USING centers_import AS imported
WHERE cs.center_id = btrim(imported.unsere_id)::integer;

INSERT INTO services (name)
SELECT DISTINCT offered.service_name
FROM (
    SELECT btrim(offered.value) AS service_name
    FROM centers_import AS imported
    CROSS JOIN LATERAL unnest(string_to_array(COALESCE(imported.leistungen, ''), ',')) AS offered(value)
    WHERE btrim(offered.value) <> ''

    UNION ALL

    SELECT offered.service_name
    FROM centers_import AS imported
    CROSS JOIN LATERAL (
        VALUES
            ('Pflegestützpunkt', NULLIF(btrim(pflegestuetzpunkt), '')::boolean),
            ('Pflegeberatung', NULLIF(btrim(pflegeberatung), '')::boolean),
            ('Wohnberatung', NULLIF(btrim(wohnberatung), '')::boolean),
            ('Demenzberatung', NULLIF(btrim(demenzberatung), '')::boolean),
            ('Angehörigenberatung', NULLIF(btrim(angehoerigenberatung), '')::boolean),
            ('Betreuungsberatung', NULLIF(btrim(betreuungsberatung), '')::boolean)
    ) AS offered(service_name, is_offered)
    WHERE offered.is_offered
) AS offered
ON CONFLICT (name) DO NOTHING;

INSERT INTO center_services (center_id, service_id)
SELECT imported_offers.center_id, services.id
FROM (
    SELECT
        btrim(imported.unsere_id)::integer AS center_id,
        btrim(offered.value) AS service_name
    FROM centers_import AS imported
    CROSS JOIN LATERAL unnest(
        string_to_array(COALESCE(imported.leistungen, ''), ',')
    ) AS offered(value)
    WHERE btrim(offered.value) <> ''

    UNION ALL

    SELECT
        btrim(imported.unsere_id)::integer,
        offered.service_name
    FROM centers_import AS imported
    CROSS JOIN LATERAL (
        VALUES
            ('Pflegestützpunkt', NULLIF(btrim(pflegestuetzpunkt), '')::boolean),
            ('Pflegeberatung', NULLIF(btrim(pflegeberatung), '')::boolean),
            ('Wohnberatung', NULLIF(btrim(wohnberatung), '')::boolean),
            ('Demenzberatung', NULLIF(btrim(demenzberatung), '')::boolean),
            ('Angehörigenberatung', NULLIF(btrim(angehoerigenberatung), '')::boolean),
            ('Betreuungsberatung', NULLIF(btrim(betreuungsberatung), '')::boolean)
    ) AS offered(service_name, is_offered)
    WHERE offered.is_offered
) AS imported_offers
JOIN services ON services.name = imported_offers.service_name
ON CONFLICT DO NOTHING;

COMMIT;