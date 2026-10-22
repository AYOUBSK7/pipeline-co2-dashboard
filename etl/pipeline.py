"""Chef d'orchestre : enchaîne Extract -> Transform -> Contrôles -> Load.

Utilisation :
    python -m etl.pipeline              # exécution normale
    python -m etl.pipeline --forcer     # re-télécharge les sources
    python -m etl.pipeline --sans-load  # tout sauf l'écriture en base (test à sec)
"""
import argparse
import logging
import sys
import time

from etl import extract, load, quality, transform


def configurer_logs() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-13s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline ETL CO2 -> PostgreSQL")
    parser.add_argument("--forcer", action="store_true", help="re-télécharger les sources")
    parser.add_argument("--sans-load", action="store_true", help="ne pas écrire en base")
    args = parser.parse_args(argv)

    configurer_logs()
    log = logging.getLogger("etl.pipeline")
    t0 = time.perf_counter()

    try:
        log.info("=== 1/4 EXTRACT ===")
        brut = extract.extraire(forcer=args.forcer)

        log.info("=== 2/4 TRANSFORM ===")
        tables = transform.transformer(brut)

        log.info("=== 3/4 CONTRÔLES QUALITÉ ===")
        quality.controler(tables)

        if args.sans_load:
            log.info("=== 4/4 LOAD ignoré (--sans-load) ===")
        else:
            log.info("=== 4/4 LOAD ===")
            load.charger(tables)
    except Exception:
        log.exception("Le pipeline a échoué")
        return 1

    log.info("Pipeline terminé en %.1f s", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
