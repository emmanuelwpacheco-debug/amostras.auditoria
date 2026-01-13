import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import fiona
import random
import io

# Habilita drivers KML
fiona.drvsupport.supported_drivers['KML'] = 'rw'

st.set_page_config(page_title="Auditoria Rodoviária", layout="wide")

st.title("🚧 Auditoria: Amostragem com Alternância de Bordos")
st.markdown("Sequência: **Direito ➔ Eixo ➔ Esquerdo**.")

# --- SIDEBAR ---
st.sidebar.header("Parâmetros Técnicos")
uploaded_file = st.sidebar.file_uploader("Carregue o KML da Rodovia", type=['kml'])
largura = st.sidebar.number_input("Largura da pista (m)", value=7.0, step=0.5)
area_min = st.sidebar.number_input("Área mínima por amostra (m²)", value=7000.0, step=100.0)
qtd_desejada = st.sidebar.number_input("Quantidade pretendida", value=50, step=1)
dist_min = st.sidebar.number_input("Distância mínima (m)", value=320.0, step=10.0)

def identificar_zonas_curvas(linha, recuo=130):
    zonas = []
    passo = 10
    for d in range(passo, int(linha.length) - passo, passo):
        p1, p2, p3 = linha.interpolate(d-passo), linha.interpolate(d), linha.interpolate(d+passo)
        v1 = np.array([p2.x-p1.x, p2.y-p1.y])
        v2 = np.array([p3.x-p2.x, p3.y-p2.y])
        norm = (np.linalg.norm(v1) * np.linalg.norm(v2))
        if norm != 0 and (np.dot(v1, v2)/norm) < 0.9995:
            zonas.append((d - recuo, d + recuo))
    return zonas

if uploaded_file:
    gdf = gpd.read_file(uploaded_file, driver='KML')
    utm_gdf = gdf.to_crs(gdf.estimate_utm_crs())
    linha_rodovia = utm_gdf.geometry.iloc[0]
    extensao = linha_rodovia.length
    
    # Cálculo da quantidade
    n_minimo = int(np.ceil((extensao * largura) / area_min))
    n_final = max(qtd_desejada, n_minimo)

    if st.sidebar.button("Gerar Amostras"):
        zonas_proibidas = identificar_zonas_curvas(linha_rodovia)
        amostras_temp = []
        tentativas = 0
        
        while len(amostras_temp) < n_final and tentativas < 50000:
            dist = random.uniform(0, extensao)
            esta_proibido = any(i <= dist <= f for i, f in zonas_proibidas)
            if not esta_proibido:
                if all(abs(dist - a['dist']) >= dist_min for a in amostras_temp):
                    amostras_temp.append({'dist': dist})
            tentativas += 1

        amostras_temp.sort(key=lambda x: x['dist'])
        sequencia_bordos = ["Bordo Direito", "Eixo", "Bordo Esquerdo"]
        dados_finais = []
        
        for i, amos in enumerate(amostras_temp):
            bordo = sequencia_bordos[i % 3]
            offset = (largura/2) if bordo == "Bordo Direito" else (-(largura/2) if bordo == "Bordo Esquerdo" else 0)
            p1, p2 = linha_rodovia.interpolate(amos['dist']), linha_rodovia.interpolate(amos['dist'] + 0.1)
            mag = np.sqrt((p2.x - p1.x)**2 + (p2.y - p1.y)**2)
            ponto_geom = Point(p1.x - (p2.y - p1.y)/mag * offset, p1.y + (p2.x - p1.x)/mag * offset)
            ponto_wgs84 = gpd.GeoSeries([ponto_geom], crs=utm_gdf.crs).to_crs(epsg=4326)[0]
            
            dados_finais.append({
                'Amostra': i + 1, 'Identificação': f"Amostra {i+1:02d}",
                'Posição Lateral': bordo, 'Quilometragem': f"km {amos['dist']/1000:.3f}",
                'Latitude': ponto_wgs84.y, 'Longitude': ponto_wgs84.x, 'geometry': ponto_geom
            })

        df_final = pd.DataFrame(dados_finais)
        st.success(f"Foram geradas {len(df_final)} amostras.")
        st.dataframe(df_final.drop(columns=['geometry']), use_container_width=True)

        col1, col2 = st.columns(2)

        # Download KML (Prioridade)
        try:
            amostras_gdf = gpd.GeoDataFrame(df_final, geometry='geometry', crs=utm_gdf.crs).to_crs(epsg=4326)
            amostras_gdf['Name'] = amostras_gdf['Identificação'] + " - " + amostras_gdf['Posição Lateral']
            buffer_kml = io.BytesIO()
            amostras_gdf[['Name', 'geometry']].to_file(buffer_kml, driver='KML')
            col1.download_button("📥 Baixar KML", buffer_kml.getvalue(), "amostras.kml")
        except Exception as e:
            st.error(f"Erro ao gerar KML: {e}")

        # Download Excel
        try:
            buffer_excel = io.BytesIO()
            df_final.drop(columns=['geometry']).to_excel(buffer_excel, index=False, engine='openpyxl')
            col2.download_button("📥 Baixar Excel", buffer_excel.getvalue(), "amostras.xlsx")
        except Exception as e:
            st.warning(f"Erro ao gerar Excel (Verifique o requirements.txt): {e}")

