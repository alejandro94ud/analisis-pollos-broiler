# -*- coding: utf-8 -*-
"""
Limpieza y unificación de los registros de pollos de engorde (broiler)
Granja en Monterrey, Casanare - lotes 1 a 17, enero-julio 2021.

Fuentes (copias descargadas, los originales en Drive NO se modifican):
  - pollos_gsheet.xlsx  -> Google Sheet "Pollos " (archivo principal)
  - hasta_270321.xlsx   -> Google Sheet "Pollos/hasta/270321" (pestaña PesoLote3-4)

Salidas (carpeta data/):
  datos_largos.csv, resumen_lotes.csv, diccionario.csv, log_limpieza.csv
  Pollos_limpio_portafolio.xlsx (las 4 tablas en pestañas)

Principio: no se borra ningún valor sospechoso; se marca en la columna 'flag'.
"""
import re, datetime as dt
import openpyxl
import pandas as pd

PRINCIPAL = "raw/pollos_gsheet.xlsx"   # copia privada, NO incluida en el repositorio
HASTA = "raw/hasta_270321.xlsx"
filas, log = [], []

def registrar(paso, detalle, n=""):
    """Agrega una entrada al log de limpieza."""
    log.append({"paso": paso, "detalle": detalle, "filas_afectadas": n})

MESES = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
         "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}

def parse_fecha(v, anio=2021):
    """Devuelve (fecha, flag). Convierte fechas escritas como texto ('27 de enero de 2021')."""
    if isinstance(v, dt.datetime):
        return v.date(), ""
    if isinstance(v, str):
        m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", v.lower())
        if m and m.group(2) in MESES:
            a = int(m.group(3)) if m.group(3) else anio
            f = "fecha_texto_convertida" + ("" if m.group(3) else "+anio_asumido_2021")
            return dt.date(a, MESES[m.group(2)], int(m.group(1))), f
    return None, ""

def lote_id(n):
    """Normaliza 'LOTE 1', 'Lote12', ' Lote 16' -> 'L01', 'L12', 'L16'."""
    m = re.search(r"(\d+)", str(n))
    return f"L{int(m.group(1)):02d}" if m else None

def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def agregar(fecha, lote, edad, var, valor, unidad, fuente, flag=""):
    filas.append(dict(fecha=fecha.isoformat() if fecha else "", lote=lote, edad_dias=edad,
                      variable=var, valor=valor, unidad=unidad, fuente_pestana=fuente,
                      flag=flag))

wb = openpyxl.load_workbook(PRINCIPAL, data_only=True)   # data_only: valores, no fórmulas

# ---------------------------------------------------------------------------
# 1) ALIMENTO DIARIO por lote - pestaña RegistroRacionDiariaRegistroTod
#    Formato ancho: fila = fecha (col B), columnas H.. = LOTE 1..23. Bloque diario filas 8-144.
# ---------------------------------------------------------------------------
ws = wb["RegistroRacionDiariaRegistroTod"]
cols = {c.column: lote_id(c.value) for c in ws[7] if c.column >= 8 and c.value}
ultima_fecha, inicio_lote, n_txt = None, {}, 0
for r in range(8, 256):   # bloque diario 23-ene a 30-sep-2021 (fila 257 = totales)
    f, fl = parse_fecha(ws.cell(r, 2).value)
    if f is None and ultima_fecha:          # fecha vacía: se asume día siguiente
        f, fl = ultima_fecha + dt.timedelta(days=1), "fecha_inferida_secuencia"
    if f is None:
        continue
    if fl.startswith("fecha_texto"): n_txt += 1
    ultima_fecha = f
    for c, lote in cols.items():
        v = num(ws.cell(r, c).value)
        if v is None:
            continue
        inicio_lote.setdefault(lote, f)      # primer registro = día 1 (llegada) del lote
        edad = (f - inicio_lote[lote]).days + 1
        flag = fl
        if v <= 0: flag = (flag + ";valor_cero_o_negativo").strip(";")
        agregar(f, lote, edad, "alimento_g", v, "g/lote/día", ws.title, flag)
registrar("alimento", "Pestaña ancha RegistroRacionDiariaRegistroTod (filas 8-255; la fila 257 son totales y se ignora) pasada a formato largo; "
          "edad_dias = días desde el primer registro de cada lote (+1).", "")
registrar("fechas", "Fechas escritas como texto convertidas a ISO (p.ej. '27 de enero de 2021'); "
          "si no tenían año se asumió 2021.", n_txt)

# Saltos bruscos de consumo (caída >50% respecto al día anterior) -> sospechoso
df = pd.DataFrame(filas)
n_salto = 0
for lote, g in df[df.variable == "alimento_g"].groupby("lote"):
    prev = g.valor.shift(1)
    sosp = g.index[(g.valor < 0.5 * prev) & (prev > 0)]
    for i in sosp:
        filas[i]["flag"] = (filas[i]["flag"] + ";sospechoso_caida_>50%_vs_dia_anterior").strip(";")
    n_salto += len(sosp)
registrar("alimento", "Marcadas caídas de consumo >50% respecto al día anterior (probable registro de lo "
          "servido y no de lo consumido, o día no registrado). No se corrigen.", n_salto)

# Consumo por ave (g/ave/día) = alimento del lote / aves iniciales (aprox., no descuenta muertes)
ws_m = wb["MortalidadesRegistro "]
resumen_raw = {}
inicio_tabla = None
for r in range(1, ws_m.max_row + 1):
    if ws_m.cell(r, 1).value == "Población total Lotes":
        inicio_tabla = r
for r in range(inicio_tabla + 1, inicio_tabla + 20):
    lt = ws_m.cell(r, 2).value
    if isinstance(lt, str) and lote_id(lt) and "ote" in lt:
        resumen_raw[lote_id(lt)] = dict(
            aves_iniciales=num(ws_m.cell(r, 3).value),
            muertes_tabla=num(ws_m.cell(r, 4).value),
            desaparecidas=num(ws_m.cell(r, 7).value) or 0.0,
            proveedor=(ws_m.cell(r, 6).value or "").strip().title())
for d in list(filas):
    if d["variable"] == "alimento_g" and d["lote"] in resumen_raw and resumen_raw[d["lote"]]["aves_iniciales"]:
        agregar(dt.date.fromisoformat(d["fecha"]), d["lote"], d["edad_dias"], "alimento_g_ave",
                round(d["valor"] / resumen_raw[d["lote"]]["aves_iniciales"], 2), "g/ave/día",
                d["fuente_pestana"], ("calculado_sobre_aves_iniciales;" + d["flag"]).strip(";"))
registrar("alimento", "alimento_g_ave calculado = alimento_g / aves iniciales (no descuenta mortalidad diaria).", "")

# ---------------------------------------------------------------------------
# 2) AGUA - pestañas AguaLote2, AguaLote3, AguaLote4 (formato largo, una fila por día)
#    AguaLote1 es un modelo teórico (n=50), NO un registro real -> se excluye.
# ---------------------------------------------------------------------------
registrar("agua", "AguaLote1 excluida: contiene un modelo teórico (consumo esperado n=50), no mediciones.", "")
for hoja, lote in [("AguaLote2", "L02"), ("AguaLote3", "L03"), ("AguaLote4", "L04")]:
    ws = wb[hoja]
    hdr = {str(c.value).strip().lower(): c.column for c in ws[1] if c.value}
    c_sum = hdr["agua suministrada en litros"]; c_rec = hdr["agua rechazada en litros"]
    c_ml = next((v for k, v in hdr.items() if k.startswith("ml consumidos")), None)
    ini = None
    for r in range(2, ws.max_row + 1):
        f, fl = parse_fecha(ws.cell(r, 1).value)
        if f is None: continue
        ini = ini or f
        edad = (f - ini).days + 1
        s, rc = num(ws.cell(r, c_sum).value), num(ws.cell(r, c_rec).value)
        if s is not None:
            agregar(f, lote, edad, "agua_l", s, "L/lote/día (suministrada)", hoja,
                    (fl + (";valor_cero_sospechoso" if s == 0 else "")).strip(";"))
        else:
            agregar(f, lote, edad, "agua_l", None, "L/lote/día (suministrada)", hoja, "faltante")
        if rc is not None:
            agregar(f, lote, edad, "agua_rechazo_l", rc, "L/lote/día (sobrante)", hoja, fl)
        if s is not None and rc is not None:
            agregar(f, lote, edad, "agua_neta_l", s - rc, "L/lote/día (consumida)", hoja,
                    ("calculado;" + fl + (";rechazo_mayor_o_igual_suministro" if rc >= s else "")).strip(";"))
        if c_ml:
            m = num(ws.cell(r, c_ml).value)
            if m is not None:
                agregar(f, lote, edad, "agua_ml_ave", m, "ml/ave/día", hoja, fl)
registrar("agua", "Agua neta = suministrada - rechazada (calculada). Días sin dato marcados 'faltante'.", "")

# ---------------------------------------------------------------------------
# 3) PESO - pestaña PesoLote3-4 del archivo "Pollos/hasta/270321"
#    Bloques semanales; 5 aves muestreadas por día (aves distintas cada día).
# ---------------------------------------------------------------------------
ws = openpyxl.load_workbook(HASTA, data_only=True)["PesoLote3-4"]
llegada = {"L03": dt.date(2021, 3, 7), "L04": dt.date(2021, 3, 13)}   # según bitácoras
n_peso = 0
for r in range(1, ws.max_row + 1):
    for col0, lote in [(1, "L03"), (11, "L04")]:
        t = ws.cell(r, col0).value
        if isinstance(t, str) and t.startswith("Semana"):
            dias = {}
            for c in range(col0 + 2, col0 + 9):
                h = ws.cell(r, c).value
                m = re.search(r"(\d+)", str(h)) if h else None
                if m: dias[c] = int(m.group(1))
            for rr in range(r + 1, r + 6):           # 5 muestras
                for c, dia in dias.items():
                    v = num(ws.cell(rr, c).value)
                    if v is None: continue
                    f = llegada[lote] + dt.timedelta(days=dia - 1)
                    agregar(f, lote, dia, "peso_g", v, "g/ave (muestra individual)", "PesoLote3-4",
                            f"muestra_{int(ws.cell(rr, col0 + 1).value)};fecha_derivada_de_dia_y_llegada")
                    n_peso += 1
registrar("peso", "Pesos individuales (5 aves/día) de lotes 3 y 4; fecha = llegada + día - 1.", n_peso)

# Atípicos de peso: fuera de mediana ±40% del día
dfp = pd.DataFrame(filas)
idx = dfp.index[dfp.variable == "peso_g"]
med = dfp.loc[idx].groupby(["lote", "edad_dias"]).valor.transform("median")
n_at = 0
for i, mval in zip(idx, med):
    if abs(filas[i]["valor"] - mval) > 0.4 * mval:
        filas[i]["flag"] += ";atipico_vs_mediana_dia"; n_at += 1
registrar("peso", "Marcados pesos que se apartan >40% de la mediana del mismo lote y día.", n_at)

# Pesos vivos de muestreo de calidad al sacrificio (pestaña Ventas)
ws = wb["Ventas"]
for r0, lote, unidad in [(27, "L03", "g"), (58, "L05", "g")]:
    for r in range(r0, r0 + 5):
        v = num(ws.cell(r, 7).value)
        if v: agregar(None, lote, None, "peso_sacrificio_g", v, "g/ave (muestra calidad)", "Ventas",
                      "sin_fecha_exacta;muestra_aleatoria_5_aves")
for r in range(199, 214):
    v = num(ws.cell(r, 7).value)
    if v: agregar(None, "L11", None, "peso_sacrificio_g", round(v * 453.592, 1), "g/ave (convertido de lb)",
                  "Ventas", "convertido_libras_a_gramos;sin_fecha_exacta")
registrar("unidades", "Pesos de muestra del lote 11 venían en libras; convertidos a gramos (x453.592).", 15)

# ---------------------------------------------------------------------------
# 4) MORTALIDAD - eventos (1 fila = 1 ave muerta) de MortalidadesRegistro
# ---------------------------------------------------------------------------
n_sin = 0
for r in range(2, inicio_tabla):
    nro, fv, lt, edad = (ws_m.cell(r, c).value for c in (1, 2, 3, 4))
    if nro is None or lt is None: continue
    lote = lote_id(lt)
    f, fl = parse_fecha(fv)
    flag = fl
    if f is None:
        flag = "sin_fecha(22-jun a 12-jul-2021 sin registro exacto)"; n_sin += 1
    e = num(edad)
    causa = (ws_m.cell(r, 5).value or "")
    agregar(f, lote, int(e) if e else None, "mortalidad", 1, "aves", "MortalidadesRegistro ",
            (flag + (";nro_evento_texto" if isinstance(nro, str) else "")).strip(";"))
    filas[-1]["nota"] = str(causa)[:200].replace("\n", " ")
registrar("mortalidad", "Cada evento = 1 ave. Numeración original salta del 16 al 18 y mezcla texto/número; "
          "se ignora la numeración y se cuenta por filas.", "")
registrar("mortalidad", "Eventos sin fecha (periodo 22-jun a 12-jul-2021) se conservan con fecha vacía.", n_sin)

# ---------------------------------------------------------------------------
# 5) VENTAS - pestaña Ventas, bloques por lote (solo 'Carne'; menudencias aparte)
# ---------------------------------------------------------------------------
lote_act, modo = None, "carne"
for r in range(1, ws.max_row + 1):
    a = ws.cell(r, 1).value
    if isinstance(a, str) and re.match(r"\s*lotes?\s*\d+", a, re.I):
        nums = re.findall(r"\d+", a)          # 'Lotes 12 y 13' -> grupo de venta combinado
        lote_act = "+".join(f"L{int(n):02d}" for n in nums); modo = "carne"; continue
    if isinstance(a, str) and a.strip().lower().startswith("menudencia"):
        modo = "menudencias"; continue
    if lote_act is None or not isinstance(a, dt.datetime): continue
    f = a.date()
    kg, und, cop = (num(ws.cell(r, c).value) for c in (2, 3, 4))
    if modo == "menudencias":
        if cop: agregar(f, lote_act, None, "ventas_menudencias_cop", cop, "COP", "Ventas")
        continue
    if kg is not None and kg > 0:
        fl = "sospechoso_kg_por_ave>5" if und and kg / und > 5 else ""
        if "+" in lote_act: fl = (fl + ";venta_combinada_de_dos_lotes").strip(";")
        agregar(f, lote_act, None, "ventas_kg", kg, "kg carne (canal)", "Ventas", fl)
    if und: agregar(f, lote_act, None, "ventas_unidades", und, "aves", "Ventas",
                    "" if kg else "sin_peso_registrado")
    if cop:
        fl = "sospechoso_valor_bajo(<1000 COP)" if cop < 1000 else ""
        agregar(f, lote_act, None, "ventas_cop", cop, "COP", "Ventas", fl)
    if kg and cop and cop >= 1000:
        p = round(cop / kg)
        agregar(f, lote_act, None, "precio_cop_kg", p, "COP/kg", "Ventas",
                "calculado" + (";precio_fuera_rango_5000-15000" if not 5000 <= p <= 15000 else ""))
registrar("ventas", "Se toman solo filas con fecha de cada bloque de lote; filas de totales y cálculos "
          "auxiliares se ignoran. Menudencias en variable aparte.", "")

# ---------------------------------------------------------------------------
# 6) TABLA LARGA FINAL
# ---------------------------------------------------------------------------
largo = pd.DataFrame(filas)
largo["nota"] = largo.get("nota", "").fillna("")
largo["flag"] = largo["flag"].fillna("").str.strip(";")
largo["edad_dias"] = largo["edad_dias"].astype("Int64")
largo = largo.sort_values(["lote", "variable", "fecha", "edad_dias"]).reset_index(drop=True)
dup = largo.duplicated(["fecha", "lote", "variable", "valor", "fuente_pestana", "nota"], keep=False) & \
      ~largo.variable.isin(["mortalidad", "peso_g", "peso_sacrificio_g"])
largo.loc[dup, "flag"] = (largo.loc[dup, "flag"] + ";posible_duplicado").str.strip(";")
registrar("duplicados", "Filas idénticas (fecha, lote, variable, valor) marcadas como posible_duplicado, no borradas.", int(dup.sum()))

# ---------------------------------------------------------------------------
# 7) RESUMEN POR LOTE
# ---------------------------------------------------------------------------
res = []
for grp in ["L12+L13", "L14+L15"]:          # ventas registradas en bloque combinado
    a, b = grp.split("+")
    resumen_raw[grp] = dict(aves_iniciales=resumen_raw[a]["aves_iniciales"] + resumen_raw[b]["aves_iniciales"],
        muertes_tabla=resumen_raw[a]["muertes_tabla"] + resumen_raw[b]["muertes_tabla"],
        desaparecidas=resumen_raw[a]["desaparecidas"] + resumen_raw[b]["desaparecidas"],
        proveedor=resumen_raw[a]["proveedor"], combinado=(a, b))
for lote, info in sorted(resumen_raw.items()):
    g = largo[largo.lote.isin(info.get("combinado", ())) | (largo.lote == lote)]
    alim = g[g.variable == "alimento_g"].valor.sum()
    gk = g[g.variable == "ventas_kg"]
    kg = gk[~gk.flag.str.contains("sospechoso_kg")].valor.sum()   # se excluye el kg imposible
    vend = g[g.variable == "ventas_unidades"].valor.sum()
    muertes = int(g[g.variable == "mortalidad"].valor.sum())
    ini = info["aves_iniciales"]
    fechas = g[g.variable == "alimento_g"].fecha
    res.append(dict(
        lote=lote, proveedor=info["proveedor"],
        fecha_llegada=fechas.min() if len(fechas) else "", ultimo_registro_alimento=fechas.max() if len(fechas) else "",
        dias_registrados=len(fechas), aves_iniciales=ini,
        muertes_eventos=muertes, muertes_tabla_original=info["muertes_tabla"],
        desaparecidas=info["desaparecidas"], vendidas=vend,
        sin_explicar=ini - muertes - info["desaparecidas"] - vend if ini else None,
        kg_vendidos=round(kg, 2), peso_canal_prom_kg=round(kg / vend, 3) if vend and kg else None,
        alimento_total_kg=round(alim / 1000, 2),
        conversion_alimento_canal=round(alim / 1000 / kg, 2) if kg else None,
        ingreso_cop=g[g.variable == "ventas_cop"].valor.sum(),
        mortalidad_pct=round(100 * info["muertes_tabla"] / ini, 2) if ini else None))
resumen = pd.DataFrame(res)
# Anonimización: cada proveedor real -> 'Proveedor A', 'B', ... según orden de aparición
orden = [p for p in dict.fromkeys(resumen.proveedor) if p]
mapa = {p: f"Proveedor {chr(65 + i)}" for i, p in enumerate(orden)}
resumen["proveedor"] = resumen.proveedor.map(mapa).fillna("")
registrar("ventas", "Ventas de lotes 12-13 y 14-15 registradas juntas: lote='L12+L13'/'L14+L15'; el resumen incluye filas combinadas.", "")
registrar("ventas", "Kg con >5 kg/ave (L05: 76.44 kg por 1 ave, 18-may-2021) se conserva marcado y se EXCLUYE de kg_vendidos.", 1)
registrar("resumen", "Conversión = alimento total registrado (kg) / kg de canal vendidos. Es conversión sobre "
          "CARNE LIMPIA, no sobre peso vivo; no comparable 1:1 con estándar Ross/Cobb (~1.6-1.8 vivo).", "")
registrar("resumen", "mortalidad_pct usa muertes de la tabla resumen original; muertes_eventos cuenta filas del "
          "registro de eventos (pueden diferir). sin_explicar = iniciales - muertes - desaparecidas - vendidas.", "")

# Anomalías de resumen al log
for _, r in resumen.iterrows():
    if r.muertes_eventos != r.muertes_tabla_original:
        registrar("anomalia", f"{r.lote}: muertes en eventos ({r.muertes_eventos}) ≠ tabla resumen ({r.muertes_tabla_original}).", 1)
    if r.sin_explicar not in (0, None) and pd.notna(r.sin_explicar) and r.vendidas > 0:
        registrar("anomalia", f"{r.lote}: {r.sin_explicar:+.0f} aves sin explicar (iniciales-muertes-desap.-vendidas).", 1)
    if r.vendidas == 0:
        registrar("anomalia", f"{r.lote}: sin ventas registradas.", 1)
    if r.dias_registrados == 0:
        registrar("anomalia", f"{r.lote}: sin registro diario de alimento.", 1)
registrar("anomalia", "Pestaña Inventario contiene 6 fechas de 2023 (posteriores al proyecto); no se usan.", 6)
registrar("anomalia", "Temperatura no existe como variable numérica (solo en texto de bitácoras); no incluida.", "")
registrar("anomalia", "Pestaña 'Lotes 5 y 6' vacía; peso diario solo existe para lotes 3 y 4 (días 1-11).", "")

# ---------------------------------------------------------------------------
# 8) DICCIONARIO
# ---------------------------------------------------------------------------
desc = {
 "alimento_g": "Alimento suministrado al lote en el día", "alimento_g_ave": "Alimento del día / aves iniciales",
 "agua_l": "Agua suministrada al lote", "agua_rechazo_l": "Agua sobrante/rechazada",
 "agua_neta_l": "Agua suministrada - rechazada", "agua_ml_ave": "ml por ave según registro original",
 "peso_g": "Peso individual de ave muestreada", "peso_sacrificio_g": "Peso de ave en muestreo de calidad al sacrificio",
 "mortalidad": "1 = un ave muerta (columna nota = causa)", "ventas_kg": "Kg de carne (canal limpia) vendidos",
 "ventas_unidades": "Aves vendidas", "ventas_cop": "Valor de la venta", "precio_cop_kg": "Valor venta / kg",
 "ventas_menudencias_cop": "Venta de menudencias"}
dic = [dict(tabla="datos_largos", campo=c, descripcion=d) for c, d in [
 ("fecha", "Fecha ISO AAAA-MM-DD (vacía si no hay registro)"), ("lote", "Lote normalizado L01..L23"),
 ("edad_dias", "Día de vida en granja (1 = llegada)"), ("variable", "Nombre de la medición (ver abajo)"),
 ("valor", "Valor numérico"), ("unidad", "Unidad del valor"), ("fuente_pestana", "Pestaña de origen"),
 ("flag", "Notas de calidad separadas por ';' (vacío = sin observaciones)"), ("nota", "Texto libre (causa de muerte)")]]
for v, d in desc.items():
    u = largo[largo.variable == v].unidad
    dic.append(dict(tabla="datos_largos.variable", campo=v, descripcion=f"{d} [{u.iloc[0] if len(u) else ''}] - {len(u)} filas"))
for c in resumen.columns:
    dic.append(dict(tabla="resumen_lotes", campo=c, descripcion=""))
dic = pd.DataFrame(dic)

# ---------------------------------------------------------------------------
# 9) GUARDAR
# ---------------------------------------------------------------------------
logdf = pd.DataFrame(log)
largo.to_csv("data/datos_largos.csv", index=False, encoding="utf-8-sig")
resumen.to_csv("data/resumen_lotes.csv", index=False, encoding="utf-8-sig")
dic.to_csv("data/diccionario.csv", index=False, encoding="utf-8-sig")
logdf.to_csv("data/log_limpieza.csv", index=False, encoding="utf-8-sig")
with pd.ExcelWriter("data/Pollos_limpio_portafolio.xlsx") as w:
    largo.to_excel(w, sheet_name="datos_largos", index=False); resumen.to_excel(w, sheet_name="resumen_lotes", index=False)
    dic.to_excel(w, sheet_name="diccionario", index=False); logdf.to_excel(w, sheet_name="log_limpieza", index=False)
print(largo.variable.value_counts().to_string())
print(resumen.to_string())
