#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
from typing import Dict, Any, List

import requests
import folium


def fetch_regions_geojson() -> Dict[str, Any]:
    """
    Récupère les régions de France, d'abord via geo.api.gouv.fr (GeoJSON),
    puis via des sources publiques de secours si nécessaire.
    """
    candidate_urls: List[str] = [
        # Essais geo.api.gouv.fr (avec variantes de paramètres)
        "https://geo.api.gouv.fr/regions?format=geojson&geometry=contour&projection=WGS84",
        "https://geo.api.gouv.fr/regions?format=geojson&geometry=contours&projection=WGS84",
        "https://geo.api.gouv.fr/regions?format=geojson&geometry=contour",
        "https://geo.api.gouv.fr/regions?format=geojson&geometry=contours",
        "https://geo.api.gouv.fr/regions?format=geojson",
        "https://geo.api.gouv.fr/regions?projection=WGS84&format=geojson",
    ]
    last_err: Exception | None = None

    for url in candidate_urls:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("features"):
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    # Fallback: jeux de données GeoJSON publics (mêmes régions, géométries propres)
    fallbacks: List[str] = [
        "https://france-geojson.gregoiredavid.fr/repo/regions.geojson",
        "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/regions.geojson",
    ]
    for url in fallbacks:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("features"):
                # Normalisation basique des propriétés pour s'aligner sur geo.api (nom/code)
                for feat in data.get("features", []):
                    props = feat.get("properties", {}) or {}
                    if "nom" not in props and "name" in props:
                        props["nom"] = props["name"]
                    if "code" not in props:
                        for key in ("code_insee", "code_region", "id"):
                            if key in props:
                                props["code"] = props[key]
                                break
                    feat["properties"] = props
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    raise SystemExit(
        "Impossible de récupérer les régions (geo.api.gouv.fr et sources de secours indisponibles). "
        f"Dernière erreur: {last_err}"
    )


def enrich_regions_metadata(geojson: Dict[str, Any]) -> None:
    """
    Enrichit chaque région avec des infos indicatives (population, surface, densité, part de pop.).
    Valeurs approximatives (ordre de grandeur) pour démonstration.
    """
    mapping = {
        "Île-de-France": {"population": 12271794, "surface_km2": 12012},
        "Auvergne-Rhône-Alpes": {"population": 8078271, "surface_km2": 69711},
        "Nouvelle-Aquitaine": {"population": 6073000, "surface_km2": 84036},
        "Occitanie": {"population": 5999000, "surface_km2": 72724},
        "Grand Est": {"population": 5549000, "surface_km2": 57441},
        "Hauts-de-France": {"population": 6006000, "surface_km2": 31813},
        "Provence-Alpes-Côte d'Azur": {"population": 5098000, "surface_km2": 31400},
        "Pays de la Loire": {"population": 3883000, "surface_km2": 32082},
        "Bretagne": {"population": 3420000, "surface_km2": 27208},
        "Centre-Val de Loire": {"population": 2573000, "surface_km2": 39151},
        "Bourgogne-Franche-Comté": {"population": 2807000, "surface_km2": 47784},
        "Normandie": {"population": 3330000, "surface_km2": 29906},
        "Corse": {"population": 351000, "surface_km2": 8680},
        "Guadeloupe": {"population": 376000, "surface_km2": 1628},
        "Martinique": {"population": 353000, "surface_km2": 1128},
        "Guyane": {"population": 294000, "surface_km2": 83846},
        "La Réunion": {"population": 859000, "surface_km2": 2512},
        "Mayotte": {"population": 310000, "surface_km2": 376},
    }
    total_pop = sum(v["population"] for v in mapping.values())
    for feat in geojson.get("features", []):
        props = feat.get("properties", {}) or {}
        name = props.get("nom") or props.get("name")
        meta = mapping.get(name)
        if meta:
            pop = int(meta["population"])
            surf = float(meta["surface_km2"])
            dens = round(pop / surf, 1) if surf else None
            props["population"] = pop
            props["surface_km2"] = surf
            props["densite_km2"] = dens
            if total_pop:
                props["part_population_pct"] = round(100 * pop / total_pop, 2)
        feat["properties"] = props


def build_map(geojson: Dict[str, Any], out_file: str = "index.html") -> None:
    """
    Construit une carte Folium centrée sur la France avec les polygones des régions.
    - Survol: mise en évidence
    - Clic: redirection vers Régions/NOM.HTML
    - Infobulle: nom et code de la région
    """
    # Carte de base
    m = folium.Map(
        location=[46.6, 2.5],
        zoom_start=5,
        tiles="CartoDB positron",  # carte claire, lisible
        control_scale=True,
        prefer_canvas=True,
        min_zoom=4,
        max_zoom=12,
    )

    # Style des régions
    def density_color(d):
        try:
            d = float(d)
        except (TypeError, ValueError):
            return "#2E6EEA"
        if d < 50:
            return "#D4EEFF"
        if d < 100:
            return "#9BD1FF"
        if d < 150:
            return "#6FB2FF"
        if d < 250:
            return "#3D7CFF"
        if d < 500:
            return "#2E6EEA"
        return "#1F4DBF"

    def style_function(feature: Dict[str, Any]) -> Dict[str, Any]:
        dens = (feature.get("properties") or {}).get("densite_km2")
        return {
            "fillColor": density_color(dens),
            "color": "#1F4DBF",
            "weight": 1,
            "fillOpacity": 0.35,
        }

    def highlight_function(feature: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "weight": 3,
            "fillOpacity": 0.55,
            "color": "#3D7CFF",
        }

    enrich_regions_metadata(geojson)

    tooltip = folium.GeoJsonTooltip(fields=["nom", "code"], aliases=["Région", "Code"], sticky=True)

    popup = folium.GeoJsonPopup(
        fields=["nom", "code", "population", "surface_km2", "densite_km2", "part_population_pct"],
        aliases=["Région", "Code", "Population", "Surface (km²)", "Densité (hab/km²)", "Part pop. (%)"],
        localize=True,
        labels=True,
    )

    gj = folium.GeoJson(
        geojson,
        name="Régions",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=tooltip,
        popup=popup,
        embed=False,
    )
    gj.add_to(m)

    # Adapter la vue aux limites des régions si disponible
    try:
        # Centrage explicite sur la France métropolitaine
        m.fit_bounds([[41.0, -5.5], [51.5, 10.0]])
    except Exception:  # noqa: BLE001
        pass

    # Bandeau d'instructions
    title_html = """
    <div style="position: fixed; top: 12px; left: 12px; right: 12px; z-index: 9999;
                 max-width: 680px;
                 background: rgba(11,19,32,0.78); color: #eaeef7; padding: 12px 14px;
                 border-radius: 10px; border: 1px solid rgba(255,255,255,0.25);
                 font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell;
                 font-size: 14px;">
      <div style="font-size:16px; font-weight:600; margin-bottom:4px;">
        Qualité de l’eau potable en France — Carte interactive
      </div>
      <div style="opacity:.95; line-height:1.35;">
        Visualisation agrégée par région sur les 12 derniers mois.
        Survolez une région pour la mettre en évidence, puis cliquez pour ouvrir la page
        régionale correspondante&nbsp;: <b>Régions/NOM_DE_LA_RÉGION.HTML</b>.
      </div>
    </div>"""
    m.get_root().html.add_child(folium.Element(title_html))
    legend_html = """
    <div style="position: fixed; bottom: 12px; left: 12px; z-index: 9999;
                background: rgba(11,19,32,0.78); color: #eaeef7; padding: 10px 12px;
                border-radius: 10px; border: 1px solid rgba(255,255,255,0.25);
                font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell;
                font-size: 12px; line-height: 1.2;">
      <div style="font-weight:600; margin-bottom:6px;">Densité (hab/km²)</div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#D4EEFF;border:1px solid #1F4DBF33;"></span><span>< 50</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#9BD1FF;border:1px solid #1F4DBF33;"></span><span>50–100</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#6FB2FF;border:1px solid #1F4DBF33;"></span><span>100–150</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#3D7CFF;border:1px solid #1F4DBF33;"></span><span>150–250</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#2E6EEA;border:1px solid #1F4DBF33;"></span><span>250–500</span>
      </div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="display:inline-block;width:18px;height:12px;background:#1F4DBF;border:1px solid #1F4DBF33;"></span><span>≥ 500</span>
      </div>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))

    # Script pour la navigation au clic (Leaflet)
    map_id = m.get_name()
    js = f"""
    <script>
    window.addEventListener('load', function() {{
      var map = window['{map_id}'] || {map_id};

      // Centrer la vue sur la France métropolitaine (sans restreindre la navigation)
      try {{
        if (map && typeof L !== 'undefined' && L.latLngBounds) {{
          var frMetropole = L.latLngBounds([[41.0, -5.5], [51.5, 10.0]]);
          map.fitBounds(frMetropole, {{ padding: [20, 20] }});
        }}
      }} catch (e) {{}}

      function attach(layer) {{
        if (!layer) return;
        var f = layer.feature;
        if (f && f.properties && f.properties.nom) {{
          layer.on('click', function() {{
            var nom = f.properties.nom;
            var url = "Régions/" + encodeURIComponent(nom) + ".HTML";
            window.location.href = url;
          }});
          layer.on('mouseover', function() {{
            try {{ map.getContainer().style.cursor = 'pointer'; }} catch(e) {{}}
          }});
          layer.on('mouseout', function() {{
            try {{ map.getContainer().style.cursor = ''; }} catch(e) {{}}
          }});
        }}
      }}
      if (map && typeof map.eachLayer === 'function') {{
        map.eachLayer(function(l) {{
          if (typeof l.eachLayer === 'function') {{
            l.eachLayer(function(sl) {{ attach(sl); }});
          }} else {{
            attach(l);
          }}
        }});
      }}
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(js))

    folium.LayerControl(collapsed=True).add_to(m)
    m.save(out_file)
    print(f"Carte générée dans: {out_file}")


def main() -> None:
    # S'assurer que le dossier des pages régionales existe
    os.makedirs("Régions", exist_ok=True)

    # Construire la carte principale
    geojson = fetch_regions_geojson()
    build_map(geojson, out_file="index.html")


if __name__ == "__main__":
    main()
