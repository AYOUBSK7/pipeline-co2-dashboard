"""Tableau de bord des émissions de CO2 — lit l'entrepôt PostgreSQL.

Lancer :  streamlit run dashboard/app.py

Le tableau de bord n'interroge QUE les vues dw.v_emissions et dw.v_pays_annee :
il ne connaît pas le détail du schéma en étoile (séparation des couches).
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import bindparam, text

sys.path.append(str(Path(__file__).resolve().parent.parent))
from etl.load import creer_moteur  # noqa: E402

st.set_page_config(page_title="Émissions de CO2", page_icon="🌍", layout="wide")

# Palette catégorielle validée (ordre fixe, jamais recyclé) : chaque source
# garde TOUJOURS la même couleur, même quand un filtre en retire certaines.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
ORDRE_SOURCES = ["Charbon", "Pétrole", "Gaz naturel", "Ciment", "Torchage", "Autres industries"]
COULEUR_SOURCE = dict(zip(ORDRE_SOURCES, PALETTE))
ORDRE_CONTINENTS = ["Asie", "Amériques", "Europe", "Afrique", "Océanie"]
COULEUR_CONTINENT = dict(zip(ORDRE_CONTINENTS, PALETTE))
BLEU = PALETTE[0]
RAMPE_BLEUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

POLICE = dict(family="Inter, system-ui, sans-serif", size=13, color="#52514e")


def mise_en_forme(fig, hauteur=380):
    """Style commun : grille discrète, pas de cadre, légende en haut."""
    fig.update_layout(
        height=hauteur, margin=dict(l=10, r=10, t=30, b=10), font=POLICE,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.08, x=0, title=None),
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(showgrid=False, linecolor="#d8d7d2", title=None)
    fig.update_yaxes(gridcolor="#ecebe7", zeroline=False)
    return fig


# ----------------------------------------------------------------------
#  Accès aux données (mis en cache 10 min pour ne pas réinterroger la base)
# ----------------------------------------------------------------------
@st.cache_resource
def moteur():
    return creer_moteur()


@st.cache_data(ttl=600)
def requete(sql: str, **params) -> pd.DataFrame:
    with moteur().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


try:
    bornes = requete("SELECT MIN(annee) AS mini, MAX(annee) AS maxi FROM dw.v_pays_annee")
except Exception as exc:  # base absente ou pipeline jamais lancé
    st.error("Impossible de lire l'entrepôt. Avez-vous lancé `python -m etl.pipeline` ?")
    st.caption(str(exc))
    st.stop()

annee_min, annee_max = int(bornes.mini[0]), int(bornes.maxi[0])
continents = requete("SELECT DISTINCT continent FROM dw.v_pays_annee ORDER BY 1")["continent"].tolist()

# ----------------------------------------------------------------------
#  En-tête et filtres (une seule rangée, au-dessus des graphiques)
# ----------------------------------------------------------------------
st.title("Émissions mondiales de CO2")
st.caption(
    "Émissions fossiles et industrielles (hors usage des sols), en millions de tonnes. "
    "Source : Our World in Data (CC BY 4.0) — chargées par le pipeline ETL dans PostgreSQL."
)

f1, f2, f3 = st.columns([2, 2, 1])
periode = f1.slider("Période", annee_min, annee_max, (1990, annee_max))
choix_continents = f2.multiselect(
    "Continents", continents, default=[c for c in continents if c != "Antarctique"]
)
annee_ref = f3.selectbox("Année de référence", list(range(annee_max, annee_min - 1, -1)))

if not choix_continents:
    st.info("Sélectionnez au moins un continent.")
    st.stop()

filtre = dict(debut=periode[0], fin=periode[1], continents=tuple(choix_continents))
CLAUSE = "annee BETWEEN :debut AND :fin AND continent IN :continents"


def requete_filtree(sql: str, **extra) -> pd.DataFrame:
    """Exécute `sql` avec les filtres de la page (période, continents).

    Requête paramétrée : les valeurs ne sont jamais collées dans le texte SQL
    (protection contre l'injection SQL). « IN :continents » demande un
    paramètre « expanding » qui se déplie en IN ('Asie', 'Europe', …).
    """
    stmt = text(sql).bindparams(bindparam("continents", expanding=True))
    with moteur().connect() as conn:
        return pd.read_sql(stmt, conn, params={**filtre, **extra})


# ----------------------------------------------------------------------
#  Indicateurs clés (KPI)
# ----------------------------------------------------------------------
kpi = requete_filtree(
    """
    SELECT annee,
           SUM(co2_mt)                                   AS co2,
           SUM(co2_mt) FILTER (WHERE population IS NOT NULL) * 1e6
             / NULLIF(SUM(population), 0)                AS t_par_hab,
           COUNT(*)                                      AS nb_pays
    FROM dw.v_pays_annee
    WHERE annee IN (:ref, :ref_prec) AND continent IN :continents
    GROUP BY annee ORDER BY annee
    """,
    ref=annee_ref, ref_prec=annee_ref - 1,
)
k_ref = kpi[kpi.annee == annee_ref]
k_prec = kpi[kpi.annee == annee_ref - 1]

c1, c2, c3, c4 = st.columns(4)
if len(k_ref):
    co2 = float(k_ref.co2.iloc[0])
    delta = (co2 / float(k_prec.co2.iloc[0]) - 1) if len(k_prec) else None
    c1.metric(f"CO2 émis en {annee_ref}", f"{co2/1000:,.1f} Gt".replace(",", " "),
              f"{delta:+.1%} vs {annee_ref-1}" if delta is not None else None,
              delta_color="inverse")
    c2.metric("CO2 par habitant", f"{float(k_ref.t_par_hab.iloc[0]):.2f} t")
    c3.metric("Pays couverts", int(k_ref.nb_pays.iloc[0]))

part = requete_filtree(
    """
    SELECT SUM(co2_mt) FILTER (WHERE categorie = 'Combustible fossile') / SUM(co2_mt) AS part
    FROM dw.v_emissions WHERE annee = :ref AND continent IN :continents
    """,
    ref=annee_ref,
)
if part.part.notna().any():
    c4.metric("Part des combustibles fossiles", f"{float(part.part.iloc[0]):.0%}")

st.divider()

# ----------------------------------------------------------------------
#  1. Évolution par source d'émission (aire empilée)
# ----------------------------------------------------------------------
g1, g2 = st.columns([3, 2])

par_source = requete_filtree(
    f"SELECT annee, source, SUM(co2_mt)/1000 AS gt FROM dw.v_emissions "
    f"WHERE {CLAUSE} GROUP BY annee, source ORDER BY annee"
)
fig = px.area(
    par_source, x="annee", y="gt", color="source",
    category_orders={"source": ORDRE_SOURCES}, color_discrete_map=COULEUR_SOURCE,
    labels={"gt": "Gt CO2", "annee": "Année", "source": "Source"},
)
fig.update_traces(line=dict(width=1), hovertemplate="%{y:.2f} Gt")
fig.update_layout(hovermode="x unified")
g1.subheader("D'où viennent les émissions ?")
g1.plotly_chart(mise_en_forme(fig), width="stretch")

# ----------------------------------------------------------------------
#  2. Top 15 pays émetteurs (barres horizontales, une seule série)
# ----------------------------------------------------------------------
top = requete_filtree(
    """
    SELECT nom_pays, co2_mt, co2_t_par_hab FROM dw.v_pays_annee
    WHERE annee = :ref AND continent IN :continents
    ORDER BY co2_mt DESC LIMIT 15
    """,
    ref=annee_ref,
)
fig = px.bar(
    top.sort_values("co2_mt"), x="co2_mt", y="nom_pays", orientation="h",
    labels={"co2_mt": "Mt CO2", "nom_pays": ""}, custom_data=["co2_t_par_hab"],
)
fig.update_traces(
    marker_color=BLEU, marker_cornerradius=4,
    hovertemplate="<b>%{y}</b><br>%{x:,.0f} Mt<br>%{customdata[0]:.1f} t/hab<extra></extra>",
)
g2.subheader(f"15 premiers émetteurs en {annee_ref}")
fig = mise_en_forme(fig, 380)
fig.update_xaxes(showgrid=True, gridcolor="#ecebe7")  # barres horizontales :
fig.update_yaxes(showgrid=False)                       # grille verticale
g2.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------
#  3. Carte : CO2 par habitant (échelle séquentielle, une seule teinte)
# ----------------------------------------------------------------------
carte = requete_filtree(
    """
    SELECT code_iso3, nom_pays, co2_t_par_hab, co2_mt FROM dw.v_pays_annee
    WHERE annee = :ref AND continent IN :continents
      AND co2_t_par_hab IS NOT NULL
    """,
    ref=annee_ref,
)
fig = px.choropleth(
    carte, locations="code_iso3", color="co2_t_par_hab", hover_name="nom_pays",
    color_continuous_scale=RAMPE_BLEUE, range_color=(0, 20),
    labels={"co2_t_par_hab": "t/hab"},
    custom_data=["co2_t_par_hab", "co2_mt"],
)
fig.update_traces(
    marker_line_color="#ffffff", marker_line_width=0.5,
    hovertemplate="<b>%{hovertext}</b><br>%{customdata[0]:.2f} t par habitant"
                  "<br>%{customdata[1]:,.1f} Mt au total<extra></extra>",
)
fig.update_geos(showframe=False, showcoastlines=False, projection_type="natural earth",
                bgcolor="rgba(0,0,0,0)", lataxis_range=[-58, 85])
st.subheader(f"CO2 par habitant en {annee_ref}")
st.caption("Échelle plafonnée à 20 t/hab pour garder les écarts lisibles (quelques pays pétroliers dépassent).")
st.plotly_chart(mise_en_forme(fig, 460), width="stretch")

# ----------------------------------------------------------------------
#  4. Évolution par continent  |  5. Richesse et émissions
# ----------------------------------------------------------------------
g3, g4 = st.columns(2)

par_continent = requete_filtree(
    f"SELECT annee, continent, SUM(co2_mt)/1000 AS gt FROM dw.v_pays_annee "
    f"WHERE {CLAUSE} GROUP BY annee, continent ORDER BY annee"
)
fig = px.line(
    par_continent, x="annee", y="gt", color="continent",
    category_orders={"continent": ORDRE_CONTINENTS}, color_discrete_map=COULEUR_CONTINENT,
    labels={"gt": "Gt CO2", "annee": "Année", "continent": "Continent"},
)
fig.update_traces(line_width=2, hovertemplate="%{y:.2f} Gt")
fig.update_layout(hovermode="x unified")
g3.subheader("Émissions par continent")
g3.plotly_chart(mise_en_forme(fig), width="stretch")

nuage = requete_filtree(
    """
    SELECT nom_pays, co2_t_par_hab, pib_usd / population AS pib_par_hab, population
    FROM dw.v_pays_annee
    WHERE annee = :annee_pib AND continent IN :continents
      AND pib_usd IS NOT NULL AND population > 0
    """,
    annee_pib=min(annee_ref, 2022),
)
fig = px.scatter(
    nuage, x="pib_par_hab", y="co2_t_par_hab", size="population", hover_name="nom_pays",
    log_x=True, size_max=40,
    labels={"pib_par_hab": "PIB par habitant ($ internationaux, log)", "co2_t_par_hab": "t CO2/hab"},
)
fig.update_traces(
    marker=dict(color=BLEU, opacity=0.6, line=dict(width=1, color="#ffffff")),
    hovertemplate="<b>%{hovertext}</b><br>PIB/hab : %{x:,.0f} $<br>%{y:.1f} t/hab<extra></extra>",
)
g4.subheader(f"Richesse et émissions ({min(annee_ref, 2022)})")
g4.plotly_chart(mise_en_forme(fig), width="stretch")
if annee_ref > 2022:
    g4.caption("Le PIB n'est publié que jusqu'en 2022 : ce graphique montre 2022.")

# ----------------------------------------------------------------------
#  Données brutes + journal des chargements
# ----------------------------------------------------------------------
with st.expander("Voir les données (vue dw.v_pays_annee)"):
    tableau = requete_filtree(
        f"SELECT annee, nom_pays, continent, co2_mt, population, co2_t_par_hab "
        f"FROM dw.v_pays_annee WHERE {CLAUSE} ORDER BY annee DESC, co2_mt DESC"
    )
    st.dataframe(tableau, width="stretch", hide_index=True)
    st.download_button("Télécharger en CSV", tableau.to_csv(index=False).encode("utf-8"),
                       "emissions_co2.csv", "text/csv")

dernier = requete(
    "SELECT fin, nb_faits_emis FROM meta.journal_chargement "
    "WHERE statut = 'SUCCES' ORDER BY run_id DESC LIMIT 1"
)
if len(dernier):
    st.caption(
        f"Dernier chargement réussi : {dernier.fin[0]:%d/%m/%Y %H:%M} — "
        f"{int(dernier.nb_faits_emis[0]):,} faits d'émission.".replace(",", " ")
    )
