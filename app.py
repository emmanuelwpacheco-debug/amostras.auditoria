import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import fiona
import random
import io

# Configuração de drivers para KML
fiona.drvsupport.supported_drivers['KML'] = 'rw'

st.set_page_config(page_title="Auditoria Rodoviária", layout="wide")

st.title("Auditoria: Amostragem Aleatória Sequencial")
st.markdown("Geração de pontos com alternância de bordos: **Direito ➔ Eixo ➔ Esquerdo**.")

# --- SIDEBAR (Entradas do Usuário) ---
st.sidebar.header("Parâmetros Técnicos")
uploaded_file = st.sidebar.file_uploader("Carregue o KML da Rodovia", type=['kml'])
largura = st.sidebar.number_input("Largura da pista (m)", value=7.0, step=0.5)
area_min = st.sidebar.number_input("Área mínima por amostra (m²)", value=3000.0, step=100.0)
qtd_desejada = st.sidebar.number_input("Quantidade mínima de amostras", value=5, step=1)
dist_min = st.sidebar.number_input("Distância mínima entre amostras (m)", value=130.0, step=10.0)
recuo_curva = 130.0

# --- FUNÇÕES DE APOIO ---
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
    # Leitura e Projeção
    gdf = gpd.read_file(uploaded_file, driver='KML')
    utm_gdf = gdf.to_crs(gdf.estimate_utm_crs())
    linha_rodovia = utm_gdf.geometry.iloc[0]
    extensao = linha_rodovia.length
    
    # Cálculos Normativos
    n_minimo = int(np.ceil((extensao * largura) / area_min))
    n_final = max(qtd_desejada, n_minimo)

    if st.sidebar.button("Gerar Amostras"):
        zonas_proibidas = identificar_zonas_curvas(linha_rodovia, recuo_curva)
        amostras_temp = []
        tentativas = 0
        
        # 1. Sorteio Aleatório de Estacas Seguras
        while len(amostras_temp) < n_final and tentativas < 30000:
            dist = random.uniform(0, extensao)
            esta_proibido = any(i <= dist <= f for i, f in zonas_proibidas)
            if not esta_proibido:
                if all(abs(dist - a['dist']) >= dist_min for a in amostras_temp):
                    amostras_temp.append({'dist': dist})
            tentativas += 1

        # 2. Ordenação Longitudinal
        amostras_temp.sort(key=lambda x: x['dist'])

        # 3. Atribuição de Bordos (Direito, Eixo, Esquerdo)
        sequencia_bordos = ["Bordo Direito", "Eixo", "Bordo Esquerdo"]
        dados_finais = []
        
        for i, amos in enumerate(amostras_temp):
            bordo = sequencia_bordos[i % 3]
            # Offset: BD = positivo, BE = negativo, Eixo = 0
            offset = (largura/2) if bordo == "Bordo Direito" else (-(largura/2) if bordo == "Bordo Esquerdo" else 0)
            
            # Cálculo do ponto geográfico perpendicular
            p1, p2 = linha_rodovia.interpolate(amos['dist']), linha_rodovia.interpolate(amos['dist'] + 0.1)
            dx, dy = p2.x - p1.x, p2.y - p1.y
            mag = np.sqrt(dx**2 + dy**2)
            ponto_geom = Point(p1.x - dy/mag * offset, p1.y + dx/mag * offset)
            
            # Converte para Lat/Long para a tabela
            ponto_wgs84 = gpd.GeoSeries([ponto_geom], crs=utm_gdf.crs).to_crs(epsg=4326)[0]
            
            dados_finais.append({
                'Amostra': i + 1,
                'Identificação': f"Amostra {i+1:02d}",
                'Posição Lateral': bordo,
                'Quilometragem': f"km {amos['dist']/1000:.3f}",
                'Estaca (m)': round(amos['dist'], 2),
                'Latitude': ponto_wgs84.y,
                'Longitude': ponto_wgs84.x,
                'geometry': ponto_geom
            })

        df_final = pd.DataFrame(dados_finais)

        # --- EXIBIÇÃO DOS RESULTADOS ---
        st.success(f"Sucesso! {len(df_final)} pontos gerados.")
        
        st.subheader("📋 Tabela de Amostragem")
        st.dataframe(df_final.drop(columns=['geometry']), use_container_width=True)

        # --- DOWNLOADS ---
        col1, col2 = st.columns(2)
        
        # Gerar Excel na memória
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df_final.drop(columns=['geometry']).to_excel(writer, index=False, sheet_name='Amostras')
        
        col1.download_button(
            label="📥 Baixar Tabela Excel",
            data=output_excel.getvalue(),
            file_name="relatorio_amostragem.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Gerar KML na memória
        amostras_gdf = gpd.GeoDataFrame(df_final, geometry='geometry', crs=utm_gdf.crs).to_crs(epsg=4326)
        amostras_gdf['Name'] = amostras_gdf['Identificação'] + " - " + amostras_gdf['Posição Lateral'] + " (" + amostras_gdf['Quilometragem'] + ")"
        amostras_gdf['Description'] = "Local de coleta: " + amostras_gdf['Posição Lateral']
        
        output_kml = io.BytesIO()
        amostras_gdf[['Name', 'Description', 'geometry']].to_file(output_kml, driver='KML')
        
        col2.download_button(
            label="📥 Baixar Arquivo KML",
            data=output_kml.getvalue(),
            file_name="amostras_campo.kml",
            mime="application/vnd.google-earth.kml+xml"
        )
