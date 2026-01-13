import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import fiona
import random
import io

# ATENÇÃO: Habilita o suporte a KML explicitamente
fiona.drvsupport.supported_drivers['KML'] = 'rw'
fiona.drvsupport.supported_drivers['LIBKML'] = 'rw'

st.set_page_config(page_title="Auditoria Rodoviária", layout="wide")

st.title("🚧 Auditoria: Amostragem com Alternância de Bordos")
st.markdown("Geração de pontos sequenciais: **Direito ➔ Eixo ➔ Esquerdo**.")

# --- SIDEBAR ---
st.sidebar.header("Parâmetros Técnicos")
uploaded_file = st.sidebar.file_uploader("Carregue o KML da Rodovia", type=['kml'])
largura = st.sidebar.number_input("Largura da pista (m)", value=7.0, step=0.5)
area_min = st.sidebar.number_input("Área mínima por amostra (m²)", value=3000.0, step=100.0)
qtd_desejada = st.sidebar.number_input("Quantidade mínima", value=5, step=1)
dist_min = st.sidebar.number_input("Distância mínima (m)", value=130.0, step=10.0)
recuo_curva = 130.0

# --- FUNÇÕES AUXILIARES ---
def identificar_zonas_curvas(linha, recuo):
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

# --- PROCESSAMENTO ---
if uploaded_file:
    try:
        gdf = gpd.read_file(uploaded_file, driver='KML')
        utm_gdf = gdf.to_crs(gdf.estimate_utm_crs())
        linha_rodovia = utm_gdf.geometry.iloc[0]
        extensao = linha_rodovia.length
        
        n_minimo = int(np.ceil((extensao * largura) / area_min))
        n_final = max(qtd_desejada, n_minimo)

        if st.sidebar.button("Gerar Amostras"):
            zonas_proibidas = identificar_zonas_curvas(linha_rodovia, recuo_curva)
            amostras_temp = []
            tentativas = 0
            
            while len(amostras_temp) < n_final and tentativas < 30000:
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
                dx, dy = p2.x - p1.x, p2.y - p1.y
                mag = np.sqrt(dx**2 + dy**2)
                ponto_geom = Point(p1.x - dy/mag * offset, p1.y + dx/mag * offset)
                
                ponto_wgs84 = gpd.GeoSeries([ponto_geom], crs=utm_gdf.crs).to_crs(epsg=4326)[0]
                
                dados_finais.append({
                    'Amostra': i + 1,
                    'Identificação': f"Amostra {i+1:02d}",
                    'Posição Lateral': bordo,
                    'Quilometragem': f"km {amos['dist']/1000:.3f}",
                    'Latitude': ponto_wgs84.y,
                    'Longitude': ponto_wgs84.x,
                    'geometry': ponto_geom
                })

            df_final = pd.DataFrame(dados_finais)

            st.success(f"Foram geradas {len(df_final)} amostras.")
            st.dataframe(df_final.drop(columns=['geometry']), use_container_width=True)

            # --- PREPARAÇÃO DOS ARQUIVOS PARA DOWNLOAD ---
            
            # 1. EXCEL
            buffer_excel = io.BytesIO()
            with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                df_final.drop(columns=['geometry']).to_excel(writer, index=False)
            
            # 2. KML (Ajuste de gravação para Streamlit)
            amostras_gdf = gpd.GeoDataFrame(df_final, geometry='geometry', crs=utm_gdf.crs).to_crs(epsg=4326)
            amostras_gdf['Name'] = amostras_gdf['Identificação'] + " - " + amostras_gdf['Posição Lateral'] + " (" + amostras_gdf['Quilometragem'] + ")"
            amostras_gdf['Description'] = "Local de coleta: " + amostras_gdf['Posição Lateral']
            
            # Usamos uma string KML temporária para evitar erros de driver direto no buffer
            try:
                kml_data = amostras_gdf[['Name', 'Description', 'geometry']].to_json() # Backup em JSON se KML falhar
                
                # Tentativa de gerar KML puro
                buffer_kml = io.BytesIO()
                amostras_gdf[['Name', 'Description', 'geometry']].to_file(buffer_kml, driver='KML')
                kml_bytes = buffer_kml.getvalue()
            except:
                # Se o driver KML falhar no servidor, geramos um GeoJSON (que o Google Earth também abre)
                buffer_kml = io.BytesIO()
                amostras_gdf[['Name', 'Description', 'geometry']].to_file(buffer_kml, driver='GeoJSON')
                kml_bytes = buffer_kml.getvalue()
                st.warning("Nota: O arquivo foi gerado em formato GeoJSON para compatibilidade. O Google Earth abre este arquivo normalmente.")

            col1, col2 = st.columns(2)
            col1.download_button("📥 Baixar Planilha Excel", buffer_excel.getvalue(), "amostras.xlsx")
            col2.download_button("📥 Baixar Pontos (KML/GeoJSON)", kml_bytes, "amostras_campo.kml")

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
