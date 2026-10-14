"""Готовит учебные таблицы из исходных файлов UCI.

    python scripts/prepare_data.py

Читает data/raw/, пишет app/static/data/. Значения не исправляются: пропуски,
нулевой холестерин и прочие особенности исходных данных сохраняются — на них
построены уроки о качестве данных.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "app" / "static" / "data"

HEART_DISEASE_COLUMNS = [
    "age", "sex", "cp", "trestbps", "chol", "fbs", "restecg",
    "thalach", "exang", "oldpeak", "slope", "ca", "thal", "num",
]
CLINICS = {
    "cleveland": "processed.cleveland.data",
    "hungary": "processed.hungarian.data",
    "switzerland": "processed.switzerland.data",
    "long_beach": "processed.va.data",
}


def prepare_heart_failure() -> pd.DataFrame:
    return pd.read_csv(RAW / "heart_failure_clinical_records_dataset.csv")


def prepare_heart_disease() -> pd.DataFrame:
    parts = []
    for clinic, filename in CLINICS.items():
        part = pd.read_csv(RAW / filename, header=None, names=HEART_DISEASE_COLUMNS, na_values="?")
        part.insert(0, "clinic", clinic)
        parts.append(part)
    data = pd.concat(parts, ignore_index=True)
    # Все признаки, кроме oldpeak, целочисленные; Int64 сохраняет пропуски без превращения чисел в дробные.
    for column in HEART_DISEASE_COLUMNS:
        if column != "oldpeak":
            data[column] = data[column].astype("Int64")
    return data


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        ("heart_failure.csv", prepare_heart_failure()),
        ("heart_disease.csv", prepare_heart_disease()),
    ):
        frame.to_csv(OUT / name, index=False, lineterminator="\n")
        print(f"{name}: {len(frame)} строк, {frame.shape[1]} столбцов, пропусков: {int(frame.isna().sum().sum())}")


if __name__ == "__main__":
    main()
