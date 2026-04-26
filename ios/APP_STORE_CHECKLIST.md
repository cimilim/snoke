# App Store Checklist (Snoke iOS)

## 1) Apple Accounts & IDs

- Apple Developer Program aktiv
- App ID / Bundle ID final (z. B. `com.cimilim.snoke`)
- Team in Xcode korrekt gesetzt

## 2) Build & Signing

- Release-Build auf physischem iPhone getestet
- Version + Build Number gepflegt
- Automatic Signing aktiv (oder manuell korrekt konfiguriert)

## 3) App Quality

- Onboarding, Dashboard, History und Event-Logging getestet
- Offline-Verhalten getestet (Flugmodus)
- Fehlertexte nutzerfreundlich

## 4) Backend Production Readiness

- HTTPS-Endpoint in App Settings gesetzt
- Keine Dev-URLs in Release
- API auth flows stabil (`/users/register`, `Bearer`-Token)

## 5) Privacy & Legal

- Privacy Policy URL vorhanden
- App Privacy Fragen in App Store Connect korrekt beantwortet
- Erklaerung, welche Daten erhoben werden und warum

## 6) Store Listing

- App Name, Subtitle, Beschreibung final
- Keywords gepflegt
- Support URL und Marketing URL gesetzt
- Screenshots fuer relevante iPhone-Groessen erstellt
- App Icon (1024x1024) final

## 7) TestFlight

- Build zu TestFlight hochgeladen
- Interne Tester eingeladen
- Kritische Flows getestet (Register, Refresh, Log events)
- Crash-/Fehlerfeedback eingearbeitet

## 8) Submission

- Release Notes vorbereitet
- Export Compliance beantwortet
- Review Notes (Test-Account/Backend-Hinweise) ausgefuellt
- Build zur Review eingereicht
