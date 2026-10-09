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

\copy centers_import FROM '/tmp/centers.csv' WITH (FORMAT csv, HEADER true, DELIMITER ';', ENCODING 'UTF8')

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
    SELECT btrim(leistungen) AS service_name
    FROM centers_import
    WHERE NULLIF(btrim(leistungen), '') IS NOT NULL

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
        btrim(imported.leistungen) AS service_name
    FROM centers_import AS imported
    WHERE NULLIF(btrim(imported.leistungen), '') IS NOT NULL

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
