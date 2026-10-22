"""Contrôles qualité : vérifier les données AVANT de les charger.

Un entrepôt rempli de données fausses est pire qu'un entrepôt vide, car
on prend des décisions dessus. On distingue :
  - les contrôles BLOQUANTS : si l'un échoue, on arrête tout (pas de chargement) ;
  - les AVERTISSEMENTS : on charge quand même, mais on le signale dans les logs.
"""
import logging

import pandas as pd

log = logging.getLogger(__name__)


class ErreurQualite(Exception):
    """Levée quand un contrôle bloquant échoue."""


def controler(tables: dict[str, pd.DataFrame], tolerance: float = 0.01) -> list[str]:
    erreurs: list[str] = []
    avertissements: list[str] = []

    pays, annee = tables["pays"], tables["annee"]
    emis, indic = tables["emissions"], tables["indicateurs"]

    # 1. Unicité du grain : jamais deux lignes pour la même combinaison
    if emis.duplicated(["code_iso3", "annee", "code_source"]).any():
        erreurs.append("Doublons dans les émissions (pays, année, source)")
    if indic.duplicated(["code_iso3", "annee"]).any():
        erreurs.append("Doublons dans les indicateurs (pays, année)")
    if pays["code_iso3"].duplicated().any():
        erreurs.append("Code ISO en double dans la dimension pays")

    # 2. Intégrité référentielle : chaque fait pointe vers une dimension existante
    orphelins = set(emis["code_iso3"]) - set(pays["code_iso3"])
    if orphelins:
        erreurs.append(f"Faits sans pays dans la dimension : {sorted(orphelins)[:5]}")
    if not set(emis["annee"]).issubset(annee["annee"]):
        erreurs.append("Faits avec une année absente de la dimension")

    # 3. Valeurs plausibles
    if (emis["co2_mt"] < 0).any():
        erreurs.append(f"{(emis['co2_mt'] < 0).sum()} émissions négatives")
    if (indic["population"].dropna() <= 0).any():
        erreurs.append("Population nulle ou négative")

    # 4. Cohérence : somme des sources ≈ total publié par OWID
    total = tables.get("_co2_total")
    if total is not None:
        somme = emis.groupby(["code_iso3", "annee"], as_index=False)["co2_mt"].sum()
        comp = somme.merge(total.dropna(subset=["co2"]), on=["code_iso3", "annee"])
        ecart = (comp["co2_mt"] - comp["co2"]).abs()
        hors_tolerance = comp[ecart > tolerance * comp["co2"].abs() + 0.01]
        if len(hors_tolerance):
            avertissements.append(
                f"{len(hors_tolerance)} couples pays/année où la somme des sources "
                f"s'écarte de plus de {tolerance:.0%} du total OWID"
            )

    # 5. Complétude (simple information)
    taux_pib = indic["pib_usd"].notna().mean()
    if taux_pib < 0.5:
        avertissements.append(f"PIB renseigné pour seulement {taux_pib:.0%} des lignes")

    for a in avertissements:
        log.warning("Qualité : %s", a)
    if erreurs:
        for e in erreurs:
            log.error("Qualité BLOQUANT : %s", e)
        raise ErreurQualite("; ".join(erreurs))

    log.info("Contrôles qualité OK (%d avertissement(s))", len(avertissements))
    return avertissements
