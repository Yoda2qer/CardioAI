AUC показывает, насколько хорошо модель отличает больных от здоровых. Но врачу нужен не порядок пациентов, а число: «риск 30%» должен означать именно 30%. И ему нужно понимать, на чём основан прогноз. Этот урок — о двух свойствах, без которых модели нельзя доверять: о калибровке и интерпретируемости.

## Что такое калибровка

Модель **хорошо откалибрована**, если её вероятности совпадают с реальными частотами: среди пациентов, которым она назначила риск 30%, событие действительно происходит примерно у 30 из 100.

Различающая способность и калибровка — разные свойства. Модель, которая каждому больному выдаёт 0,51, а каждому здоровому 0,49, имеет идеальный AUC и бесполезные вероятности. И наоборот: модель, сообщающая всем «55%» в выборке с 55% больных, откалибрована безупречно и ничего не различает.

Сравним две модели диагностики ИБС.

```python
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

hd = pd.read_csv("heart_disease.csv")
hd[["chol", "trestbps"]] = hd[["chol", "trestbps"]].replace(0, np.nan)
hd["target"] = (hd["num"] > 0).astype(int)
numeric = ["age", "trestbps", "chol", "thalach", "oldpeak"]
features = numeric + ["cp", "sex", "exang"]

def make_model(classifier):
    preprocess = ColumnTransformer([
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")),
                          ("scaler", StandardScaler())]), numeric),
        ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), ["cp"]),
        ("bin", SimpleImputer(strategy="most_frequent"), ["sex", "exang"]),
    ])
    return Pipeline([("prep", preprocess), ("clf", classifier)])

X, y = hd[features], hd["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)

models = {
    "Логистическая регрессия": make_model(LogisticRegression(max_iter=1000)),
    "Случайный лес": make_model(RandomForestClassifier(n_estimators=200, random_state=42)),
}
probas = {}
for name, model in models.items():
    probas[name] = model.fit(X_train, y_train).predict_proba(X_test)[:, 1]
    print(f"{name:24} AUC {roc_auc_score(y_test, probas[name]):.3f}   Brier {brier_score_loss(y_test, probas[name]):.3f}")
```

```output
Логистическая регрессия  AUC 0.898   Brier 0.128
Случайный лес            AUC 0.896   Brier 0.130
```

**Оценка Брайера** — средний квадрат разности между предсказанной вероятностью и исходом (0 или 1). Чем она меньше, тем лучше; значение 0,25 соответствует ответу «50%» для каждого. Она учитывает сразу и различающую способность, и калибровку.

## Калибровочная кривая

Тестовых пациентов делят на группы по величине предсказанного риска и в каждой сравнивают средний прогноз с реальной долей больных.

```python fig=s4-calibration
import matplotlib.pyplot as plt
from sklearn.calibration import calibration_curve

fig, ax = plt.subplots(figsize=(5.6, 5.2))
ax.plot([0, 1], [0, 1], linestyle="--", color="#898781", label="Идеальная калибровка")
for name, proba in probas.items():
    observed, predicted = calibration_curve(y_test, proba, n_bins=5, strategy="quantile")
    ax.plot(predicted, observed, marker="o", label=name)
ax.set_xlabel("Средняя предсказанная вероятность")
ax.set_ylabel("Наблюдаемая доля больных")
ax.set_title("Калибровочные кривые")
ax.legend(loc="upper left")
plt.show()
```

![Калибровочные кривые двух моделей: обе идут вдоль диагонали идеальной калибровки от примерно 0,1 до 0,95](/static/img/lessons/s4-calibration.png)

Точки на диагонали — прогноз совпадает с действительностью. Ниже диагонали модель завышает риск, выше — занижает. Здесь обе модели откалиброваны прилично. Это не случайность: тестовые пациенты взяты из той же совокупности, что и обучающие.

## Калибровка ломается первой

Обучим модель только на пациентах Кливленда и применим её к пациентам из Будапешта.

```python
cleveland = hd[hd["clinic"] == "cleveland"]
hungary = hd[hd["clinic"] == "hungary"]

model = make_model(LogisticRegression(max_iter=1000)).fit(cleveland[features], cleveland["target"])
proba_hungary = model.predict_proba(hungary[features])[:, 1]

print(f"AUC на пациентах Будапешта: {roc_auc_score(hungary['target'], proba_hungary):.3f}")
print(f"Средний предсказанный риск: {proba_hungary.mean():.1%}")
print(f"Реальная доля больных:      {hungary['target'].mean():.1%}")
```

```output
AUC на пациентах Будапешта: 0.880
Средний предсказанный риск: 44.1%
Реальная доля больных:      36.1%
```

Различающая способность сохранилась — AUC почти такой же, как в Кливленде. Но модель систематически завышает риск: в среднем она ожидает 44% больных, а их 36%. В Будапеште на ангиографию направляли пациентов с меньшей вероятностью болезни, и «точка отсчёта», выученная в Кливленде, там не подходит.

::: clinic Почему это важно для решений
Клинические рекомендации привязаны к абсолютному риску: назначать ли терапию при десятилетнем риске выше 10%, направлять ли на обследование при вероятности выше 15%. Модель, которая верно ранжирует пациентов, но завышает риск на восемь процентных пунктов, отправит на лишнее обследование заметную долю людей. При переносе модели в другую клинику, страну или десятилетие калибровку проверяют обязательно и при необходимости исправляют — это называют рекалибровкой.
:::

## На что опирается модель

Вторая составляющая доверия — понимание того, какие признаки определяют прогноз. В третьем разделе мы видели, что встроенная оценка важности случайного леса завышает роль непрерывных показателей. Более честный способ — **перестановочная важность**.

Идея проста. Берём обученную модель и тестовую выборку. Случайно перемешиваем значения одного признака между пациентами, разрушая его связь с исходом, и смотрим, насколько упало качество. Если упало сильно — модель на этот признак опирается. Если не изменилось — признак ей не нужен.

```python fig=s4-permutation
from sklearn.inspection import permutation_importance

hf = pd.read_csv("heart_failure.csv")
hf_features = [c for c in hf.columns if c not in ("time", "DEATH_EVENT")]
Xh_train, Xh_test, yh_train, yh_test = train_test_split(
    hf[hf_features], hf["DEATH_EVENT"], test_size=0.3, random_state=0, stratify=hf["DEATH_EVENT"]
)
forest = RandomForestClassifier(n_estimators=500, random_state=42).fit(Xh_train, yh_train)

result = permutation_importance(forest, Xh_test, yh_test, scoring="roc_auc", n_repeats=30, random_state=0)
table = pd.DataFrame({
    "встроенная": forest.feature_importances_,
    "перестановочная": result.importances_mean,
}, index=hf_features).sort_values("перестановочная", ascending=False)
print(table.round(3))

names = {
    "age": "Возраст", "anaemia": "Анемия", "creatinine_phosphokinase": "КФК",
    "diabetes": "Диабет", "ejection_fraction": "Фракция выброса",
    "high_blood_pressure": "Гипертензия", "platelets": "Тромбоциты",
    "serum_creatinine": "Креатинин", "serum_sodium": "Натрий", "sex": "Пол", "smoking": "Курение",
}
top = table.sort_values("перестановочная")
fig, ax = plt.subplots(figsize=(7.2, 4.4))
ax.barh([names[f] for f in top.index], top["перестановочная"])
ax.axvline(0, color="#898781", linewidth=1)
ax.set_xlabel("Падение AUC при перемешивании признака")
ax.set_title("Перестановочная важность: модель опирается на три признака")
ax.grid(axis="y", visible=False)
plt.show()
```

```output
                          встроенная  перестановочная
serum_creatinine               0.201            0.097
ejection_fraction              0.203            0.068
age                            0.140            0.031
serum_sodium                   0.107            0.014
platelets                      0.117            0.006
anaemia                        0.023            0.005
high_blood_pressure            0.018            0.005
diabetes                       0.020            0.004
sex                            0.021            0.002
smoking                        0.020           -0.005
creatinine_phosphokinase       0.130           -0.006
```

![Горизонтальная столбчатая диаграмма перестановочной важности: заметное падение AUC дают только креатинин, фракция выброса и возраст, остальные признаки около нуля](/static/img/lessons/s4-permutation.png)

Сравните два столбца таблицы. По встроенной оценке КФК и тромбоциты входили в число главных признаков. Перестановочная важность показывает, что их перемешивание качество не ухудшает: модель строила по ним разбиения, но пользы они не приносили. По-настоящему прогноз держится на креатинине, фракции выброса и возрасте — в полном согласии и со статистическими тестами, и с клиническим опытом.

## Как правильно читать важность признаков

::: warning Важность — не причинность
Высокая важность означает, что *модель использует* признак, а не что признак *вызывает* исход. Срок наблюдения из прошлого урока получил бы огромную важность, оставаясь артефактом. Маркер тяжести состояния может быть важен для прогноза и при этом не быть мишенью для лечения.
:::

Ещё три оговорки.

- **Связанные признаки делят важность.** Если два показателя несут одну информацию, перемешивание одного мало что меняет — модель получает её из второго. Оба будут выглядеть «неважными».
- **Важность зависит от модели.** У логистической регрессии и леса на одних данных она может различаться.
- **Это средняя по больнице.** Перестановочная важность описывает модель в целом. Для объяснения прогноза конкретному пациенту нужны другие методы — например, значения Шепли (библиотека SHAP), которые раскладывают отдельный прогноз на вклады признаков.

Самая полезная функция анализа важности — **поиск ошибок**. Если главным признаком оказался номер палаты, дата поступления или идентификатор аппарата, модель выучила не медицину.

::: summary
- Калибровка — совпадение предсказанных вероятностей с наблюдаемыми частотами; AUC её не измеряет.
- Калибровочная кривая и оценка Брайера показывают, можно ли верить самим числам риска.
- При переносе модели на других пациентов калибровка нарушается раньше, чем различающая способность.
- Перестановочная важность измеряет падение качества при разрушении связи признака с исходом и считается на тестовых данных.
- Важность признака говорит об использовании его моделью, а не о причинной роли.
:::
