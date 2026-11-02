"""
Monitor de Alarmes da Frota (Dahua) — Flask
Rodar:  pip install flask pandas openpyxl  &&  python app.py   ->  http://localhost:5000
"""
import io
import pandas as pd
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


def norm_prefixo(v) -> str:
    """Normaliza prefixo: tira espaços/.0 e completa com zeros à esquerda (00209)."""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(5) if s.isdigit() else s


def ler_frota(arquivo) -> list[dict]:
    """Cada aba (exceto 'Tabela') é um grupo; coluna 'Prefixo' lista os carros."""
    xls = pd.ExcelFile(arquivo)
    frota = []
    for aba in xls.sheet_names:
        if aba.strip().lower() == "tabela":
            continue
        df = xls.parse(aba, dtype=str)
        col = next((c for c in df.columns if "prefixo" in str(c).lower()), df.columns[0])
        col_fw = next((c for c in df.columns if "fw" in str(c).lower()), None)
        for _, r in df.dropna(subset=[col]).iterrows():
            fw = r[col_fw] if col_fw and pd.notna(r[col_fw]) else ""
            frota.append({"prefixo": norm_prefixo(r[col]), "grupo": aba.strip(), "fw": str(fw).strip()})
    return frota


def ler_alarmes(arquivo) -> dict:
    df = pd.read_excel(arquivo, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    low = {c: c.lower() for c in df.columns}
    # Aceita os dois modelos: "Fonte de Alarme" (antigo) e "Nome do Dispositivo" (Segurança Ativa)
    c_fonte = next(c for c in df.columns if "fonte" in low[c] or "nome do dispositivo" in low[c])
    c_tipo = next(c for c in df.columns if low[c].startswith("tipo"))
    c_hora = next((c for c in df.columns if low[c].startswith(("hora", "data"))), None)

    df = df.dropna(subset=[c_fonte]).copy()
    df["prefixo"] = df[c_fonte].map(norm_prefixo)
    df["tipo"] = df[c_tipo].fillna("Sem tipo").str.strip()
    if c_hora:
        df["hora"] = pd.to_datetime(df[c_hora], errors="coerce")
    else:
        df["hora"] = pd.NaT

    por_carro: dict = {}
    for (p, t), g in df.groupby(["prefixo", "tipo"]):
        d = por_carro.setdefault(p, {"tipos": {}, "ultimo": None})
        d["tipos"][t] = int(len(g))
        ult = g["hora"].max()
        if pd.notna(ult) and (d["ultimo"] is None or ult.isoformat() > d["ultimo"]):
            d["ultimo"] = ult.isoformat()

    dias: dict = {}
    d2 = df.dropna(subset=["hora"])
    for (dia, t), g in d2.groupby([d2["hora"].dt.strftime("%Y-%m-%d"), "tipo"]):
        dias.setdefault(dia, {})[t] = int(len(g))

    periodo = None
    if df["hora"].notna().any():
        periodo = {"inicio": df["hora"].min().isoformat(), "fim": df["hora"].max().isoformat()}
    return {"alarmes": por_carro, "total": int(len(df)), "dias": dias, "periodo": periodo,
            "tipos": sorted(df["tipo"].unique().tolist())}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analisar", methods=["POST"])
def analisar():
    try:
        f_frota, f_alarm = request.files.get("frota"), request.files.get("alarmes")
        if not f_frota or not f_alarm:
            return jsonify(erro="Envie as duas planilhas."), 400
        frota = ler_frota(io.BytesIO(f_frota.read()))
        alarmes = ler_alarmes(io.BytesIO(f_alarm.read()))
        return jsonify(frota=frota, **alarmes)
    except StopIteration:
        return jsonify(erro="Não encontrei as colunas 'Nome do Dispositivo' e 'Tipo de Alarme' na planilha de alarmes."), 400
    except Exception as e:  # noqa
        return jsonify(erro=f"Erro ao ler as planilhas: {e}"), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)
