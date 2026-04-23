# Craving-Wahrscheinlichkeits-Modell

Snoke schätzt zu jedem Zeitpunkt \(t\) die Wahrscheinlichkeit, dass der User
in einem Zeitfenster von \(\Delta t = 15\) Minuten ein Rauchverlangen verspürt
bzw. raucht:

\[
P(\text{craving in } [t, t+\Delta t] \mid \text{Kontext}_t)
\]

Das Modell ist **hybrid**: ein regelbasierter Kaltstart wird durch ein
bayessches Online-Update individualisiert, ein Rule-Layer legt kurzfristige
Boosts/Dämpfer darüber.

## 1. Feature-Extraktion

Jeder `ContextSnapshot` wird in einen diskreten **Bucket-Key** überführt:

```
bucket = (hourOfDay // 2, weekday in {weekday, weekend},
          activity in {still, active, driving},
          stress in {low, mid, high},
          location in {home, work, elsewhere})
```

Damit gibt es maximal `12 × 2 × 3 × 3 × 3 = 648` Buckets. In der Praxis
beobachten wir pro User nur ein Subset.

`stress` wird aus HRV/RHR abgeleitet: relative Abweichung des rollenden
5-Minuten-HRV zum rollenden 24-h-HRV-Median.

## 2. Prior (Kaltstart)

Jedem Bucket \(b\) weisen wir einen informierten Beta-Prior
\(\text{Beta}(\alpha_0^b, \beta_0^b)\) zu. Grundmuster für einen typischen
Raucher:

| Tageszeit     | Erwartete Rate | Prior                    |
| ------------- | -------------- | ------------------------ |
| 6–10 Uhr      | hoch           | Beta(3, 5)               |
| 10–14 Uhr     | mittel         | Beta(2, 6)               |
| 14–18 Uhr     | mittel-hoch    | Beta(3, 6)               |
| 18–22 Uhr     | hoch           | Beta(4, 5)               |
| 22–06 Uhr     | niedrig        | Beta(1, 10)              |

Zusätzliche Kontextmodifikatoren beim Prior: +1 auf \(\alpha\) für
`location=elsewhere` (sozial), +1 auf \(\beta\) für `activity=active`.

## 3. Bayes-Update (Beta-Bernoulli)

Pro Zeitschlitz \(\Delta t\) liegt eine Bernoulli-Beobachtung vor
(1 = Craving/Zigarette beobachtet, 0 = nicht). Die konjugierte Aktualisierung
ist trivial:

\[
\alpha_{n+1} = \alpha_n + x_n,\qquad \beta_{n+1} = \beta_n + (1 - x_n)
\]

Der Posterior-Mittelwert ist die geschätzte Bucket-Rate:

\[
\hat{p}^b = \frac{\alpha^b}{\alpha^b + \beta^b}
\]

Gespeichert wird das in `BucketStat` (SwiftData).

### Vergessen über die Zeit

Da sich Gewohnheiten ändern, "verfällt" alte Evidenz mit einem Zerfallsfaktor
\(\lambda \in (0,1)\) pro Tag (Standard 0.995):

\[
(\alpha, \beta) \leftarrow \lambda\,(\alpha, \beta) + (1-\lambda)(\alpha_0, \beta_0)
\]

## 4. Rule-Layer

Kurzfristige, regelbasierte Anpassungen über dem Bucket-Prior:

| Auslöser (<30 Min zurück)       | Modifikator |
| ------------------------------- | ----------- |
| Kaffee eingeloggt               | × 1.30      |
| Alkohol eingeloggt              | × 1.50      |
| Mahlzeit eingeloggt             | × 1.20      |
| Aktive Bewegung >5 Min          | × 0.70      |
| Letzte Zigarette < 20 Min her   | × 0.40      |
| Ziel für heute bereits erreicht | × 0.90      |

Ergebnis wird auf `[0, 1]` geclippt.

## 5. Ausgabe

- `P_now` – Momentanwahrscheinlichkeit
- `P_next_hour` – Maximum der nächsten vier 15-Min-Fenster
- `top_triggers` – Top-3 Buckets mit höchstem \(\hat{p}\) in den letzten 14 Tagen

## 6. Weaning-Planner

Tagesziel (maximale Anzahl Zigaretten):

\[
\text{target}_d = \max\left(0,\; \lfloor \overline{x}_{d-7..d-1} \cdot (1 - r) \rfloor\right)
\]

mit Weaning-Rate \(r\) (Standard 0.05, d.h. −5 %/Woche, konfigurierbar
im Onboarding). Bei Überschreiten ≥ 80 % des Tagesziels werden Nudges
aggressiver (höhere Threshold-Sensibilität, häufigere Erinnerungen).

## 7. Interventions-Auswahl

Gegeben `P_now` und Kontext wählt `NudgeSelector` aus dem Katalog:

- `P_now < 0.25` → stilles Logging, keine Unterbrechung
- `0.25 ≤ P_now < 0.55` → sanfter Impuls (Wasser, 60-s-Atmung)
- `P_now ≥ 0.55` und kontextabhängig:
  - Stress (HRV-Drop) → 4-7-8-Atmung oder kurze Meditation
  - Sedentär + Social-Scroll-Proxy → 5-Min-Bewegungspause
  - Soziale Situation (elsewhere, evening) → 2-Min-Delay-Challenge

## 8. Evaluation

Zur Offline-Evaluation des Modells (später): Brier-Score pro Bucket, Calibration
Plot, Hit-Rate der JITAI-Nudges (reduzierte Rauchwahrscheinlichkeit in den
30 Min nach Nudge).
