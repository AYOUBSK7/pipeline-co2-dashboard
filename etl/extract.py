"""E — EXTRACT : récupérer les données brutes, sans les modifier.

Principe : on télécharge les fichiers sources dans data/raw/ et on les
relit avec pandas. On ne touche pas encore au contenu : si la transformation
plante, on peut la relancer sans re-télécharger (et on garde une trace
exacte de ce qu'on a reçu).
"""
import logging
from pathlib import Path

import pandas as pd
import requests

from etl import config

log = logging.getLogger(__name__)


def telecharger(url: str, destination: Path, forcer: bool = False) -> Path:
    """Télécharge `url` vers `destination` (sauf s'il existe déjà)."""
    if destination.exists() and not forcer:
        log.info("Déjà présent, pas de téléchargement : %s", destination.name)
        return destination

    log.info("Téléchargement de %s", url)
    reponse = requests.get(url, timeout=60)
    reponse.raise_for_status()  # lève une erreur si HTTP 404, 500…
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(reponse.content)
    log.info("  -> %s (%.1f Mo)", destination.name, len(reponse.content) / 1e6)
    return destination


def extraire(forcer: bool = False) -> dict[str, pd.DataFrame]:
    """Retourne les deux jeux de données bruts sous forme de DataFrames."""
    f_co2 = telecharger(config.URL_CO2, config.DOSSIER_RAW / "owid-co2-data.csv", forcer)
    f_reg = telecharger(config.URL_REGIONS, config.DOSSIER_RAW / "iso_regions.csv", forcer)

    co2 = pd.read_csv(f_co2)
    # keep_default_na=False : sinon le code ISO « NA » (Namibie) devient NaN !
    regions = pd.read_csv(f_reg, keep_default_na=False, na_values=[""])

    log.info("Extrait : %d lignes CO2, %d pays ISO", len(co2), len(regions))
    return {"co2": co2, "regions": regions}
