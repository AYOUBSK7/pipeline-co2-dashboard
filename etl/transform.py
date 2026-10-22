"""T — TRANSFORM : nettoyer, enrichir et remodeler les données.

C'est ici que se trouve l'essentiel de la « logique métier ».
Chaque fonction est PURE : elle reçoit des DataFrames et en renvoie
d'autres, sans base de données ni réseau. On peut donc la tester
facilement (voir tests/test_transform.py).

Sortie : 5 DataFrames, un par table de l'entrepôt
    pays, annee, source           -> les dimensions
    emissions, indicateurs        -> les faits
"""
import logging

import pandas as pd

from etl import config

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
#  Référentiels (petites tables de correspondance écrites à la main)
# ----------------------------------------------------------------------

# Colonnes OWID -> ligne de la dimension « source d'émission »
SOURCES = pd.DataFrame(
    [
        ("coal_co2", "charbon", "Charbon", "Combustible fossile"),
        ("oil_co2", "petrole", "Pétrole", "Combustible fossile"),
        ("gas_co2", "gaz", "Gaz naturel", "Combustible fossile"),
        ("flaring_co2", "torchage", "Torchage", "Combustible fossile"),
        ("cement_co2", "ciment", "Ciment", "Procédé industriel"),
        ("other_industry_co2", "autres_industrie", "Autres industries", "Procédé industriel"),
    ],
    columns=["colonne_owid", "code_source", "libelle", "categorie"],
)

CONTINENTS_FR = {
    "Africa": "Afrique",
    "Americas": "Amériques",
    "Asia": "Asie",
    "Europe": "Europe",
    "Oceania": "Océanie",
}

SOUS_REGIONS_FR = {
    "Northern Africa": "Afrique du Nord",
    "Sub-Saharan Africa": "Afrique subsaharienne",
    "Latin America and the Caribbean": "Amérique latine et Caraïbes",
    "Northern America": "Amérique du Nord",
    "Central Asia": "Asie centrale",
    "Eastern Asia": "Asie de l'Est",
    "South-eastern Asia": "Asie du Sud-Est",
    "Southern Asia": "Asie du Sud",
    "Western Asia": "Asie de l'Ouest",
    "Eastern Europe": "Europe de l'Est",
    "Northern Europe": "Europe du Nord",
    "Southern Europe": "Europe du Sud",
    "Western Europe": "Europe de l'Ouest",
    "Australia and New Zealand": "Australie et Nouvelle-Zélande",
    "Melanesia": "Mélanésie",
    "Micronesia": "Micronésie",
    "Polynesia": "Polynésie",
}

# Cas que le fichier ISO ne couvre pas : on les complète à la main.
# (C'est très courant en ETL : on documente l'exception au lieu de la cacher.)
REGIONS_MANUELLES = {
    "TWN": ("Asie", "Asie de l'Est"),
    "ATA": ("Antarctique", "Antarctique"),
    "XKX": ("Europe", "Europe du Sud"),
}

# Kosovo n'a pas de code ISO officiel : OWID laisse la case vide.
# On utilise le code « XKX », l'usage de l'UE et de la Banque mondiale.
CODES_ISO_MANQUANTS = {"Kosovo": "XKX"}


# ----------------------------------------------------------------------
#  Étape 1 : nettoyage
# ----------------------------------------------------------------------

def nettoyer_co2(co2: pd.DataFrame, annee_min: int = config.ANNEE_MIN) -> pd.DataFrame:
    """Ne garde que les vrais pays, à partir de `annee_min`.

    Le fichier OWID mélange pays et agrégats (« World », « Africa »,
    « High-income countries »…). Les agrégats n'ont pas de code ISO à
    3 lettres : on les écarte, sinon on compterait certaines émissions
    deux fois (France + Europe + World…).
    """
    df = co2.copy()

    # Compléter les codes ISO manquants connus (Kosovo)
    manquant = df["iso_code"].isna() & df["country"].isin(CODES_ISO_MANQUANTS)
    df.loc[manquant, "iso_code"] = df.loc[manquant, "country"].map(CODES_ISO_MANQUANTS)

    est_pays = df["iso_code"].fillna("").str.fullmatch(r"[A-Z]{3}")
    df = df[est_pays & (df["year"] >= annee_min)]

    # Sécurité : une seule ligne par (pays, année)
    df = df.drop_duplicates(subset=["iso_code", "year"], keep="last")

    log.info(
        "Nettoyage : %d lignes conservées (%d pays, %d–%d)",
        len(df), df["iso_code"].nunique(), df["year"].min(), df["year"].max(),
    )
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------
#  Étape 2 : construction des dimensions
# ----------------------------------------------------------------------

def construire_dim_pays(co2_pays: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par pays, enrichie du continent et de la sous-région.

    Enrichissement = JOINTURE entre deux sources différentes, sur une clé
    commune (le code ISO alpha-3).
    """
    pays = (
        co2_pays[["iso_code", "country"]]
        .drop_duplicates(subset="iso_code", keep="last")
        .rename(columns={"iso_code": "code_iso3", "country": "nom_pays"})
    )

    ref = regions[["alpha-3", "region", "sub-region"]].rename(
        columns={"alpha-3": "code_iso3", "region": "continent", "sub-region": "sous_region"}
    )
    ref["continent"] = ref["continent"].map(CONTINENTS_FR)
    ref["sous_region"] = ref["sous_region"].map(SOUS_REGIONS_FR)

    # how="left" : on garde TOUS les pays OWID, même sans correspondance
    pays = pays.merge(ref, on="code_iso3", how="left")

    for iso, (continent, sous_region) in REGIONS_MANUELLES.items():
        masque = pays["code_iso3"] == iso
        pays.loc[masque, ["continent", "sous_region"]] = [continent, sous_region]

    sans_region = pays["continent"].isna()
    if sans_region.any():
        log.warning("Pays sans continent : %s", pays.loc[sans_region, "code_iso3"].tolist())
        pays[["continent", "sous_region"]] = pays[["continent", "sous_region"]].fillna("Non classé")

    return pays.sort_values("code_iso3").reset_index(drop=True)


def periode_climat(annee: int) -> str:
    """Repères des grandes conférences sur le climat."""
    if annee < 1992:
        return "Avant le Sommet de Rio"
    if annee < 2005:
        return "Rio → Kyoto"
    if annee < 2016:
        return "Protocole de Kyoto"
    return "Accord de Paris"


def construire_dim_annee(annees: pd.Series) -> pd.DataFrame:
    """Une ligne par année, avec des attributs pour regrouper (décennie…)."""
    annees = sorted(int(a) for a in annees.unique())
    return pd.DataFrame(
        {
            "annee": annees,
            "decennie": [a // 10 * 10 for a in annees],
            "periode": [periode_climat(a) for a in annees],
        }
    )


def construire_dim_source() -> pd.DataFrame:
    return SOURCES[["code_source", "libelle", "categorie"]].copy()


# ----------------------------------------------------------------------
#  Étape 3 : construction des faits
# ----------------------------------------------------------------------

def construire_fait_emissions(co2_pays: pd.DataFrame) -> pd.DataFrame:
    """Passe d'un format LARGE (1 colonne par source) à un format LONG
    (1 ligne par source) : c'est le « dépivotage » (melt).

    Avant :  FRA | 2022 | coal_co2=26.2 | oil_co2=179.3 | …
    Après :  FRA | 2022 | charbon  | 26.2
             FRA | 2022 | petrole  | 179.3
             …
    Ce format long permet d'ajouter une source sans changer la table.
    """
    colonnes = SOURCES["colonne_owid"].tolist()
    long = co2_pays.melt(
        id_vars=["iso_code", "year"],
        value_vars=colonnes,
        var_name="colonne_owid",
        value_name="co2_mt",
    )
    # Valeur absente = « non mesuré », pas « zéro » : on ne l'invente pas.
    long = long.dropna(subset=["co2_mt"])

    long = long.merge(SOURCES[["colonne_owid", "code_source"]], on="colonne_owid")
    long = long.rename(columns={"iso_code": "code_iso3", "year": "annee"})
    long["annee"] = long["annee"].astype(int)

    return (
        long[["code_iso3", "annee", "code_source", "co2_mt"]]
        .sort_values(["code_iso3", "annee", "code_source"])
        .reset_index(drop=True)
    )


def construire_fait_indicateurs(co2_pays: pd.DataFrame) -> pd.DataFrame:
    """Population, PIB et énergie : une ligne par pays et par année."""
    df = co2_pays[["iso_code", "year", "population", "gdp", "primary_energy_consumption"]].rename(
        columns={
            "iso_code": "code_iso3",
            "year": "annee",
            "gdp": "pib_usd",
            "primary_energy_consumption": "energie_primaire_twh",
        }
    )
    mesures = ["population", "pib_usd", "energie_primaire_twh"]
    df = df.dropna(subset=mesures, how="all")  # ligne totalement vide = inutile
    df["annee"] = df["annee"].astype(int)
    # Int64 (majuscule) = entier qui accepte les valeurs manquantes
    df["population"] = df["population"].round().astype("Int64")
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------
#  Point d'entrée
# ----------------------------------------------------------------------

def transformer(brut: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    co2_pays = nettoyer_co2(brut["co2"])

    tables = {
        "pays": construire_dim_pays(co2_pays, brut["regions"]),
        "annee": construire_dim_annee(co2_pays["year"]),
        "source": construire_dim_source(),
        "emissions": construire_fait_emissions(co2_pays),
        "indicateurs": construire_fait_indicateurs(co2_pays),
        # gardé pour le contrôle qualité (total officiel OWID)
        "_co2_total": co2_pays[["iso_code", "year", "co2"]].rename(
            columns={"iso_code": "code_iso3", "year": "annee"}
        ),
    }
    for nom, t in tables.items():
        if not nom.startswith("_"):
            log.info("  %-12s %7d lignes", nom, len(t))
    return tables
