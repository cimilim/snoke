# Modellvalidierung und wissenschaftliche Einordnung

Diese Notiz beschreibt, wie das Snoke-Modell als **Hypothesenmodell** betrieben
und empirisch überprüft wird.

## 1) Modellstatus

- Das Zustandsmodell (`D`, `W`, `H`) ist eine formalisierte Hypothese.
- Mathematische Konsistenz allein ist kein Nachweis biologischer Wahrheit.
- Deshalb werden Transparenz, Baselines und Metriken als Pflichtteil geführt.

## 2) Validierungsprotokoll

- Zeitliche Evaluation auf Event-Historie (keine zufällige Leckage-Splits).
- Primärmetriken:
  - **Brier Score** (Wahrscheinlichkeitsgüte)
  - **AUC** (Diskriminationsfähigkeit)
  - **Kalibrierungsfehler (ECE)**
- Vergleich gegen Baselines:
  - `hour_block` (stundenblockbasierte Trigger-Rate)
  - `recent_event_rate` (letzte Ereignisdichte)
- Ablationen:
  - `ohne_kalman`
  - `ohne_sport`
  - `ohne_rules`

## 3) Unsicherheit im Live-Betrieb

- Zusätzlich zum Punktwert `p_now` wird ein Ensemble-Intervall
  (`p_low`, `p_high`) ausgegeben.
- Intervallbreite wird in qualitative Vertrauensstufen übersetzt:
  - `hoch`: schmal
  - `mittel`: moderat
  - `niedrig`: breit

## 4) Wissenschaftliche Quellen (DOI)

1. Koob GF, Volkow ND (2016). *Neurobiology of addiction: a neurocircuitry analysis.*  
   DOI: [10.1016/S2215-0366(16)00104-8](https://doi.org/10.1016/S2215-0366(16)00104-8)

2. Robinson TE, Berridge KC (2008). *The incentive sensitization theory of addiction: some current issues.*  
   DOI: [10.1098/rstb.2008.0093](https://doi.org/10.1098/rstb.2008.0093)

3. Baker TB et al. (2004). *Addiction motivation reformulated: an affective processing model of negative reinforcement.*  
   DOI: [10.1037/0033-295X.111.1.33](https://doi.org/10.1037/0033-295X.111.1.33)

4. Benowitz NL (2008). *Clinical pharmacology of nicotine.*  
   DOI: [10.1038/clpt.2008.3](https://doi.org/10.1038/clpt.2008.3)

## 5) Grenzen

- Latente Zustände sind nicht direkt messbar.
- Parameter sind teilweise heuristisch, teilweise literaturbasiert.
- Nutzung als Entscheidungsunterstützung, nicht als medizinische Diagnose.
