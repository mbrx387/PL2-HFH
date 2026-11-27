-- Issue #85: Sperrvermerk fuer manuell gepflegte Einrichtungen.
--
-- Docker fuehrt diese Datei NUR beim ersten Initialisieren eines leeren
-- Datenbank-Volumes aus (wie 001_create_centers.sql und 002_create_mail_history.sql).
-- Bei einer bereits bestehenden Datenbank legt die App dieselben Spalten beim
-- Start an (app/maintenance.py, ensure_manual_maintenance_columns, mit Advisory
-- Lock gegen parallel startende Gunicorn-Worker). Beide Wege erzeugen dasselbe
-- Schema; die Datei ist idempotent.
--
-- manuell_gepflegt = true schuetzt einen Eintrag vor dem woechentlichen Import:
-- db/import_centers.sql ueberspringt gesperrte Eintraege vollstaendig (Felder
-- und Angebote) und meldet die Anzahl per NOTICE im Import-Log. Die Spalten
-- stehen nicht in der INSERT-Spaltenliste des Imports, der Upsert setzt sie
-- also nie zurueck.
--
-- Bereits vorhandene manuell angelegte Einrichtungen (id >= 1.000.000) werden
-- hier automatisch gesperrt (Altlasten). manuell_geaendert_von/-am bleiben bei
-- Altlasten NULL, weil der Zeitpunkt der manuellen Aenderung unbekannt ist.

ALTER TABLE centers ADD COLUMN IF NOT EXISTS manuell_gepflegt boolean NOT NULL DEFAULT false;
ALTER TABLE centers ADD COLUMN IF NOT EXISTS manuell_geaendert_von varchar(255);
ALTER TABLE centers ADD COLUMN IF NOT EXISTS manuell_geaendert_am timestamptz;

UPDATE centers
SET manuell_gepflegt = true
WHERE id >= 1000000
  AND NOT manuell_gepflegt;
