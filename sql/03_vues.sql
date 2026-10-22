-- =====================================================================
--  Vues analytiques : la couche que le tableau de bord interroge.
--  Elles cachent les jointures du schéma en étoile derrière des noms
--  lisibles. Si le modèle évolue, on adapte la vue, pas le dashboard.
-- =====================================================================

-- Émissions détaillées, toutes dimensions « dépliées »
CREATE OR REPLACE VIEW dw.v_emissions AS
SELECT
    a.annee,
    a.decennie,
    p.code_iso3,
    p.nom_pays,
    p.continent,
    p.sous_region,
    s.code_source,
    s.libelle      AS source,
    s.categorie,
    f.co2_mt
FROM dw.fait_emissions f
JOIN dw.dim_pays   p ON p.pays_key   = f.pays_key
JOIN dw.dim_annee  a ON a.annee_key  = f.annee_key
JOIN dw.dim_source s ON s.source_key = f.source_key;

-- Un pays une année : total CO2 + indicateurs + ratios calculés
CREATE OR REPLACE VIEW dw.v_pays_annee AS
WITH total AS (
    SELECT pays_key, annee_key, SUM(co2_mt) AS co2_mt
    FROM dw.fait_emissions
    GROUP BY pays_key, annee_key
)
SELECT
    a.annee,
    p.code_iso3,
    p.nom_pays,
    p.continent,
    p.sous_region,
    t.co2_mt,
    i.population,
    i.pib_usd,
    i.energie_primaire_twh,
    -- tonnes de CO2 par habitant  (Mt -> t : x 1 000 000)
    ROUND(t.co2_mt * 1e6 / NULLIF(i.population, 0), 3)             AS co2_t_par_hab,
    -- kg de CO2 par dollar de PIB (intensité carbone de l'économie)
    ROUND(t.co2_mt * 1e9 / NULLIF(i.pib_usd, 0), 4)                AS co2_kg_par_usd
FROM total t
JOIN dw.dim_pays  p ON p.pays_key  = t.pays_key
JOIN dw.dim_annee a ON a.annee_key = t.annee_key
LEFT JOIN dw.fait_indicateurs_pays i
       ON i.pays_key = t.pays_key AND i.annee_key = t.annee_key;
