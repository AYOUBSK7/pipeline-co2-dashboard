# Guide d'explication du projet

Ce guide explique **chaque idée** du projet, dans l'ordre où les données circulent. À la fin, vous devez pouvoir présenter le projet à l'oral et répondre aux questions d'un recruteur ou d'un jury.

---

## 1. Le projet en une phrase

On récupère automatiquement des données publiques sur les émissions de CO2, on les **nettoie** et on les **range** dans une base conçue pour l'analyse, puis on affiche des **indicateurs** dans un tableau de bord.

```
Données ouvertes  ──►  Pipeline Python  ──►  Entrepôt PostgreSQL  ──►  Tableau de bord
 (fichiers CSV)       (extract, transform,    (schéma en étoile)       (Streamlit)
                       contrôles, load)
```

---

## 2. Le vocabulaire de base

### ETL = Extract, Transform, Load

| Étape | Question | Dans le projet |
|---|---|---|
| **Extract** | Où sont les données ? | Télécharger deux CSV depuis GitHub (`etl/extract.py`) |
| **Transform** | Comment les rendre utilisables ? | Retirer les agrégats, compléter les codes, joindre les continents, dépivoter (`etl/transform.py`) |
| **Load** | Où les ranger ? | Les écrire dans PostgreSQL (`etl/load.py` + `sql/`) |

On ajoute entre T et L une étape de **contrôles qualité** (`etl/quality.py`) : on ne charge que des données vérifiées.

> C'est exactement ce que fait Pentaho Data Integration (Spoon) avec ses transformations et ses jobs, mais ici **écrit en code**. Avantages du code : versionnable avec Git, testable automatiquement, relisible par n'importe quel développeur.

### Base transactionnelle (OLTP) vs entrepôt de données (OLAP)

| | Base transactionnelle (OLTP) | Entrepôt de données (OLAP) |
|---|---|---|
| Rôle | Faire tourner une application (inscriptions, commandes…) | **Analyser** l'historique |
| Opérations | Beaucoup de petits INSERT/UPDATE | Peu d'écritures, grosses requêtes `GROUP BY` |
| Modèle | Normalisé (3FN), beaucoup de tables | **Dénormalisé** : schéma en étoile |
| Exemple | La base de votre application de réservation de salles | Ce projet |

### Zone de transit (*staging*)

Une zone tampon où l'on dépose les données **juste avant** de les intégrer à l'entrepôt. Ici c'est le schéma PostgreSQL `staging`. On y écrit sans contrainte, puis le SQL recopie proprement vers `dw`.

---

## 3. Les données sources

### Source 1 : Our World in Data (OWID) — `owid-co2-data.csv`

~50 000 lignes, 79 colonnes. **Une ligne = un « pays » et une année.**

```
country | year | iso_code | population | gdp  | co2   | coal_co2 | oil_co2 | gas_co2 | …
France  | 2022 | FRA      | 66277412   | 3e12 | 295.3 | 26.2     | 179.3   | 78.0    | …
World   | 2022 |          | 7.9e9      | …    | 37000 | …
```

**Problèmes découverts en explorant les données** (c'est l'étape la plus importante d'un projet data — on ne conçoit rien avant d'avoir regardé) :

1. Le fichier mélange **pays et agrégats** (« World », « Africa », « High-income countries », « European Union (27) »…). Si on les garde, on compte la France 3 fois (France + Europe + World). → Les agrégats n'ont **pas de code ISO à 3 lettres** : c'est notre critère de filtre.
2. Le **Kosovo** est un vrai pays mais n'a pas de code ISO dans le fichier. → On lui attribue `XKX` (usage UE / Banque mondiale).
3. Les données avant 1950 sont très incomplètes. → On garde 1950–2024 (paramètre `ANNEE_MIN`).
4. Valeurs manquantes : le PIB s'arrête en 2022, certaines sources ne sont pas mesurées pour certains pays. → Une valeur absente n'est **pas** un zéro : on ne l'invente pas.
5. Bonne nouvelle vérifiée : charbon + pétrole + gaz + torchage + ciment + autres = `co2` total, à l'arrondi près. → Ça devient un **contrôle qualité**.

### Source 2 : codes ISO 3166 — `iso_regions.csv`

Une ligne par pays avec son code ISO alpha-3, son continent et sa sous-région. Elle sert à **enrichir** les pays OWID (qui n'ont pas de continent).

Pièges rencontrés :
- **Taïwan** et l'**Antarctique** n'ont pas de continent dans ce fichier → complétés à la main (`REGIONS_MANUELLES`).
- Le code alpha-2 de la Namibie est `"NA"`, que pandas lit par défaut comme *valeur manquante* ! → `keep_default_na=False` à la lecture.

> En entretien, raconter ce genre de détail montre que vous avez **vraiment** manipulé les données.

---

## 4. Le schéma en étoile

### Faits et dimensions

Une question d'analyse ressemble toujours à :
**« Combien** de CO2 (*mesure*) **par** pays, **par** année, **par** source (*axes d'analyse*) ? »

- Les **mesures** (des nombres qu'on additionne) vont dans une **table de faits**.
- Les **axes d'analyse** (le contexte : qui, quand, quoi) vont dans des **tables de dimensions**.

```
                 ┌────────────┐
                 │ dim_annee  │
                 └─────┬──────┘
┌────────────┐   ┌─────┴──────────┐   ┌────────────┐
│ dim_pays   ├───┤ fait_emissions ├───┤ dim_source │
└────────────┘   └────────────────┘   └────────────┘
```

La table de faits au centre, les dimensions autour : d'où le nom **étoile**.

### Le grain

Le **grain**, c'est ce que représente **une ligne** de la table de faits. C'est la première décision à prendre.

- `fait_emissions` : **1 pays × 1 année × 1 source** → ex. « France, 2022, pétrole : 179,3 Mt ».
- `fait_indicateurs_pays` : **1 pays × 1 année** → ex. « France, 2022 : 66 M habitants, PIB… ».

**Pourquoi deux tables de faits ?** La population n'a pas de « source d'émission ». Si on la mettait dans `fait_emissions`, elle serait répétée 6 fois (une par source), et un `SUM(population)` donnerait 6 fois la vraie population. Règle : **une table de faits = un seul grain**.

Les deux tables partagent `dim_pays` et `dim_annee` : on dit que ce sont des **dimensions conformes**. On peut ainsi croiser les deux faits (CO2 par habitant).

### Mesure additive

`co2_mt` est **additive** : on peut la sommer selon n'importe quelle dimension (total d'un continent, d'une décennie, toutes sources…). La population, elle, est **semi-additive** : on peut sommer les pays, mais pas les années (additionner la population de 2021 et 2022 n'a pas de sens).

### Clé de substitution vs clé naturelle

| | Clé naturelle | Clé de substitution |
|---|---|---|
| Exemple | `code_iso3 = 'FRA'` | `pays_key = 67` |
| Vient de | La source (le métier) | L'entrepôt (`SERIAL`) |
| Rôle | Retrouver la ligne lors du chargement | Faire les jointures faits ↔ dimensions |

Pourquoi ne pas utiliser `'FRA'` directement comme clé ? Parce que l'entrepôt ne doit pas dépendre des choix de la source : si demain une source code la France `'FR'`, seules les clés naturelles changent, pas les millions de lignes de faits. Et un entier se joint plus vite qu'un texte.

**Exception classique** : pour le temps, on utilise une clé « intelligente » : `annee_key = 2022`. C'est lisible et l'année ne changera jamais.

### Pourquoi ce modèle est rapide pour l'analyse

Toute question se résout avec **une table de faits + des jointures directes** sur les dimensions, puis un `GROUP BY`. Pas de chaîne de 6 jointures comme dans un modèle très normalisé.

```sql
-- Émissions de l'Afrique du Nord par source en 2024
SELECT s.libelle, SUM(f.co2_mt)
FROM dw.fait_emissions f
JOIN dw.dim_pays   p ON p.pays_key   = f.pays_key
JOIN dw.dim_source s ON s.source_key = f.source_key
WHERE p.sous_region = 'Afrique du Nord' AND f.annee_key = 2024
GROUP BY s.libelle;
```

---

## 5. Le pipeline, fichier par fichier

### `etl/config.py` — la configuration

Tout ce qui peut changer (adresse de la base, mot de passe, URL, année minimum) est **en dehors du code**, dans le fichier `.env`. Ce fichier est dans `.gitignore` : **le mot de passe n'est jamais publié sur GitHub**. On publie seulement `.env.example`, un modèle sans secret.

### `etl/extract.py` — Extract

- `requests.get(...)` télécharge le fichier ; `raise_for_status()` arrête tout si le serveur répond une erreur (404, 500).
- Le fichier est **sauvegardé** dans `data/raw/` avant d'être lu. Si la suite plante, on relance sans re-télécharger, et on garde une trace exacte de ce qu'on a reçu.
- Aucune modification ici : l'extraction ne fait **que** récupérer.

### `etl/transform.py` — Transform

Toutes les fonctions sont **pures** : DataFrame en entrée, DataFrame en sortie, pas de base, pas de réseau. C'est ce qui les rend **testables**.

| Fonction | Ce qu'elle fait | Notion pandas |
|---|---|---|
| `nettoyer_co2` | Garde les vrais pays depuis 1950, complète le Kosovo, supprime les doublons | filtre booléen, `str.fullmatch`, `drop_duplicates` |
| `construire_dim_pays` | Joint les continents, traduit en français, complète les cas manquants | `merge(how="left")`, `map` |
| `construire_dim_annee` | Ajoute décennie et période climatique | liste en compréhension |
| `construire_fait_emissions` | Passe du format **large** au format **long** | `melt` |
| `construire_fait_indicateurs` | Population, PIB, énergie | `Int64` (entier nullable) |

**Le dépivotage (`melt`)**, transformation clé du projet :

```
AVANT (large)                             APRÈS (long)
iso | année | coal_co2 | oil_co2 | …      iso | année | source  | co2_mt
FRA | 2022  | 26.2     | 179.3   |        FRA | 2022  | charbon | 26.2
                                          FRA | 2022  | petrole | 179.3
                                          …
```

Pourquoi ? Dans le format large, la **source** est cachée dans le nom des colonnes : impossible de faire `GROUP BY source`. Dans le format long, c'est une vraie colonne, donc une vraie dimension. Et ajouter une nouvelle source = ajouter des lignes, pas modifier la structure de la table.

**`merge(how="left")`** : jointure gauche, on garde **tous** les pays OWID même s'ils n'ont pas de correspondance dans le fichier ISO. Avec une jointure interne (`inner`), Taïwan aurait disparu **silencieusement**. Ensuite on vérifie explicitement qui n'a pas de continent.

### `etl/quality.py` — Contrôles qualité

| Contrôle | Type | Pourquoi |
|---|---|---|
| Pas de doublon sur le grain | Bloquant | Sinon les sommes sont fausses |
| Chaque fait a son pays et son année dans les dimensions | Bloquant | Intégrité référentielle |
| Pas d'émission négative, pas de population ≤ 0 | Bloquant | Valeurs impossibles |
| Somme des sources ≈ total publié (±1 %) | Avertissement | Détecte une source oubliée ou mal mappée |
| Taux de PIB renseigné | Avertissement | Information sur la complétude |

Un contrôle bloquant lève `ErreurQualite` : le pipeline s'arrête **avant** d'écrire en base.

### `etl/load.py` + `sql/` — Load

1. **`01_schema.sql`** crée les schémas et les tables avec `IF NOT EXISTS` (on peut le relancer sans erreur).
2. pandas dépose chaque DataFrame dans `staging` avec `to_sql`. Pour aller vite, on utilise la commande **`COPY`** de PostgreSQL (une seule opération pour 60 000 lignes) au lieu de 60 000 `INSERT`.
3. **`02_staging_vers_dw.sql`** :
   - **Dimensions : upsert** (`INSERT … ON CONFLICT (clé naturelle) DO UPDATE`). Un nouveau pays est inséré, un pays connu est mis à jour : **sa `pays_key` ne change jamais**.
   - **Faits : rechargement complet** (`TRUNCATE` puis `INSERT … SELECT`). OWID révise aussi les anciennes années à chaque publication, donc on remplace tout. Les clés de substitution sont retrouvées par **jointure sur la clé naturelle** (`code_iso3`, `code_source`).
4. **`03_vues.sql`** crée les vues utilisées par le tableau de bord.

Les étapes 2 à 4 sont dans **une seule transaction** (`with moteur.begin()`) : si une instruction échoue, PostgreSQL annule tout (*rollback*). L'entrepôt n'est **jamais à moitié chargé**.

#### L'idempotence

Un pipeline est **idempotent** si l'exécuter 1 fois ou 10 fois donne le **même** résultat. Ici : upsert des dimensions + remplacement des faits ⇒ aucune ligne en double, aucune clé qui change. C'est indispensable : en production, un pipeline est relancé après chaque panne.

#### Le journal

Chaque exécution écrit une ligne dans `meta.journal_chargement` : début, fin, statut (`SUCCES` / `ECHEC`), nombre de lignes, message d'erreur. Le tableau de bord affiche la date du dernier chargement réussi.

### `etl/pipeline.py` — l'orchestration

Il enchaîne les étapes, écrit des **logs** horodatés (pas de `print`) et renvoie un code de sortie (0 = succès, 1 = échec), ce qui permet à un planificateur (cron, GitHub Actions) de savoir si ça a marché.

---

## 6. Les vues et le tableau de bord

### Pourquoi des vues ?

Le tableau de bord n'interroge **que** `dw.v_emissions` et `dw.v_pays_annee`. Les jointures de l'étoile sont cachées dans les vues. Si on change le modèle, on adapte la vue, pas le code du tableau de bord : c'est la **séparation des couches**.

`v_pays_annee` calcule aussi les **ratios** :
- CO2 par habitant = `co2_mt × 1 000 000 / population` (Mt → tonnes)
- Intensité carbone = kg de CO2 par dollar de PIB

`NULLIF(population, 0)` évite une division par zéro.

### Le tableau de bord (`dashboard/app.py`)

| Élément | Question à laquelle il répond | Type de visuel et pourquoi |
|---|---|---|
| Indicateurs (KPI) | Combien cette année ? En hausse ou en baisse ? | Grands chiffres : une seule valeur n'a pas besoin de graphique |
| Aire empilée par source | D'où viennent les émissions et comment ça évolue ? | Aire empilée : évolution du total **et** de sa composition |
| Top 15 | Qui émet le plus ? | Barres horizontales triées : noms de pays lisibles |
| Carte | Où émet-on le plus **par habitant** ? | Carte avec une seule couleur du clair au foncé (intensité) |
| Lignes par continent | Quels continents tirent la hausse ? | Courbes : comparer des tendances |
| Nuage PIB / CO2 | Les pays riches émettent-ils plus par habitant ? | Nuage de points, PIB en échelle log, taille = population |

Bonnes pratiques appliquées :
- **Une couleur = une catégorie, toujours la même** (le charbon est toujours bleu, même si on filtre).
- **Pas de double axe Y** : deux mesures d'échelles différentes → deux graphiques.
- **Requêtes paramétrées** (`:debut`, `:continents`) : les valeurs choisies par l'utilisateur ne sont jamais collées dans le texte SQL → protection contre l'**injection SQL**.
- **Cache** (`@st.cache_data`) : une même requête n'est pas réexécutée à chaque clic.
- Infobulle au survol sur chaque graphique, table de données téléchargeable en CSV.

> Remarque : la carte a besoin d'Internet pour télécharger le fond de carte (cdn.plot.ly).

---

## 7. Les tests et l'intégration continue

### Tests unitaires (`tests/test_transform.py`)

On fabrique un **mini-jeu de données à la main** (France, Tunisie, World, Kosovo…) dont on connaît le résultat attendu, puis on vérifie :
- que « World » est bien retiré et le Kosovo reçoit `XKX` ;
- que le `melt` produit 6 lignes par pays et par année ;
- qu'une valeur manquante ne devient pas un zéro ;
- que la somme des sources égale le total ;
- que les contrôles qualité **bloquent** bien des doublons et des valeurs négatives.

```bash
pytest -v
```

### GitHub Actions (`.github/workflows/ci.yml`)

À chaque `git push`, GitHub démarre une machine virtuelle avec un PostgreSQL, installe les dépendances, lance les tests **puis le pipeline complet**. Un badge vert/rouge indique si le projet fonctionne. C'est une preuve concrète pour un recruteur.

---

## 8. Requêtes d'analyse à essayer (OLAP en SQL)

```sql
-- Émissions par continent et par décennie, avec sous-totaux (ROLLUP)
SELECT p.continent, a.decennie, ROUND(SUM(f.co2_mt)) AS co2_mt
FROM dw.fait_emissions f
JOIN dw.dim_pays  p ON p.pays_key  = f.pays_key
JOIN dw.dim_annee a ON a.annee_key = f.annee_key
WHERE a.decennie >= 1990
GROUP BY ROLLUP (p.continent, a.decennie)
ORDER BY p.continent, a.decennie;

-- Classement des pays par CO2 par habitant en 2024 (fonction de fenêtrage)
SELECT nom_pays, co2_t_par_hab,
       RANK() OVER (ORDER BY co2_t_par_hab DESC) AS rang
FROM dw.v_pays_annee
WHERE annee = 2024 AND population > 1000000
LIMIT 20;

-- Évolution annuelle de la Tunisie (LAG = valeur de l'année précédente)
SELECT annee, co2_mt,
       ROUND(100 * (co2_mt / LAG(co2_mt) OVER (ORDER BY annee) - 1), 1) AS variation_pct
FROM dw.v_pays_annee
WHERE code_iso3 = 'TUN'
ORDER BY annee DESC;

-- Part de chaque source dans le total mondial, par période climatique
SELECT a.periode, s.libelle,
       ROUND(100 * SUM(f.co2_mt) / SUM(SUM(f.co2_mt)) OVER (PARTITION BY a.periode), 1) AS part_pct
FROM dw.fait_emissions f
JOIN dw.dim_annee  a ON a.annee_key  = f.annee_key
JOIN dw.dim_source s ON s.source_key = f.source_key
GROUP BY a.periode, s.libelle
ORDER BY a.periode, part_pct DESC;
```

---

## 9. Questions qu'on peut vous poser (et réponses)

**Pourquoi un schéma en étoile plutôt qu'un modèle normalisé ?**
Parce que l'objectif est l'analyse : des requêtes d'agrégation simples et rapides, avec une seule couche de jointures entre faits et dimensions. La redondance (le continent répété sur chaque pays) est acceptée car l'entrepôt est surtout lu.

**Quel est le grain de votre table de faits ?**
Un pays, une année, une source d'émission. Les indicateurs démographiques ont un autre grain (pays × année), d'où une deuxième table de faits avec des dimensions conformes.

**Pourquoi des clés de substitution ?**
Pour isoler l'entrepôt des codes de la source, et pour des jointures sur des entiers. La clé naturelle (code ISO) sert à les retrouver lors du chargement.

**Que se passe-t-il si le pipeline plante au milieu ?**
Le chargement est dans une transaction : PostgreSQL annule tout. L'erreur est inscrite dans le journal avec le statut `ECHEC`. On corrige et on relance : le pipeline est idempotent.

**Comment garantissez-vous la qualité des données ?**
Contrôles avant chargement (unicité du grain, intégrité référentielle, valeurs plausibles, cohérence avec le total publié), tests unitaires, et la CI qui exécute le pipeline à chaque modification.

**Chargement complet ou incrémental ?**
Complet pour les faits, car la source révise l'historique et le volume est faible (60 000 lignes en ~2 s). Pour un gros volume, on passerait à un chargement incrémental (uniquement les nouvelles années ou les lignes modifiées).

**Pourquoi pandas et pas Pentaho ?**
Le code se versionne avec Git, se teste automatiquement, se relit en revue de code et tourne partout où il y a Python. Pentaho est plus visuel, mais moins adapté à l'intégration continue.

**Et si les données devenaient 1000 fois plus grosses ?**
pandas charge tout en mémoire : on passerait à un traitement par morceaux (`chunksize`), à Polars ou Spark, et on ferait davantage de transformations directement en SQL dans la base (approche ELT, par exemple avec dbt).

---

## 10. Mettre le projet sur GitHub

```bash
# Une seule fois : se présenter à Git
git config --global user.name  "Ayoub Boussoukaya"
git config --global user.email "votre-email@exemple.com"

# Dans le dossier du projet
git init
git add .
git commit -m "Pipeline ETL CO2 et tableau de bord"
git branch -M main

# Créer d'abord un dépôt VIDE sur github.com (bouton « New », sans README),
# puis :
git remote add origin https://github.com/<votre-compte>/pipeline-co2-dashboard.git
git push -u origin main
```

Vérifiez avant de pousser que `.env` **n'apparaît pas** dans `git status` (il est ignoré grâce à `.gitignore`).
