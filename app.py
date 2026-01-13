import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, LineString
from google.colab import files
import fiona
import random
import io

fiona.drvsupport.supported_drivers['KML'] = 'rw'

def processar_auditoria_v7():
    print("1. SELECIONE O ARQUIVO KML DA RODOVIA")
    uploaded = files.upload()
    if not uploaded: return
    kml_path = list(uploaded.keys())[0]

    print("\n2. PARÂMETROS TÉCNICOS")
    largura_pista = float(input("Largura da pista (m): "))
    area_min_amostra = float(input("Área mínima por amostra (m²): "))
    qtd_desejada = int(input("Quantidade de amostras pretendida: "))
    dist_min_entre_pontos = float(input("Distância mínima entre amostras (m): "))
    recuo_curva = 130.0 

    # 3. Processamento Geográfico
    gdf = gpd.read_file(kml_path, driver='KML')
    utm_gdf = gdf.to_crs(gdf.estimate_utm_crs())
    linha_rodovia = utm_gdf.geometry.iloc[0]
    extensao_metros = linha_rodovia.length
    
    zonas_proibidas = identificar_zonas_curvas(linha_rodovia, recuo_curva)

    # 4. Memorial de Cálculo
    area_total = extensao_metros * largura_pista
    qtd_minima_normativa = int(np.ceil(area_total / area_min_amostra))
    qtd_final = max(qtd_desejada, qtd_minima_normativa)

    # 5. Algoritmo de Alocação
    amostras_temp = []
    tentativas = 0
    while len(amostras_temp) < qtd_final and tentativas < 40000:
        dist_aleatoria = random.uniform(0, extensao_metros)
        if not esta_em_zona_proibida(dist_aleatoria, zonas_proibidas):
            if all(abs(dist_aleatoria - a['dist']) >= dist_min_entre_pontos for a in amostras_temp):
                amostras_temp.append({'dist': dist_aleatoria})
        tentativas += 1

    # ORDENAÇÃO E ATRIBUIÇÃO DE BORDOS
    amostras_temp.sort(key=lambda x: x['dist'])
    sequencia_bordos = ["BD", "EIXO", "BE"]
    
    dados_finais = []
    for i, amos in enumerate(amostras_temp):
        bordo = sequencia_bordos[i % 3]
        offset = (largura_pista / 2) if bordo == "BD" else (-largura_pista / 2 if bordo == "BE" else 0)
        
        ponto_geom = gerar_ponto_com_offset(linha_rodovia, amos['dist'], offset)
        
        # Coordenadas Geográficas para a tabela
        ponto_wgs84 = gpd.GeoSeries([ponto_geom], crs=utm_gdf.crs).to_crs(epsg=4326)[0]
        
        dados_finais.append({
            'Amostra': i + 1,
            'Identificação': f"Amostra {i+1:02d}",
            'Posição': bordo,
            'Estaca (m)': round(amos['dist'], 2),
            'Quilometragem': f"{(amos['dist']/1000):.3f}",
            'Latitude': ponto_wgs84.y,
            'Longitude': ponto_wgs84.x
        })

    # 6. Geração de Resultados
    df_resultados = pd.DataFrame(dados_finais)
    
    # Exibição da Tabela
    print("\n" + "="*80)
    print("PLANILHA DE AMOSTRAGEM GERADA")
    print(df_resultados.to_string(index=False))
    print("="*80)

    # Exportação para EXCEL
    excel_name = "relatorio_amostragem.xlsx"
    df_resultados.to_excel(excel_name, index=False)
    
    # Exportação para KML
    amostras_gdf = gpd.GeoDataFrame(df_resultados, 
                                     geometry=[Point(lon, lat) for lon, lat in zip(df_resultados['Longitude'], df_resultados['Latitude'])], 
                                     crs="EPSG:4326")
    
    amostras_gdf['Name'] = amostras_gdf['Identificação'] + " - " + amostras_gdf['Posição'] + " (km " + amostras_gdf['Quilometragem'] + ")"
    amostras_gdf['Description'] = "Posição lateral: " + amostras_gdf['Posição']
    
    kml_name = "amostras_auditoria.kml"
    amostras_gdf[['Name', 'Description', 'geometry']].to_file(kml_name, driver='KML')
    
    # Download dos arquivos
    print(f"\nDownload concluído: {excel_name} e {kml_name}")
    files.download(excel_name)
    files.download(kml_name)

# --- FUNÇÕES AUXILIARES ---

def identificar_zonas_curvas(linha, recuo, passo=10):
    zonas = []
    for d in range(passo, int(linha.length) - passo, passo):
        p1, p2, p3 = linha.interpolate(d-passo), linha.interpolate(d), linha.interpolate(d+passo)
        v1 = np.array([p2.x-p1.x, p2.y-p1.y])
        v2 = np.array([p3.x-p2.x, p3.y-p2.y])
        norm = (np.linalg.norm(v1) * np.linalg.norm(v2))
        if norm != 0 and (np.dot(v1, v2)/norm) < 0.9995:
            zonas.append((d - recuo, d + recuo))
    return zonas

def esta_em_zona_proibida(dist, zonas):
    for inicio, fim in zonas:
        if inicio <= dist <= fim: return True
    return False

def gerar_ponto_com_offset(linha, dist, offset):
    p1, p2 = linha.interpolate(dist), linha.interpolate(dist + 0.5)
    dx, dy = p2.x - p1.x, p2.y - p1.y
    mag = np.sqrt(dx**2 + dy**2)
    nx, ny = -dy/mag, dx/mag
    return Point(p1.x + nx * offset, p1.y + ny * offset)

processar_auditoria_v7()
