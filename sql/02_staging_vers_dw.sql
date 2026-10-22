-- =====================================================================
--  Copie staging -> dw  (exécuté dans UNE transaction par load.py)
--  Si une instruction échoue, tout est annulé : l'entrepôt n'est jamais
--  laissé à moitié chargé.
-- =====================================================================

-- 1) DIMENSIONS : « upsert » sur la clé naturelle.
--    - nouveau pays           -> INSERT (une nouvelle pays_key est créée)
--    - pays déjà connu        -> UPDATE des attributs (nom, continent…)
--    Les clés de substitution existantes ne changent donc jamais :
--    relancer le pipeline 10 fois donne le même résultat (idempotence).

INSERT INTO dw.dim_pays (code_iso3, nom_pays, continent, sous_region)
SELECT code_iso3, nom_pays, continent, sous_region
FROM staging.pays
ON CONFLICT (code_iso3) DO UPDATE
   SET nom_pays    = EXCLUDED.nom_pays,
       continent   = EXCLUDED.continent,
       sous_region = EXCLUDED.sous_region;

INSERT INTO dw.dim_annee (annee_key, annee, decennie, periode)
SELECT annee, annee, decennie, periode
FROM staging.annee
ON CONFLICT (annee_key) DO UPDATE
   SET decennie = EXCLUDED.decennie,
       periode  = EXCLUDED.periode;

INSERT INTO dw.dim_source (code_source, libelle, categorie)
SELECT code_source, libelle, categorie
FROM staging.source
ON CONFLICT (code_source) DO UPDATE
   SET libelle   = EXCLUDED.libelle,
       categorie = EXCLUDED.categorie;

-- 2) FAITS : rechargement complet (« full refresh »).
--    Les données OWID sont révisées chaque année (même les anciennes
--    années), donc on remplace tout plutôt que d'ajouter.
--    La jointure sur les clés naturelles retrouve les clés de substitution.

TRUNCATE dw.fait_emissions, dw.fait_indicateurs_pays;

INSERT INTO dw.fait_emissions (pays_key, annee_key, source_key, co2_mt)
SELECT p.pays_key, s.annee, src.source_key, s.co2_mt
FROM staging.emissions s
JOIN dw.dim_pays   p   ON p.code_iso3     = s.code_iso3
JOIN dw.dim_source src ON src.code_source = s.code_source;

INSERT INTO dw.fait_indicateurs_pays (pays_key, annee_key, population, pib_usd, energie_primaire_twh)
SELECT p.pays_key, s.annee, s.population, s.pib_usd, s.energie_primaire_twh
FROM staging.indicateurs s
JOIN dw.dim_pays p ON p.code_iso3 = s.code_iso3;
