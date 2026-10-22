"""Tests unitaires de la transformation.

On fabrique de PETITS jeux de données à la main, dont on connaît le
résultat attendu, et on vérifie que chaque fonction se comporte bien.
Aucune base de données ni connexion internet n'est nécessaire.

Lancer :  pytest -v
"""
import numpy as np
import pandas as pd
import pytest

from etl import quality, transform


@pytest.fixture
def co2_brut() -> pd.DataFrame:
    """Mini-extrait au format OWID : 2 pays, 1 agrégat, Kosovo sans ISO."""
    lignes = [
        # country, year, iso_code, population, gdp, energy, coal, oil, gas, flaring, cement, other
        ("France", 2021, "FRA", 66e6, 2.9e12, 2600, 27, 180, 75, 2, 6, 4),
        ("France", 2022, "FRA", 66.3e6, 3.0e12, 2500, 26, 179, 78, 2, 6, 4),
        ("Tunisia", 2022, "TUN", 12.1e6, 1.3e11, 120, 0, 15, 13, np.nan, 3, np.nan),
        ("World", 2022, np.nan, 8e9, 1.3e14, 170000, 15000, 11000, 7800, 400, 1500, 300),
        ("Kosovo", 2022, np.nan, 1.7e6, np.nan, np.nan, 7, 1, 0, 0, 0.5, np.nan),
        ("France", 1900, "FRA", 40e6, np.nan, np.nan, 100, 0, 0, 0, 0, 0),
    ]
    cols = ["country", "year", "iso_code", "population", "gdp",
            "primary_energy_consumption", "coal_co2", "oil_co2", "gas_co2",
            "flaring_co2", "cement_co2", "other_industry_co2"]
    df = pd.DataFrame(lignes, columns=cols)
    df["co2"] = df[cols[6:]].sum(axis=1, min_count=1)
    return df


@pytest.fixture
def regions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "alpha-3": ["FRA", "TUN"],
            "region": ["Europe", "Africa"],
            "sub-region": ["Western Europe", "Northern Africa"],
        }
    )


# --- nettoyage --------------------------------------------------------

def test_nettoyage_retire_les_agregats_et_les_annees_anciennes(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    assert "World" not in propre["country"].values
    assert propre["year"].min() >= 1950


def test_nettoyage_complete_le_code_iso_du_kosovo(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    assert propre.loc[propre["country"] == "Kosovo", "iso_code"].item() == "XKX"


# --- dimensions -------------------------------------------------------

def test_dim_pays_traduit_et_complete_les_regions(co2_brut, regions):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    pays = transform.construire_dim_pays(propre, regions).set_index("code_iso3")

    assert pays.loc["FRA", "continent"] == "Europe"
    assert pays.loc["TUN", "sous_region"] == "Afrique du Nord"
    assert pays.loc["XKX", "continent"] == "Europe"  # complément manuel
    assert pays.index.is_unique


@pytest.mark.parametrize(
    "annee, attendu",
    [(1991, "Avant le Sommet de Rio"), (1992, "Rio → Kyoto"),
     (2005, "Protocole de Kyoto"), (2016, "Accord de Paris")],
)
def test_periode_climat(annee, attendu):
    assert transform.periode_climat(annee) == attendu


def test_dim_annee_calcule_la_decennie():
    dim = transform.construire_dim_annee(pd.Series([2022, 1999, 2022]))
    assert dim["annee"].tolist() == [1999, 2022]  # dédoublonnée et triée
    assert dim["decennie"].tolist() == [1990, 2020]


# --- faits ------------------------------------------------------------

def test_fait_emissions_depivote_une_ligne_par_source(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    emis = transform.construire_fait_emissions(propre)

    fra = emis[(emis["code_iso3"] == "FRA") & (emis["annee"] == 2022)]
    assert len(fra) == 6
    assert fra.set_index("code_source").loc["petrole", "co2_mt"] == 179


def test_fait_emissions_ne_transforme_pas_les_manquants_en_zero(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    emis = transform.construire_fait_emissions(propre)

    tun = emis[emis["code_iso3"] == "TUN"]
    assert "torchage" not in tun["code_source"].values  # NaN -> ligne absente
    assert "charbon" in tun["code_source"].values      # vrai zéro -> conservé


def test_somme_des_sources_egale_le_total(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    emis = transform.construire_fait_emissions(propre)
    total = emis.groupby(["code_iso3", "annee"])["co2_mt"].sum()
    attendu = propre.set_index(["iso_code", "year"])["co2"]
    assert np.allclose(total.sort_index(), attendu.sort_index())


def test_fait_indicateurs_population_entiere(co2_brut):
    propre = transform.nettoyer_co2(co2_brut, annee_min=1950)
    indic = transform.construire_fait_indicateurs(propre)
    assert str(indic["population"].dtype) == "Int64"
    assert indic["pib_usd"].isna().sum() == 1  # Kosovo : PIB manquant conservé


# --- contrôles qualité ------------------------------------------------

def test_controle_qualite_passe_sur_des_donnees_saines(co2_brut, regions):
    tables = transform.transformer({"co2": co2_brut, "regions": regions})
    quality.controler(tables)  # ne doit pas lever d'exception


def test_controle_qualite_bloque_les_doublons(co2_brut, regions):
    tables = transform.transformer({"co2": co2_brut, "regions": regions})
    tables["emissions"] = pd.concat([tables["emissions"], tables["emissions"].head(1)])
    with pytest.raises(quality.ErreurQualite, match="Doublons"):
        quality.controler(tables)


def test_controle_qualite_bloque_les_valeurs_negatives(co2_brut, regions):
    tables = transform.transformer({"co2": co2_brut, "regions": regions})
    tables["emissions"].loc[0, "co2_mt"] = -5
    with pytest.raises(quality.ErreurQualite, match="négatives"):
        quality.controler(tables)
