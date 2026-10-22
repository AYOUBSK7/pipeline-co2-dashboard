-- =====================================================================
--  Entrepôt de données CO2 — schéma en étoile
--  Exécuté automatiquement par le pipeline (idempotent : IF NOT EXISTS)
-- =====================================================================
--
--  staging : zone de transit. Les données transformées par pandas y sont
--            déposées telles quelles, puis recopiées dans le schéma dw.
--  dw      : l'entrepôt proprement dit (dimensions + tables de faits).
--  meta    : le journal des exécutions du pipeline.

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS meta;

-- ---------------------------------------------------------------------
--  DIMENSIONS : le « contexte » (qui ? quand ? quoi ?)
-- ---------------------------------------------------------------------

-- Qui émet ? Une ligne par pays.
-- pays_key  = clé de substitution (technique, générée par PostgreSQL)
-- code_iso3 = clé naturelle (métier, vient de la source) -> UNIQUE
CREATE TABLE IF NOT EXISTS dw.dim_pays (
    pays_key     SERIAL PRIMARY KEY,
    code_iso3    CHAR(3)      NOT NULL UNIQUE,
    nom_pays     VARCHAR(100) NOT NULL,
    continent    VARCHAR(50)  NOT NULL,
    sous_region  VARCHAR(80)  NOT NULL
);

-- Quand ? Une ligne par année.
-- Pour le temps, on utilise une clé « intelligente » : l'année elle-même.
CREATE TABLE IF NOT EXISTS dw.dim_annee (
    annee_key    INTEGER PRIMARY KEY,
    annee        INTEGER     NOT NULL UNIQUE,
    decennie     INTEGER     NOT NULL,          -- 1990, 2000, 2010…
    periode      VARCHAR(40) NOT NULL           -- repère historique
);

-- Quoi ? D'où vient le CO2 (charbon, pétrole, gaz…).
CREATE TABLE IF NOT EXISTS dw.dim_source (
    source_key   SERIAL PRIMARY KEY,
    code_source  VARCHAR(30) NOT NULL UNIQUE,
    libelle      VARCHAR(60) NOT NULL,
    categorie    VARCHAR(40) NOT NULL           -- combustible fossile / procédé industriel
);

-- ---------------------------------------------------------------------
--  FAITS : les mesures numériques, au croisement des dimensions
-- ---------------------------------------------------------------------

-- Grain : 1 ligne = 1 pays x 1 année x 1 source d'émission.
-- Mesure additive : on peut la sommer selon n'importe quelle dimension.
CREATE TABLE IF NOT EXISTS dw.fait_emissions (
    pays_key     INTEGER NOT NULL REFERENCES dw.dim_pays(pays_key),
    annee_key    INTEGER NOT NULL REFERENCES dw.dim_annee(annee_key),
    source_key   INTEGER NOT NULL REFERENCES dw.dim_source(source_key),
    co2_mt       NUMERIC(14, 4) NOT NULL,       -- millions de tonnes de CO2
    PRIMARY KEY (pays_key, annee_key, source_key)
);

-- Grain : 1 ligne = 1 pays x 1 année.
-- Population, PIB, énergie n'ont pas de « source d'émission » : les mettre
-- dans fait_emissions les dupliquerait 6 fois. D'où une 2e table de faits
-- qui partage les mêmes dimensions (dimensions « conformes »).
CREATE TABLE IF NOT EXISTS dw.fait_indicateurs_pays (
    pays_key              INTEGER NOT NULL REFERENCES dw.dim_pays(pays_key),
    annee_key             INTEGER NOT NULL REFERENCES dw.dim_annee(annee_key),
    population            BIGINT,
    pib_usd               NUMERIC(20, 2),       -- $ internationaux, prix 2011
    energie_primaire_twh  NUMERIC(14, 4),
    PRIMARY KEY (pays_key, annee_key)
);

-- Index sur les clés étrangères les plus filtrées par le tableau de bord
CREATE INDEX IF NOT EXISTS ix_fait_emissions_annee  ON dw.fait_emissions (annee_key);
CREATE INDEX IF NOT EXISTS ix_fait_emissions_source ON dw.fait_emissions (source_key);
CREATE INDEX IF NOT EXISTS ix_fait_indic_annee      ON dw.fait_indicateurs_pays (annee_key);

-- ---------------------------------------------------------------------
--  JOURNAL DES CHARGEMENTS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.journal_chargement (
    run_id          SERIAL PRIMARY KEY,
    debut           TIMESTAMP   NOT NULL,
    fin             TIMESTAMP,
    statut          VARCHAR(20) NOT NULL,       -- EN_COURS / SUCCES / ECHEC
    nb_pays         INTEGER,
    nb_faits_emis   INTEGER,
    nb_faits_indic  INTEGER,
    message         TEXT
);
