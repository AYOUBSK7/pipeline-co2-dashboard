"""Configuration centralisée du pipeline.

Les paramètres sensibles (mot de passe de la base) ne sont JAMAIS écrits
dans le code : ils sont lus depuis les variables d'environnement, ou depuis
un fichier .env local (ignoré par Git). Voir .env.example.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")

# --- Base de données ----------------------------------------------------
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB = os.getenv("PG_DB", "entrepot_co2")
PG_USER = os.getenv("PG_USER", "etl_user")
PG_PASSWORD = os.getenv("PG_PASSWORD", "etl_password")

DATABASE_URL = (
    f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
)

# --- Sources de données ouvertes -----------------------------------------
# Our World in Data — émissions de CO2 par pays (licence CC BY 4.0)
URL_CO2 = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"
# Codes ISO 3166 avec continents et sous-régions (licence CC BY-SA 4.0)
URL_REGIONS = (
    "https://raw.githubusercontent.com/lukes/"
    "ISO-3166-Countries-with-Regional-Codes/master/all/all.csv"
)

# --- Dossiers ------------------------------------------------------------
DOSSIER_RAW = RACINE / "data" / "raw"
DOSSIER_SQL = RACINE / "sql"

# --- Règles métier -------------------------------------------------------
# On ne garde que l'après-guerre : avant 1950 les données sont très lacunaires.
ANNEE_MIN = int(os.getenv("ANNEE_MIN", "1950"))
