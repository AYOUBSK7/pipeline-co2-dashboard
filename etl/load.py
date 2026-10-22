"""L — LOAD : écrire les données transformées dans PostgreSQL.

Stratégie en deux temps (comme un vrai entrepôt) :
  1. pandas dépose chaque DataFrame dans le schéma `staging` (zone de transit)
  2. un script SQL recopie staging -> dw dans UNE transaction
     (upsert des dimensions, rechargement complet des faits)

Pourquoi ne pas écrire directement dans dw ? Parce que les clés de
substitution (pays_key…) sont générées par PostgreSQL : c'est donc en SQL,
par jointure sur la clé naturelle, qu'on les retrouve le plus proprement.
"""
import csv
import io
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from etl import config

log = logging.getLogger(__name__)


def creer_moteur(url: str = config.DATABASE_URL) -> Engine:
    return create_engine(url, future=True)


def executer_script(conn, nom_fichier: str) -> None:
    """Exécute un fichier .sql du dossier sql/."""
    sql = (config.DOSSIER_SQL / nom_fichier).read_text(encoding="utf-8")
    conn.exec_driver_sql(sql)
    log.info("Script exécuté : %s", nom_fichier)


def _insertion_copy(table, conn, colonnes, lignes):
    """Méthode d'insertion pour pandas.to_sql qui utilise COPY de PostgreSQL.

    COPY envoie toutes les lignes d'un bloc : ~50x plus rapide que des
    milliers d'INSERT individuels.
    """
    tampon = io.StringIO()
    csv.writer(tampon).writerows(lignes)
    tampon.seek(0)
    noms = ", ".join(f'"{c}"' for c in colonnes)
    cible = f"{table.schema}.{table.name}" if table.schema else table.name
    with conn.connection.cursor() as cur:
        cur.copy_expert(f"COPY {cible} ({noms}) FROM STDIN WITH CSV", tampon)


def deposer_en_staging(conn, tables: dict[str, pd.DataFrame]) -> None:
    for nom, df in tables.items():
        if nom.startswith("_"):
            continue  # tables techniques, pas destinées à l'entrepôt
        df.to_sql(nom, conn, schema="staging", if_exists="replace",
                  index=False, method=_insertion_copy)
        log.info("staging.%-12s <- %d lignes", nom, len(df))


def charger(tables: dict[str, pd.DataFrame], moteur: Engine | None = None) -> dict:
    moteur = moteur or creer_moteur()

    # Création des schémas/tables si besoin (idempotent)
    with moteur.begin() as conn:
        executer_script(conn, "01_schema.sql")
        run_id = conn.execute(
            text("INSERT INTO meta.journal_chargement (debut, statut) "
                 "VALUES (:d, 'EN_COURS') RETURNING run_id"),
            {"d": datetime.now()},
        ).scalar_one()

    try:
        # Tout ce bloc est UNE transaction : tout réussit ou rien n'est écrit
        with moteur.begin() as conn:
            deposer_en_staging(conn, tables)
            executer_script(conn, "02_staging_vers_dw.sql")
            executer_script(conn, "03_vues.sql")
            stats = {
                "nb_pays": conn.execute(text("SELECT COUNT(*) FROM dw.dim_pays")).scalar_one(),
                "nb_faits_emis": conn.execute(text("SELECT COUNT(*) FROM dw.fait_emissions")).scalar_one(),
                "nb_faits_indic": conn.execute(text("SELECT COUNT(*) FROM dw.fait_indicateurs_pays")).scalar_one(),
            }
    except Exception as exc:
        with moteur.begin() as conn:
            conn.execute(
                text("UPDATE meta.journal_chargement SET fin=:f, statut='ECHEC', message=:m "
                     "WHERE run_id=:r"),
                {"f": datetime.now(), "m": str(exc)[:1000], "r": run_id},
            )
        raise

    with moteur.begin() as conn:
        conn.execute(
            text("UPDATE meta.journal_chargement SET fin=:f, statut='SUCCES', "
                 "nb_pays=:nb_pays, nb_faits_emis=:nb_faits_emis, nb_faits_indic=:nb_faits_indic "
                 "WHERE run_id=:r"),
            {"f": datetime.now(), "r": run_id, **stats},
        )
    log.info("Chargement terminé (run %d) : %s", run_id, stats)
    return stats
